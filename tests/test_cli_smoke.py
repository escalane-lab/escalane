import json
import subprocess
import sys
from pathlib import Path


def test_cli_smoke_mock(repo_root: Path):
    incident = repo_root / "src" / "escalane" / "examples" / "incidents" / "php_502.json"
    catalog = repo_root / "datasets" / "sysops_decide" / "catalog.yaml"
    if not catalog.is_file():
        catalog = repo_root / "src" / "escalane" / "examples" / "catalog.yaml"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "escalane.cli",
            "decide",
            "--backend",
            "mock",
            "--state",
            str(incident),
            "--catalog",
            str(catalog),
            "--gate-config",
            "A3",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "answers" in data
    assert "gate" in data
    assert data["answers"]["playbook"]["choice"] in (
        "restart_php_fpm",
        "escalate",
    )
