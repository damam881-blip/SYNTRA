import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CHECKS = (
    ("Ruff linting", ("-m", "ruff", "check", ".")),
    ("Ruff formatting", ("-m", "ruff", "format", "--check", ".")),
    ("Pytest", ("-m", "pytest", "-q")),
)


def run_checks() -> int:
    for label, args in CHECKS:
        print(f"\n>>> {label}", flush=True)
        result = subprocess.run([sys.executable, *args], cwd=PROJECT_ROOT)

        if result.returncode != 0:
            return result.returncode

    print("\nAll quality checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_checks())
