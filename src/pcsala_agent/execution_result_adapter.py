import math

from .execution_contract import (
    ExecutionRequest, ExecutionResult, resolve_profile,
)
from .output_collector import CollectedOutput


class InvalidCollectedOutput(ValueError):
    """Dados de coleta invalidos ou incoerentes."""


class SignalTerminationUnsupported(InvalidCollectedOutput):
    """O contrato atual nao representa diretamente termino por sinal."""

    def __init__(self, returncode):
        self.returncode = returncode
        super().__init__(
            "COMMAND_ERROR com codigo negativo exige tratamento explicito; "
            f"codigo bruto={returncode}"
        )


def adapt_collected_output(
    request: ExecutionRequest,
    collected: CollectedOutput,
) -> ExecutionResult:
    """Adapta somente dados; nao executa nem confirma encerramento.

    TIMEOUT e OUTPUT_LIMIT descartam o codigo bruto no contrato.
    Excecoes de coleta nao sao convertidas: falta a contagem parcial.
    """
    checked = ExecutionRequest.model_validate(request)
    profile = resolve_profile(checked)

    if type(collected) is not CollectedOutput:
        raise InvalidCollectedOutput(
            "Exigido CollectedOutput, nao excecao ou objeto alternativo"
        )

    status = collected.status
    if type(status) is not str or status not in (
        "SUCCESS", "COMMAND_ERROR", "TIMEOUT", "OUTPUT_LIMIT",
    ):
        raise InvalidCollectedOutput("Status de coleta invalido")

    code = collected.returncode
    if type(code) is not int:
        raise InvalidCollectedOutput("Codigo bruto deve ser inteiro estrito")

    if type(collected.stdout) is not bytes:
        raise InvalidCollectedOutput("stdout deve ser bytes")
    if type(collected.stderr) is not bytes:
        raise InvalidCollectedOutput("stderr deve ser bytes")

    output_bytes = len(collected.stdout) + len(collected.stderr)
    if output_bytes > profile.output_bytes_max:
        raise InvalidCollectedOutput("Saida retida excede o perfil")

    elapsed = collected.elapsed_seconds
    if type(elapsed) not in (int, float) or elapsed < 0:
        raise InvalidCollectedOutput("Duracao invalida")
    try:
        finite = math.isfinite(elapsed)
    except OverflowError:
        finite = False
    if not finite:
        raise InvalidCollectedOutput("Duracao deve ser finita")

    if status == "SUCCESS":
        if code != 0:
            raise InvalidCollectedOutput("Sucesso exige codigo bruto zero")
        exit_code = 0
    elif status == "COMMAND_ERROR":
        if code < 0:
            raise SignalTerminationUnsupported(code)
        if not 1 <= code <= 255:
            raise InvalidCollectedOutput(
                "Erro de comando exige codigo entre 1 e 255"
            )
        exit_code = code
    else:
        exit_code = None

    return ExecutionResult(
        request=checked,
        status=status,
        exit_code=exit_code,
        output_bytes=output_bytes,
    )
