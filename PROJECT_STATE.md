# Estado do projeto — 2026-10-23

## Modelos operacionais (5)

| Modelo | Porta | Ctx | Geração | Observações |
|---|---|---|---|---|
| Bonsai 27B GPU + MTP | 8080 | 55K | 28-48 tok/s | Primário |
| Bonsai 9B CPU | 8090 | 32K | 6,08 tok/s | Sem MTP |
| Laguna XS 2.1 CPU | 8091 | — | — | Desativado (libera RAM) |
| Laguna XS 2.1 GPU | 8082 | 128K | ~47 tok/s | Build Pascal; desativado |
| Ornith 35B GPU | 8092 | — | ~40 tok/s | PrismML; MTP experimental (24,7 tok/s, depth 2) |

## Política de acesso

API obrigatória, API key não. Firewall: ufw + nft `pcsala_api`, apenas 192.168.0.0/16.

## Comandos

```bash
./pcsala models list
./pcsala models switch bonsai-27b-gpu
./pcsala health
./pcsala enqueue --prompt "texto"
./pcsala status <id>
./pcsala cancel <id>
./pcsala reconcile
./pcsala backup
```

## Próximos passos

- Worker: reiniciar quando GPU voltar ao Bonsai.
- Ornith MTP: integrar depende de autorização.
- Projetos reais no executor isolado.
- Laguna como padrão: alternativa ao Bonsai.