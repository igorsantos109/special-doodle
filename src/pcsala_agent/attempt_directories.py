import os
import stat

FLAGS = os.O_NOFOLLOW | os.O_DIRECTORY
DIR_CREATE_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class AttemptAlreadyExists(Exception):
    pass


class DirectoryPreparationError(Exception):
    pass


class PreparedAttempt:
    def __init__(self, relative_attempt, relative_workspace):
        self.relative_attempt = relative_attempt
        self.relative_workspace = relative_workspace


def _reject_writable(st, label):
    if stat.S_IMODE(st.st_mode) & 0o022:
        raise DirectoryPreparationError(f"{label} gravavel")


def prepare_attempt(root_fd, request):
    parts = (
        request.project_id,
        request.session_id,
        request.task_id,
        request.attempt_id,
    )
    root_st = os.fstat(root_fd)
    if not stat.S_ISDIR(root_st.st_mode):
        raise DirectoryPreparationError("root não é diretório")
    _reject_writable(root_st, "root")
    current = root_fd
    for i, name in enumerate(parts):
        is_last = i == len(parts) - 1
        try:
            fd = os.open(name, DIR_CREATE_FLAGS, dir_fd=current)
            st = os.fstat(fd)
            if stat.S_ISDIR(st.st_mode):
                os.close(fd)
                current = os.open(name, DIR_CREATE_FLAGS, dir_fd=current)
                if is_last:
                    raise AttemptAlreadyExists(
                        "/".join([request.project_id, request.session_id,
                                  request.task_id, request.attempt_id])
                    )
                _reject_writable(os.fstat(current), "/".join(parts[:i + 1]))
                continue
            os.close(fd)
            raise DirectoryPreparationError(f"{name} não é diretório")
        except FileNotFoundError:
            try:
                os.mkdir(name, 0o700, dir_fd=current)
            except FileExistsError:
                current = os.open(name, DIR_CREATE_FLAGS, dir_fd=current)
                if is_last:
                    raise AttemptAlreadyExists("/".join(parts))
                _reject_writable(os.fstat(current), "/".join(parts[:i + 1]))
                continue
            current = os.open(name, DIR_CREATE_FLAGS, dir_fd=current)
    try:
        os.mkdir("workspace", 0o700, dir_fd=current)
    except FileExistsError:
        pass
    os.close(current)
    return PreparedAttempt(
        relative_attempt="/".join(parts),
        relative_workspace="/".join(parts) + "/workspace",
    )
