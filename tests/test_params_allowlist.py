"""ADR-005: enum + catalog allowlists at bind and execute."""

from __future__ import annotations

import pytest

from escalane.catalog import load_catalog
from escalane.executor import ExecutorError, execute
from escalane.state import StateError, bind_params, normalize_state, validate_bound_params


@pytest.fixture
def homelab(repo_root):
    return load_catalog(repo_root / "datasets" / "homelab_decide" / "catalog.yaml")


def test_homelab_catalog_loads_allowlists(homelab):
    assert "convenience-app" in homelab.allowlists["container"]
    assert "sensor-bridge" in homelab.allowlists["service"]


def test_off_list_container_rejected_at_bind(homelab):
    state = normalize_state(
        {
            "inventory": {"host": "laptop-01", "container": "evil-app"},
            "alert": {"labels": {"container": "evil-app"}},
            "locks": {},
        }
    )
    with pytest.raises(StateError, match="enum allowlist|allowlist"):
        bind_params(
            state,
            homelab.get("restart_docker_container"),
            catalog_allowlists=homelab.allowlists,
        )


def test_pattern_legal_but_off_list_fails_execute(homelab):
    """Even if a caller skips bind, execute re-checks nouns."""
    pb = homelab.get("restart_docker_container")
    with pytest.raises(ExecutorError, match="bound_params rejected"):
        execute(homelab, pb.id, {"container": "evil-app"}, dry_run=True)


def test_allowlisted_container_binds(homelab):
    state = normalize_state(
        {
            "inventory": {"host": "laptop-01", "container": "convenience-app"},
            "alert": {"labels": {}},
            "locks": {},
        }
    )
    bound = bind_params(
        state,
        homelab.get("restart_docker_container"),
        catalog_allowlists=homelab.allowlists,
    )
    assert bound["container"] == "convenience-app"
    obs = execute(homelab, "restart_docker_container", bound, dry_run=True)
    assert obs.argv == ["docker", "restart", "convenience-app"]


def test_high_noul_cannot_ship_off_list_noun(homelab):
    """Model self-report is irrelevant: off-list noun never reaches argv."""
    with pytest.raises((StateError, ExecutorError)):
        validate_bound_params(
            {"container": "evil-app"},
            homelab.get("restart_docker_container"),
            catalog_allowlists=homelab.allowlists,
        )


def test_blast_ux_high_means_wide(homelab):
    from escalane.gates import blast_band_for_score, blast_ux_fields

    pb = homelab.get("restart_docker_container")
    # auto_max_blast=0.7, require_hitl_above=1.4 → mid-high is deny; extreme is hitl
    assert blast_band_for_score(0.98, pb) == "deny"
    assert blast_band_for_score(1.5, pb) == "hitl"
    assert blast_band_for_score(0.2, pb) == "auto_ok"
    ux = blast_ux_fields({"blast": {"score": 0.9822}}, pb)
    assert ux["blast_polarity"] == "high_means_wide"
    assert ux["blast_radius_score"] == pytest.approx(0.9822)
    assert ux["blast_band"] == "deny"
