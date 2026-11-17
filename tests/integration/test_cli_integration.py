"""CLI decide / run / replay via uv (offline mock)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


def _uv_sysone(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    # Ensure write kill-switch stays off unless a test opts in.
    full_env.pop("ALLOW_WRITE_OPERATIONS", None)
    return subprocess.run(
        ["uv", "run", "escalane", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


@pytest.fixture
def fixture_state(tmp_path: Path, suite_states_by_id) -> Path:
    rec = suite_states_by_id["st_php_02"]
    path = tmp_path / "state.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


@pytest.fixture
def catalog_path(suite_catalog_path: Path) -> Path:
    return suite_catalog_path


def test_cli_decide_mock(repo_root: Path, fixture_state: Path, catalog_path: Path):
    proc = _uv_sysone(
        "decide",
        "--backend",
        "mock",
        "--state",
        str(fixture_state),
        "--catalog",
        str(catalog_path),
        "--gate-config",
        "A2",
        cwd=repo_root,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "answers" in data
    assert "gate" in data
    assert "catalog_hash" in data
    assert data["answers"]["playbook"]["choice"] == "restart_php_fpm"
    assert data["gate"]["decision"] in {"dry_run", "allow", "hitl", "deny", "escalate"}


def test_cli_run_dry_run_and_replay(
    repo_root: Path,
    fixture_state: Path,
    catalog_path: Path,
    tmp_path: Path,
):
    audit = tmp_path / "audit.jsonl"
    proc = _uv_sysone(
        "run",
        "--dry-run",
        "--backend",
        "mock",
        "--state",
        str(fixture_state),
        "--catalog",
        str(catalog_path),
        "--gate-config",
        "A2",
        "--audit",
        str(audit),
        cwd=repo_root,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "answers" in data
    assert "gate" in data
    assert "execution" in data
    if data["gate"]["decision"] in ("dry_run", "allow"):
        assert data["execution"] is not None
        assert data["execution"]["dry_run"] is True
        assert data["execution"]["side_effect_called"] is False
        assert data["execution"]["argv"] == ["systemctl", "restart", "php8.2-fpm"]

    assert audit.is_file()
    replay = _uv_sysone("replay", "--episode", str(audit), cwd=repo_root)
    assert replay.returncode == 0, replay.stderr
    summary = json.loads(replay.stdout)
    assert summary["count"] >= 1
    assert "episodes" in summary
    assert summary["episodes"][0]["decision"] in {
        "dry_run",
        "allow",
        "hitl",
        "deny",
        "escalate",
    }
