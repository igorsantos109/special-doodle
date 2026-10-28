# GUIA MESTRE — PC-SALA-AGENT (v8.3 compacto)

**Data:** 28/10/2026 · **Host:** `pc-sala` (192.168.1.150) · **GPU:** Tesla P40 23 GB

## Arquitetura

```
CLI pcsala / ia  →  Worker (LangGraph) / ModelCoordinator
                     →  llama-server (inferencia)
```

## Hardware

| Componente | Especificação |
|---|---|
| CPU | Xeon E5-2697 v4, 36 threads @ 2.30 GHz |
| RAM | 30 GiB (~16 GiB livre) |
| GPU | Tesla P40 23.040 MiB, CC 6.1, driver 580.178.04 |
| CUDA | 12.4.131 |

## Modelos

| Modelo | Porta | Ctx | Gen tok/s | Estado |
|---|---|---|---|---|
| Bonsai 27B GPU + MTP | 8080 | 64K | 28-48 | primario, exclusivo (gpu-slot-1) |
| Bonsai 4B GPU | 8093 | 64K | — | residente, nao no boot |
| Bonsai 9B CPU | 8090 | 32K | 6,08 | ativo |
| Laguna XS 2.1 CPU | 8091 | — | 2,6 | desativado |
| Laguna XS 2.1 GPU | 8082 | 128K | ~47 | desativado, exclusivo (gpu-slot-1) |
| Ornith 35B GPU | 8092 | — | ~40 | desativado, exclusivo (gpu-slot-1) |
| **Nemotron 3.5 Ternary 30B** | 8083 | 262K | 24,9-100 | desativado, exclusivo (gpu-slot-1) |

GPU exclusiva para modelos grandes — um por vez (27B, Laguna, Ornith, Nemotron).
Apenas o Bonsai 4B fica residente na GPU.

### Bonsai 27B (primario)
- Modelo: `Ternary-Bonsai-2-27B-PQ2_0.gguf` (6,8 GB) + drafter MTP (1 GB)
- Build: `5d80cff0b` (PrismML + patch Pascal), binario `prism-pascal-build/build/bin/llama-server`
- Flags: `-c 64000 -ngl 99 -t 8 -n 2048 --flash-attn on`, MTP `--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-p-min 0.4`, `--slot-save-path /var/lib/pcsala-worker/slots`
- VRAM: ~12,9 GB · Prompt eval: 126-243 tok/s · Aceitacao MTP: 0,60-0,87
- `--cache-reuse` e `--context-shift` **não suportados** (rope MROPE)
- Sem `--api-key-file` (docs dizem "API key nao"); `--no-kv-offload` removido.

### Bonsai 4B (residente)
- Porta 8093, build Pascal, mesmo binario, `--slot-save-path` habilitado.
- Nao habilitado no boot; iniciar manualmente quando necessario.

### Bonsai 9B CPU
- Modelo: `Ternary-Bonsai-2-9B-PQ2_0.gguf` (2,4 GB), 32 threads
- **MTP impossível**: sem cabeça drafter e build CPU sem caminho NEXTN

### Laguna XS 2.1
- CPU: 2,6 tok/s, 17,9 GB RAM. GPU (Pascal): `-ngl 40`, 128K ctx, ~47 tok/s, 15-21 GB VRAM
- GGUF: `Laguna-XS-2.1-APEX-I-Compact.gguf` (15 GB), SHA-256 `b674541d…05d2`

### Ornith 35B
- GGUF: `ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` (21 GB)
- PrismML: 40 tok/s (sem MTP). llama.cpp oficial + MTP: 24,7 tok/s, 74% aceitacao, depth 2

### Nemotron 3.5 Ternary 30B (novo, 28/10)
- Modelo: `boro64/Ternary-Nemotron-3.5-Lightning-30B-A3B-GGUF` — `nemotron_h_moe`,
  pesos Q2_0 ternarios (8,82 GiB), embeddings/lm_head Q8_0, SHA-256 `38854de6…4f3`
- GGUF: `/home/igor/models/ternary-nemotron-3.5-30b-a3b/Ternary-Nemotron-3.5-Lightning-30B-A3B-GGUF.gguf`
- Build: llama.cpp `c3df4b7` fresco (unico com `nemotron_h_moe`), binario
  `/home/igor/opt/llama-cpp-nemotron/build/bin/llama-server`
- Compilacao: CUDA **12.4.131** (12.x obrigatorio; 13+ nao suporta Pascal),
  `-DCMAKE_CUDA_ARCHITECTURES=61` (cubins sm_61 confirmados por cuobjdump),
  host `gcc-13` porque o nvcc 12.4 rejeita o gcc 15
- Flags: `-c 262144 -np 1 -ngl 99 -fa on -ub 2048 --cache-type-k q8_0 --cache-type-v q8_0 -t 8 --no-jinja`
- Unidade `nemotron.service` (porta 8083, `enable`, perfil `nemotron-ternary-v1`)
- VRAM: **11253 MiB** constantes (KV de 262144 pre-alocado, nao cresce com o uso)
- Desempenho medido (P40): geracao 100 tok/s (ctx curto) -> 90,8 (8K) ->
  73,3 (32K) -> 56,2 (66K) -> 41,4 (134K) -> 24,9 (200K); prefill 1514 ->
  1098 -> 817 -> 537 -> 399 tok/s. Extrap. 262144: prefill 13-15 min,
  geracao 15-25 tok/s.
- **Viabilidade do contexto maximo**: memoria OK (11,3 de 23 GB), tempo
    nao. Recomendado <=32K interactivo; 64-128K para ingestao de fundo.
  - **Contexto declarado no cliente**: `contextWindow: 66000` (dsh/kilocode)
    desde 2026-10-28, com `maxTokens: 4096` -> 70096 < 262144 do servidor.
    Verificado com 66755 tokens reais: HTTP 200, prefill 81,7 s (56,2 tok/s)
    e geracao 56,2 tok/s. Aos 32K ainda sao 73,3 tok/s e prefill 30 s: a
    diferenca e' latencia, nao capacidade. Regra de compactacao: 66000-4096
    = 61904 tok de prompt.
- Regras de uso: `pcsala enqueue --profile nemotron-ternary-v1`; trocar
  com `ia solo nemotron` ou `./pcsala models switch nemotron-3.5-30b-gpu`
- Reproduzir: `scripts/bench_nemotron.py`, `scripts/bench_contexto_max.py`

## Comandos

```bash
./pcsala models list
./pcsala models status <id>
./pcsala models health <id>
./pcsala models start <id>
./pcsala models stop <id>
./pcsala models switch <id>   # apenas modelos exclusivos (27B, Laguna GPU, Ornith, Nemotron)
./pcsala models vram          # VRAM por modelo e folga
./pcsala models operation <id>
./pcsala health
./pcsala enqueue --prompt "texto" [--profile nemotron-ternary-v1]
./pcsala status <id>
./pcsala cancel <id>
./pcsala reconcile
./pcsala backup
```

Gestor diario `ia` (operacao rapida, sem guardas de VRAM): ver
`guias/GUIA_DIDATICA_IA.md` — `ia list`, `ia status`, `ia health <m>`,
`ia on/off <m>`, `ia solo <m>`, `ia doctor`.

## Serviços systemd

| Serviço | Porta | Estado |
|---|---|---|
| `bonsai2-27b.service` | 8080 | active |
| `bonsai-4b-gpu.service` | 8093 | disabled (residente, nao no boot) |
| `bonsai2-cpu.service` | 8090 | active |
| `laguna.service` | 8091 | disabled |
| `laguna-gpu.service` | 8082 | disabled |
| `ornith.service` | 8092 | disabled |
| `nemotron.service` | 8083 | disabled (enabled; parado) |
| `pcsala-worker.service` | — | worker contínuo |

Lock de troca de GPU: `/run/pcsala/pcsala-gpu-switch.lock`.

### Permissões (sem sudo)

Duas peças obrigatórias para gerir modelos como `igor`:

1. **`/etc/tmpfiles.d/pcsala.conf`** — cria `/run/pcsala` (`igor:igor`) no
   arranque; sem ela o `switch` falha com `PermissionError: '/run/pcsala'`.
2. **`/etc/polkit-1/rules.d/50-pcsala.rules`** — autoriza `igor` a
   `start|stop` das units listadas. Obrigatorio: comentarios em **`//`**
   (um `#` provoca `SyntaxError` e o polkit ignora a regra em silencio),
   unidade via `action.lookup("unit")` (nao `action.subject`), e a
   unidade alvo presente em `allowed_units`.

Instalacao:
```bash
sudo install -D -m 0644 deploy/tmpfiles/pcsala.conf /etc/tmpfiles.d/pcsala.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/pcsala.conf
sudo install -m 0644 deploy/polkit/50-pcsala.rules /etc/polkit-1/rules.d/
sudo systemctl restart polkit
```
Verificacao: `systemctl --no-ask-password stop nemotron.service` (permitido)
e `systemctl --no-ask-password stop ssh.service` (tem de negar).

Firewall: `pcsala-bonsai-firewall.service` (nftables, persiste no reboot), regra `pcsala_api` permite apenas 192.168.0.0/16.

## API

API obrigatória, **API key não**. `Authorization` aceite mas ignorado.

## Slot save/restore de KV (documentos longos)

Subiu os serviços com `--slot-save-path`. O worker chama `POST /slots/<id>?action=save|restore` em tarefas "document" com prefixo repetido.

**Desativado por default.** Ativar apenas (`PCSALA_SLOT_SAVE_RESTORE=1`) apos validar num slot descartavel se o MROPE aceita o restauro. Se nao aceitar, registrar neste guia e manter desativado.

## Limites

- Nenhum executor privilegiado; preparacao segura de diretorios pendente.
- Tetos de saida/armazenamento apenas declarados no perfil.
- Checkpoints/arquivos/Git nao formam transacao conjunta.
- Nao executar planos do orquestrador como root.
