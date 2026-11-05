# PC-SALA 1.0.1rc1 — candidata com correções de segurança

## O que este pacote é

Código completo do `special-doodle` com as correções R01–R09 implementadas, testes de regressão, wheel e evidências. Não é instalação pronta no pc-sala, não contém pesos e não conclui API externa, STRATA, integração inacessível do ialocalagent ou pools P100. Não usar a palavra “final” como sinônimo de produção validada.

Base: `igorsantos109/special-doodle`, commit b1767c9560b22e36d46284cef1a8814d33016580.
Versão candidata: 1.0.1rc1. Sem push ou merge no GitHub.

## Conteúdo da entrega

- `projeto/`: árvore completa de código, documentação e testes, sem `.git`, caches, banco ou ambiente Python.
- `dist/`: wheel instalável 1.0.1rc1, incluindo os scripts SQL de migração.
- `patches/`: diff aplicável somente ao SHA base, sem instalação automática.
- `evidence/`: logs reais de testes e build, versões do ambiente e comparação de lint.
- `MANIFEST.json` e `SHA256SUMS`: identificação e integridade dos arquivos.

Os exemplos são para cópia de DESENVOLVIMENTO, não para o ambiente em uso. Nenhum script de serviço ou implantação foi executado na preparação desta entrega. Os arquivos deploy/ originais permanecem para histórico; não são recomendação para aplicá-los sem inspeção.

## Testar o código

Em diretório novo, extraído do ZIP, com Python 3.11+:

```bash
cd projeto
bash tools/verify_release.sh --install-dev
```

Esse comando baixa dependências Python, cria/usa `.venv`, roda a suíte sem GPU com comandos systemd/GPU bloqueados por executáveis falsos temporários e verifica os arquivos novos. Não inicia modelos, não baixa GGUF e não modifica configuração global. Servidores HTTP falsos escutam somente em loopback durante os testes.

Os testes antigos de fila exigem `.venv/bin/python`, motivo para manter esse caminho na verificação. Dependências variam porque pyproject não fixa versões; as versões efetivamente testadas constam em `evidence/environment.json` e `environment-freeze.txt`. O lock legado não foi regenerado nem validado. O ambiente medido foi Python 3.12.8, não Python 3.11 da CI.

## Experimentar o wheel isoladamente

Na raiz da entrega, em ambiente de desenvolvimento novo:

```bash
python3 -m venv /tmp/pcsala-rc1-env
/tmp/pcsala-rc1-env/bin/python -m pip install dist/pc_sala_agent-1.0.1rc1-py3-none-any.whl
/tmp/pcsala-rc1-env/bin/pcsala --help
```

`pip install` pode baixar dependências. O wheel não inclui modelos, CUDA, binários llama.cpp nem serviços. Não usar comandos models/start/stop/switch no pc-sala antes de autorização e inventário. A instalação local efetiva requer backup e avaliação dos serviços existentes.

## Aplicar somente o patch

Em árvore Git limpa no SHA base, primeiro executar `git apply --check` com o patch fornecido. O patch não se aplica indiscriminadamente a HEADs diferentes. Não rodar `git reset --hard`, não descartar mudanças locais e não fazer push antes de revisão. A lista de arquivos alterados está no relatório e no patch.

## Comportamentos corrigidos

O adaptador encaminha timeout de perfil, limita leitura, fecha a resposta e não aceita conteúdo truncado como sucesso. Resposta textual vazia continua sendo rejeitada no grafo, preservando os campos de saída históricos. A limitação é de socket; não há deadline global estrito contra um servidor que entregue bytes continuamente.

Reservas exclusivas persistidas são idempotentes e transacionais; um grupo já reservado não é atribuído a outro modelo. Isso não resolve sozinho orçamento completo de VRAM, modelos residentes ou processos iniciados fora do gestor. O piso legado de 1536 MiB continua sendo somente um piso, não uma prova de capacidade.

`stop`, falha de start e falha de health mantêm reserva quando não é possível confirmar liberação. `switch` só restaura o modelo anterior depois de confirmar parada do alvo. Em situação desconhecida, exige reconciliação manual. `ROLLED_BACK`/`ROLLBACK_FAILED` ficam em confirmed_status; a operação usa FAILED, compatível com o schema já existente.

`update()` da fila conclui apenas tarefas RESERVED; estados QUEUED/CANCELLED/COMPLETED/FAILED não são sobrescritos. Não foi criado lease ou protocolo de nova tentativa: o único worker continua sendo parte do contrato existente. Não reintroduzir tarefas manualmente sem nova tentativa identificada.

## Antes de produção

1. Revisão independente de código por outra família de modelo/pessoa.
2. Suíte no Python 3.11 e resolução do lint legado da CI.
3. Acesso e avaliação do ialocalagent caso ainda seja necessário à unificação.
4. Inventário efetivo do ia, modelos, serviços, disco, RAM e GPU no pc-sala.
5. Resolver divergência do Laguna: projeto histórico versus configuração protegida, sem editá-lo implicitamente.
6. Validar identidade do modelo, geração real, memória, retomada e reversão na P40.
7. Implementar API autenticada/pools/STRATA em fases próprias se ainda desejados.

P100 permanece futura e não é inicializada pelo pacote. Não há benchmark nem promessa de tokens/s. Toda configuração protegida e o alias voz devem ser preservados. Não expor endpoints fora de 127.0.0.1 automaticamente.
