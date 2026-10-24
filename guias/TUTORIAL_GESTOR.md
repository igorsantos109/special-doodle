# Tutorial: Gestor de Modelos — PC-SALA-AGENT

Um guia simples e prático para usar o gestor de modelos de IA do `pc-sala`.

---

## O que você pode fazer

| Você quer... | Comando |
|---|---|
| Saber quais modelos existem | `ia list` |
| Ver o estado de tudo | `ia status` |
| Trocar o modelo da GPU | `ia solo <modelo>` |
| Iniciar um modelo CPU | `ia on <modelo>` |
| Verificar se um modelo está saudável | `ia health <modelo>` |
| Diagnóstico completo | `ia doctor` |

---

## Modelos disponíveis

### GPU (apenas UM por vez — exclusivo)

| Alias | Modelo | Porta | Quando usar |
|---|---|---|---|
| `bonsai` | Bonsai 27B + MTP | 8080 | **Padrão.** Raciocínio geral, tarefas do worker |
| `laguna-gpu` | Laguna XS 2.1 | 8082 | Programação, contexto longo (128K), ~47 tok/s |
| `ornith` | Ornith 35B | 8092 | Programação, ~40 tok/s |

### CPU (todos podem rodar ao mesmo tempo — compartilhado)

| Alias | Modelo | Porta | Quando usar |
|---|---|---|---|
| `bonsai-cpu` | Bonsai 9B | 8090 | Compressão de contexto, tarefas leves |
| `laguna` | Laguna XS 2.1 | 8091 | Programação (lento: 2.6 tok/s, mas sempre disponível) |

---

## Como trocar o modelo da GPU

O Bonsai é o modelo padrão e **já está rodando**. Se você quiser usar outro modelo:

### Para Laguna GPU

```bash
# Passo 1: Ver o estado atual
ia status

# Passo 2: Trocar para Laguna GPU
# (para o Bonsai, inicia o Laguna — leva ~1 minuto)
ia solo laguna-gpu

# Passo 3: Testar
curl -X POST http://192.168.1.150:8082/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"def hello","n_predict":50}'
```

### Para Ornith

```bash
ia solo ornith

# Testar
curl -X POST http://192.168.1.150:8092/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"def hello","n_predict":50}'
```

### Para voltar ao Bonsai

```bash
ia solo bonsai
```

### Pelo `pcsala` (equivalente)

```bash
./pcsala models switch laguna-xs-2.1-gpu
./pcsala models switch ornith-35b-gpu
./pcsala models switch bonsai-27b-gpu
```

---

## Qual modelo escolher?

| Prioridade | Escolha | Motivo |
|---|---|---|
| Tarefas do sistema (worker) | `bonsai` (GPU) | É o padrão, não trocar sem necessidade |
| Programação rápida | `laguna-gpu` | 47 tok/s, 128K contexto, código excelente |
| Programação (alternativa) | `ornith` | 40 tok/s, mas consome mais VRAM |
| Consulta rápida sem interromper | `laguna` (CPU) | 2.6 tok/s, sempre disponível, não ocupa GPU |
| Contexto muito longo | `laguna-gpu` | Até 128K tokens |

---

## Exemplos práticos

### 1. Gerar código com Laguna GPU

```bash
# Trocar para Laguna GPU
ia solo laguna-gpu

# Pedir uma função
curl -X POST http://192.168.1.150:8082/completion \
  -H "Content-Type: application/json" \
  -d '{
    "prompt":"Escreva uma função que valida CPF em Python:",
    "n_predict":200,
    "temperature":0.1
  }'
```

### 2. Resumo rápido com CPU (sem interromper a GPU)

```bash
curl -X POST http://192.168.1.150:8091/completion \
  -H "Content-Type: application/json" \
  -d '{
    "prompt":"Resuma em 3 linhas: O que é inteligência artificial?",
    "n_predict":100
  }'
```

### 3. Usar a fila de tarefas

```bash
# Enfileirar (usa o Bonsai GPU automaticamente)
./pcsala enqueue --prompt "Explique o que é Python"

# Ver resultado depois
./pcsala status 1
```

---

## Dicas importantes

- **GPU é recurso exclusivo.** Só um modelo GPU roda por vez. Trocar leva de 30s a 1min (precisa carregar o modelo).
- **CPU é compartilhado.** Todos os modelos CPU podem rodar juntos sem conflito.
- **Não pare CPUs.** O gestor bloqueia `ia off` em modelos CPU — eles são permanentes.
- **Worker parado.** Se o Bonsai foi trocado, o worker (fila automática) fica sem GPU. Volte ao Bonsai e reinicie: `sudo systemctl start pcsala-worker.service`
- **Se um modelo não responder**, verifique: `ia health <modelo>` ou `ia doctor`

---

## Solução de problemas

| Problema | Causa provável | Solução |
|---|---|---|
| `ia solo ornith` trava | GPU ocupada por Bonsai | `ia solo` gerencia a troca automaticamente |
| Health 503 | Modelo carregando | Aguardar 30-60s |
| Health 000 | GPU ocupada por outro processo | `nvidia-smi` para verificar |
| 401 Invalid API Key | Já não deve acontecer — API sem chave desde 2026-10-23 | Verificar `--api-key-file` no drop-in (`systemctl cat bonsai2-27b.service`) |
| Geração vazia ou erro | Prompt sem formato esperado | Usar template correto ou `--no-jinja`