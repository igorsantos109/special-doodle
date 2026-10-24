import os
import subprocess
import time

import pytest

from pcsala_agent.output_collector import (
    OutputCollectionError, collect_output, validate_output_limits,
)


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", running=False, hold=False):
        self.returncode = None if running else 0
        self.wait_calls = 0
        self.stop_calls = 0
        self.fail_wait_once = False
        self.writers = []
        self.stdout = self.make_pipe(stdout, hold)
        self.stderr = self.make_pipe(stderr, hold)

    def make_pipe(self, data, hold):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "rb", buffering=0)
        if data:
            os.write(write_fd, data)
        if hold:
            self.writers.append(write_fd)
        else:
            os.close(write_fd)
        return stream

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.wait_calls += 1
        if self.fail_wait_once:
            self.fail_wait_once = False
            raise subprocess.TimeoutExpired("fake", timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode

    def terminate(self):
        self.stop_calls += 1
        if self.returncode is None:
            self.returncode = -9

    def close(self):
        self.stdout.close()
        self.stderr.close()
        for fd in self.writers:
            os.close(fd)
        self.writers.clear()


@pytest.fixture
def processes():
    created = []

    def factory(**kwargs):
        process = FakeProcess(**kwargs)
        created.append(process)
        return process

    yield factory
    for process in created:
        process.close()


def collect(process, **kwargs):
    return collect_output(
        process,
        terminate=process.terminate,
        timeout_seconds=0.2,
        **kwargs,
    )


def test_success_and_binary_data(processes):
    process = processes(stdout=bytes([0, 255]), stderr=b"note")
    result = collect(process)
    assert result.status == "SUCCESS"
    assert result.stdout == bytes([0, 255])
    assert result.stderr == b"note"
    assert result.retained_bytes == 6
    assert process.stop_calls == 0
    assert process.stdout.closed and process.stderr.closed


def test_command_error(processes):
    process = processes(stderr=b"error")
    process.returncode = 7
    result = collect(process)
    assert result.status == "COMMAND_ERROR"
    assert result.returncode == 7


def test_exact_shared_limit(processes):
    process = processes(stdout=b"abc", stderr=b"de")
    result = collect(process, output_limit=5)
    assert result.status == "SUCCESS"
    assert result.stdout == b"abc"
    assert result.stderr == b"de"
    assert result.retained_bytes == 5


@pytest.mark.parametrize("stdout,stderr", [
    (b"abcdef", b""),
    (b"", b"abcdef"),
    (b"abc", b"def"),
])
def test_overflow_is_shared_and_stops_even_exited_leader(
    processes, stdout, stderr,
):
    process = processes(stdout=stdout, stderr=stderr)
    result = collect(process, output_limit=5)
    assert result.status == "OUTPUT_LIMIT"
    assert result.retained_bytes == 5
    assert process.stop_calls == 1
    assert process.stdout.closed and process.stderr.closed


def test_timeout_with_open_pipes(processes):
    process = processes(running=True, hold=True)
    result = collect_output(
        process,
        terminate=process.terminate,
        timeout_seconds=0.01,
    )
    assert result.status == "TIMEOUT"
    assert result.returncode == -9
    assert result.retained_bytes == 0
    assert process.stop_calls == 1


def test_timeout_with_exited_leader_and_inherited_pipes(processes):
    process = processes(hold=True)
    result = collect_output(
        process,
        terminate=process.terminate,
        timeout_seconds=0.01,
    )
    assert result.status == "TIMEOUT"
    assert process.stop_calls == 1
    assert result.returncode == 0


def test_read_failure_still_cleans_up(processes, monkeypatch):
    import pcsala_agent.output_collector as module

    process = processes(stdout=b"x", running=True)

    def broken_read(*args):
        raise OSError("read failure")

    monkeypatch.setattr(module.os, "read", broken_read)
    with pytest.raises(OutputCollectionError) as caught:
        collect(process)
    assert isinstance(caught.value.__cause__, OSError)
    assert process.stop_calls == 1
    assert process.stdout.closed and process.stderr.closed


def test_selector_failure_still_cleans_up(processes, monkeypatch):
    import pcsala_agent.output_collector as module

    process = processes(running=True)

    def broken_selector():
        raise OSError("selector failure")

    monkeypatch.setattr(module.selectors, "DefaultSelector", broken_selector)
    with pytest.raises(OutputCollectionError):
        collect(process)
    assert process.stop_calls == 1
    assert process.stdout.closed and process.stderr.closed


def test_wait_failure_is_not_command_error(processes):
    process = processes()
    process.fail_wait_once = True
    with pytest.raises(OutputCollectionError):
        collect(process)
    assert process.stop_calls == 1
    assert process.wait_calls == 2
    assert process.stdout.closed and process.stderr.closed


def test_stop_failure_does_not_skip_pipe_cleanup(processes):
    process = processes(hold=True)

    def broken_stop():
        process.stop_calls += 1
        raise OSError("stop failure")

    with pytest.raises(OutputCollectionError):
        collect_output(
            process,
            terminate=broken_stop,
            timeout_seconds=0.01,
        )
    assert process.stop_calls == 1
    assert process.stdout.closed and process.stderr.closed


def test_keyboard_interrupt_preserved_after_cleanup(processes, monkeypatch):
    import pcsala_agent.output_collector as module

    process = processes(stdout=b"x", running=True)

    def interrupted_read(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(module.os, "read", interrupted_read)
    with pytest.raises(KeyboardInterrupt):
        collect(process)
    assert process.stop_calls == 1
    assert process.stdout.closed and process.stderr.closed


def test_collector_does_not_launch_commands(processes, monkeypatch):
    process = processes(stdout=b"ok")

    def forbidden(*args, **kwargs):
        raise AssertionError("Lancamento de comando no coletor")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    assert collect(process).stdout == b"ok"


def test_elapsed_time_includes_supplied_start(processes):
    process = processes()
    start = time.monotonic() - 0.05
    result = collect_output(
        process,
        terminate=process.terminate,
        timeout_seconds=1,
        started_at=start,
    )
    assert result.elapsed_seconds >= 0.05


@pytest.mark.parametrize("value", [0, -1, 65537, True, "100"])
def test_invalid_limits(value):
    with pytest.raises(ValueError):
        validate_output_limits(value, 1)


@pytest.mark.parametrize("value", [
    0, -1, 16, True, "1", float("inf"), float("nan"),
])
def test_invalid_deadlines(value):
    with pytest.raises(ValueError):
        validate_output_limits(65536, value)
