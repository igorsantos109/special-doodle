import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from pcsala_agent.attempt_directories import (
    FLAGS,
    AttemptAlreadyExists,
    DirectoryPreparationError,
    prepare_attempt,
)
from pcsala_agent.execution_contract import ExecutionRequest


def request():
    return ExecutionRequest(
        project_id="p", session_id="s", task_id="t",
        attempt_id="a", profile="diagnostic-v1",
    )

@pytest.fixture
def environment(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir(mode=0o700)
    fd = os.open(root, FLAGS)
    try:
        yield root, fd
    finally:
        os.close(fd)

def test_creates_separate_directories(environment):
    root, fd = environment
    result = prepare_attempt(fd, request())
    assert result.relative_attempt == "p/s/t/a"
    assert result.relative_workspace == "p/s/t/a/workspace"
    for relative in ("p", "p/s", "p/s/t", "p/s/t/a", result.relative_workspace):
        info = (root / relative).stat()
        assert stat.S_IMODE(info.st_mode) == 0o700
        assert info.st_uid == os.geteuid()
    os.fstat(fd)

def test_existing_attempt_preserved(environment):
    root, fd = environment
    result = prepare_attempt(fd, request())
    sentinel = root / result.relative_workspace / "preservar.txt"
    sentinel.write_text("preservar")
    with pytest.raises(AttemptAlreadyExists):
        prepare_attempt(fd, request())
    assert sentinel.read_text() == "preservar"

@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_symlink_components_rejected(environment, tmp_path, depth):
    root, fd = environment
    parts = ("p", "s", "t", "a")
    parent = root
    for name in parts[:depth]:
        parent = parent / name
        parent.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir()
    (parent / parts[depth]).symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, DirectoryPreparationError)):
        prepare_attempt(fd, request())
    assert list(outside.iterdir()) == []
    assert (parent / parts[depth]).is_symlink()

@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_file_components_rejected(environment, depth):
    root, fd = environment
    parts = ("p", "s", "t", "a")
    parent = root
    for name in parts[:depth]:
        parent = parent / name
        parent.mkdir(mode=0o700)
    blocker = parent / parts[depth]
    blocker.write_text("nao apagar")
    with pytest.raises((OSError, DirectoryPreparationError)):
        prepare_attempt(fd, request())
    assert blocker.read_text() == "nao apagar"

def test_writable_root_rejected(environment):
    root, fd = environment
    root.chmod(0o770)
    with pytest.raises(DirectoryPreparationError):
        prepare_attempt(fd, request())
    assert list(root.iterdir()) == []

def test_writable_parent_rejected(environment):
    root, fd = environment
    (root / "p").mkdir(mode=0o700)
    (root / "p").chmod(0o777)
    with pytest.raises(DirectoryPreparationError):
        prepare_attempt(fd, request())
    assert list((root / "p").iterdir()) == []

def test_concurrent_attempt_has_one_winner(environment):
    _, fd = environment
    def create():
        try:
            prepare_attempt(fd, request())
            return "created"
        except AttemptAlreadyExists:
            return "exists"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert sorted(results) == ["created", "exists"]

def test_partial_failure_preserved(environment, monkeypatch):
    root, fd = environment
    original = os.mkdir
    def fail_workspace(path, *args, **kwargs):
        if path == "workspace":
            raise OSError("Falha artificial")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(os, "mkdir", fail_workspace)
    with pytest.raises(OSError, match="Falha artificial"):
        prepare_attempt(fd, request())
    assert (root / "p/s/t/a").is_dir()
    with pytest.raises(AttemptAlreadyExists):
        prepare_attempt(fd, request())

def test_no_subprocess(environment, monkeypatch):
    _, fd = environment
    def forbidden(*args, **kwargs):
        raise AssertionError("Subprocesso proibido")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    prepare_attempt(fd, request())
