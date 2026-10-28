#!/bin/bash
# Warm-up do Bonsai 2 27B MTP: espera pelo /health e gera tokens para
# montar CUDA graphs e rampar os clocks da P40 antes do primeiro cliente.
# Executado por ExecStartPost do bonsai2-27b.service. Saida vai para o journal.
# Os modelos nao exigem API key; se existir, e apenas enviada por compatibilidade.
set -u

URL="http://127.0.0.1:8080"
KEY_FILE="/home/igor/.config/pcsala-bonsai/api.key"
HEALTH_TIMEOUT=150
GEN_TIMEOUT=120

echo "[warmup] $(date -Is) aguardar servir $URL"

AUTH_HEADER=(-H "Content-Type: application/json")
if [ -r "$KEY_FILE" ]; then
    AUTH_HEADER=(-H "Content-Type: application/json" -H "Authorization: Bearer $(cat "$KEY_FILE")")
fi

ready=0
for _ in $(seq 1 "$HEALTH_TIMEOUT"); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$URL/health" 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then ready=1; break; fi
    sleep 1
done

if [ "$ready" != "1" ]; then
    echo "[warmup] ABORT: /health nao respondeu em ${HEALTH_TIMEOUT}s"
    exit 0
fi

echo "[warmup] servico de saude OK, a gerar para aquecer CUDA graphs e clocks"
start=$SECONDS

code=$(curl -s -o /tmp/bonsai-warmup-body.json --max-time "$GEN_TIMEOUT" -w '%{http_code}' -X POST \
    "${AUTH_HEADER[@]}" \
    -d '{"prompt":"Escreva um texto detalhado de trezentas palavras sobre quantizacao ternaria de modelos de linguagem, com exemplos e detalhes tecnicos.","n_predict":400,"temperature":0.8,"cache_prompt":false,"stream":false}' \
    "$URL/completion" 2>/dev/null || echo 000)

elapsed=$((SECONDS - start))

if [ "$code" = "200" ]; then
    tokens=$(grep -o '"predicted_n":[0-9]*' /tmp/bonsai-warmup-body.json 2>/dev/null | cut -d: -f2)
    rate=$(grep -o '"predicted_per_second":[0-9.]*' /tmp/bonsai-warmup-body.json 2>/dev/null | cut -d: -f2)
    echo "[warmup] OK em ${elapsed}s - ${tokens:-?} tokens, ${rate:-?} tok/s"
else
    echo "[warmup] AVISO: resposta ${code} em ${elapsed}s"
fi

rm -f /tmp/bonsai-warmup-body.json
exit 0
