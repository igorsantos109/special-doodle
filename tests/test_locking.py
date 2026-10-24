import os
import subprocess
import sys

import pytest

from pcsala_agent.locking import ExecutorBusy, database_lock

CHILD = """
import sys
from pcsala_agent.locking import ExecutorBusy, database_lock
try:
    with database_lock(sys.argv[1]):
        print("ADQUIRIDO")
except ExecutorBusy:
    print("OCUPADO")
    sys.exit(23)
"""

def child(database):
    return subprocess.run(
        [sys.executable, "-c", CHILD, str(database)],
        capture_output=True, text=True, timeout=15,
    )

def test_impede_segundo_processo(tmp_path):
    database = tmp_path / "state.sqlite"
    with database_lock(database):
        result = child(database)
        assert result.returncode == 23, result.stderr
        assert "OCUPADO" in result.stdout
    result = child(database)
    assert result.returncode == 0, result.stderr
    assert "ADQUIRIDO" in result.stdout

def test_libera_apos_excecao(tmp_path):
    database = tmp_path / "state.sqlite"
    with pytest.raises(ValueError):
        with database_lock(database):
            raise ValueError("falha simulada")
    with database_lock(database):
        pass

def test_bancos_distintos(tmp_path):
    with database_lock(tmp_path / "primeiro.sqlite"):
        result = child(tmp_path / "segundo.sqlite")
        assert result.returncode == 0, result.stderr

def test_libera_apos_saida_abrupta(tmp_path):
    database = tmp_path / "state.sqlite"
    script = """
import os
import sys
from pcsala_agent.locking import database_lock
with database_lock(sys.argv[1]):
    os._exit(73)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(database)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 73, result.stderr
    result = child(database)
    assert result.returncode == 0, result.stderr

def test_recusa_lock_simbolico(tmp_path):
    database = tmp_path / "state.sqlite"
    target = tmp_path / "outro-arquivo"
    target.write_text("preservar")
    lock = tmp_path / "state.sqlite.lock"
    lock.symlink_to(target)
    with pytest.raises(OSError):
        with database_lock(database):
            pass
    assert target.read_text() == "preservar"
