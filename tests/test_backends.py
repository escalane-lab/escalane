"""Backend preset resolution + HttpSystemOne retries (httpx mock transport)."""

from __future__ import annotations

import json

import httpx
import pytest

from escalane.systemone import (
    BACKEND_PRESETS,
    AuthError,
    BackendError,
    EmptyAnswers,
    HttpSystemOne,
    Unreachable,
    make_client,
    resolve_backend,
)


def test_lmstudio_preset_defaults_to_1234() -> None:
    base, model, key = resolve_backend("lmstudio")
    assert base == "http://localhost:1234"
    assert model == BACKEND_PRESETS["lmstudio"]["model"]
    assert key == "lm-studio"


def test_ollama_preset_defaults_to_d3_2b() -> None:
    base, model, key = resolve_backend("ollama")
    assert base == "http://localhost:11434"
    assert model == "d3:2b"
    assert key is None


def test_lmstudio_default_model_is_d3_family() -> None:
    _, model, _ = resolve_backend("lmstudio")
    assert model.startswith("d3")


def test_env_overrides_base_and_model(monkeypatch) -> None:
    monkeypatch.setenv("ESCALANE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("ESCALANE_MODEL", "my-decision")
    base, model, _ = resolve_backend("lmstudio")
    assert base == "http://127.0.0.1:9999"
    assert model == "my-decision"


def test_legacy_sysone_env_still_works(monkeypatch) -> None:
    monkeypatch.delenv("ESCALANE_BASE_URL", raising=False)
    monkeypatch.delenv("ESCALANE_MODEL", raising=False)
    monkeypatch.setenv("SYSONE_BASE_URL", "http://127.0.0.1:8888")
    monkeypatch.setenv("SYSONE_MODEL", "legacy-model")
    base, model, _ = resolve_backend("lmstudio")
    assert base == "http://127.0.0.1:8888"
    assert model == "legacy-model"


def test_make_client_lmstudio_http() -> None:
    client = make_client("lmstudio", model="local-tev")
    assert client.base_url == "http://localhost:1234"
    assert client.model == "local-tev"
    assert client.api_key == "lm-studio"


def test_make_client_mock() -> None:
    client = make_client("mock")
    assert client.model == "mock"


def test_http_preset_requires_base_url(monkeypatch) -> None:
    monkeypatch.delenv("ESCALANE_BASE_URL", raising=False)
    monkeypatch.delenv("SYSONE_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="ESCALANE_BASE_URL"):
        resolve_backend("http")


def test_http_preset_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ESCALANE_BASE_URL", "https://decide.example:8080")
    monkeypatch.setenv("ESCALANE_API_KEY", "secret-key")
    monkeypatch.setenv("ESCALANE_MODEL", "my-jev")
    base, model, key = resolve_backend("http")
    assert base == "https://decide.example:8080"
    assert model == "my-jev"
    assert key == "secret-key"


def test_custom_alias_uses_jev_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ESCALANE_API_KEY", raising=False)
    monkeypatch.delenv("SYSONE_API_KEY", raising=False)
    monkeypatch.setenv("ESCALANE_BASE_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("JEV_API_KEY", "jev-secret")
    base, model, key = resolve_backend("custom")
    assert base == "http://127.0.0.1:9000"
    assert model == BACKEND_PRESETS["custom"]["model"]
    assert key == "jev-secret"


def test_make_client_http_passes_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ESCALANE_BASE_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("ESCALANE_API_KEY", "tok")
    client = make_client("http", model="x")
    assert isinstance(client, HttpSystemOne)
    assert client.api_key == "tok"
    assert client.backend == "http"


def _ok_answers(model: str = "d3:2b") -> dict:
    return {
        "model": model,
        "answers": {
            "playbook": {"type": "choice", "choice": "escalate", "confidence": 0.9},
            "safe_to_act": {"type": "noul", "noul": 0.1},
            "blast": {"type": "score", "score": 2.0, "confidence": 0.9},
        },
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }


def test_http_decide_success(catalog, php_state, monkeypatch) -> None:
    monkeypatch.setattr("escalane.systemone._retry_sleep", lambda *_a, **_k: None)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/systemone"
        assert request.headers.get("Authorization") == "Bearer tok"
        return httpx.Response(200, json=_ok_answers())

    transport = httpx.MockTransport(handler)
    client = HttpSystemOne(
        base_url="http://test",
        model="d3:2b",
        api_key="tok",
        transport=transport,
        max_retries=0,
    )
    resp = client.decide(php_state, catalog)
    assert resp.answers["playbook"]["choice"] == "escalate"
    assert resp.usage["input_tokens"] == 1


def test_http_retries_on_5xx_then_succeeds(catalog, php_state, monkeypatch) -> None:
    monkeypatch.setattr("escalane.systemone._retry_sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json=_ok_answers())

    client = HttpSystemOne(
        base_url="http://test",
        model="d3:2b",
        transport=httpx.MockTransport(handler),
        max_retries=3,
    )
    resp = client.decide(php_state, catalog)
    assert calls["n"] == 3
    assert resp.model == "d3:2b"


def test_http_5xx_exhausted_raises(catalog, php_state, monkeypatch) -> None:
    monkeypatch.setattr("escalane.systemone._retry_sleep", lambda *_a, **_k: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    client = HttpSystemOne(
        base_url="http://test",
        model="d3:2b",
        transport=httpx.MockTransport(handler),
        max_retries=2,
    )
    with pytest.raises(BackendError) as ei:
        client.decide(php_state, catalog)
    assert ei.value.status_code == 502


def test_http_401_no_retry(catalog, php_state, monkeypatch) -> None:
    monkeypatch.setattr("escalane.systemone._retry_sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    client = HttpSystemOne(
        base_url="http://test",
        model="d3:2b",
        api_key="bad",
        transport=httpx.MockTransport(handler),
        max_retries=3,
    )
    with pytest.raises(AuthError) as ei:
        client.decide(php_state, catalog)
    assert calls["n"] == 1
    assert ei.value.status_code == 401


def test_http_timeout_retries_then_unreachable(catalog, php_state, monkeypatch) -> None:
    monkeypatch.setattr("escalane.systemone._retry_sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)

    client = HttpSystemOne(
        base_url="http://test",
        model="d3:2b",
        transport=httpx.MockTransport(handler),
        max_retries=2,
        timeout=0.1,
    )
    with pytest.raises(Unreachable):
        client.decide(php_state, catalog)
    assert calls["n"] == 3


def test_http_empty_answers_fail_closed(catalog, php_state, monkeypatch) -> None:
    monkeypatch.setattr("escalane.systemone._retry_sleep", lambda *_a, **_k: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "d3:2b", "answers": {}})

    client = HttpSystemOne(
        base_url="http://test",
        model="d3:2b",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )
    with pytest.raises(EmptyAnswers):
        client.decide(php_state, catalog)


def test_errors_never_include_api_key(catalog, php_state, monkeypatch) -> None:
    monkeypatch.setattr("escalane.systemone._retry_sleep", lambda *_a, **_k: None)
    secret = "super-secret-api-key-xyz"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "nope"})

    client = HttpSystemOne(
        base_url="http://test",
        model="d3:2b",
        api_key=secret,
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )
    with pytest.raises(AuthError) as ei:
        client.decide(php_state, catalog)
    assert secret not in str(ei.value)
    assert secret not in json.dumps({"msg": str(ei.value)})
