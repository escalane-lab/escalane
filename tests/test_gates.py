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


def test_gate_A0_membership(catalog):
    ans = make_answers("not_a_real_playbook", catalog)
    ans["playbook"]["choice"] = "not_a_real_playbook"
    r = apply_gates(ans, catalog, {}, config=GateConfig.A0, platform=_platform())
    assert r.decision == Decision.DENY
    assert r.reason == "unknown_playbook"

    ans2 = make_answers("escalate", catalog)
    r2 = apply_gates(ans2, catalog, {}, config=GateConfig.A0, platform=_platform())
    assert r2.decision == Decision.ESCALATE


def test_gate_A1_noul_veto(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.1, score=0.2, confidence=0.95)
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A1,
        platform=_platform(),
    )
    assert r.decision == Decision.DENY
    assert r.reason == "noul_fail"


def test_gate_A2_score_bands(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=3.0, confidence=0.95)
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A2,
        platform=_platform(),
        precheck_ok=True,
    )
    assert r.decision in (Decision.HITL, Decision.DENY)
    assert r.reason in ("blast_band", "blast_too_high")


def test_gate_A3_precision_hitl(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.95, score=0.3, confidence=0.95)
    # High-risk / precision_gate present → missing precision table → HITL
    r = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A3,
        platform=_platform(),
        per_label_precision={},  # missing → HITL when precision_gate set
        precheck_ok=True,
    )
    assert r.decision == Decision.HITL
    assert r.reason == "label_precision"

    r_ok = apply_gates(
        ans,
        catalog,
        {"host": "web-02"},
        config=GateConfig.A3,
        platform=_platform(),
        per_label_precision={"restart_php_fpm": 0.99},
        precheck_ok=True,
    )
    assert r_ok.decision == Decision.DRY_RUN
