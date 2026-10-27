"""Leitura de VRAM da GPU via nvidia-smi.

A consulta e injetavel para permitir testes sem hardware/GPU presente.
"""
from dataclasses import dataclass
import subprocess


@dataclass(frozen=True)
class GpuMemory:
    index: int
    name: str
    total_mb: int
    used_mb: int
    free_mb: int


class GpuMonitor:
    def __init__(self, query_vram=None):
        self._query_vram = query_vram or self._run_nvidia_smi

    def query_vram(self):
        return self._query_vram()

    def free_mb(self):
        gpus = self.query_vram()
        if not gpus:
            return None
        return sum(gpu.free_mb for gpu in gpus)

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
