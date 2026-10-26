# Plano MTP — Bonsai 2 27B GPU (P40)

## Estado atual

- **Modelo:** `Ternary-Bonsai-2-27B-PQ2_0.gguf` (6,8 GB) + drafter MTP (1 GB, SHA-256 `9d11de22…287e7`)
- **Build ativo:** `5d80cff0b` (PrismML + patch Pascal) em `prism-pascal-build/build/bin/llama-server`
- **Contexto:** 64K (`-c 64000`, elevado de 55K em 2026-10-23)
- **VRAM:** ~12,9 GB · Prompt eval: 126-243 tok/s · Geração: 28-48 tok/s
- **MTP:** `--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-p-min 0.4`
- **Limitação:** `--cache-reuse` e `--context-shift` inertes (rope MROPE)

## Limitações do build

- Binário `73bfe6c` (base) não tem patch Pascal: rota Hadamard para cabeça MTP pode falhar na P40
- `reserve_engine()` implementado no gestor, mas **não chamado pelo worker** (usa apenas `ensure_model_ready`)
- Reservas são dict em memória — não sobrevivem a reinício
- GPU switch usa lock de arquivo `/tmp/pcsala-gpu-switch.lock`
- `CUDA_VISIBLE_DEVICES` **não é gerenciado** pelo gestor

## Próximos passos

- Validar drafter no build Pascal (já feito — MTP ativo, aceitação 0,60-0,87)
- Integrar `reserve_engine()` no worker para robustez
- Gerenciar `CUDA_VISIBLE_DEVICES` no switch de GPU
- Recalcular orçamento MTP conforme uso real

## Recursos

- Disco livre: 150 GB · RAM: 30 GB (27 GB disponível)
- cmake 4.2.3 · gcc 15.2.0 · CUDA 12.4.131 · driver 580.178.04