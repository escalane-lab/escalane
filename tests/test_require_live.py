"""Fail-closed live claim fence: no silent mock fallback."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import REPO_ROOT


def _load_runner():
    path = REPO_ROOT / "eval" / "sysops_decide" / "runner.py"
    spec = importlib.util.spec_from_file_location("sysops_decide_runner", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Avoid executing main; still need dependencies on sys.path.
    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


def test_require_live_exits_nonzero_when_unreachable(monkeypatch) -> None:
    mod = _load_runner()
    monkeypatch.setattr(mod, "backend_reachable", lambda *_a, **_k: False)
    with pytest.raises(SystemExit) as ei:
        mod.main(
            [
                "--backend",
                "ollama",
                "--require-live",
                "--subset",
                "injection",
                "--limit",
                "1",
            ]
        )
    assert ei.value.code == 1


def test_live_optional_exits_zero_when_unreachable(monkeypatch, capsys) -> None:
    mod = _load_runner()
    monkeypatch.setattr(mod, "backend_reachable", lambda *_a, **_k: False)
    with pytest.raises(SystemExit) as ei:
        mod.main(
            [
                "--backend",
                "ollama",
                "--live-optional",
                "--subset",
                "injection",
                "--limit",
                "1",
            ]
        )
    assert ei.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "skipped_live"
    assert "mock" not in out.get("note", "").lower() or "refusing" in out.get("note", "").lower()
    assert out["backend"] == "ollama"


def test_mock_summary_records_backend_role_plumbing() -> None:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "eval/sysops_decide/runner.py",
            "--backend",
            "mock",
            "--subset",
            "injection",
            "--limit",
            "2",
            "--configs",
            "A0",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["backend_role"] == "plumbing"
    assert payload["catalog_hash"]
    assert payload["model"] == "mock"


def test_generative_require_live_exit(monkeypatch) -> None:
    path = REPO_ROOT / "eval" / "sysops_decide" / "generative_baseline.py"
    spec = importlib.util.spec_from_file_location("generative_baseline", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ollama_model_status", lambda *_a, **_k: "unreachable")
    with pytest.raises(SystemExit) as ei:
        mod.main(["--backend", "ollama", "--require-live", "--limit", "1"])
    assert ei.value.code == 1
