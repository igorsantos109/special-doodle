# Teste — Bonsai 2 4B na Tesla P40

**Modelo:** `Ternary-Bonsai-2-4B-PQ2_0-MTP-Q8_0.gguf` (~1,27 GB; PQ2_0 com cabeca MTP embutida)
**Origem:** `prism-ml/Ternary-Bonsai-2-4B-gguf` (derivado do Qwen3.5-4B, atencao hibrida, contexto nativo 262K)
**Porta:** 8093 · **Servico:** `bonsai2-4b-gpu.service` (nao habilitado)

## Requisitos

- Build Pascal (`prism-pascal-build`). PQ2_0 e rejeitado pelo llama.cpp oficial.
- Carregar o arquivo MTP no lugar do PQ2_0 simples, nunca os dois.
- Coexiste com o Bonsai 27B (~13 GB): somados, ficam bem abaixo dos 23 GB.

## Instalacao (bash)

```bash
mkdir -p ~/models/bonsai-2-4b
hf download prism-ml/Ternary-Bonsai-2-4B-gguf \
  Ternary-Bonsai-2-4B-PQ2_0-MTP-Q8_0.gguf --local-dir ~/models/bonsai-2-4b
sha256sum ~/models/bonsai-2-4b/*.gguf
sudo cp bonsai2-4b-gpu.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start bonsai2-4b-gpu.service
```

## Verificacao

```bash
curl -s http://127.0.0.1:8093/health
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
journalctl -u bonsai2-4b-gpu.service -n 50 --no-pager
```

## Medicao

```bash
~/opt/prism-pascal-build/build/bin/llama-bench \
  -m ~/models/bonsai-2-4b/Ternary-Bonsai-2-4B-PQ2_0-MTP-Q8_0.gguf \
  -ngl 99 -p 8192 -n 128
```

Registrar: prompt eval (tok/s), geracao (tok/s), aceitacao MTP, VRAM e se o 27B perdeu velocidade com os dois ativos.

## Pendencias

- Registro no ModelCoordinator (`pcsala models`): o codigo-fonte (`src/`) nao esta no repositorio.
- Se o patch Pascal recusar a cabeca MTP embutida, remover a linha `--spec-type` e testar sem MTP.
- Rever os caminhos do binario e do modelo se diferirem do host.
- Se `-c 65536` falhar, reduzir para 32768.
