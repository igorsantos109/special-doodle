# HANDOFF DEV — PC-SALA Model Management
**Para:** AI Developer | **Host:** PC-SALA (192.168.1.184) | **GPU:** Tesla P40 24GB | **CPU:** Xeon E5-2678 v3 (24T, 128GB RAM)
**Última atualização:** 2026-11-21 | **Versão:** 1.0

---

## 1. ARQUITETURA RÁPIDA

```
┌─────────────────────────────────────────────────────────────┐
│  LOCAL (192.168.1.170)           PC-SALA (192.168.1.184)   │
│  ─────────────────────           ────────────────────────  │
│  ~/.local/bin/ia  ◄──SSH──►  ~/.local/bin/ia                │
│  ~/.config/ia/modelos.conf       ~/.config/ia/modelos.conf  │
│  tunnel-pcsala (127.0.0.1:*)     systemd services           │
│  DSH providers (HTTP)            llama-server / Strata      │
└─────────────────────────────────────────────────────────────┘
```

**Regra de ouro:** IA manager local gerencia **endpoints HTTP**; systemd roda **no PC-SALA**.

---

## 2. MODELOS ATUAIS — REFERÊNCIA RÁPIDA

### GPU (exclusivo `gpu-slot-1` — apenas 1 por vez)
| Alias | Modelo | Porta | Engine | Contexto | VRAM | Comando |
|-------|--------|-------|--------|----------|------|---------|
| `qwen36-q4` | Qwen3.6-35B UD-Q4_K_XL | 8098 | llama.cpp | 55k | ~21GB | `ia solo qwen36-q4` |
| **`qwen36-q4-strata`** | **Qwen3.6-35B UD-Q4_K_XL** | **8098** | **Strata 0.1.55** | **100k** | **~22.3GB** | **`ia solo qwen36-q4-strata`** |
| qwen36-q3 | Qwen3.6-35B UD-Q3_K_XL | 8096 | llama.cpp | 55k | ~16GB | `ia solo qwen36-q3` |
| qwen38-gyro-s | Qwen3.8 Gyro-S | 8081 | Strata | 32k | ~21GB | `ia solo gyro-s` |
| ttf-qwen38 | TTF Qwen3.8 27B | 8108 | ttf-home | 32k | ~7.7GB | `ia solo ttf-qwen38` |
| qwen3-coder | Qwen3-Coder 30B | 8084 | llama.cpp | 32k | ~17GB | `ia solo qwen3-coder` |
| clover-35b | Clover 35B Block-Diff | 8085 | llama.cpp | 32k | ~20GB | `ia solo clover-35b` |
| mellum | Mellum 12B | 8086 | llama.cpp | 64k | ~12GB | `ia solo mellum` |
| flint | Flint APEX-I | 8094 | llama.cpp | 32k | ~22GB | `ia solo flint` |
| devstral | Devstral 2507 | 8097 | llama.cpp | 32k | ~8GB | `ia solo devstral` |
| potato-coder | Potato 12GB | 8099 | llama.cpp | 55k | ~10GB | `ia solo potato-coder` |
| glm47 | GLM-4.7-Flash 30B | 8100 | llama.cpp | 64k | ~18GB | `ia solo glm47` |
| fusion4 | PXA Fusion4 35B | 8102 | llama.cpp | 32k | ~20GB | `ia solo fusion4` |
| ttf-qwen38 | TTF Qwen3.8 27B | 8108 | ttf-home | 32k | ~7.7GB | `ia solo ttf-qwen38` |
| qwenpi | Qwen3.8 Pi-Adapted | 8110 | llama.cpp | 32k | ~15GB | `ia solo qwenpi` |

### CPU (todos simultâneos)
| Alias | Modelo | Porta | Engine | Contexto | RAM |
|-------|--------|-------|--------|----------|-----|
| `maple-pro` | Maple-Pro 20B-A1B | 8193 | llama.cpp YARN | 65k | ~1.3GB |
| `qwen3-30b-a3b` | Qwen3-30B-A3B MoE IQ4_K | 8109 | ik_llama.cpp YARN | 65k | ~21GB |
| `qwen3-1.7b` | Qwen3-1.7B | 8103 | llama.cpp | 8k | ~1.5GB |
| `lfm2.5-1.2b` | LFM2.5-1.2B | 8104 | llama.cpp | 32k | ~1GB |
| `qwen2.5-1.5b` | Qwen2.5-1.5B | 8105 | llama.cpp | 32k | ~1.2GB |
| `phi35-mini` | Phi-3.5-mini | 8106 | llama.cpp | 4k | ~0.8GB |
| `smollm2-1.7b` | SmolLM2-1.7B | 8107 | llama.cpp | 8k | ~1GB |
| `bonsai-9b` | Bonsai 9B | 8090 | llama.cpp | 32k | ~5GB |

---

## 3. IA MANAGER — COMANDOS ESSENCIAIS

### No PC-SALA (via SSH):
```bash
ssh igor@192.168.1.184 ia list           # lista todos
ssh igor@192.168.1.184 ia status <alias>  # status + health
ssh igor@192.168.1.184 ia health <alias>  # só GET /health
ssh igor@192.168.1.184 ia on <alias>      # systemctl start
ssh igor@192.168.1.184 ia off <alias>     # systemctl stop
ssh igor@192.168.1.184 ia restart <alias> # systemctl restart
ssh igor@192.168.1.184 ia solo <alias>    # GPU: para atual, sobe solicitado
ssh igor@192.168.1.184 ia doctor          # diagnóstico completo
```

### Local (túnel ativo):
```bash
ia list              # lê ~/.config/ia/modelos.conf local
ia health <alias>    # HTTP GET em 192.168.1.184:porta
ia doctor            # HTTP checks + systemd local (limitado)
```

---

## 4. TÚNEL SSH — APIs LOCAIS

```bash
# Iniciar (mantém vivo via ControlMaster)
/home/igor/.local/bin/tunnel-pcsala start

# Verificar
/home/igor/.local/bin/tunnel-pcsala status
/home/igor/.local/bin/tunnel-pcsala test

# Parar
/home/igor/.local/bin/tunnel-pcsala stop
```

**Todas as APIs ficam em `127.0.0.1:porta` — apenas máquina local acessa.**

---

## 5. ADICIONAR NOVO MODELO — CHECKLIST COMPLETO

### 5.1 Preparar pesos (GGUF)
```bash
# No PC-SALA
cd /home/igor/models
mkdir -p meu-modelo
# Colocar .gguf aqui ou symlink para /mnt/arquivos/models/
```

### 5.2 Criar systemd service
```bash
# Template: /home/igor/ia-sh/pc-sala-agent/qwen36-q4.service (llama.cpp)
#          /etc/systemd/system/qwen36-q4-strata.service (Strata)

# Copiar e editar:
sudo cp /home/igor/ia-sh/pc-sala-agent/TEMPLATE.service /etc/systemd/system/meu-modelo.service
sudo systemctl daemon-reload
sudo systemctl enable meu-modelo.service
```

**Campos obrigatórios no service:**
- `ExecStart` com caminho correto do binário + `-m /path/modelo.gguf`
- `--port PORT` livre (ver `ss -ltnp`)
- `-ngl 99` (GPU) ou `-ngl 0 --threads 20` (CPU)
- `--jinja` (obrigatório para tools)
- `Conflicts=` com outros GPU se exclusivo
- `Wants=network-online.target`

### 5.3 Registrar no IA Manager (PC-SALA)
```bash
# Editar ~/.config/ia/modelos.conf no PC-SALA
# Adicionar objeto JSON no array:
{
  "alias": "meu-alias",
  "model_id": "meu-modelo-id",
  "name": "Meu Modelo Display Name",
  "unit": "meu-modelo.service",
  "endpoint": "http://127.0.0.1:PORT",
  "class": "GPU",  // ou "CPU"
  "exclusive_group": "gpu-slot-1",  // null se CPU
  "profile": "perfil-inferencia",
  "shared": false,  // true se residente CPU
  "startup_timeout": 180
}
```

### 5.4 Registrar no pcsala models (auditado)
```bash
# Em src/pcsala_agent/model_manager.py
# Adicionar ModelSpec no ModelRegistry.__init__

# Em src/pcsala_agent/inference_profiles.py
# Adicionar ProfileConfig se novo perfil necessário
```

### 5.5 Validar
```bash
# No PC-SALA
python3 -c "
import json
raw = open('/home/igor/.config/ia/modelos.conf').read()
body = '\n'.join(l for l in raw.splitlines() if not l.strip().startswith('#'))
d = json.loads(body)
print(f'OK: {len(d)} modelos')
for m in d:
    print(f'  {m[\"alias\"]:20s} -> {m[\"endpoint\"]} ({m[\"class\"]})')
"

# Testar service
sudo systemctl start meu-modelo.service
sleep 10
curl http://127.0.0.1:PORT/health
ssh igor@192.168.1.184 ia status meu-alias
```

---

## 6. REMOVER MODELO — CHECKLIST

```bash
# 1. Parar e desabilitar service
sudo systemctl stop meu-modelo.service
sudo systemctl disable meu-modelo.service
sudo rm /etc/systemd/system/meu-modelo.service
sudo systemctl daemon-reload

# 2. Remover do IA Manager (PC-SALA)
# Editar ~/.config/ia/modelos.conf — remover objeto do array

# 3. Remover do pcsala models
# src/pcsala_agent/model_manager.py — remover ModelSpec
# src/pcsala_agent/inference_profiles.py — remover ProfileConfig se órfão

# 4. Limpar pesos (opcional)
rm -rf /home/igor/models/meu-modelo
# ou rm /mnt/arquivos/models/meu-modelo

# 5. Validar
python3 -c "import json; raw=open('/home/igor/.config/ia/modelos.conf').read(); body='\n'.join(l for l in raw.splitlines() if not l.strip().startswith('#')); d=json.loads(body); print(f'OK: {len(d)} modelos')"
```

---

## 7. STRATA ESPECÍFICO — 100K CONTEXTO

### Configuração validada (qwen36-q4-strata):
```bash
# Preset Strata:
launch-qwen36-ud-q4-100k-cpu-offload
# Profile: launch-qwen36-ud-q4-100k-cpu-offload
# Config: 100k ctx, KV q4_0, STRATA_PIN_BY_NEED=1, --gpu-roles 0=main, MTP on

# Service systemd (Type=oneshot, RemainAfterExit=yes):
ExecStartPre=/home/igor/.local/bin/strata runtime stop --profile launch-qwen36-ud-q4-100k-cpu-offload
ExecStart=/home/igor/.local/bin/strata runtime start --profile launch-qwen36-ud-q4-100k-cpu-offload
ExecStop=/home/igor/.local/bin/strata runtime stop --profile launch-qwen36-ud-q4-100k-cpu-offload
RemainAfterExit=yes
```

### Testar 100k:
```bash
curl http://192.168.1.184:8098/health
# {"status":"ok","max_context":102400,"model":"qwen3.6-35b-a3b-ud-q4_k_xl",...}

# Needle in haystack 54k tokens: PASS confirmado
```

---

## 8. DSH INTEGRATION

```yaml
# ~/.dsh/profiles/web/cordis.patch.yml
providers:
  meu-modelo:
    displayName: Meu Modelo (PC-SALA:PORT)
    apiKeyEnv: PCSALA_LOCAL_API_KEY
    api: openai-completions
    baseURL: http://192.168.1.184:PORT/v1
    timeoutMs: 10800000
    models:
      - id: meu-modelo-id
        name: Meu Modelo Display
        contextWindow: 100000
        maxTokens: 4096
        input: [text]
```

**Reiniciar GUI:** `cd /home/igor/.npm-global/lib/node_modules/@deepseek-ai/dsh && pnpm run dev:web`

---

## 9. DEBUGGING COMUM

| Problema | Solução |
|----------|---------|
| `ia health` mostra "serviço parado" | Verificar se service roda no PC-SALA: `ssh igor@192.168.1.184 systemctl status unit` |
| VRAM OOM no start | `nvidia-smi` — parar outro GPU: `ia solo outro-modelo` |
| Porta em uso | `ss -ltnp | grep PORT` — escolher porta livre |
| `ia solo` não alterna | Verificar `Conflicts=` no service, `exclusive_group` no modelos.conf |
| Strata não inicia 100k | Verificar VRAM: `nvidia-smi` — precisa ~22.3GB livres; usar KV q4_0 |
| Health check falha | `curl -v http://127.0.0.1:PORT/health` — ver logs: `journalctl -u unit -f` |

---

## 10. ARQUIVOS-CHAVE

| Arquivo | Localização | Função |
|---------|-------------|--------|
| `modelos.conf` | `~/.config/ia/` (PC-SALA + local) | Config IA Manager |
| `qwen36-q4.service` | `/etc/systemd/system/` | Template llama.cpp GPU |
| `qwen36-q4-strata.service` | `/etc/systemd/system/` | Template Strata |
| `model_manager.py` | `src/pcsala_agent/` | Registry pcsala models |
| `inference_profiles.py` | `src/pcsala_agent/` | Perfis de inferência |
| `tunnel-pcsala` | `~/.local/bin/` | SSH tunnel script |
| `HANDOFF.md` | `/home/igor/ia-sh/pc-sala-agent/` | Estado vivo |
| `GUIA_MESTRE.md` | `guias/` | Referência completa |

---

## 11. COMANDOS RÁPIDOS — RESUMO

```bash
# Status geral
ssh igor@192.168.1.184 ia doctor

# Alternar GPU
ssh igor@192.168.1.184 ia solo qwen36-q4-strata

# Subir/descer CPU
ssh igor@192.168.1.184 ia on maple-pro
ssh igor@192.168.1.184 ia off qwen3-1.7b

# Ver logs
ssh igor@192.168.1.184 journalctl -u qwen36-q4-strata.service -f

# Túnel
/home/igor/.local/bin/tunnel-pcsala {start|stop|status|test}

# Health via túnel
curl http://127.0.0.1:8098/health
```

---

## 12. PADRÃO OBRIGATÓRIO — NÃO VIOLAR

1. **GPU exclusivo:** `ia solo <alias>` — NUNCA dois GPU simultâneos
2. **systemd no PC-SALA:** IA manager local só faz HTTP; systemd é remoto
3. **Túnel para APIs locais:** `127.0.0.1:porta` via SSH — apenas máquina local
4. **modelos.conf JSON válido:** Array, comentários `#` só em linhas inteiras
4. **Backup antes de editar:** `cp modelos.conf modelos.conf.bak-$(date +%Y%m%d)-motivo`
5. **Validar JSON:** `python3 -c "import json; ..."` antes de salvar
6. **Porta livre:** `ss -ltnp | grep PORT` antes de criar service
7. **Conflitos GPU:** `Conflicts=` no service + `exclusive_group` no modelos.conf

---

**FIM — HANDOFF DEV PC-SALA**  
*Baseado em HANDOFF.md, GUIA_MESTRE.md, GUIA_DIDATICA_IA.md, TUTORIAL_GESTOR.md, README.md*  
*Todos modelos seguem padrão unificado: GPU exclusivo, CPU compartilhado, túnel local, Strata 100k validado*