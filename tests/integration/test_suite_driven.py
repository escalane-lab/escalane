"""Suite-driven offline episodes over states.jsonl (Mock/Fake gold heuristics)."""

from __future__ import annotations

import pytest

from helpers import FakeSystemOne, state_from_suite_record
from integration.pipeline import run_episode
from escalane.gates import Decision, GateConfig, PlatformPolicy

# Keep runtime reasonable: full seed suite is ~60 rows; all fine offline.
ALLOWED = {d.value for d in Decision}


@pytest.fixture
def dry_platform(catalog) -> PlatformPolicy:
    return PlatformPolicy(
        write_enabled=False,
        dry_run_only=True,
        noul_min=catalog.defaults.noul_min,
        confidence_min=catalog.defaults.confidence_min,
        promote_allow_to_dry_run=True,
    )


def test_all_suite_states_produce_valid_episodes(
    catalog,
    suite_states,
    dry_platform,
):
    assert suite_states, "states.jsonl missing"
    client = FakeSystemOne()
    for rec in suite_states:
        state = state_from_suite_record(rec)
        out = run_episode(
            state,
            client,
            catalog,
            gate_config=GateConfig.A2,
            platform=dry_platform,
        )
        assert out["missing_fields"] == [], rec.get("id")
        assert out["gate"].decision.value in ALLOWED, rec.get("id")
        assert out["episode"]["catalog_hash"] == catalog.catalog_hash

        gold = rec.get("golden_choice")
        noul_safe = rec.get("noul_safe")
        # Mock follows gold; mutate + noul_safe should not die on noul_fail under A2.
        if gold and gold != "escalate" and noul_safe is True:
            assert out["choice"] == gold, rec.get("id")
            assert out["gate"].reason != "noul_fail", rec.get("id")
            assert out["gate"].decision != Decision.DENY or out["gate"].reason != "noul_fail"


def test_mutate_safe_subset_not_noul_deny(catalog, suite_states, dry_platform):
    client = FakeSystemOne()
    safe = [
        r
        for r in suite_states
        if r.get("noul_safe") is True
        and r.get("golden_choice") not in (None, "escalate")
        and not str(r.get("id", "")).startswith("st_inj_")
    ]
    assert len(safe) >= 5
    for rec in safe[:20]:
        out = run_episode(
            state_from_suite_record(rec),
            client,
            catalog,
            gate_config=GateConfig.A2,
            platform=dry_platform,
        )
        assert out["gate"].reason != "noul_fail", rec["id"]
        assert out["gate"].decision in (
            Decision.DRY_RUN,
            Decision.ALLOW,
            Decision.HITL,
            Decision.DENY,  # blast/params/precheck still allowed
        )
        if out["gate"].decision == Decision.DENY:
            assert out["gate"].reason != "noul_fail"


def test_twin_pairs_gold_selection(catalog, suite_twins, suite_states_by_id, dry_platform):
    client = FakeSystemOne()
    for twin in suite_twins:
        for sid, gold in ((twin["state_a"], twin["gold_a"]), (twin["state_b"], twin["gold_b"])):
            out = run_episode(
                state_from_suite_record(suite_states_by_id[sid]),
                client,
                catalog,
                gate_config=GateConfig.A2,
                platform=dry_platform,
            )
            assert out["choice"] == gold, twin["twin_id"]
