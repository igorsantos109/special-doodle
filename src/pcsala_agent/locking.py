import errno
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

class ExecutorBusy(RuntimeError):
    pass

@contextmanager
def database_lock(database_path):
    """Bloqueio cooperativo local. Nao excluir o arquivo de lock."""
    database = Path(database_path).resolve()
    if not database.parent.is_dir():
        raise FileNotFoundError(database.parent)

    lock_path = database.with_name(database.name + ".lock")
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise ExecutorBusy(
                    "Outro executor possui o bloqueio deste banco"
                ) from error
            raise
        yield
    finally:
        try:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
