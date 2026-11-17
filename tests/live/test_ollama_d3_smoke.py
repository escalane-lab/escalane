"""Optional live Ollama d3:2b smoke — skipped when unreachable / not pulled."""

from __future__ import annotations

import os

import httpx
import pytest

from escalane.systemone import (
    HttpSystemOne,
    build_systemone_request,
    ollama_reachable,
)

pytestmark = pytest.mark.live

OLLAMA_BASE = os.environ.get("SYSONE_BASE_URL", "http://localhost:11434")
D3_MODEL = os.environ.get("SYSONE_MODEL", "d3:2b")


def _d3_pulled(base_url: str = OLLAMA_BASE, model: str = D3_MODEL) -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            r = client.get(f"{base_url.rstrip('/')}/api/tags")
            if r.status_code != 200:
                return False
            names = {m.get("name") for m in (r.json().get("models") or [])}
            # Tags may appear as d3:2b or with digest suffix.
            if model in names:
                return True
            return any(isinstance(n, str) and (n == model or n.startswith(model + "-")) for n in names)
    except Exception:
        return False


@pytest.fixture(scope="module")
def require_ollama_d3():
    if not ollama_reachable(OLLAMA_BASE):
        pytest.skip("Ollama unreachable")
    if not _d3_pulled():
        if os.environ.get("SYSONE_LIVE_PULL", "").lower() in ("1", "true", "yes"):
            with httpx.Client(timeout=600.0) as client:
                # Streaming pull; only when explicitly requested.
                with client.stream(
                    "POST",
                    f"{OLLAMA_BASE.rstrip('/')}/api/pull",
                    json={"name": D3_MODEL},
                ) as resp:
                    for _ in resp.iter_bytes():
                        pass
            if not _d3_pulled():
                pytest.skip(f"{D3_MODEL} pull failed")
        else:
            pytest.skip(f"{D3_MODEL} not pulled (set SYSONE_LIVE_PULL=1 to pull)")


def test_ollama_d3_packed_decide_structure(catalog, php_502_state, require_ollama_d3):
    client = HttpSystemOne(base_url=OLLAMA_BASE, model=D3_MODEL, timeout=120.0)
    # Soft structural asserts only — no accuracy claims.
    req = build_systemone_request(php_502_state, catalog, D3_MODEL)
    assert set(req["questions"]) == {"playbook", "safe_to_act", "blast"}

    resp = client.decide(php_502_state, catalog, model=D3_MODEL)
    assert isinstance(resp.answers, dict)
    playbook = resp.answers.get("playbook")
    assert isinstance(playbook, dict)
    assert "choice" in playbook
    assert isinstance(playbook["choice"], str)

    noul = resp.answers.get("safe_to_act")
    assert isinstance(noul, dict)
    assert "noul" in noul
    assert isinstance(noul["noul"], (int, float))

    blast = resp.answers.get("blast")
    assert isinstance(blast, dict)
    assert "score" in blast
    assert isinstance(blast["score"], (int, float))
