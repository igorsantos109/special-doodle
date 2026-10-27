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


def adapt_collected_output(req, collected):
    if isinstance(collected, OutputCollectionError):
        raise InvalidCollectedOutput("saida parcial indisponivel")
    if not isinstance(collected, CollectedOutput):
        raise InvalidCollectedOutput("objeto de saida invalido")
    validated = _revalidate(req)
    status = collected.status
    code = collected.returncode
    if code is not None and code < 0:
        raise SignalTerminationUnsupported(code)
    if status == "SUCCESS":
        if code != 0:
            raise InvalidCollectedOutput("SUCCESS com exit_code != 0")
        exit_code = 0
        result_status = "SUCCESS"
    elif status == "COMMAND_ERROR":
        if code is None or code == 0 or code < 1 or code > 255:
            raise InvalidCollectedOutput("COMMAND_ERROR codigo invalido")
        exit_code = code
        result_status = "COMMAND_ERROR"
    elif status in ("TIMEOUT", "OUTPUT_LIMIT"):
        if code is not None and code != 0 and code != -9:
            raise InvalidCollectedOutput("status de controle com exit_code inesperado")
        exit_code = None
        result_status = status
    else:
        raise InvalidCollectedOutput(f"status desconhecido: {status}")
    output_bytes = min(len(collected.stdout) + len(collected.stderr), 65536)
    try:
        return ExecutionResult(
            request=validated,
            status=result_status,
            exit_code=exit_code,
            output_bytes=output_bytes,
        )
    except ValidationError as exc:
        raise InvalidCollectedOutput(str(exc)) from exc
