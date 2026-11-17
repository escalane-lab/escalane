"""Offline generative contrast: mock injection hallucinates; missing tags skip."""

from __future__ import annotations

import importlib.util

from helpers import REPO_ROOT, SUITE_DIR


def _load():
    path = REPO_ROOT / "eval" / "sysops_decide" / "generative_baseline.py"
    spec = importlib.util.spec_from_file_location("generative_baseline", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_skip_reason_does_not_substitute_models():
    mod = _load()
    assert mod.DEFAULT_GENERATIVE_MODEL == "qwen3.5:4b"
    assert "not a generative twin" in mod.CHECKPOINT_LIMITATION
    assert mod.live_skip_reason(server_up=False, names=[], model="qwen3.5:4b") == "ollama_unreachable"
    assert (
        mod.live_skip_reason(server_up=True, names=["d3:2b", "qwen3.6:35b"], model="qwen3.5:4b")
        == "model_missing"
    )
    assert mod.model_tag_present(["qwen3.5:4b"], "qwen3.5:4b")
    assert mod.model_tag_present(["qwen3.5:4b:latest"], "qwen3.5:4b")
    assert not mod.model_tag_present(["qwen3.5:40b"], "qwen3.5:4b")
    assert mod.live_skip_reason(server_up=True, names=["qwen3.5:4b"], model="qwen3.5:4b") is None


def test_mock_injection_hallucinates_args(tmp_path):
    mod = _load()
    summary = mod.run_generative(
        backend="mock",
        subset="injection",
        suite=SUITE_DIR,
        write=True,
        results_dir=tmp_path,
    )
    metrics = summary["metrics"]
    assert summary["label"] == "plumbing"
    assert summary["backend_role"] == "plumbing"
    assert summary["catalog_hash"]
    assert summary["suite_version"] == "v0.1"
    assert metrics["n"] >= 15
    assert metrics["injection_false_permit_rate"] > 0
    assert metrics["param_hallucination_rate"] > 0
    assert metrics["unauthorized_argv"] > 0
    assert "d3" in summary["limitation"]
    assert (tmp_path / "generative_latest.json").is_file()
