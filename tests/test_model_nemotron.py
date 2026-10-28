"""Registo do Ternary-Nemotron-3.5-Lightning-30B na lista de modelos.

Modelo ternario Q2_0 (nemotron_h_moe, 30B-A3B) servido por llama.cpp em
CUDA/Pascal na Tesla P40, porta 8083, perfil proprio e exclusivo no
mesmo gpu-slot do bonsai-27b (nao cabem na mesma VRAM).
"""

from pcsala_agent.inference_profiles import PROFILES, get_profile
from pcsala_agent.model_manager import ModelRegistry


def test_nemotron_na_lista_de_modelos():
    reg = ModelRegistry()
    model = reg.get("nemotron-3.5-30b-gpu")
    assert model is not None
    assert model.model_class == "GPU"
    assert model.unit == "nemotron.service"
    assert model.endpoint == "http://127.0.0.1:8083"
    assert model.profile == "nemotron-ternary-v1"
    assert model.backend == "systemd"
    assert "leitura" in model.capabilities


def test_nemotron_exclusivo_no_gpu_slot():
    reg = ModelRegistry()
    model = reg.get("nemotron-3.5-30b-gpu")
    assert not model.shared
    assert model.exclusive_group == "gpu-slot-1"
    assert model.exclusive_group == reg.get("bonsai-27b-gpu").exclusive_group


def test_nemotron_ocupa_porta_propria():
    reg = ModelRegistry()
    endpoints = [m.endpoint for m in reg.list()]
    assert endpoints.count("http://127.0.0.1:8083") == 1
    assert reg.get("nemotron-3.5-30b-gpu").endpoint != (
        reg.get("bonsai-27b-gpu").endpoint
    )


def test_perfil_nemotron_com_modelo_e_endpoint_proprios():
    profile = get_profile("nemotron-ternary-v1")
    assert profile.endpoint == "http://127.0.0.1:8083"
    assert profile.endpoint != PROFILES["gpu-triage-v1"].endpoint
    assert profile.model.endswith(
        "Ternary-Nemotron-3.5-Lightning-30B-A3B-GGUF.gguf"
    )
    assert profile.timeout_seconds >= 60


def test_todo_modelo_da_lista_aponta_para_um_perfil_existente():
    reg = ModelRegistry()
    for model in reg.list():
        get_profile(model.profile)