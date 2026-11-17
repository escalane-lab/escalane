"""System One request packing + backend resolve (offline)."""

from __future__ import annotations

from escalane.systemone import (
    BACKEND_PRESETS,
    MockSystemOne,
    build_systemone_request,
    make_answers,
    resolve_backend,
)


def test_build_packs_choice_noul_score(catalog, php_state):
    req = build_systemone_request(php_state, catalog, "mock")
    assert req["model"] == "mock"
    assert req["state"] is php_state or req["state"] == php_state
    q = req["questions"]
    assert q["playbook"]["type"] == "choice"
    assert "restart_php_fpm" in q["playbook"]["criteria"]
    assert q["safe_to_act"]["type"] == "noul"
    assert set(q["safe_to_act"]["criteria"]) == {"true", "false"}
    assert q["blast"]["type"] == "score"
    assert isinstance(q["blast"]["criteria"], list)
    assert len(q["blast"]["criteria"]) >= 3


def test_make_answers_structure(catalog):
    ans = make_answers("escalate", catalog, noul=0.2, score=2.0, confidence=0.91)
    assert ans["playbook"]["choice"] == "escalate"
    assert ans["playbook"]["confidence"] == 0.91
    assert ans["safe_to_act"]["noul"] == 0.2
    assert ans["blast"]["score"] == 2.0
    assert abs(sum(ans["playbook"]["probabilities"].values()) - 1.0) < 1e-6


def test_mock_register_state_id(catalog, php_state):
    client = MockSystemOne()
    scripted = make_answers("escalate", catalog, noul=0.1, score=2.0)
    client.register_state_id("demo", scripted)
    state = dict(php_state)
    state["meta"] = {"id": "demo"}
    resp = client.decide(state, catalog)
    assert resp.answers["playbook"]["choice"] == "escalate"
    assert resp.answers["safe_to_act"]["noul"] == 0.1


def test_resolve_backend_presets():
    o_base, o_model, o_key = resolve_backend("ollama")
    assert o_base == BACKEND_PRESETS["ollama"]["base_url"]
    assert o_model == "d3:2b"
    assert o_key is None

    j_base, j_model, _ = resolve_backend("jev")
    assert "typesafe" in j_base
    assert j_model == "jev-latest"

    m_base, m_model, m_key = resolve_backend("mock")
    assert m_base == ""
    assert m_model == "mock"
    assert m_key is None
