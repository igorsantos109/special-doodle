"""Regression tests using injected HTTP, service and GPU implementations only."""
import io
import json
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from pcsala_agent.inference_adapter import InferenceAdapter, _urlrequest
from pcsala_agent.inference_contract import InferenceConfig, InferenceRequest
from pcsala_agent.locking import ExecutorBusy
from pcsala_agent.migrations import migrate
from pcsala_agent.model_manager import ModelCoordinator, ModelRegistry
from pcsala_agent.models_cli import ModelsCLI
from pcsala_agent.task_queue import cancel, enqueue, get, reserve, update


def request():
    return InferenceRequest(project_id='p', session_id='s', task_id='t', attempt_id='a',
                            profile='cpu-triage-v1', user_prompt='teste')


def completion(finish='stop', text='ok'):
    return json.dumps({'model': 'test', 'choices': [
        {'message': {'content': text}, 'finish_reason': finish}]}).encode()


def test_timeout_forwarded():
    captured = {}
    def transport(req, **kwargs):
        captured.update(kwargs)
        return io.BytesIO(completion())
    assert InferenceAdapter(InferenceConfig(timeout_seconds=7)).query(
        request(), _urlopen=transport).status == 'SUCCESS'
    assert captured['timeout'] == 7


def test_default_transport_preserves_timeout(monkeypatch):
    captured = {}
    def transport(req, **kwargs):
        captured.update(kwargs)
        return 'response'
    monkeypatch.setattr('urllib.request.urlopen', transport)
    assert _urlrequest('request', timeout=7) == 'response'
    assert captured['timeout'] == 7


def test_read_timeout_is_classified_and_closed():
    class Response(io.BytesIO):
        def read(self, *args):
            raise TimeoutError('read timed out')
    response = Response()
    result = InferenceAdapter().query(request(), _urlopen=lambda *a, **k: response)
    assert result.status == 'TIMEOUT'
    assert response.closed


@pytest.mark.parametrize('body', [b'{"choices":[]}', b'{"choices":null}',
    b'{"choices":[null]}', b'{"choices":[{"message":null}]}',
    b'{"choices":"bad"}'])
def test_malformed_payload_is_invalid(body):
    result = InferenceAdapter().query(request(), _urlopen=lambda *a, **k: io.BytesIO(body))
    assert result.status == 'INVALID_RESPONSE'


def test_truncation_is_not_success():
    result = InferenceAdapter().query(request(), _urlopen=lambda *a, **k:
                                      io.BytesIO(completion('length')))
    assert result.status == 'INVALID_RESPONSE'


def test_response_read_is_bounded_and_closed():
    class Response(io.BytesIO):
        requested = None
        def read(self, n=-1):
            self.requested = n
            return super().read(n)
    response = Response(b'x' * 50)
    result = InferenceAdapter(InferenceConfig(max_response_bytes=10)).query(
        request(), _urlopen=lambda *a, **k: response)
    assert response.requested == 11
    assert response.closed
    assert result.status == 'INVALID_RESPONSE'


def test_wrapped_timeout():
    def transport(*args, **kwargs):
        raise urllib.error.URLError(TimeoutError('wrapped'))
    assert InferenceAdapter().query(request(), _urlopen=transport).status == 'TIMEOUT'


def coordinator(tmp_path):
    path = tmp_path / 'state.sqlite'
    migrate(path)
    return ModelCoordinator(ModelRegistry(), database=path), path


def test_reservation_conflict(tmp_path):
    coord, _ = coordinator(tmp_path)
    coord.reserve_engine('bonsai-27b-gpu')
    with pytest.raises(ExecutorBusy):
        coord.reserve_engine('laguna-xs-2.1-gpu')


def test_reservation_is_idempotent(tmp_path):
    coord, _ = coordinator(tmp_path)
    assert coord.reserve_engine('bonsai-27b-gpu') == coord.reserve_engine('bonsai-27b-gpu')


def test_concurrent_reservations_have_one_winner(tmp_path):
    coord, path = coordinator(tmp_path)
    coord.reserve_engine('bonsai-27b-gpu')
    coord.release_engine('bonsai-27b-gpu')
    barrier = Barrier(2)
    def run(model):
        own = ModelCoordinator(ModelRegistry(), database=path)
        barrier.wait(timeout=5)
        try:
            own.reserve_engine(model)
            return True
        except ExecutorBusy:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(run, ['bonsai-27b-gpu', 'laguna-xs-2.1-gpu'])) == 1


@pytest.mark.parametrize('status', ['ROLLED_BACK', 'ROLLBACK_FAILED'])
def test_rollback_outcome_uses_existing_operation_states(tmp_path, status):
    coord, _ = coordinator(tmp_path)
    op = coord.request_start('bonsai-27b-gpu')
    coord.update_confirmed_status(op.operation_id, status)
    result = coord.get_operation(op.operation_id)
    assert result['status'] == 'FAILED'
    assert result['confirmed_status'] == status


def test_failed_stop_keeps_reservation(tmp_path):
    coord, _ = coordinator(tmp_path)
    coord.reserve_engine('bonsai-27b-gpu')
    cli = ModelsCLI(coordinator=coord, systemctl=lambda *a: 1,
                    lock_dir=tmp_path / 'locks', skip_vram_guard=True)
    assert cli.run(['stop', 'bonsai-27b-gpu']) == 1
    assert coord.engine_reserved('bonsai-27b-gpu')


def test_cpu_start_without_gpu(tmp_path):
    class NoGpu:
        def free_mb(self):
            raise AssertionError('CPU must not query GPU')
    coord = ModelCoordinator(ModelRegistry())
    coord.wait_for_health = lambda *a, **k: True
    cli = ModelsCLI(coordinator=coord, systemctl=lambda *a: 0,
                    gpu_monitor=NoGpu(), lock_dir=tmp_path / 'locks')
    assert cli.run(['start', 'bonsai-9b-cpu']) == 0


def test_cancelled_task_is_terminal(tmp_path):
    path = tmp_path / 'state.sqlite'
    task = enqueue(path, 'teste')
    assert cancel(path, task['id'])
    update(path, task['id'], inference_response='late')
    assert get(path, task['id'])['status'] == 'CANCELLED'


def test_completed_task_is_terminal(tmp_path):
    path = tmp_path / 'state.sqlite'
    task = enqueue(path, 'teste')
    reserve(path)
    update(path, task['id'], inference_response='first')
    update(path, task['id'], inference_response='late', error='late error')
    assert get(path, task['id'])['inference_response'] == 'first'
    assert get(path, task['id'])['status'] == 'COMPLETED'


def switch_fixture(tmp_path, monkeypatch, *, fail_start=False, fail_health=False):
    coord, _ = coordinator(tmp_path)
    old = 'bonsai-27b-gpu'
    new = 'laguna-xs-2.1-gpu'
    coord.reserve_engine(old)
    registry = ModelRegistry()
    active = {registry.get(old).unit}
    calls = []
    def systemctl(action, unit):
        calls.append((action, unit))
        if action == 'start' and unit == registry.get(new).unit and fail_start:
            return 1
        if action == 'start':
            active.add(unit)
        elif action == 'stop':
            active.discard(unit)
        return 0
    monkeypatch.setattr('pcsala_agent.models_cli._unit_inactive', lambda unit: unit not in active)
    monkeypatch.setattr('pcsala_agent.model_manager._unit_active', lambda unit: unit in active)
    coord.wait_for_health = lambda model: not (fail_health and model == new)
    cli = ModelsCLI(coordinator=coord, systemctl=systemctl, skip_vram_guard=True,
                    lock_dir=tmp_path / 'locks')
    cli._await_vram_release = lambda: None
    return cli, coord, old, new, active, calls


def test_switch_releases_previous_reservation(tmp_path, monkeypatch):
    cli, coord, old, new, _active, _calls = switch_fixture(tmp_path, monkeypatch)
    assert cli.run(['switch', new]) == 0
    assert not coord.engine_reserved(old)
    assert coord.engine_reserved(new)


def test_switch_rollback_restores_reservation(tmp_path, monkeypatch):
    cli, coord, old, new, active, _calls = switch_fixture(tmp_path, monkeypatch,
                                                       fail_start=True)
    assert cli.run(['switch', new]) == 1
    assert coord.engine_reserved(old)
    assert not coord.engine_reserved(new)
    assert ModelRegistry().get(old).unit in active


def test_failed_health_stops_target_before_restoring_previous(tmp_path, monkeypatch):
    cli, coord, old, new, _active, calls = switch_fixture(tmp_path, monkeypatch,
                                                       fail_health=True)
    assert cli.run(['switch', new]) == 1
    target_stop = calls.index(('stop', ModelRegistry().get(new).unit))
    old_start = calls.index(('start', ModelRegistry().get(old).unit))
    assert target_stop < old_start
    assert coord.engine_reserved(old)
    assert not coord.engine_reserved(new)


def test_start_never_stops_running_group_peer(tmp_path, monkeypatch):
    cli, coord, old, new, _active, calls = switch_fixture(tmp_path, monkeypatch)
    assert cli.run(['start', new]) == 3
    assert calls == []
    assert coord.engine_reserved(old)


def test_failed_start_with_live_process_keeps_reservation(tmp_path, monkeypatch):
    coord, _ = coordinator(tmp_path)
    cli = ModelsCLI(coordinator=coord, systemctl=lambda *a: 1,
                    skip_vram_guard=True, lock_dir=tmp_path / 'locks')
    monkeypatch.setattr('pcsala_agent.models_cli._unit_inactive', lambda unit: False)
    cli._is_model_running = lambda model: False
    assert cli.run(['start', 'bonsai-27b-gpu']) == 1
    assert coord.engine_reserved('bonsai-27b-gpu')


def test_failed_health_with_live_process_keeps_reservation(tmp_path, monkeypatch):
    coord, _ = coordinator(tmp_path)
    coord.wait_for_health = lambda *a: False
    cli = ModelsCLI(coordinator=coord, systemctl=lambda *a: 0,
                    skip_vram_guard=True, lock_dir=tmp_path / 'locks')
    cli._is_model_running = lambda model: False
    monkeypatch.setattr('pcsala_agent.models_cli._unit_inactive', lambda unit: False)
    assert cli.run(['start', 'bonsai-27b-gpu']) == 1
    assert coord.engine_reserved('bonsai-27b-gpu')


def test_stop_success_but_still_active_keeps_reservation(tmp_path, monkeypatch):
    coord, _ = coordinator(tmp_path)
    coord.reserve_engine('bonsai-27b-gpu')
    cli = ModelsCLI(coordinator=coord, systemctl=lambda *a: 0,
                    lock_dir=tmp_path / 'locks')
    monkeypatch.setattr('pcsala_agent.models_cli._unit_inactive', lambda unit: False)
    assert cli.run(['stop', 'bonsai-27b-gpu']) == 1
    assert coord.engine_reserved('bonsai-27b-gpu')


def test_switch_failed_target_stop_never_restarts_previous(tmp_path, monkeypatch):
    cli, coord, old, new, _active, calls = switch_fixture(tmp_path, monkeypatch,
                                                       fail_health=True)
    original = cli.systemctl
    def transport(action, unit):
        if action == 'stop' and unit == ModelRegistry().get(new).unit:
            calls.append((action, unit))
            return 1
        return original(action, unit)
    cli.systemctl = transport
    assert cli.run(['switch', new]) == 1
    assert ('start', ModelRegistry().get(old).unit) not in calls
    assert coord.engine_reserved(new)


def test_queued_task_cannot_be_completed_without_reservation(tmp_path):
    path = tmp_path / 'state.sqlite'
    task = enqueue(path, 'not reserved')
    update(path, task['id'], inference_response='late')
    assert get(path, task['id'])['status'] == 'QUEUED'


@pytest.mark.parametrize('state,code,expected', [
    ('inactive', 3, True), ('failed', 3, True), ('active', 0, False),
    ('activating', 3, False), ('deactivating', 3, False), ('unknown', 4, False),
    ('', 1, False),
])
def test_inactive_requires_confirmed_terminal_state(monkeypatch, state, code, expected):
    from types import SimpleNamespace

    from pcsala_agent.model_manager import _unit_inactive
    monkeypatch.setattr('pcsala_agent.model_manager.subprocess.run',
                        lambda *a, **k: SimpleNamespace(stdout=state, returncode=code))
    assert _unit_inactive('test.service') is expected


def test_missing_migration_directory_fails_explicitly(tmp_path):
    from pcsala_agent.migrations import MigrationError
    with pytest.raises(MigrationError):
        migrate(tmp_path / 'missing.sqlite', tmp_path / 'absent')


def test_reserved_queue_failure_is_terminal(tmp_path):
    path = tmp_path / 'state.sqlite'
    task = enqueue(path, 'failed')
    reserve(path)
    update(path, task['id'], error='first')
    update(path, task['id'], inference_response='late success')
    assert get(path, task['id'])['status'] == 'FAILED'
    assert get(path, task['id'])['error'] == 'first'


def test_switch_low_memory_restores_previous(tmp_path, monkeypatch):
    cli, coord, old, new, active, calls = switch_fixture(tmp_path, monkeypatch)
    cli.skip_vram_guard = False
    cli._vram_ok = lambda: False
    assert cli.run(['switch', new]) == 3
    assert coord.engine_reserved(old)
    assert not coord.engine_reserved(new)
    assert ('start', ModelRegistry().get(new).unit) not in calls
    assert ModelRegistry().get(old).unit in active


def test_start_checks_live_peer_without_reservation(tmp_path, monkeypatch):
    cli, coord, old, new, _active, calls = switch_fixture(tmp_path, monkeypatch)
    coord.release_engine(old)
    assert cli.run(['start', new]) == 3
    assert calls == []


def test_unit_state_query_failure_is_not_inactive(monkeypatch):
    from pcsala_agent.model_manager import _unit_inactive
    def failure(*args, **kwargs):
        raise OSError('systemd unavailable')
    monkeypatch.setattr('pcsala_agent.model_manager.subprocess.run', failure)
    assert _unit_inactive('test.service') is False


def test_systemctl_timeout_returns_failure_code(monkeypatch):
    import subprocess
    def failure(*args, **kwargs):
        raise subprocess.TimeoutExpired('systemctl', 30)
    monkeypatch.setattr('subprocess.run', failure)
    assert ModelsCLI._run_systemctl('start', 'test.service') == 124
