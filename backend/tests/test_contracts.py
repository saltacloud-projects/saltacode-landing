import subprocess
import sys
from pathlib import Path


def test_exported_contracts_are_current() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/export_contracts.py", "--check"],
        cwd=backend_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
