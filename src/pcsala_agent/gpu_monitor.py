"""Leitura de VRAM da GPU via nvidia-smi.

A consulta e injetavel para permitir testes sem hardware/GPU presente.
"""
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class GpuMemory:
    index: int
    name: str
    total_mb: int
    used_mb: int
    free_mb: int


def _default_gpu_index():
    try:
        return int(os.environ.get("PCSALA_GPU_INDEX", "0"))
    except ValueError:
        return 0


class GpuMonitor:
    def __init__(self, query_vram=None, gpu_index=None):
        self._query_vram = query_vram or self._run_nvidia_smi
        self.gpu_index = gpu_index if gpu_index is not None else _default_gpu_index()

    def query_vram(self):
        return self._query_vram()

    def free_mb(self, gpu_index=None):
        """VRAM livre (MB) de uma GPU específica.

        Quando nvidia-smi está indisponível, retorna None (falha fechada).
        """
        index = self.gpu_index if gpu_index is None else gpu_index
        gpus = self.query_vram()
        if not gpus:
            return None
        for g in gpus:
            if g.index == index:
                return g.free_mb
        return None

    def gpu_count(self):
        gpus = self.query_vram()
        if not gpus:
            return None
        return len(gpus)

    def all_gpus(self):
        return self.query_vram()

    @staticmethod
    def _run_nvidia_smi():
        try:
            output = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        gpus = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                gpus.append(GpuMemory(
                    index=int(parts[0]),
                    name=parts[1],
                    total_mb=int(parts[2]),
                    used_mb=int(parts[3]),
                    free_mb=int(parts[4]),
                ))
            except ValueError:
                continue
        return gpus
