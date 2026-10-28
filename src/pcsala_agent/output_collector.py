import os
import selectors
import time
from dataclasses import dataclass


class OutputCollectionError(Exception):
    pass


@dataclass
class CollectedOutput:
    status: str
    returncode: int
    stdout: bytes
    stderr: bytes
    retained_bytes: int = 0
    elapsed_seconds: float = 0.0


def validate_output_limits(output_limit, timeout_seconds):
    if isinstance(output_limit, bool) or not isinstance(output_limit, int):
        raise ValueError("output_limit invalido")
    if output_limit < 1 or output_limit > 65536:
        raise ValueError("output_limit fora de faixa")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout invalido")
    if timeout_seconds != timeout_seconds:
        raise ValueError("timeout nan")
    if timeout_seconds == float("inf"):
        raise ValueError("timeout inf")
    if timeout_seconds <= 0 or timeout_seconds > 15:
        raise ValueError("timeout fora de faixa")
    return True


def _close_streams(process):
    for name in ("stdout", "stderr"):
        stream = getattr(process, name, None)
        if stream is not None and not getattr(stream, "closed", True):
            try:
                stream.close()
            except Exception:
                pass


def _terminate(process, terminate):
    try:
        terminate() if terminate is not None else process.terminate()
    except Exception:
        pass

def _terminate_or_fail(process, terminate):
    """Chama terminate e propaga falha como OutputCollectionError."""
    try:
        terminate() if terminate is not None else process.terminate()
    except Exception as exc:
        _close_streams(process)
        raise OutputCollectionError("falha ao encerrar processo") from exc

def _wait_for_returncode(process):
    try:
        return process.wait(timeout=5)
    except Exception as exc:
        raise OutputCollectionError("nao foi possivel aguardar o processo") from exc


def _clip(data, limit):
    return data[:limit], min(len(data), limit)


def collect_output(process, terminate=None, timeout_seconds=5, output_limit=65536,
                   started_at=None):
    validate_output_limits(output_limit, timeout_seconds)
    if started_at is None:
        started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    stdout = b""
    stderr = b""
    overflow = False
    timed_out = False
    eofs = set()
    try:
        sel = selectors.DefaultSelector()
    except OSError as exc:
        _terminate_or_fail(process, terminate)
        _close_streams(process)
        raise OutputCollectionError("selector failure") from exc
    registered = []
    try:
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            if stream is not None:
                registered.append((name, stream))
                sel.register(stream, selectors.EVENT_READ, (name, stream))
    except OSError as exc:
        sel.close()
        _terminate_or_fail(process, terminate)
        _close_streams(process)
        raise OutputCollectionError("selector failure") from exc
    total_limit = output_limit

    def _do_read(name, stream):
        nonlocal stdout, stderr
        try:
            data = os.read(stream.fileno(), 65536)
        except OSError as exc:
            _terminate_or_fail(process, terminate)
            _close_streams(process)
            raise OutputCollectionError("read failure") from exc
        if not data:
            eofs.add(stream)
            return
        if name == "stdout":
            stdout += data
        else:
            stderr += data

    try:
        while True:
            now = time.monotonic()
            if now >= deadline:
                if process.poll() is None or not eofs.issuperset({s for _, s in registered}):
                    timed_out = True
                break
            timeout = deadline - now
            try:
                events = sel.select(timeout)
            except OSError as exc:
                _terminate_or_fail(process, terminate)
                _close_streams(process)
                raise OutputCollectionError("selector failure") from exc
            if not events:
                if process.poll() is not None and eofs.issuperset(
                    {s for _, s in registered}
                ):
                    break
                continue
            for key, _ in events:
                name, stream = key.data
                _do_read(name, stream)
                total = len(stdout) + len(stderr)
                if total > total_limit:
                    overflow = True
                    break
            if overflow:
                break
            if process.poll() is not None and eofs.issuperset(
                {s for _, s in registered}
            ):
                break

        rc = process.poll()
        if timed_out:
            _terminate_or_fail(process, terminate)
            if rc is None:
                rc = _wait_for_returncode(process)
            if rc is None:
                rc = -9
            status = "TIMEOUT"
        elif overflow:
            _terminate_or_fail(process, terminate)
            if rc is None:
                rc = _wait_for_returncode(process)
            if rc is None:
                rc = -9
            status = "OUTPUT_LIMIT"
        else:
            if rc is None:
                rc = _wait_for_returncode(process)
            if rc is None:
                rc = 0
            status = "COMMAND_ERROR" if rc else "SUCCESS"
        capped_stdout = stdout[:output_limit]
        rem = max(0, output_limit - len(capped_stdout))
        capped_stderr = stderr[:rem]
        retained = len(capped_stdout) + len(capped_stderr)
        _close_streams(process)
        return CollectedOutput(
            status=status,
            returncode=rc if rc is not None else 0,
            stdout=capped_stdout,
            stderr=capped_stderr,
            retained_bytes=retained,
            elapsed_seconds=time.monotonic() - started_at,
        )
    except KeyboardInterrupt:
        _terminate(process, terminate)
        _close_streams(process)
        raise
    finally:
        sel.close()
        _close_streams(process)
