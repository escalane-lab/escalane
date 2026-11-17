"""Audit episode validation + replay_summary."""

from __future__ import annotations

from escalane.audit import (
    AuditLog,
    episode_complete,
    load_episodes,
    new_op_id,
    replay_summary,
    validate_episode,
)


def test_episode_required_fields_and_replay(catalog, tmp_path):
    path = tmp_path / "ep.jsonl"
    audit = AuditLog(path)
    ep = episode_complete(
        op_id=new_op_id(),
        catalog_hash=catalog.catalog_hash,
        model="mock",
        state_digest="sha256:abc",
        answers={"playbook": {"choice": "restart_php_fpm"}},
        gate_result={"gates": [{"name": "noul", "result": "pass"}], "decision": "dry_run"},
        playbook_id="restart_php_fpm",
        bound_params={"host": "web-02"},
        decision="dry_run",
        execution={"argv": ["systemctl", "restart", "php8.2-fpm"], "dry_run": True},
        usage={"input_tokens": 1, "output_tokens": 2},
    )
    assert validate_episode(ep) == []
    audit.append(ep)
    audit.append(
        {
            "schema": "escalane.audit.v1",
            "event": "other",
            "op_id": new_op_id(),
        }
    )

    loaded = load_episodes(path)
    assert len(loaded) == 2
    summary = replay_summary(loaded)
    assert len(summary) == 1
    assert summary[0]["decision"] == "dry_run"
    assert summary[0]["playbook_id"] == "restart_php_fpm"
    assert summary[0]["catalog_hash"] == catalog.catalog_hash


def test_validate_episode_reports_missing():
    missing = validate_episode({"event": "episode.complete"})
    assert "op_id" in missing
    assert "decision" in missing
    assert "catalog_hash" in missing
