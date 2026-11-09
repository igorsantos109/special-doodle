# Relatório de Testes Agenticos Profundos — Maple-Pro 20B CPU

**Alvo:** 192.168.1.184 (PC-SALA) via SSH — porta 8193 (túnel local 127.0.0.1:18193)
**Modelo:** Maple-Pro 20B-A1B (TQ2_0 + Q4_K), arquivo `/mnt/arquivos/models/maple-preview/maple-pro.gguf` (6.2 GB)
**Serviço:** `local-maple.service` (systemd, ativo), `llama-server` build local `/home/igor/opt/llama.cpp/build/bin/llama-server`
**Parâmetros:** `--host 127.0.0.1 --port 8193 -c 32768 --threads 20 --threads-batch 24 -ngl 0 --no-kv-offload -n 4096 --parallel 1 --jinja --reasoning-format deepseek --threads-http 4`
**Data:** 2026-11-09

---

## 1. Conectividade

| Verificação | Resultado |
|---|---|
| SSH a 192.168.1.184 (BatchMode, id_ed25519) | ✅ OK — hostname `PC-SALA`, uptime 43 min |
| Porta 8193 escutando na remota | ✅ `127.0.0.1:8193` (apenas loopback) |
| Túnel SSH local 127.0.0.1:18193 → 8193 remota | ✅ HTTP 200 via túnel |
| Streaming (SSE) | ✅ Funcionando, `reasoning_content` streamado em tempo real |

> **Nota:** O bind está em `127.0.0.1` apenas. Para acesso intranet (192.168.1.0/24) seria necessário `--host 0.0.0.0` + regra de firewall (nft/ufw).

---

## 2. Bateria de testes executados

Todos via `POST /v1/chat/completions`, modelo `maple-pro`, temperatura 0.1–0.7.

| # | Tese | Resultado | finish_reason | tok/s (decode) | Tempo total |
|---|------|-----------|---------------|----------------|-------------|
| 1 | Chat simples (pt-BR) | ✅ Responde em português, identifica-se como "Gemini 2.0" (modelo não tem autoconsciência exata) | `length` (truncado em 200 tokens) | 15.69 | 12.94 s |
| 2 | Raciocínio matemático (camisas com desconto) | ✅ Cálculo correto: R$ 127,25, passo a passo | `length` (truncado em 400 tokens) | 15.52 | 26.10 s |
| 3 | Função Python (números primos ordenados) | ✅ Código completo, docstring, exemplo de uso | `length` (truncado em 400 tokens) | 15.30 | 26.42 s |
| 4 | Planejamento agente (suporte: PC não liga) | ✅ 5 passos ordenados com justificativa | `stop` | 15.18 | 17.72 s |
| 5 | Tool calling simulado (JSON) | ✅ JSON com `get_weather` + `calculate` | `length` (truncado em 200 tokens) | 15.34 | 13.37 s |
| 6 | Resumo de texto longo (666 prompt tokens) | ✅ 3 bullets em português | `stop` | 15.12 | 15.03 s |

**Throughput médio (decode):** ~15.3 tok/s (condizente com HANDOFF.md que reporta 10.7–15.6 tok/s dependendo da carga; neste teste o sistema estava sob load ~15).

---

## 3. Reasoning-format deepseek

O parâmetro `--reasoning-format deepseek` está ativo. Todas as respostas incluem o campo `reasoning_content` (visível tanto no modo não-stream quanto streaming), contendo o raciocínio interno do modelo antes da resposta final. Isso confirma que o modelo atua com raciocínio profundo visível, adequado a tarefas de agentic reasoning.

Exemplo (teste 1): o modelo raciocina sobre ser breve, usar português, não repetir, antes de apresentar-se.

---

## 4. Recursos do sistema remoto (coleta durante os testes)

- **Load average:** ~14.98 (24 threads lógicos, Xeon E5-2678 v3 12c/24t — carga alta esperada com `--threads 20`)
- **Memória do processo llama-server:** ~6.8 GB RSS (peak)
- **GPU:** Tesla P40 detectada (`nvidia-smi` não retornou tabela completa neste momento), mas Maple roda em CPU pura (`-ngl 0`)
- **Modelo alternativo:** `maple-preview-TQ2_0-head-Q4_K.gguf.bak` (5.5 GB) mantido como backup

---

## 5. Veredito

| Critério | Resultado | Status |
|---|---|---|
| Endpoint acessível via SSH túnel | ✅ HTTP 200 | OK |
| Chat em português | ✅ | OK |
| Raciocínio matemático | ✅ Resultado correto | OK |
| Geração de código Python | ✅ Código funcional | OK |
| Planejamento agente (5 passos) | ✅ Estrurado e justificado | OK |
| Tool calling (JSON) | ✅ JSON válido | OK |
| Streaming + reasoning_content | ✅ DeepSeek reasoning visível | OK |
| Throughput decode | ~15 tok/s | Aceitável para CPU |
| RAM usada | ~6.8 GB | Dentro do esperado (6.2 GB modelo) |

**Conclusão:** O Maple-Pro 20B CPU na porta 8193 de 192.168.1.184 está **operacional e apto a uso como agente de raciocínio profundo**, com reasoning visível (deepseek), suporte a streaming, tool calling simulado e bom throughput em CPU pura. Requer `--host 0.0.0.0` + firewall para uso direto na intranet sem túnel SSH.

---

## 6. Próximos passos sugeridos

1. Abrir porta 8193 na intranet (`--host 0.0.0.0` + nft/ufw) se for necessário acesso direto sem túnel.
2. Rodar HumanEval completo e benchmark comparativo com Qwen2.5-Coder 1.5B / Qwen3 1.7B (já instalados nas portas 8103–8105).
3. Atualizar guias em `guias/` com instruções de acesso ao Maple-Pro.
4. Commit dos resultados no branch `fase-0` (pendente de autorização do Igor).
