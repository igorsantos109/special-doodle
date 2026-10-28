import fcntl
import os
from pathlib import Path


class ExecutorBusy(Exception):
    pass


class FileLock:
    """Lock de arquivo baseado em fcntl.flock (bloqueio nao-bloqueante)."""

    def __init__(self, path):
        self.path = Path(str(path) + ".lock")
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise OSError("symlink in lock path")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise ExecutorBusy(str(self.path))
        self.fd = fd
        return self

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                os.close(self.fd)
                self.fd = None
        except OSError:
            pass
        return False


def switch_lock(lock_dir):
    """Retorna um FileLock para o diretório de troca de GPU.

    Levanta OSError se não conseguir criar o diretório de lock.
    """
    Path(lock_dir).mkdir(parents=True, exist_ok=True)
    return FileLock(Path(lock_dir) / "pcsala-gpu-switch.lock")


def database_lock(database):
    path = Path(database)
    if path.is_symlink():
        raise OSError("symlink in database path")
    return FileLock(path)
