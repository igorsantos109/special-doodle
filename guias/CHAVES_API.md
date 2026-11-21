# CHAVES DE API — PC-SALA (192.168.1.184)

**Data:** 2026-11-21 | **Host:** PC-SALA | **Acesso:** 192.168.1.170 (via túnel SSH / firewall UFW)

---

## 🔑 CHAVES DE API ATIVAS

### Strata Engine (qwen36-q4-strata)
| Item | Valor |
|------|-------|
| **Provider** | Strata 0.2.9 (build 0.1.55) |
| **Modelo** | qwen3.6-35b-a3b-ud-q4_k_xl |
| **Endpoint LAN** | http://192.168.1.184:8098/v1 |
| **Endpoint Local (túnel)** | http://127.0.0.1:8098/v1 |
| **API Key** | `sk-strata-zhmxMe6u9RcjJmmI4ykiZ2meu7L5-H2J` |
| **Contexto** | 102400 tokens (100K) |
| **Headers** | `Authorization: Bearer sk-strata-zhmxMe6u9RcjJmmI4ykiZ2meu7L5-H2J` |
| **Content-Type** | application/json |

### PCSALA Local API (llama.cpp / ik_llama.cpp)
| Item | Valor |
|------|-------|
| **API Key** | `pcsala-open-no-auth` |
| **Header** | `Authorization: Bearer pcsala-open-no-auth` (opcional, aceito mas ignorado) |
| **Endpoints** | Ver tabela de modelos abaixo |

---

## 📋 ENDPOINTS POR MODELO (PC-SALA)

| Modelo | Porta | Endpoint LAN | Endpoint Local (túnel) | Auth |
|--------|-------|--------------|------------------------|------|
| **qwen36-q4-strata** | **8098** | http://192.168.1.184:8098/v1 | http://127.0.0.1:8098/v1 | **Bearer sk-strata-...** |
| qwen36-q4 (llama.cpp) | 8098 | http://192.168.1.184:8098/v1 | http://127.0.0.1:8098/v1 | Bearer pcsala-open-no-auth |
| qwen36-q3 | 8096 | http://192.168.1.184:8096/v1 | http://127.0.0.1:8096/v1 | Bearer pcsala-open-no-auth |
| qwen3-coder | 8084 | http://192.168.1.184:8084/v1 | http://127.0.0.1:8084/v1 | Bearer pcsala-open-no-auth |
| qwen38-gyro-s (Strata) | 8081 | http://192.168.1.184:8081/v1 | http://127.0.0.1:8081/v1 | Bearer sk-strata-... |
| qwen3-30b-a3b (CPU) | 8109 | http://192.168.1.184:8109/v1 | http://127.0.0.1:8109/v1 | Bearer pcsala-open-no-auth |
| maple-pro (CPU) | 8193 | http://192.168.1.184:8193/v1 | http://127.0.0.1:8193/v1 | Bearer pcsala-open-no-auth |
| qwen3-1.7b | 8103 | http://192.168.1.184:8103/v1 | http://127.0.0.1:8103/v1 | Bearer pcsala-open-no-auth |
| lfm2.5-1.2b | 8104 | http://192.168.1.184:8104/v1 | http://127.0.0.1:8104/v1 | Bearer pcsala-open-no-auth |
| qwen2.5-1.5b | 8105 | http://192.168.1.184:8105/v1 | http://127.0.0.1:8105/v1 | Bearer pcsala-open-no-auth |
| tiel-coder | 8087 | http://192.168.1.184:8087/v1 | http://127.0.0.1:8087/v1 | Bearer pcsala-open-no-auth |
| clover-35b | 8085 | http://192.168.1.184:8085/v1 | http://127.0.0.1:8085/v1 | Bearer pcsala-open-no-auth |
| mellum | 8086 | http://192.168.1.184:8086/v1 | http://127.0.0.1:8086/v1 | Bearer pcsala-open-no-auth |
| flint | 8094 | http://192.168.1.184:8094/v1 | http://127.0.0.1:8094/v1 | Bearer pcsala-open-no-auth |
| devstral | 8097 | http://192.168.1.184:8097/v1 | http://127.0.0.1:8097/v1 | Bearer pcsala-open-no-auth |
| glm47 | 8100 | http://192.168.1.184:8100/v1 | http://127.0.0.1:8100/v1 | Bearer pcsala-open-no-auth |
| qwenpi | 8110 | http://192.168.1.184:8110/v1 | http://127.0.0.1:8110/v1 | Bearer pcsala-open-no-auth |
| bonsai-27b | 8080 | http://192.168.1.184:8080/v1 | http://127.0.0.1:8080/v1 | Bearer pcsala-open-no-auth |
| bonsai-9b | 8090 | http://192.168.1.184:8090/v1 | http://127.0.0.1:8090/v1 | Bearer pcsala-open-no-auth |

---

## 🛡️ FIREWALL (UFW) — REGRAS ATIVAS PARA 192.168.1.170

Todas as portas acima estão liberadas no UFW para origem `192.168.1.170`:

```bash
# Verificar
sudo ufw status numbered | grep 192.168.1.170
```

Portas liberadas: 8080,8081,8084,8085,8086,8087,8088,8089,8090,8091,8092,8093,8094,8096,8097,8098,8099,8100,8102,8103,8104,8105,8106,8107,8108,8109,8110,8193

---

## 🔌 TÚNEL SSH — ACESSO LOCAL (127.0.0.1)

```bash
# Iniciar túnel (todas portas → 127.0.0.1:porta)
/home/igor/.local/bin/tunnel-pcsala start

# Verificar
/home/igor/.local/bin/tunnel-pcsala status
/home/igor/.local/bin/tunnel-pcsala test

# Parar
/home/igor/.local/bin/tunnel-pcsala stop
```

**Todas as APIs ficam disponíveis em `127.0.0.1:PORT` — apenas máquina local (192.168.1.170) acessa.**

---

## 🧪 TESTES RÁPIDOS

### Strata 100k (qwen36-q4-strata):
```bash
# Health check
curl http://127.0.0.1:8098/health
# {"status":"ok","max_context":102400,"model":"qwen3.6-35b-a3b-ud-q4_k_xl",...}

# Chat completion
curl -X POST http://127.0.0.1:8098/v1/chat/completions \
  -H "Authorization: Bearer sk-strata-zhmxMe6u9RcjJmmI4ykiZ2meu7L5-H2J" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b-ud-q4_k_xl","messages":[{"role":"user","content":"teste"}],"max_tokens":10}'
```

### llama.cpp / ik_llama.cpp (ex: qwen3-30b-a3b CPU):
```bash
curl http://127.0.0.1:8109/health
curl -X POST http://127.0.0.1:8109/v1/chat/completions \
  -H "Authorization: Bearer pcsala-open-no-auth" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-30b-a3b-moe-iq4k","messages":[{"role":"user","content":"teste"}],"max_tokens":10}'
```

---

## 📝 DSH PROVIDER CONFIG (cordis.patch.yml)

```yaml
# Strata 100k
qwen36-q4-strata:
  displayName: Qwen3.6-35B-A3B UD-Q4_K_XL Strata (PC-SALA:8098, 100K)
  apiKeyEnv: PCSALA_LOCAL_API_KEY
  api: openai-completions
  baseURL: http://192.168.1.184:8098/v1
  timeoutMs: 10800000
  streamIdleTimeoutMs: 5400000
  reasoning: off
  compat:
    supportsDeveloperRole: false
    maxTokensField: max_tokens
  models:
    - id: qwen3.6-35b-a3b-q4-xl-strata
      name: Qwen3.6-35B-A3B UD-Q4_K_XL Strata (100K)
      contextWindow: 102400
      maxTokens: 4096
      reasoning: off
      input: [text]

# llama.cpp / ik_llama.cpp (exemplo)
qwen3-30b-a3b:
  displayName: Qwen3-30B-A3B MoE IQ4_K CPU (PC-SALA:8109, 65K)
  apiKeyEnv: PCSALA_LOCAL_API_KEY
  api: openai-completions
  baseURL: http://192.168.1.184:8109/v1
  timeoutMs: 10800000
  streamIdleTimeoutMs: 5400000
  models:
    - id: qwen3-30b-a3b-moe-iq4k
      name: Qwen3-30B-A3B MoE IQ4_K CPU (65K)
      contextWindow: 65536
      maxTokens: 4096
      input: [text]
```

---

## ⚠️ NOTAS IMPORTANTES

1. **Strata requer API Key** — `Authorization: Bearer sk-strata-...`
2. **llama.cpp/ik_llama.cpp aceita `pcsala-open-no-auth`** — header opcional
3. **Túnel SSH bind 127.0.0.1** — apenas máquina local conecta
4. **Firewall UFW** — apenas 192.168.1.170 acessa portas no PC-SALA
5. **Strata 100k confirmado** — `max_context: 102400` no health check
6. **DSH GUI restart** após mudanças: `cd ~/.npm-global/lib/node_modules/@deepseek-ai/dsh && pnpm run dev:web`

---

**Arquivo:** `/home/igor/ia-sh/pc-sala-agent/guias/CHAVES_API.md`  
**Não versionar chaves sensíveis no Git** — este arquivo é para referência local apenas.