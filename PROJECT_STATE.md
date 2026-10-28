# Estado do projeto — 2026-10-28

## Modelos operacionais (7)

| Modelo | Porta | Ctx | Geração | Observações |
|---|---|---|---|---|
| Bonsai 27B GPU + MTP | 8080 | 64K | 28-48 tok/s | Primario, exclusivo (gpu-slot-1) |
| Bonsai 4B GPU | 8093 | 64K | — | Residente (nao habilitado no boot) |
| Bonsai 9B CPU | 8090 | 32K | 6,08 tok/s | Sem MTP |
| Laguna XS 2.1 CPU | 8091 | — | — | Desativado (libera RAM) |
| Laguna XS 2.1 GPU | 8082 | 128K | ~47 tok/s | Build Pascal; exclusivo (gpu-slot-1) |
| Ornith 35B GPU | 8092 | — | ~40 tok/s | PrismML; MTP experimental (24,7 tok/s, depth 2) |
| Nemotron 3.5 Ternary 30B | 8083 | 262K | 100 → 24,9 tok/s | Q2_0 ternario 8,82 GiB; exclusivo (gpu-slot-1); perfil `nemotron-ternary-v1`; enabled/parado |

## Coexistência GPU

Apenas o Bonsai 4B fica residente na GPU. O Bonsai 27B, Laguna GPU,
Ornith e Nemotron compoem o grupo exclusivo `gpu-slot-1`: apenas um fica
carregado por vez. O `switch` aplica-se apenas a modelos desse grupo.
4B nao eh habilitado no boot.

VRam: `pcsala models vram` mostra a VRAM usada por modelo e a folga. `start`
e `switch` recusam o arranque se a folga for menor que 1,5 GB. O Nemotron
usa 11253 MiB com `-c 262144` (KV pre-alocado): a P40 aguenta o maximo,
mas o prefill a 262144 fica em ~13-15 min — usar ≤32K para uso
interactivo.

## Gestores de modelos (2, não unificados)

- `ia` — operação diária rápida (`~/.local/bin/ia`,
  `~/.config/ia/modelos.conf`): `list/status/health/on/off/restart/solo/doctor`.
  6 modelos. **Guia: `guias/GUIA_DIDATICA_IA.md`.**
- `./pcsala models` — operações auditadas em SQLite com guarda de VRAM.

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
