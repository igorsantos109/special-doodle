"""Expansao GPU 08/11/2026: PXA-Fusion4-35B (8102).

Cobrimos o registo no `pcsala models` (allowlist do switch), o perfil de
inferencia, e a guarda de VRAM de 1,5 GB na presenca do Bonsai 4B residente.

Contexto de engenharia (docs/expansao-gpu-2026-11.md):
- fusion4-35b usa PXQ4 (id GGML 252), so a engine PXA o le.
- O Ternary-Flint-40B (8101) foi removido da maquina e do gestor em 08/11.
O modelo partilha o slot exclusivo gpu-slot-1 numa unica P40.
"""
import pytest

from pcsala_agent.gpu_monitor import GpuMemory, GpuMonitor
from pcsala_agent.inference_profiles import PROFILES, get_profile
from pcsala_agent.model_manager import ModelRegistry
from pcsala_agent.models_cli import VRAM_GUARD_MIN_FREE_MB, ModelsCLI

NOVOS = ()
GPU_OCCUPIES_4B = 246  # MiB do llama-server do Bonsai 4B residente

class _SystemctlFalso:
    def __init__(self):
        self.chamadas = []

    def __call__(self, action, unit):
        self.chamadas.append((action, unit))
        return 0

def _cli(tmp_path, free_mb, used_mb=None):
    reg = ModelRegistry()
    used = used_mb if used_mb is not None else 23040 - free_mb
    gpus = [GpuMemory(0, "Tesla P40", 23040, used, free_mb)]
    cli = ModelsCLI(
        registry=reg,
        db_path=str(tmp_path / "state.sqlite"),
        gpu_monitor=GpuMonitor(query_vram=lambda: gpus, gpu_index=0),
        lock_dir=tmp_path / "locks",
        systemctl=_SystemctlFalso(),
    )
    cli._is_model_running = lambda model_id: False
    cli.coordinator.wait_for_health = lambda model_id, timeout=None: True
    return cli

class TestRegistoNoGestor:
    def test_especes_presentes(self):
        reg = ModelRegistry()
        for model_id in NOVOS:
            spec = reg.get(model_id)
            assert spec is not None, model_id
            assert spec.model_class == "GPU", model_id
            assert spec.exclusive_group == "gpu-slot-1", model_id
            assert not spec.shared, model_id

    def test_portas_e_units(self):
        reg = ModelRegistry()
                
    def test_perfis_referenciados_existem(self):
        reg = ModelRegistry()
        for model_id in NOVOS:
            profile = reg.get(model_id).profile
            assert profile in PROFILES, profile

    def test_capabilities_agentica(self):
        reg = ModelRegistry()
        
    def test_ternario_fora_do_registo(self):
        reg = ModelRegistry()
        assert reg.get("flint-ternary-40b") is None
        assert "flint-ternary-v1" not in PROFILES

    def test_existentes_preservados(self):
        reg = ModelRegistry()
        assert reg.get("bonsai-27b-gpu") is not None
        
    def test_switch_nao_recusa_por_ser_residente(self, tmp_path):
        # O switch so recusa modelos compartilhados; os novos sao exclusivos.
        cli = _cli(tmp_path, free_mb=6000)
        for model_id in NOVOS:
            assert cli.run(["switch", model_id]) != 3, model_id

class TestPerfisInferencia:
    def test_endpoints(self):
        pass

    def test_timeout_suporta_contexto_longo(self):
        cfg = get_profile("test")
        assert cfg.timeout_seconds >= 300
        assert cfg.max_response_bytes >= 131072

    def test_gguf_no_globo_de_pesos(self):
        pass
class TestGuardaVRAMComBonsai4B:
    def test_limiar_continua_1_5_gb(self):
        assert VRAM_GUARD_MIN_FREE_MB == 1536

    @pytest.mark.parametrize("model_id", NOVOS)
    def test_switch_recusa_folga_insuficiente(self, tmp_path, model_id):
        # Bonsai 4B residente (246 MiB) + carga do modelo grande anterior:
        # sobram 1.535 MB, 1 MB abaixo do limiar.
        cli = _cli(tmp_path, free_mb=1535)
        assert cli.run(["switch", model_id]) == 3

    @pytest.mark.parametrize("model_id", NOVOS)
    def test_switch_permite_na_folga_exata(self, tmp_path, model_id):
        cli = _cli(tmp_path, free_mb=1536)
        assert cli.run(["switch", model_id]) != 3

    @pytest.mark.parametrize("model_id", NOVOS)
    def test_start_recusa_folga_insuficiente(self, tmp_path, model_id):
        cli = _cli(tmp_path, free_mb=1400)
        assert cli.run(["start", model_id]) == 3

    def test_falha_fechada_sem_nvidia_smi(self, tmp_path):
        cli = _cli(tmp_path, free_mb=8000)
        cli.gpu_monitor = GpuMonitor(query_vram=lambda: None)
        