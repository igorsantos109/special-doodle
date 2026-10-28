# Tutorial: Gestor de Modelos

## Comandos rápidos

| Quer... | Comando |
|---|---|
| Listar modelos | `./pcsala models list` |
| Ver estado | `./pcsala models status <id>` |
| Ver saúde | `./pcsala models health <id>` |
| Trocar GPU | `./pcsala models switch <id>` |
| Iniciar CPU | `./pcsala models start <id>` |
| Parar | `./pcsala models stop <id>` |

## Modelos

### GPU (exclusivo — um por vez)

| Alias | Modelo | Porta | Quando usar |
|---|---|---|---|
| `bonsai-27b-gpu` | Bonsai 27B + MTP | 8080 | padrão, raciocínio geral |
| `laguna-xs-2.1-gpu` | Laguna XS 2.1 | 8082 | programação, 128K ctx, ~47 tok/s |
| `ornith-35b-gpu` | Ornith 35B | 8092 | programação, ~40 tok/s |
| `nemotron-3.5-30b-gpu` | Nemotron 3.5 Ternary 30B | 8083 | leitura/RAG/síntese, 262K ctx; ≤32K interativo (≥73 tok/s), fraco em matemática |

### CPU (compartilhado)

| Alias | Modelo | Porta | Quando usar |
|---|---|---|---|
| `bonsai-9b-cpu` | Bonsai 9B | 8090 | tarefas leves, compressão |
| `laguna-xs-2.1-cpu` | Laguna XS 2.1 | 8091 | programação (2,6 tok/s) |

## Trocar para Laguna GPU

```bash
./pcsala models switch laguna-xs-2.1-gpu
curl -s http://127.0.0.1:8082/health
```

## Trocar para Nemotron

```bash
./pcsala models switch nemotron-3.5-30b-gpu
curl -s http://127.0.0.1:8083/health      # deve devolver 200

# ou, sem guarda e com confirmação, pelo gestor diário:
ia solo nemotron
```

As tarefas usam o perfil do modelo: `--profile nemotron-ternary-v1`.
Verifica a fila antes de trocar — o perfil `gpu-triage-v1` fica sem
servidor enquanto o Nemotron estiver sozinho na GPU.

## Voltar ao Bonsai

```bash
./pcsala models switch bonsai-27b-gpu
```

## Dica

Use `./pcsala health` para diagnóstico completo do sistema.
Para o gestor `ia` (estado, liga/desliga, `doctor`): `guias/GUIA_DIDATICA_IA.md`.