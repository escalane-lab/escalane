from escalane.audit import episode_complete, new_op_id, validate_episode


def test_audit_required_fields(catalog):
    ep = episode_complete(
        op_id=new_op_id(),
        catalog_hash=catalog.catalog_hash,
        model="mock",
        state_digest="sha256:abc",
        answers={"playbook": {"choice": "escalate"}},
        gate_result={"gates": [{"name": "escalate", "result": "pass"}]},
        playbook_id="escalate",
        bound_params={},
        decision="escalate",
        usage={"input_tokens": 0, "output_tokens": 0},
    )
    assert validate_episode(ep) == []
    assert ep["schema"] == "escalane.audit.v1"
    assert ep["event"] == "episode.complete"
    assert ep["harness_version"]
    assert ep["catalog_hash"] == catalog.catalog_hash
