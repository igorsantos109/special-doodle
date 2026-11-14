# DIAGNOSTICO (atualizado 2026-11-13)

Historico: o diagnostico da FASE 0 (2026-10-26) registou o `.git` corrompido e o `src/`
ausente. Esse bloqueio foi superado: `src/pcsala_agent/` tem hoje 33 modulos e o
`pyproject.toml` define `pythonpath=["src"]` e o entry point `pcsala`.

## Resolvido

- Codigo-fonte recuperado e versionado.
- `pyproject.toml` com entry point, pytest e ruff.
- Caminhos parametrizados por `PCSALA_HOME`, `PCSALA_ROOT`, `PCSALA_BACKUP_DIR`.
- CI em `.github/workflows/ci.yml` (ruff + pytest sem GPU; instala do lock com hashes).
- Arquivos `.bak` removidos e ignorados via `.gitignore`; o CI falha se reaparecerem.
- Script `pcsala` da raiz reduzido a wrapper de `pcsala_agent.cli` (a copia antiga
  nao tinha `models gen-llama-swap`).

## Pendente

1. Confirmar que `pip install --require-hashes -r requirements.lock` passa em Python
   3.11 e 3.13 (o lock tinha hash divergente em `charset-normalizer`).
2. Mover os `.service` da raiz e de `configs/` para `deploy/systemd/` e ajustar os
   comandos `sudo cp` nos guias.
3. Caminhos `/home/igor/pc-sala-agent` ainda aparecem em `pcsala-worker.service`,
   `CONTINUITY.md` e `guias/GUIA_MESTRE.md`.
4. `cli.py`: `SRC_DIR` aponta para `src/src` (parent.parent de `src/pcsala_agent/cli.py`);
   inofensivo quando o pacote esta instalado, mas deve ser corrigido.
5. Autenticacao real nas APIs (hoje o cabecalho `Authorization` e ignorado; apenas
   ufw/nft para 192.168.0.0/16).
6. Unificar os gestores `ia` e `pcsala models` numa unica fonte de registo.
7. Medir funcoes longas e dividir `models_cli.py`, `model_manager.py`, `real_graph.py`.
