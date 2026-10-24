import os
import stat
from contextlib import ExitStack
from dataclasses import dataclass

from .execution_contract import ExecutionRequest

class DirectoryPreparationError(RuntimeError):
    pass

class AttemptAlreadyExists(DirectoryPreparationError):
    pass

@dataclass(frozen=True)
class PreparedAttempt:
    relative_attempt: str
    relative_workspace: str

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

def _check(fd):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise DirectoryPreparationError("Descritor nao representa diretorio")
    if info.st_uid != os.geteuid():
        raise DirectoryPreparationError("Proprietario administrativo inesperado")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise DirectoryPreparationError("Diretorio gravavel por grupo ou outros")

def prepare_attempt(root_fd: int, request: ExecutionRequest) -> PreparedAttempt:
    """Prototipo local: todos os diretorios permanecem com o UID chamador."""
    checked = ExecutionRequest.model_validate(request)
    parts = (
        checked.project_id, checked.session_id,
        checked.task_id, checked.attempt_id,
    )
    with ExitStack() as stack:
        parent = os.dup(root_fd)
        stack.callback(os.close, parent)
        _check(parent)

        for name in parts[:3]:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            child = os.open(name, FLAGS, dir_fd=parent)
            stack.callback(os.close, child)
            _check(child)
            parent = child

        try:
            os.mkdir(parts[3], mode=0o700, dir_fd=parent)
        except FileExistsError as error:
            raise AttemptAlreadyExists(
                "Tentativa ja existe; nao sera reutilizada"
            ) from error

        attempt = os.open(parts[3], FLAGS, dir_fd=parent)
        stack.callback(os.close, attempt)
        _check(attempt)

        os.mkdir("workspace", mode=0o700, dir_fd=attempt)
        workspace = os.open("workspace", FLAGS, dir_fd=attempt)
        stack.callback(os.close, workspace)
        _check(workspace)

    relative = "/".join(parts)
    return PreparedAttempt(relative, relative + "/workspace")
