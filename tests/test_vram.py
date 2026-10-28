import sqlite3

from pcsala_agent.gpu_monitor import GpuMemory, GpuMonitor
from pcsala_agent.model_manager import ModelCoordinator, ModelRegistry
from pcsala_agent.model_vram import ModelVramStore
from pcsala_agent.models_cli import VRAM_GUARD_MIN_FREE_MB, ModelsCLI

GPU_FULL = [
    GpuMemory(0, "Tesla P40", 23040, 22000, 1040),
]
GPU_LOW = [
    GpuMemory(0, "Tesla P40", 23040, 22500, 540),
]
GPU_TWO = [
    GpuMemory(0, "Tesla P40", 23040, 22000, 500),
    GpuMemory(1, "Tesla P40", 23040, 22000, 2000),
]


class TestGpuMonitor:
    def test_free_mb_injectable(self):
        mon = GpuMonitor(query_vram=lambda: GPU_FULL)
        assert mon.free_mb() == 1040

    def test_free_mb_none_when_unavailable(self):
        mon = GpuMonitor(query_vram=lambda: None)
        assert mon.free_mb() is None

    def test_free_mb_target_gpu_not_sum(self):
        mon = GpuMonitor(query_vram=lambda: GPU_TWO, gpu_index=0)
        assert mon.free_mb() == 500  # GPU 0, nao soma das duas

    def test_free_mb_gpu_index_from_env(self, monkeypatch):
        monkeypatch.setenv("PCSALA_GPU_INDEX", "1")
        mon = GpuMonitor(query_vram=lambda: GPU_TWO)
        assert mon.gpu_index == 1
        assert mon.free_mb() == 2000  # GPU 1

    def test_free_mb_none_when_gpu_index_not_found(self):
        mon = GpuMonitor(query_vram=lambda: GPU_FULL, gpu_index=5)
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
    def _cli(self, free_mb, tmp_path, gpu_index=0, skip_guard=False):
        db_path = tmp_path / "state.sqlite"
        reg = ModelRegistry()
        gpus = [GpuMemory(0, "P40", 23040, 0, free_mb)]
        if gpu_index == 1:
            gpus = [GpuMemory(0, "P40", 23040, 0, 100),
                    GpuMemory(1, "P40", 23040, 0, free_mb)]
        mon = GpuMonitor(query_vram=lambda: gpus, gpu_index=gpu_index)
        return ModelsCLI(
            registry=reg,
            db_path=str(db_path),
            gpu_monitor=mon,
            lock_dir=tmp_path / "locks",
            skip_vram_guard=skip_guard,
        )

    def test_start_recusa_com_menos_de_1_5gb(self, tmp_path):
        cli = self._cli(500, tmp_path)
        code = cli.run(["start", "bonsai-27b-gpu"])
        assert code == 3

    def test_start_falha_fechada_sem_nvidia_smi(self, tmp_path):
        cli = self._cli(2000, tmp_path)
        # Força nvidia-smi indisponível
        cli.gpu_monitor = GpuMonitor(query_vram=lambda: None)
        code = cli.run(["start", "bonsai-27b-gpu"])
        assert code == 3

    def test_start_permite_com_sem_guarda_vram_mesmo_sem_nvidia_smi(
        self, tmp_path,
    ):
        cli = self._cli(0, tmp_path, skip_guard=True)
        cli.gpu_monitor = GpuMonitor(query_vram=lambda: None)
        # Nao recusa por VRAM (guarda ignorada), systemctl falha por falta
        # de systemd -> codigo nao 3
        code = cli.run(["start", "bonsai-27b-gpu"])
        assert code != 3

    def test_start_permite_com_acima_de_1_5gb_mas_sem_sistema(self, tmp_path):
        cli = self._cli(2000, tmp_path)
        code = cli.run(["start", "bonsai-27b-gpu"])
        assert code != 3

    def test_start_permite_com_exatamente_1_5gb(self, tmp_path):
        cli = self._cli(1536, tmp_path)
        code = cli.run(["start", "bonsai-27b-gpu"])
        assert code != 3

    def test_start_recusa_com_1535_mb(self, tmp_path):
        cli = self._cli(1535, tmp_path)
        code = cli.run(["start", "bonsai-27b-gpu"])
        assert code == 3

    def test_switch_recusa_com_menos_de_1_5gb(self, tmp_path):
        cli = self._cli(500, tmp_path)
        code = cli.run(["switch", "laguna-xs-2.1-gpu"])
        assert code == 3

    def test_switch_recusa_modelo_residente(self, tmp_path):
        cli = self._cli(2000, tmp_path)
        code = cli.run(["switch", "bonsai-4b-gpu"])
        assert code == 3

    def test_switch_mede_gpu_alvo_nao_soma(self, tmp_path):
        # GPU 0 tem 500 MB (baixo), GPU 1 tem 2000 MB (alto). Alvo = 1.
        # Deve permitir (não soma as duas).
        cli = self._cli(0, tmp_path, gpu_index=1)
        # gpu_index=1, free_mb() retorna 2000 da GPU 1
        cli.gpu_monitor = GpuMonitor(
            query_vram=lambda: [
                GpuMemory(0, "P40", 23040, 0, 500),
                GpuMemory(1, "P40", 23040, 0, 2000),
            ],
            gpu_index=1,
        )
        code = cli.run(["switch", "laguna-xs-2.1-gpu"])
        assert code != 3

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
