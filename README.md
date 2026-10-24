# PC-SALA Agent

Protótipo de programação agêntica híbrida, conforme o handoff 1.0.
Não é uma plataforma de produção.

## Estado consolidado

Última suíte apresentada em 2026-10-19:
121 testes aprovados, 13 avisos, em 10,12 segundos.
A consolidação não executa novamente os testes.

## Implementado

- SQLite, checkpoints e artefatos com SHA-256.
- Integração simulada com LangGraph.
- Migrações versionadas.
- Controle persistente de sessões, tentativas, pausa e auditoria.
- Classificação de interrupções sem repetição automática.
- Encerramento lógico DRAINING -> CHECKPOINTING -> STOPPED.
- Contrato estrito de pedidos e resultados.
- Planejador determinístico, sem execução de comandos.

## Ensaios operacionais separados da suíte

- Bubblewrap iniciado como pcsala-executor.
- Workspace gravável, sentinela externo não visível e /usr em leitura.
- Namespace de rede separado e loopback do hospedeiro inacessível.
- Cgroups: CPU, memória, swap, tarefas e duração.
- Bubblewrap e cgroups combinados, mantendo NoNewPrivileges.

Os ensaios usam dados artificiais. Não comprovam segurança universal.

## Executar a suíte

```bash
PYTHONPATH="$PWD/src" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    .venv/bin/python -m pytest -q tests
```

## Limitações e próximo trabalho

- Nenhum executor privilegiado habilitado.
- Nenhuma regra de sudo instalada para o agente.
- Preparação segura de diretórios ainda pendente.
- Tetos de saída e armazenamento apenas declarados no perfil.
- Reconciliação administrativa e vínculos completos ainda pendentes.
- Sem execução de repositórios reais ou código não confiável.
- Sem modelos, API externa ou painel integrados por este projeto.
- Sem garantia universal de execução exatamente uma vez.
- Checkpoints, arquivos e Git não formam uma transação conjunta.

Não executar diretamente como root um plano recebido do orquestrador.
O helper futuro deverá validar o pedido e usar código/perfis confiáveis.

Registros locais, bancos e ambiente virtual não integram esta cópia
do código. Consulte PROJECT_STATE.md para referências operacionais.
