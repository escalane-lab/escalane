"""Full gate matrix A0–A3 beyond the smoke coverage in test_gates.py."""

from __future__ import annotations

import pytest

from escalane.gates import Decision, GateConfig, PlatformPolicy, apply_gates
from escalane.systemone import make_answers


def _platform(**kwargs) -> PlatformPolicy:
    base = dict(
        write_enabled=False,
        dry_run_only=True,
        noul_min=0.85,
        confidence_min=0.90,
        promote_allow_to_dry_run=True,
    )
    base.update(kwargs)
    return PlatformPolicy(**base)


def test_A0_allows_mutate_as_dry_run_without_noul(catalog):
    ans = {
        "playbook": {
            "type": "choice",
            "choice": "restart_php_fpm",
            "confidence": 0.99,
            "probabilities": {"restart_php_fpm": 1.0},
        }
    }
    r = apply_gates(ans, catalog, {"host": "web-02"}, config=GateConfig.A0, platform=_platform())
    assert r.decision == Decision.DRY_RUN
    assert r.reason == "a0_choice_only"


def test_A1_missing_noul_denies(catalog):
    ans = {
        "playbook": {
            "type": "choice",
            "choice": "restart_php_fpm",
            "confidence": 0.99,
            "probabilities": {},
        }
    }
    r = apply_gates(ans, catalog, {"host": "web-02"}, config=GateConfig.A1, platform=_platform())
    assert r.decision == Decision.DENY
    assert r.reason == "parse"


def test_A1_low_confidence_hitl(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.2, confidence=0.5)
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A1,
        platform=_platform(),
    )
    assert r.decision == Decision.HITL
    assert r.reason == "low_confidence"


def test_A2_happy_dry_run(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.3, confidence=0.95)
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A2,
        platform=_platform(),
        precheck_ok=True,
    )
    assert r.decision == Decision.DRY_RUN


def test_A2_blast_hitl_band(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=1.6, confidence=0.95)
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A2,
        platform=_platform(),
    )
    assert r.decision == Decision.HITL
    assert r.reason == "blast_band"


def test_A2_blast_too_high_deny(catalog):
    # auto_max_blast=0.8, require_hitl_above=1.5 → score 0.9 is > auto_max but < hitl
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.9, confidence=0.95)
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A2,
        platform=_platform(),
    )
    assert r.decision == Decision.DENY
    assert r.reason == "blast_too_high"


def test_lock_and_cooldown(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.3, confidence=0.95)
    lock_key = "svc:php-fpm:web-02"
    r_lock = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A2,
        platform=_platform(),
        locks_held={lock_key},
    )
    assert r_lock.decision == Decision.DENY
    assert r_lock.reason == "lock"

    r_cd = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A2,
        platform=_platform(),
        cooldowns_active={lock_key},
    )
    assert r_cd.decision == Decision.DENY
    assert r_cd.reason == "cooldown"


def test_precheck_fail_deny(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.3, confidence=0.95)
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A2,
        platform=_platform(),
        precheck_ok=False,
    )
    assert r.decision == Decision.DENY
    assert r.reason == "precheck"


def test_missing_params_deny(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.3, confidence=0.95)
    r = apply_gates(
        ans,
        catalog,
        {},  # missing host
        config=GateConfig.A2,
        platform=_platform(),
    )
    assert r.decision == Decision.DENY
    assert r.reason == "params"


def test_writes_disabled_when_not_dry_run(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.3, confidence=0.95)
    platform = _platform(write_enabled=False, dry_run_only=False, promote_allow_to_dry_run=False)
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A2,
        platform=platform,
        precheck_ok=True,
    )
    assert r.decision == Decision.DENY
    assert r.reason == "writes_disabled"


@pytest.mark.parametrize("cfg", [GateConfig.A2, GateConfig.A3])
def test_A2_plus_requires_blast(catalog, cfg):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.3, confidence=0.95)
    del ans["blast"]
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=cfg,
        platform=_platform(),
        per_label_precision={"restart_php_fpm": 0.99},
    )
    assert r.decision == Decision.DENY
    assert r.reason == "parse"
