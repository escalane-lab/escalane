"""Offline metric helpers for the Decision Suite eval."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers import REPO_ROOT


def _load(name: str, rel: str):
    path = Path(REPO_ROOT) / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_choice_false_deny_and_tau():
    metrics = _load("sysops_decide_metrics", "eval/sysops_decide/metrics.py")
    assert metrics.choice_correct("restart_php_fpm", "restart_php_fpm")
    assert not metrics.choice_correct("escalate", "restart_php_fpm")
    assert metrics.false_deny(decision="deny", gold="restart_php_fpm", noul_safe=True)
    assert not metrics.false_deny(decision="deny", gold="escalate", noul_safe=False)
    assert not metrics.false_deny(decision="dry_run", gold="restart_php_fpm", noul_safe=True)

    fitted = metrics.fit_noul_tau_on_cal(
        [
            {"noul": 0.95, "noul_safe": True},
            {"noul": 0.96, "noul_safe": True},
            {"noul": 0.2, "noul_safe": False},
            {"noul": 0.1, "noul_safe": False},
        ]
    )
    assert fitted["fp_rate"] == 0.0
    assert fitted["fd_rate"] == 0.0
    assert fitted["tau"] <= 0.95

    rows = [
        {
            "decision": "dry_run",
            "false_permit": False,
            "false_deny": False,
            "choice_correct": True,
            "unauthorized_argv": 0,
            "missing_fields": [],
            "latency_ms": 10.0,
        },
        {
            "decision": "hitl",
            "false_permit": False,
            "false_deny": True,
            "choice_correct": False,
            "unauthorized_argv": 0,
            "missing_fields": ["op_id"],
            "latency_ms": 30.0,
        },
    ]
    stats = metrics.aggregate_config_stats(rows)
    assert stats["n"] == 2
    assert stats["hitl_rate"] == 0.5
    assert stats["false_deny"] == 1
    assert stats["choice_accuracy"] == 0.5
    assert stats["audit_completeness"] == 0.5
    assert stats["unauthorized_argv"] == 0
    assert stats["latency_p50_ms"] == 10.0


def test_latency_usage_and_rule_router():
    metrics = _load("sysops_decide_metrics_lat", "eval/sysops_decide/metrics.py")
    assert metrics.latency_ms_from_usage({"latency_ms": 12.5}) == 12.5
    assert metrics.latency_ms_from_usage({}, {"total_duration": 2_000_000}) == 2.0
    assert metrics.latency_ms_from_usage({"input_tokens": 3}) is None
    # Explicit milliseconds beat a nanosecond field on the same object.
    assert metrics.latency_ms_from_usage({"latency_ms": 4, "total_duration": 9_000_000}) == 4

    summary = metrics.rule_baseline_summary(
        [
            {
                "golden_choice": "restart_php_fpm",
                "state": {"alert": {"alertname": "Http502High"}},
            },
            {
                "golden_choice": "escalate",
                "state": {"alert": {"alertname": "Http502High"}},
            },
        ]
    )
    assert summary["n"] == 2
    assert summary["correct"] == 1
    assert summary["accuracy"] == 0.5


def test_twin_pair_requires_both():
    metrics = _load("sysops_decide_metrics_twin", "eval/sysops_decide/metrics.py")
    twins = [
        {"state_a": "a", "state_b": "b", "gold_a": "restart_php_fpm", "gold_b": "escalate"}
    ]
    both = metrics.twin_pair_accuracy(
        twins, {"a": "restart_php_fpm", "b": "escalate"}
    )
    one = metrics.twin_pair_accuracy(twins, {"a": "restart_php_fpm", "b": "restart_php_fpm"})
    assert both["pair_accuracy"] == 1.0
    assert one["both_correct"] == 0
    assert metrics.twin_pair_accuracy(twins, {"a": "restart_php_fpm"})["n_pairs"] == 0


def test_fit_per_label_precision_wilson_and_fallback():
    metrics = _load("sysops_decide_metrics_prec", "eval/sysops_decide/metrics.py")
    rows = (
        [{"choice": "restart_php_fpm", "gold": "restart_php_fpm"}] * 3
        + [{"choice": "restart_php_fpm", "gold": "escalate"}] * 2
        + [{"choice": "restart_nginx", "gold": "restart_nginx"}] * 2
    )
    fitted = metrics.fit_per_label_precision_on_cal(
        rows,
        playbook_ids=["restart_php_fpm", "restart_nginx", "clear_tmp_disk"],
        min_hits=3,
        fallback=0.0,
    )
    table = fitted["per_label_precision"]
    assert fitted["detail"]["restart_php_fpm"]["n"] == 5
    assert fitted["detail"]["restart_php_fpm"]["empirical"] == 0.6
    assert fitted["detail"]["restart_php_fpm"]["method"] == "wilson_lower"
    assert 0.0 < table["restart_php_fpm"] < 0.6
    assert table["restart_nginx"] == 0.0  # n=2 < min_hits
    assert fitted["detail"]["restart_nginx"]["method"] == "fallback_low_n"
    assert table["clear_tmp_disk"] == 0.0  # never chosen
