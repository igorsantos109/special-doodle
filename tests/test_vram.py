import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pcsala_agent.gpu_monitor import GpuMonitor, GpuMemory
from pcsala_agent.model_manager import ModelRegistry, ModelCoordinator
from pcsala_agent.model_vram import ModelVramStore
from pcsala_agent.models_cli import ModelsCLI, VRAM_GUARD_MIN_FREE_MB


GPU_FULL = [
    GpuMemory(0, "Tesla P40", 23040, 22000, 1040),
]
GPU_LOW = [
    GpuMemory(0, "Tesla P40", 23040, 22500, 540),
]


class TestGpuMonitor:
    def test_free_mb_injectable(self):
        mon = GpuMonitor(query_vram=lambda: GPU_FULL)
        assert mon.free_mb() == 1040

    def test_free_mb_none_when_unavailable(self):
        mon = GpuMonitor(query_vram=lambda: None)
        assert mon.free_mb() is None

    def test_vram_guard_threshold(self):
        assert VRAM_GUARD_MIN_FREE_MB == 1536


class TestModelVramStore:
    def test_record_and_get(self, tmp_path):
        db_path = tmp_path / "state.sqlite"
        db = sqlite3.connect(str(db_path))
        db.execute(
            """CREATE TABLE model_vram (
            model_id TEXT NOT NULL, context_size INTEGER NOT NULL,
            vram_used_mb INTEGER NOT NULL,
            measured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            PRIMARY KEY (model_id, context_size))"""
        )
        db.commit()
        store = ModelVramStore(db)
        store.record("bonsai-27b-gpu", 64000, 12900)
        row = store.get("bonsai-27b-gpu", 64000)
        assert row is not None
        assert row["vram_used_mb"] == 12900
        assert row["model_id"] == "bonsai-27b-gpu"
        all_rows = store.all()
        assert len(all_rows) == 1
        db.close()

    def test_record_upsert(self, tmp_path):
        db_path = tmp_path / "state.sqlite"
        db = sqlite3.connect(str(db_path))
        db.execute(
            """CREATE TABLE model_vram (
            model_id TEXT NOT NULL, context_size INTEGER NOT NULL,
            vram_used_mb INTEGER NOT NULL,
            measured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            PRIMARY KEY (model_id, context_size))"""
        )
        db.commit()
        store = ModelVramStore(db)
        store.record("bonsai-27b-gpu", 64000, 12900)
        store.record("bonsai-27b-gpu", 64000, 13000)
        row = store.get("bonsai-27b-gpu", 64000)
        assert row["vram_used_mb"] == 13000
        db.close()


class TestModelsCLIVramGuard:
    def _cli(self, free_mb, tmp_path):
        db_path = tmp_path / "state.sqlite"
        reg = ModelRegistry()
        mon = GpuMonitor(query_vram=lambda: [GpuMemory(0, "P40", 23040, 0, free_mb)])
        return ModelsCLI(
            registry=reg,
            db_path=str(db_path),
            gpu_monitor=mon,
            lock_dir=tmp_path / "locks",
        )

    def test_start_recusa_com_menos_de_1_5gb(self, tmp_path):
        cli = self._cli(500, tmp_path)
        code = cli.run(["start", "bonsai-27b-gpu"])
        assert code == 3

    def test_start_permite_com_acima_de_1_5gb_mas_sem_sistema(self, tmp_path):
        cli = self._cli(2000, tmp_path)
        # systemctl falha (sem systemd) -> codigo nao zero, mas nao recusa por VRAM
        code = cli.run(["start", "bonsai-27b-gpu"])
        assert code != 3

    def test_switch_recusa_com_menos_de_1_5gb(self, tmp_path):
        cli = self._cli(500, tmp_path)
        code = cli.run(["switch", "laguna-xs-2.1-gpu"])
        assert code == 3

    def test_switch_recusa_modelo_residente(self, tmp_path):
        cli = self._cli(2000, tmp_path)
        code = cli.run(["switch", "bonsai-4b-gpu"])
        assert code == 3

    def test_vram_output(self, tmp_path):
        cli = self._cli(2000, tmp_path)
        code = cli.run(["vram"])
        assert code == 0


class TestReserveEngine:
    def test_reserve_and_release_persist(self, tmp_path):
        db_path = tmp_path / "state.sqlite"
        reg = ModelRegistry()
        coord = ModelCoordinator(reg, database=db_path)
        rid = coord.reserve_engine("laguna-xs-2.1-gpu", requester="cli")
        assert rid is not None
        assert coord.engine_reserved("laguna-xs-2.1-gpu") is True
        coord.release_engine("laguna-xs-2.1-gpu")
        assert coord.engine_reserved("laguna-xs-2.1-gpu") is False

    def test_resident_model_no_reservation(self, tmp_path):
        db_path = tmp_path / "state.sqlite"
        reg = ModelRegistry()
        coord = ModelCoordinator(reg, database=db_path)
        assert coord.reserve_engine("bonsai-4b-gpu") is None
        assert coord.engine_reserved("bonsai-4b-gpu") is False
