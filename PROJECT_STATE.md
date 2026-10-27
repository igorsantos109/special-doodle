# Estado do projeto — 2026-10-23

## Modelos operacionais (6)

| Modelo | Porta | Ctx | Geração | Observações |
|---|---|---|---|---|
| Bonsai 27B GPU + MTP | 8080 | 64K | 28-48 tok/s | Primario, exclusivo (gpu-slot-1) |
| Bonsai 4B GPU | 8093 | 64K | — | Residente (nao habilitado no boot) |
| Bonsai 9B CPU | 8090 | 32K | 6,08 tok/s | Sem MTP |
| Laguna XS 2.1 CPU | 8091 | — | — | Desativado (libera RAM) |
| Laguna XS 2.1 GPU | 8082 | 128K | ~47 tok/s | Build Pascal; exclusivo (gpu-slot-1) |
| Ornith 35B GPU | 8092 | — | ~40 tok/s | PrismML; MTP experimental (24,7 tok/s, depth 2) |

## Coexistência GPU

Apenas o Bonsai 4B fica residente na GPU. O Bonsai 27B, Laguna GPU e
Ornith compoem o grupo exclusivo `gpu-slot-1`: apenas um fica carregado
por vez. O `switch` aplica-se apenas a modelos desse grupo. 4B nao eh
habilitado no boot.

VRam: `pcsala models vram` mostra a VRAM usada por modelo e a folga. `start`
e `switch` recusam o arranque se a folga for menor que 1,5 GB.

## Politica de acesso

API obrigatoria, API key nao. Firewall: ufw + nft `pcsala_api`, apenas 192.168.0.0/16.

## Comandos

```bash
./pcsala models list
./pcsala models switch bonsai-27b-gpu
./pcsala models vram
./pcsala health
./pcsala enqueue --prompt "texto"
./pcsala status <id>
./pcsala cancel <id>
./pcsala reconcile
./pcsala backup
```

## Proximos passos

- Worker: reiniciar quando GPU voltar ao Bonsai.
- Ornith MTP: integrar depende de autorizacao.
- Projetos reais no executor isolado.
- Laguna como padrao: alternativa ao Bonsai.
- Slot save/restore de KV (MROPE): desativado por default; validar num slot descartavel antes de ativar.
