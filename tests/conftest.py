from pathlib import Path

import pytest

from pcsala_agent.database import connect
from pcsala_agent.migrations import migrate


def ensure_test_environment(env, project="p", session="s", task="t", attempt="a"):
    """Versão de teste: migra e insere dados fictícios para testes.

    Em produção (graph_runner.py) a função homônima apenas migra e valida
    a existência do escopo — nunca insere dados fictícios.
    """
    db_path = Path(env) / "state.sqlite"
    migrate(db_path)
    db = connect(db_path)
    try:
        with db:
            db.execute(
                """INSERT OR IGNORE INTO projects(project_id,name,authorized_root)
                VALUES (?, ?, ?)""",
                (project, "Simulado", "/referencia"),
            )
            db.execute(
                """INSERT OR IGNORE INTO sessions
                (session_id,project_id,state,revision,api_mode)
                VALUES (?, ?, 'RUNNING', 0, 'OFFLINE')
                ON CONFLICT(session_id) DO UPDATE SET
                state=excluded.state, revision=excluded.revision""",
                (session, project),
            )
            db.execute(
                """INSERT OR IGNORE INTO tasks
                (task_id,project_id,title,acceptance_criteria,status)
                VALUES (?, ?, 'Simulado','Checkpoint confirmado','RUNNING')""",
                (task, project),
            )
            db.execute(
                """INSERT OR IGNORE INTO attempts
                (attempt_id,project_id,session_id,task_id,status)
                VALUES (?, ?, ?, ?, 'RUNNING')""",
                (attempt, project, session, task),
            )
    finally:
        db.close()
    return db_path


@pytest.fixture
def env_path(tmp_path):
    """Fixture que cria um ambiente de teste completo e retorna o diretório."""
    ensure_test_environment(tmp_path)
    return tmp_path


@pytest.fixture
def db_conn(env_path):
    """Fixture que retorna uma conexão SQLite aberta no ambiente de teste."""
    from pcsala_agent.database import connect
    db_path = env_path / "state.sqlite"
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
