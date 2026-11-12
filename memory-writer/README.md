# Memory Writer — pipeline de memória de longo prazo

Arquitetura "memory writer como função de extração": o agente de chat não extrai
memórias sozinho; ele chama a tool MCP `memory_extract_and_store` com a conversa,
e o writer LLM (endpoint trocável — hoje Gyro-S na P40, amanhã Hy-Memory-30B-A3B)
devolve `{"memories": [...]}` que é gravado no SQLite.

## Arquivos

| Arquivo | Descrição |
|---|---|
| `memory_writer_mcp.py` | Servidor MCP (stdio, JSON-RPC 2.0). Tools: `memory_extract_and_store`, `memory_write`, `memory_read`, `memory_search`, `memory_delete`. |
| `run_memory_tests.py` | Harness que valida as 4 regras do system prompt contra qualquer endpoint OpenAI-compatible. |
| `strata-mcp-memory.json` (no remoto: `~/strata-mcp-memory.json`) | Config MCP para plugar o writer no servidor Strata. |

## System Prompt (4 regras)

```
1. Extract ONLY facts EXPLICITLY stated. Do not infer or invent.
2. Each memory = concise, self-contained statement (no unresolved pronouns).
3. Ignore greetings, small talk, transient emotions, one-off opinions.
4. Return ONLY a JSON object: {"memories": ["...", "..."]}
```

## Resultados dos testes (2026-11-12, PC-SALA)

| Writer | Endpoint | Regra 1 (sem inferência) | Regra 2 (autossuficiente) | Regra 3 (sem ruído) | Regra 4 (JSON) | Tempo | tok/s decode |
|---|---|---|---|---|---|---|---|
| **Gyro-S (58 GB, P40)** | 8081 | ✅ 6/6 fatos | ✅ | ✅ | ✅ 4 memórias | 37 s | 5,4 |
| qwen3-1.7b CPU | 8103 | ❌ (memórias em inglês, teste esperava pt; conteúdo ok) | ✅ | ✅ | ✅ 5 memórias | 19,5 s | 15,2 |
| lfm2.5-1.2b CPU | 8104 | ✅ 6/6 | ✅ | ❌ (deixou "cansado", "segunda-feira") | ✅ 6 memórias | 12,7 s | 25,2 |

**Conclusão:** Gyro-S foi o único com 4/4 regras no teste em português. lfm2.5 é
2x mais rápido mas viola a regra 3 (não filtra small talk). qwen3-1.7b extraiu
corretamente mas em inglês (language matching fraco em modelo pequeno).

## Como usar

### 1. Standalone (sem Strata MCP)
```bash
# extrair e gravar:
echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"memory_extract_and_store","arguments":{"project":"meu-projeto","conversation":"..."}},"id":1}' \
  | python3 memory_writer_mcp.py

# ler / buscar:
echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"memory_read","arguments":{"project":"meu-projeto"}},"id":2}' \
  | python3 memory_writer_mcp.py
```

### 2. Integrado ao servidor Strata (web app / agentes com `strata_mcp: true`)
```bash
# No PC-SALA, com o Gyro-S parado:
strata launch --model-path /mnt/arquivos/models/qwen38-gyro-s \
  --model gyro-s --family gyro --context 32k --kv int8 --vision off \
  --gpu 0 --port 8081 --access local --mtp on --tune skip --no-tui --yes \
  --set mcp_config=/home/igor/strata-mcp-memory.json
# Requests com "strata_mcp": true ganham as tools memory_* automaticamente.
```

### 3. Trocar o writer LLM (ex.: quando o Hy-Memory-30B-A3B chegar)
Só mudar as env vars do MCP server:
```bash
MEMORY_WRITER_ENDPOINT=http://127.0.0.1:8082/v1/chat/completions \
MEMORY_WRITER_MODEL=hy-memory-30b-a3b \
MEMORY_WRITER_TEMPERATURE=0.6 \
python3 memory_writer_mcp.py
```

## Variáveis de ambiente

| Var | Padrão | Descrição |
|---|---|---|
| `MEMORY_DB` | `~/.local/share/pc-sala-agent/memory.db` | Caminho do SQLite |
| `MEMORY_WRITER_ENDPOINT` | `http://127.0.0.1:8081/v1/chat/completions` | Endpoint do writer |
| `MEMORY_WRITER_MODEL` | `qwen3.8-flash-next-gyro-gyro-s` | Modelo writer |
| `MEMORY_WRITER_TEMPERATURE` | `0.6` | Temperatura (consistência) |
| `MEMORY_WRITER_MAX_TOKENS` | `1024` | Limite de saída |
| `MEMORY_WRITER_TIMEOUT_S` | `600` | Timeout da chamada |

## Notas

- O writer é desacoplado: qualquer endpoint OpenAI-compatible serve.
- Temperatura 0.6 recomendada para extração estruturada consistente.
- Para baixa latência, habilitar `reasoning_effort: "no_think"` no body
  (nem todos os endpoints suportam; o Strata aceita via campo extra).
- Contexto longo (até 262K no Hy-Memory) permite alimentar várias sessões
  de uma vez — o Gyro-S atual está limitado a 32K.
