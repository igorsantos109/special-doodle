#!/usr/bin/env bash
# Desenvolvimento/CI: instala apenas dependências Python e executa backends falsos.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" != "--install-dev" ]]; then
  echo 'Uso: bash tools/verify_release.sh --install-dev'
  echo 'Cria/usa .venv e instala dependências de desenvolvimento; não instala serviços/modelos.'
  exit 2
fi
if [[ ! -e .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -e '.[dev]'
FAKEBIN=$(mktemp -d)
trap 'rm -rf "$FAKEBIN"' EXIT
printf '#!/bin/sh\nexit 4\n' > "$FAKEBIN/systemctl"
printf '#!/bin/sh\nexit 1\n' > "$FAKEBIN/nvidia-smi"
chmod +x "$FAKEBIN/systemctl" "$FAKEBIN/nvidia-smi"
PATH="$FAKEBIN:$PATH" .venv/bin/python -m pytest -q -m 'not gpu' tests
.venv/bin/ruff check src/pcsala_agent/inference_adapter.py tests/test_production_regressions.py
.venv/bin/python -m compileall -q src
printf '\nVerificação da candidata concluída. Não equivale a validação de produção/GPU.\n'
