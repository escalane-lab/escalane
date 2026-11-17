"""State normalize + bind_params coverage."""

from __future__ import annotations

import pytest

from escalane.state import StateError, bind_params, normalize_state, state_digest


def test_normalize_accepts_object(php_state):
    out = normalize_state(php_state)
    assert out["inventory"]["host"] == "web-02"
    assert state_digest(out).startswith("sha256:")


def test_normalize_json_string():
    out = normalize_state('{"inventory": {"host": "web-01"}}')
    assert out["inventory"]["host"] == "web-01"


def test_normalize_rejects_non_object():
    with pytest.raises(StateError):
        normalize_state([1, 2])
    with pytest.raises(StateError):
        normalize_state(None)


def test_reject_nested_command_like_fields():
    with pytest.raises(StateError, match="forbidden"):
        normalize_state({"alert": {"argv": ["rm", "-rf"]}})
    with pytest.raises(StateError, match="forbidden"):
        normalize_state({"metrics": {"raw_command": "reboot"}})
    with pytest.raises(StateError, match="forbidden"):
        normalize_state({"log_excerpts": [{"cmd": "id"}]})


def test_bind_params_success(catalog, php_state):
    bound = bind_params(normalize_state(php_state), catalog.get("restart_php_fpm"))
    assert bound == {"host": "web-02"}


def test_bind_params_prefers_inventory_over_labels(catalog):
    state = normalize_state(
        {
            "alert": {"labels": {"host": "label-host"}},
            "inventory": {"host": "inv-host"},
        }
    )
    bound = bind_params(state, catalog.get("restart_php_fpm"))
    assert bound["host"] == "inv-host"


def test_bind_params_missing_required(catalog):
    state = normalize_state({"alert": {}, "inventory": {}})
    with pytest.raises(StateError, match="cannot bind"):
        bind_params(state, catalog.get("restart_php_fpm"))


def test_bind_params_invalid_host(catalog):
    state = normalize_state({"inventory": {"host": "BAD HOST!!!"}})
    with pytest.raises(StateError, match="invalid host"):
        bind_params(state, catalog.get("restart_php_fpm"))


def test_bind_params_non_mutating_empty(catalog, php_state):
    assert bind_params(normalize_state(php_state), catalog.get("escalate")) == {}
