from escalane.systemone import MockSystemOne, build_systemone_request, make_answers


def test_mock_decide_pack(catalog, php_state):
    req = build_systemone_request(php_state, catalog, "mock")
    assert set(req["questions"]) == {"playbook", "safe_to_act", "blast"}
    assert req["questions"]["playbook"]["type"] == "choice"
    assert req["questions"]["safe_to_act"]["type"] == "noul"
    assert req["questions"]["blast"]["type"] == "score"
    assert "escalate" in req["questions"]["playbook"]["criteria"]
    # Keys AND descriptions both present
    for key, desc in req["questions"]["playbook"]["criteria"].items():
        assert key
        assert isinstance(desc, str) and desc.strip()

    client = MockSystemOne()
    resp = client.decide(php_state, catalog)
    assert resp.answers["playbook"]["choice"] == "restart_php_fpm"
    assert resp.answers["safe_to_act"]["noul"] >= 0.85
    assert "score" in resp.answers["blast"]


def test_make_answers_unknown_falls_back(catalog):
    ans = make_answers("restart_php_fpm", catalog, noul=0.1, score=2.0)
    assert ans["playbook"]["choice"] == "restart_php_fpm"
    assert ans["safe_to_act"]["noul"] == 0.1
