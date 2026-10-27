from pydantic import ValidationError

from .execution_contract import ExecutionRequest, ExecutionResult
from .output_collector import CollectedOutput, OutputCollectionError


class InvalidCollectedOutput(Exception):
    pass


class SignalTerminationUnsupported(Exception):
    def __init__(self, returncode):
        super().__init__(f"sinal {returncode} não suportado")
        self.returncode = returncode


def _revalidate(req):
    return ExecutionRequest(**req.model_dump())


def _validate_collected_fields(collected):
    """Revalida tipos dos campos de CollectedOutput (dataclass sem execucao)."""
    if not isinstance(collected.status, str):
        raise InvalidCollectedOutput("status invalido")
    if isinstance(collected.returncode, bool) or not isinstance(
        collected.returncode, int
    ):
        raise InvalidCollectedOutput("returncode invalido")
    if not isinstance(collected.stdout, bytes):
        raise InvalidCollectedOutput("stdout invalido")
    if not isinstance(collected.stderr, bytes):
        raise InvalidCollectedOutput("stderr invalido")
    if isinstance(collected.elapsed_seconds, bool) or not isinstance(
        collected.elapsed_seconds, (int, float)
    ):
        raise InvalidCollectedOutput("elapsed_seconds invalido")
    if collected.elapsed_seconds != collected.elapsed_seconds:
        raise InvalidCollectedOutput("elapsed_seconds invalido")
    if collected.elapsed_seconds in (float("inf"), float("-inf")) or collected.elapsed_seconds < 0:
        raise InvalidCollectedOutput("elapsed_seconds invalido")


def adapt_collected_output(req, collected):
    if isinstance(collected, OutputCollectionError):
        raise InvalidCollectedOutput("saida parcial indisponivel")
    if not isinstance(collected, CollectedOutput):
        raise InvalidCollectedOutput("objeto de saida invalido")
    _validate_collected_fields(collected)
    validated = _revalidate(req)
    status = collected.status
    code = collected.returncode
    if status == "SUCCESS":
        if code != 0:
            raise InvalidCollectedOutput("SUCCESS com exit_code != 0")
        exit_code = 0
        result_status = "SUCCESS"
    elif status == "COMMAND_ERROR":
        if code < 0:
            raise SignalTerminationUnsupported(code)
        if code is None or code == 0 or code < 1 or code > 255:
            raise InvalidCollectedOutput("COMMAND_ERROR codigo invalido")
        exit_code = code
        result_status = "COMMAND_ERROR"
    elif status in ("TIMEOUT", "OUTPUT_LIMIT"):
        exit_code = None
        result_status = status
    else:
        raise InvalidCollectedOutput(f"status desconhecido: {status}")
    total = len(collected.stdout) + len(collected.stderr)
    if total > 65536:
        raise InvalidCollectedOutput("saida excede o limite de 65536 bytes")
    output_bytes = total
    try:
        return ExecutionResult(
            request=validated,
            status=result_status,
            exit_code=exit_code,
            output_bytes=output_bytes,
        )
    except ValidationError as exc:
        raise InvalidCollectedOutput(str(exc)) from exc
