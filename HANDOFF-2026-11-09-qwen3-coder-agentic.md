# Handoff — Teste agêntico de programação do Qwen3-Coder-30B (ctx máximo)

## Objetivo
Avaliar o **Qwen3-Coder-30B-A3B** (`qwen3-coder-30b-a3b`, porta **8084**) para
**uso agêntico de programação**, em **contexto máximo (32 768 tokens)**:
geração de código, tool calling, restraint, agulha no palheiro em ~32K,
overflow limpo, concorrência e loop agêntico de 2 turnos.

## Estado actual (actualizado 2026-11-09 19:35)
- **Teste CONCLUÍDO (8/8)** — ver secção "Resultados" abaixo.
- **Estado actual: `bonsai2-27b.service` ATIVO (8080, pronto); `qwen3-coder.service` PARADO.**
  A máquina voltou ao padrão após o teste (rollback `ia solo bonsai`).
- Para repetir o teste: `printf 's\n' | ia solo qwen3-coder` (esperar /health,
  ~1-2 min para carregar os 17,3 GiB) e depois a suite.
- O slot `gpu-slot-1` é exclusivo: **não ligar nenhum outro modelo GPU**
  durante o teste.

## Contexto do modelo
| Campo | Valor |
|---|---|
| Aliases `ia` / `pcsala` | `qwen3-coder` (ia) — o `pcsala models` não o regista no registry |
| Unidade | `qwen3-coder.service` |
| Peso | `/home/igor/models/qwen3-coder-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` (17,3 GiB) |
| Binário | `/home/igor/opt/llama-cpp-nemotron/build/bin/llama-server` (llama.cpp b0.28.0, o único com arch `qwen3moe`) |
| Contexto | `-c 32768` (máximo), KV `q8_0`, `-fa on`, `-b 512 -ub 256`, `-ngl 99` |
| Tools | `--jinja` obrigatório (sem ele a API devolve 500 em `tools`) |
| API | OpenAI-compatível em `/v1/chat/completions` |

## Como executar o teste
```bash
cd /home/igor/pc-sala-agent
python3 scripts/test_qwen3_coder_agentic.py            # suite completa (~10 min)
python3 scripts/test_qwen3_coder_agentic.py --skip-overflow   # sem o T6
```
A suite (padrão da suíte maple-pro) executa:

| Teste | O que mede |
|---|---|
| T1 chat | resposta pt-BR coesa |
| T2 código | `parse_log_line` extraído do bloco e `compile()` sem SyntaxError |
| T3 tools | `get_weather` + `calculate` chamados com arguments JSON válidos |
| T4 restraint | sem tools → resposta directa, sem tool_call |
| T5 agulha 32K | prompt ~31K tokens (40 módulos), streaming: TTFT (prefill), tok/s decode, `finish_reason`, valor da agulha |
| T6 overflow | prompt ~40K tokens → erro limpo (400/length), **sem hang** |
| T7 concorrência | 3 requests paralelos → 3/200 |
| T8 loop agêntico | tool call → injeção de resultado → resposta final com o valor |

Saída: tabela no stdout + JSON em `/tmp/kilo/qwen3_coder_agentic_<ts>.json`.
Prompts completos: no próprio script (self-contained, std-lib).

## Limiares sugeridos (para o veredito)
| Critério | Limiar |
|---|---|
| Decode (T5, 32K) | ≥ 15 tok/s (referência: bonsai-27b 28-48 tok/s em 8080; MoE 3.3B activos deve superar) |
| Agulha 32K | 100 % (T5) |
| Overflow | erro limpo, < 60 s (T6) |
| Tool calling | T3 + T8 100 % |
| Concorrência | 3/3 (T7) |
| Código | compila (T2) |

## Resultados (2026-11-09 19:30, execução completa — 8/8)

| Teste | Resultado | Detalhe |
|---|---|---|
| T1 chat | ok | 1,9 s, finish stop |
| T2 código | ok | 2,4 s, função extraída e compila |
| T3 tools | ok | `get_weather` + `calculate`, arguments JSON válidos, 0,9 s |
| T4 restraint | ok | 0,5 s, sem tool_call |
| T5 agulha 32K | ok | **29 074 prompt tokens** (93 % da meta 31K, abaixo do teto 31 744); agulha correcta |
| T6 overflow | ok | HTTP 400 limpo em 0,9 s (sem hang) |
| T7 concorrência | ok | 3/3 |
| T8 loop agêntico | ok | resposta final correcta ("19 °C") |

### Desempenho (T5)
| Métrica | Fria (1.ª execução) | Repetida (prefixo em cache) |
|---|---|---|
| TTFT (prefill) | **94,8 s** (≈ 307 t/s) | 0,46 s |
| Decode | **24,5 tok/s** | 25,2 tok/s |
| Total | 95,8 s | 1,4 s |

> O servidor **faz cache do prefixo do prompt** entre requests (mesmo slot):
> a 2.ª execução do mesmo prompt de 29K não refaz o prefill. Para medir
> prefill frio, reiniciar o serviço (`systemctl restart qwen3-coder.service`)
> ou variar o prompt.

### Achado — fiabilidade do loop agêntico (T8)
Em 4 execuções do cenário de 2 turnos: 2 responderam limpo (apenas texto no
turno 2); **2 emitiram um tool_call extra (`calculate`) a juntar à resposta
final correcta**. A resposta final está sempre presente e correcta; um agente
com loop "até terminar sem tool_call" gastaria 1 turno extra em ~50 % dos casos
(temperatura 0,2). Ver `tool_calls_turno2` no JSON de evidência.

### Veredito
| Critério | Resultado | Limiar |
|---|---|---|
| Decode 32K | ✅ 24,5-25,2 tok/s | ≥ 15 |
| Agulha 32K | ✅ 100 % | 100 % |
| Overflow | ✅ 400 em < 1 s | limpo < 60 s |
| Tool calling | ✅ T3 100 %; T8 resposta correcta (loop extra ~50 %) | funcional |
| Concorrência | ✅ 3/3 | 3/3 |
| Código | ✅ compila | compila |

**Viável para uso agêntico de programação em contexto alto** (29K tokens),
com prefill frio lento na P40 (~95 s para 29K) e decode 24-25 tok/s. O loop
agêntico precisa de tratamento de tool_call repetido (rejeitar/ignorar a
repetição após resposta final).

### Evidência
- JSON: `/tmp/kilo/qwen3_coder_agentic_<ts>.json` (últimos: `1794254957`, `1794255025`)
- Logs: `/tmp/kilo/qwen3_t5t8.log`, `/tmp/kilo/qwen3_full.log`
- Prompt da agulha: `/tmp/kilo/needle_prompt.txt` (29 074 tokens)

## Restrições
- **Não parar/reiniciar o serviço** sem autorização; o estado actual (qwen3-coder
  activo, bonsai parado) é intencional para o teste.
- Endpoints: o serviço já está em `0.0.0.0`; não adicionar regras de firewall
  sem autorização.
- Não registar segredos; não alterar a unidade, o peso ou o binário.
- Registar a evidência (JSON + saída da suite) em `docs/` ou neste HANDOFF
  antes do rollback.

## Rollback (depois do teste, com evidência registada)
```bash
printf 's\n' | ia solo bonsai      # volta ao padrão (Bonsai 27B em 8080)
ia doctor
```

## Reversão
Nenhuma alteração no sistema: apenas leitura do serviço activo + criação deste
ficheiro e de `scripts/test_qwen3_coder_agentic.py` (removíveis por `git rm`).

## Última atualização
2026-11-09, sessão Kilo (troca GPU para qwen3-coder concluída, health OK).
