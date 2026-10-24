import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from types import MappingProxyType

from .output_collector import collect_output, validate_output_limits

PROBES = MappingProxyType({
    "success": "import os; os.write(1,b'OK\\n'); os.write(2,b'NOTE\\n')",
    "error": "import os; os.write(2,b'ERROR\\n'); raise SystemExit(7)",
    "binary": "import os; os.write(1,bytes([0,255,254]))",
    "exact": "import os; os.write(1,b'x'*65536)",
    "stdout_flood": (
        "import os\n"
        "while True: os.write(1,b'x'*4096)\n"
    ),
    "stderr_flood": (
        "import os\n"
        "while True: os.write(2,b'x'*4096)\n"
    ),
    "both_flood": (
        "import os\n"
        "while True:\n"
        " os.write(1,b'x'*4096)\n"
        " os.write(2,b'y'*4096)\n"
    ),
    "sleep": "import time; time.sleep(60)",
    "inherited_pipe": (
        "import subprocess,sys\n"
        "subprocess.Popen([sys.executable,'-I','-c',"
        "'import time; time.sleep(60)'])\n"
    ),
})

@dataclass(frozen=True)
class ProbeResult:
    status: str
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float

    @property
    def retained_bytes(self):
        return len(self.stdout) + len(self.stderr)

def run_output_probe(
    scenario: str, *, output_limit: int = 65536, timeout_seconds: float = 15
) -> ProbeResult:
    """Somente diagnosticos fixos. Nao aceita argv, ambiente ou codigo externos."""
    if not isinstance(scenario, str) or scenario not in PROBES:
        raise ValueError("Cenario nao cadastrado")
    validate_output_limits(output_limit, timeout_seconds)

    start = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-I", "-u", "-c", PROBES[scenario]],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        shell=False,
        start_new_session=True,
        close_fds=True,
        cwd="/",
        env={"PATH": "/usr/bin", "LANG": "C", "LC_ALL": "C"},
    )

    def kill_owned_group():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    result = collect_output(
        process,
        terminate=kill_owned_group,
        output_limit=output_limit,
        timeout_seconds=timeout_seconds,
        started_at=start,
    )
    return ProbeResult(
        status=result.status,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        elapsed_seconds=result.elapsed_seconds,
    )
