import subprocess
import sys

from .output_collector import collect_output, validate_output_limits

SCENARIOS = {
    "success": [
        sys.executable, "-c",
    "import sys; sys.stdout.buffer.write(b'OK\\n'); "
    "sys.stderr.buffer.write(b'NOTE\\n')",
    ],
    "error": [
        sys.executable, "-c",
        "import sys; sys.stderr.buffer.write(b'ERROR\\n'); sys.exit(7)",
    ],
    "binary": [
        sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(bytes([0, 255, 254]))",
    ],
    "exact": [
        sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(b'x'*65536)",
    ],
    "stdout_flood": [
        sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(b'x'*20000); sys.stdout.flush()",
    ],
    "stderr_flood": [
        sys.executable, "-c",
        "import sys; sys.stderr.buffer.write(b'y'*20000); sys.stderr.flush()",
    ],
    "both_flood": [
        sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(b'x'*10000); "
        "sys.stderr.buffer.write(b'y'*10000); sys.stdout.flush(); sys.stderr.flush()",
    ],
    "sleep": [
        sys.executable, "-c", "import time; time.sleep(10)",
    ],
    "inherited_pipe": [
        sys.executable, "-c", "import time; time.sleep(10)",
    ],
}


def run_output_probe(scenario, output_limit=65536, timeout_seconds=5):
    validate_output_limits(output_limit, timeout_seconds)
    if scenario not in SCENARIOS:
        raise ValueError(f"cenário desconhecido: {scenario}")
    process = subprocess.Popen(
        SCENARIOS[scenario],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return collect_output(
        process,
        terminate=process.terminate,
        timeout_seconds=timeout_seconds,
        output_limit=output_limit,
    )
