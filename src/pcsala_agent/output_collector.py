import math
import os
import selectors
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Literal


class OutputCollectionError(RuntimeError):
    """Falha de infraestrutura; nao representa resultado do comando."""


@dataclass(frozen=True)
class CollectedOutput:
    status: Literal["SUCCESS", "COMMAND_ERROR", "TIMEOUT", "OUTPUT_LIMIT"]
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float

    @property
    def retained_bytes(self):
        return len(self.stdout) + len(self.stderr)


def validate_output_limits(output_limit, timeout_seconds):
    if type(output_limit) is not int or not 1 <= output_limit <= 65536:
        raise ValueError("Teto de saida invalido")
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 15
    ):
        raise ValueError("Prazo invalido")


def collect_output(
    process,
    *,
    terminate: Callable[[], None],
    output_limit: int = 65536,
    timeout_seconds: float = 15,
    started_at: float | None = None,
) -> CollectedOutput:
    """Coleta processo existente; nao inicia comandos.

    Apos validar os argumentos, assume a limpeza dos dois pipes.
    terminate deve encerrar somente o trabalho pertencente ao chamador,
    inclusive descendentes, e tolerar que ele ja tenha terminado.
    Falhas operacionais geram OutputCollectionError, nao COMMAND_ERROR.
    """
    validate_output_limits(output_limit, timeout_seconds)
    if not callable(terminate):
        raise ValueError("Encerramento obrigatorio")

    now = time.monotonic()
    if started_at is None:
        started_at = now
    elif (
        type(started_at) not in (int, float)
        or not math.isfinite(started_at)
        or started_at > now
    ):
        raise ValueError("Inicio monotonic invalido")

    retained = {"stdout": bytearray(), "stderr": bytearray()}
    size = 0
    status = None
    failure = None
    cleanup_errors = []

    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (
                ("stdout", process.stdout),
                ("stderr", process.stderr),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)

            while True:
                if not selector.get_map() and process.poll() is not None:
                    break

                remaining = timeout_seconds - (
                    time.monotonic() - started_at
                )
                if remaining <= 0:
                    status = "TIMEOUT"
                    break

                for key, _ in selector.select(min(remaining, 0.05)):
                    try:
                        chunk = os.read(key.fd, 8192)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue

                    available = output_limit - size
                    kept = chunk[:available]
                    retained[key.data].extend(kept)
                    size += len(kept)
                    if len(chunk) > available:
                        status = "OUTPUT_LIMIT"
                        break

                if status is not None:
                    break
    except BaseException as error:
        failure = error
    finally:
        must_stop = (
            failure is not None
            or status in ("TIMEOUT", "OUTPUT_LIMIT")
        )
        if not must_stop:
            try:
                must_stop = process.poll() is None
            except BaseException as error:
                cleanup_errors.append(error)
                must_stop = True

        if must_stop:
            try:
                terminate()
            except BaseException as error:
                cleanup_errors.append(error)

        try:
            process.wait(timeout=2)
        except BaseException as error:
            cleanup_errors.append(error)
            try:
                terminate()
            except BaseException as stop_error:
                cleanup_errors.append(stop_error)
            try:
                process.wait(timeout=2)
            except BaseException as wait_error:
                cleanup_errors.append(wait_error)

        for stream_name in ("stdout", "stderr"):
            try:
                stream = getattr(process, stream_name)
                if stream is not None:
                    stream.close()
            except BaseException as error:
                cleanup_errors.append(error)

    errors = ([failure] if failure is not None else []) + cleanup_errors
    if errors:
        for error in errors:
            if not isinstance(error, Exception):
                for additional in errors:
                    if additional is not error:
                        error.add_note(
                            "Falha adicional na coleta/limpeza: "
                            + type(additional).__name__
                        )
                raise error
        error = OutputCollectionError(
            "Falha de infraestrutura na coleta ou limpeza; "
            f"{len(errors)} erro(s); encerramento pode nao estar confirmado"
        )
        for additional in errors[1:]:
            error.add_note(type(additional).__name__)
        raise error from errors[0]

    if process.returncode is None:
        raise OutputCollectionError("Termino do processo nao confirmado")
    if status is None:
        status = "SUCCESS" if process.returncode == 0 else "COMMAND_ERROR"

    return CollectedOutput(
        status=status,
        returncode=process.returncode,
        stdout=bytes(retained["stdout"]),
        stderr=bytes(retained["stderr"]),
        elapsed_seconds=time.monotonic() - started_at,
    )
