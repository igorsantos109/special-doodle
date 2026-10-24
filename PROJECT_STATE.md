# Estado consolidado — 2026-10-23 (Bonsai MTP medido; API sem chave; dsh remoto)

## Baseline verificado

**5 modelos operacionais no gestor:**
1. **Bonsai 27B GPU + MTP** — primário, porta 8080, 55K ctx, ~12,4 GB VRAM, geração **28-48 tok/s** conforme contexto (mediana 32,85 em uso real do harness)
2. **Bonsai 9B CPU** — porta 8090, 32K ctx, **6,08 tok/s gen**. **Sem MTP possível** (sem cabeça 9B — ver GUIA_MESTRE 3.2)
3. **Laguna XS 2.1 CPU** — porta 8091, **serviço desativado (libera ~18 GB RAM)**. GPU é 18x mais rápida. Reativar com `sudo systemctl enable --now laguna.service`
4. **Laguna XS 2.1 GPU** — porta 8082, **128K ctx, ~47 tok/s gen, 15-21 GB VRAM** (desativado; o dsh aponta para 8082, nunca 8084)
5. **Ornith 35B GPU** — porta 8092, runtime preferencial PrismML (~40 tok/s), MTP experimental no llama.cpp oficial (24.7 tok/s, depth 2, 74% aceitação)

## Política de acesso às APIs (2026-10-23)

**API obrigatória, API key não.** Os serviços 8080 e 8090 correm sem `--api-key-file`;
`Authorization` é aceite mas ignorado. Backup da versão com chave:
`/etc/systemd/system/bonsai2-27b.service.d/mtp.conf.bak-20261023-165825-with-apikey`.
Firewall mantém restrição de rede (ufw + `nft inet pcsala_api`, só 192.168.0.0/16 via enp6s0).

## Matriz implementado/demonstrado/pendente/bloqueado

| Funcionalidade | Implementado | Demonstrado | Pendente | Bloqueado |
|---|---|---|---|---|
| Inferência 27B GPU (MTP) | ✅ | ✅ | Orçamento MTP recalcular | - |
| Inferência 9B CPU | ✅ | ✅ | - | - |
| **Laguna XS 2.1 GPU (Pascal)** | ✅ service + gestor | ✅ (full offload, código, 128K) | Budget de contexto | - |
| **Ornith 35B GPU (PrismML, runtime preferencial)** | ✅ service + gestor | ✅ (40 tok/s, código) | Contexto maior | - |
| **Ornith MTP (llama.cpp oficial, experimental)** | ✅ build separado | ✅ (24.7 tok/s, 74% acc, depth 2) | Integração opcional | Não substitui PrismML |
| Gestor de modelos | ✅ (5 modelos) | ✅ (switch GPU funcional) | - | - |
| Worker contínuo | ✅ | ✅ | Aguarda GPU principal | Parado durante testes |
| Fila persistente | ✅ | ✅ | - | - |
| Recuperação pós-reboot | ✅ | ✅ (22/10/2026) | - | - |
| Executor integrado | ✅ | ✅ (sintético) | Projetos reais | - |
| Contexto/compressão | ✅ | ✅ | - | - |
| Fluxo documental | ✅ | ✅ (sintético) | Dependências: pdfminer | - |
| Reconciliação | ✅ | ✅ | - | - |
| Backup/restauração | ✅ | ✅ | - | - |

## Comandos de gestão de modelos

```bash
# Listar modelos
ia list
./pcsala models list

# Trocar GPU (apenas um GPU por vez)
./pcsala models switch bonsai-27b-gpu      # Bonsai (primário)
./pcsala models switch laguna-xs-2.1-gpu   # Laguna GPU
./pcsala models switch ornith-35b-gpu      # Ornith

# Estado
ia status
./pcsala models status bonsai-27b-gpu

# CLI unificada
./pcsala health
./pcsala enqueue --prompt "texto"
./pcsala list
./pcsala status <id>
./pcsala cancel <id>
./pcsala reconcile
./pcsala backup
```

## Decisões que dependem exclusivamente de Igor

1. **Worker**: reiniciar quando GPU voltar ao Bonsai (`sudo systemctl start pcsala-worker.service`)
2. **Ornith MTP**: funcional no llama.cpp oficial (depth 2, 24.7 tok/s). PrismML continua runtime preferencial (40 tok/s). Build experimental mantido. Integração ao serviço depende de autorização.
3. **Projetos reais** no executor isolado
4. **Laguna como padrão**: se necessário, substituir Bonsai como modelo principal de programação
5. **Definição de diretórios autorizados** adicionais para fluxo documental