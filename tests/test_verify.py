"""Pre/postcheck runners."""

from __future__ import annotations

from escalane.catalog import ExecutorSpec, Playbook
from escalane.verify import run_postchecks, run_prechecks


def _metric_playbook(*, expect: int) -> Playbook:
    return Playbook(
        id="metric_pb",
        criteria="test",
        prechecks=[
            {
                "type": "metric",
                "id": "idle_zero",
                "state_key": "phpfpm_idle_processes",
                "expect": expect,
            }
        ],
        executor=ExecutorSpec(kind="none"),
    )


def test_precheck_lock_absent_pass(catalog, php_state):
    pb = catalog.get("restart_php_fpm")
    result = run_prechecks(pb, {"host": "web-02"}, state=php_state)
    assert result.ok is True
    lock_checks = [c for c in result.checks if c.id == "not_migrating"]
    assert lock_checks
    assert lock_checks[0].ok is True
    assert lock_checks[0].stub is False


def test_precheck_lock_absent_fail(catalog, php_state):
    state = dict(php_state)
    state["locks"] = {"db_migrate": True, "host_maintenance": False}
    pb = catalog.get("restart_php_fpm")
    result = run_prechecks(pb, {"host": "web-02"}, state=state)
    assert result.ok is False
    assert any(c.id == "not_migrating" and not c.ok for c in result.checks)


def test_metric_precheck_true_false():
    state = {"metrics": {"phpfpm_idle_processes": 0}}
    ok = run_prechecks(_metric_playbook(expect=0), {}, state=state)
    assert ok.ok is True
    bad = run_prechecks(_metric_playbook(expect=5), {}, state=state)
    assert bad.ok is False


def test_postcheck_stub_always_ok(catalog, php_state):
    pb = catalog.get("restart_php_fpm")
    result = run_postchecks(pb, {"host": "web-02"}, state=php_state)
    assert result.ok is True
    assert result.to_dict()["ok"] is True
