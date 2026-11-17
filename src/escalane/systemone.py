"""System One HTTP client + MockSystemOne + request packer (L2)."""

from __future__ import annotations

import hashlib
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from escalane.catalog import Catalog, stable_json
from escalane.state import state_digest

logger = logging.getLogger(__name__)

# Local / hosted presets for POST {base}/v1/systemone (same wire format).
# LM Studio (0.4.26+) serves Jev-compatible /v1/systemone when a decision model is loaded:
# https://lmstudio.ai/docs/developer/jev-compat/systemone
BACKEND_PRESETS: dict[str, dict[str, str]] = {
    "ollama": {
        "base_url": "http://localhost:11434",
        # d3 family (vLLM Semantic Router) — native /v1/systemone; needs Ollama ≥0.40.9
        # https://ollama.com/library/d3 — default 2b fits ~8GB APU; use d3 / d3:4b on eGPU when free
        "model": "d3:2b",
        "probe": "/api/tags",
    },
    "lmstudio": {
        "base_url": "http://localhost:1234",
        "model": "d3:2b",  # override with LM Studio's loaded decision-model id
        "probe": "/v1/models",
    },
    "jev": {
        "base_url": "https://api.typesafe.ai",
        "model": "jev-latest",
        "probe": "/v1/models",
    },
    # Self-hosted Jev-compat / vLLM-compat decision endpoints (base URL required).
    "http": {
        "base_url": "",
        "model": "jev-latest",
        "probe": "/v1/models",
    },
    "custom": {
        "base_url": "",
        "model": "jev-latest",
        "probe": "/v1/models",
    },
}

LIVE_BACKENDS = frozenset({"ollama", "lmstudio", "jev", "http", "custom"})

BLAST_CRITERIA = [
    "Single-process / single-host; redundant capacity available",
    "One service in one AZ; brief error-budget spend",
    "Multi-host or stateful; customer-visible risk",
    "Irreversible or data-plane; never auto-execute",
]

NOUL_CRITERIA = {
    "true": "Safe to proceed with catalog execution after gates",
    "false": "Block; escalate or HITL",
}

PLAYBOOK_INSTRUCTIONS = "Which remediation playbook matches this incident state?"
NOUL_INSTRUCTIONS = (
    "Given the state, are harness preconditions for a safe automated "
    "remediation satisfied (no migration lock, evidence complete, host writable)?"
)
BLAST_INSTRUCTIONS = "How disruptive is the matching automated action right now?"


class BackendError(Exception):
    """Base for System One backend failures (never includes API keys)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        backend: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.backend = backend


class Unreachable(BackendError):
    """Backend host unreachable after retries (connect / timeout)."""


class ModelMissing(BackendError):
    """Named decision model is not available on the backend."""


class AuthError(BackendError):
    """Authentication / authorization failure (401/403)."""


class EmptyAnswers(BackendError):
    """HTTP succeeded but answers were missing or empty."""


@dataclass
class SystemOneResponse:
    model: str
    answers: dict[str, Any]
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def build_systemone_request(
    state: dict[str, Any],
    catalog: Catalog,
    model: str,
) -> dict[str, Any]:
    """Pack choice + noul + score in one request (verified API pattern)."""
    return {
        "model": model,
        "state": state,
        "questions": {
            "playbook": {
                "type": "choice",
                "instructions": PLAYBOOK_INSTRUCTIONS,
                "criteria": catalog.criteria_map(),
            },
            "safe_to_act": {
                "type": "noul",
                "instructions": NOUL_INSTRUCTIONS,
                "criteria": dict(NOUL_CRITERIA),
            },
            "blast": {
                "type": "score",
                "instructions": BLAST_INSTRUCTIONS,
                "criteria": list(BLAST_CRITERIA),
            },
        },
    }


class SystemOneClient(ABC):
    @abstractmethod
    def decide(
        self,
        state: dict[str, Any],
        catalog: Catalog,
        model: str | None = None,
    ) -> SystemOneResponse:
        raise NotImplementedError


def _retry_sleep(attempt: int, *, base: float = 0.25, cap: float = 4.0) -> None:
    """Exponential backoff with full jitter (attempt is 0-indexed)."""
    delay = min(cap, base * (2**attempt))
    time.sleep(random.uniform(0.0, delay))


class HttpSystemOne(SystemOneClient):
    """POST {base}/v1/systemone with retries for transient 5xx/timeouts only."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "tev",
        api_key: str | None = None,
        timeout: float = 60.0,
        *,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        backend: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._transport = transport
        self.backend = backend

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _client(self) -> httpx.Client:
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def decide(
        self,
        state: dict[str, Any],
        catalog: Catalog,
        model: str | None = None,
    ) -> SystemOneResponse:
        use_model = model or self.model
        payload = build_systemone_request(state, catalog, use_model)
        headers = self._headers()
        url = f"{self.base_url}/v1/systemone"
        attempts = self.max_retries + 1
        last_error: BackendError | None = None

        for attempt in range(attempts):
            try:
                with self._client() as client:
                    resp = client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = Unreachable(
                    f"timeout talking to System One at {self.base_url}",
                    backend=self.backend,
                )
                logger.warning(
                    "systemone timeout base_url=%s attempt=%s/%s",
                    self.base_url,
                    attempt + 1,
                    attempts,
                )
                if attempt + 1 < attempts:
                    _retry_sleep(attempt)
                    continue
                raise last_error from exc
            except httpx.ConnectError as exc:
                last_error = Unreachable(
                    f"unreachable System One at {self.base_url}",
                    backend=self.backend,
                )
                logger.warning(
                    "systemone connect error base_url=%s attempt=%s/%s",
                    self.base_url,
                    attempt + 1,
                    attempts,
                )
                if attempt + 1 < attempts:
                    _retry_sleep(attempt)
                    continue
                raise last_error from exc
            except httpx.TransportError as exc:
                last_error = Unreachable(
                    f"transport error talking to System One at {self.base_url}: {type(exc).__name__}",
                    backend=self.backend,
                )
                if attempt + 1 < attempts:
                    _retry_sleep(attempt)
                    continue
                raise last_error from exc

            status = resp.status_code
            if status in (401, 403):
                raise AuthError(
                    f"System One auth failed (HTTP {status})",
                    status_code=status,
                    backend=self.backend,
                )
            if status == 404:
                raise ModelMissing(
                    f"System One model not found (HTTP 404): {use_model}",
                    status_code=status,
                    backend=self.backend,
                )
            if 500 <= status < 600:
                last_error = BackendError(
                    f"System One transient HTTP {status}",
                    status_code=status,
                    backend=self.backend,
                )
                logger.warning(
                    "systemone HTTP %s base_url=%s attempt=%s/%s",
                    status,
                    self.base_url,
                    attempt + 1,
                    attempts,
                )
                if attempt + 1 < attempts:
                    _retry_sleep(attempt)
                    continue
                raise last_error
            if status >= 400:
                raise BackendError(
                    f"System One HTTP {status}",
                    status_code=status,
                    backend=self.backend,
                )

            try:
                data = resp.json()
            except ValueError as exc:
                raise BackendError(
                    "System One returned non-JSON body",
                    status_code=status,
                    backend=self.backend,
                ) from exc

            answers = data.get("answers")
            if not isinstance(answers, dict) or not answers:
                raise EmptyAnswers(
                    "System One returned empty answers",
                    status_code=status,
                    backend=self.backend,
                )
            usage = data.get("usage") or {}
            return SystemOneResponse(
                model=str(data.get("model") or use_model),
                answers=answers,
                usage={
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                },
                raw=data if isinstance(data, dict) else {},
            )

        assert last_error is not None
        raise last_error


def _fixture_key(state: dict[str, Any]) -> str:
    return state_digest(state)


class MockSystemOne(SystemOneClient):
    """Fixture backend for pytest / eval plumbing (not model quality)."""

    def __init__(
        self,
        fixtures: dict[str, dict[str, Any]] | None = None,
        default_choice: str = "escalate",
        model: str = "mock",
    ) -> None:
        self.fixtures = fixtures or {}
        self.default_choice = default_choice
        self.model = model
        # Optional: map by state id if present.
        self._by_id: dict[str, dict[str, Any]] = {}

    def register(self, key: str, answers: dict[str, Any]) -> None:
        self.fixtures[key] = answers

    def register_state_id(self, state_id: str, answers: dict[str, Any]) -> None:
        self._by_id[state_id] = answers

    def decide(
        self,
        state: dict[str, Any],
        catalog: Catalog,
        model: str | None = None,
    ) -> SystemOneResponse:
        use_model = model or self.model
        answers: dict[str, Any] | None = None
        sid = None
        if isinstance(state.get("meta"), dict):
            sid = state["meta"].get("id")
        if sid is None:
            sid = state.get("_id") or state.get("id")
        if isinstance(sid, str) and sid in self._by_id:
            answers = dict(self._by_id[sid])
        if answers is None:
            key = _fixture_key(state)
            if key in self.fixtures:
                answers = dict(self.fixtures[key])
        if answers is None:
            # Heuristic from gold-like fields when present in state envelope.
            golden = state.get("_golden_choice") or (
                state.get("meta", {}).get("golden_choice")
                if isinstance(state.get("meta"), dict)
                else None
            )
            noul_safe = state.get("_noul_safe")
            if isinstance(state.get("meta"), dict) and noul_safe is None:
                noul_safe = state["meta"].get("noul_safe")
            choice = golden if isinstance(golden, str) else self.default_choice
            if choice not in catalog.ids:
                choice = "escalate" if "escalate" in catalog.ids else next(iter(catalog.ids))
            noul = 0.95 if noul_safe is True else (0.1 if noul_safe is False else 0.5)
            score_gold = state.get("_score_blast_gold")
            if isinstance(state.get("meta"), dict) and score_gold is None:
                score_gold = state["meta"].get("score_blast_gold")
            score = float(score_gold) if score_gold is not None else 0.3
            answers = _synthetic_answers(choice, catalog, noul=noul, score=score)
        return SystemOneResponse(
            model=use_model,
            answers=answers,
            usage={"input_tokens": 0, "output_tokens": 0},
            raw={"model": use_model, "answers": answers},
        )


def _synthetic_answers(
    choice: str,
    catalog: Catalog,
    *,
    noul: float,
    score: float,
    confidence: float = 0.92,
) -> dict[str, Any]:
    probs = {pid: 0.01 for pid in catalog.ids}
    if choice in probs:
        remainder = 1.0 - 0.01 * (len(probs) - 1)
        probs[choice] = max(remainder, 0.5)
    # Renormalize lightly.
    total = sum(probs.values()) or 1.0
    probs = {k: v / total for k, v in probs.items()}
    return {
        "playbook": {
            "type": "choice",
            "choice": choice,
            "probabilities": probs,
            "confidence": confidence,
        },
        "safe_to_act": {"type": "noul", "noul": noul},
        "blast": {
            "type": "score",
            "score": score,
            "confidence": confidence,
            "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1, "3": 0.0},
        },
    }


def make_answers(
    choice: str,
    catalog: Catalog,
    *,
    noul: float = 0.95,
    score: float = 0.3,
    confidence: float = 0.92,
) -> dict[str, Any]:
    return _synthetic_answers(choice, catalog, noul=noul, score=score, confidence=confidence)


def endpoint_reachable(
    base_url: str,
    probe_path: str = "/v1/models",
    *,
    timeout: float = 1.5,
    api_key: str | None = None,
) -> bool:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{base_url.rstrip('/')}{probe_path}", headers=headers)
            return r.status_code == 200
    except Exception:
        return False


def ollama_reachable(base_url: str = "http://localhost:11434", timeout: float = 1.5) -> bool:
    return endpoint_reachable(base_url, "/api/tags", timeout=timeout)


def lmstudio_reachable(base_url: str = "http://localhost:1234", timeout: float = 1.5) -> bool:
    """LM Studio local server (default :1234). Needs a *decision* model loaded for /v1/systemone."""
    return endpoint_reachable(base_url, "/v1/models", timeout=timeout)


def resolve_backend(
    backend: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> tuple[str, str, str | None]:
    """Resolve (base_url, model, api_key) for a named backend.

    Env overrides: ESCALANE_BASE_URL / ESCALANE_MODEL / ESCALANE_API_KEY
    (legacy SYSONE_* still accepted for one release). Also JEV_API_KEY for jev/http.
    API keys are returned for client use only — never log them.
    """
    if backend == "mock":
        return "", model or "mock", None
    preset = BACKEND_PRESETS.get(backend)
    if preset is None:
        raise ValueError(f"unknown backend: {backend}")

    def _env(*names: str) -> str | None:
        for name in names:
            val = os.environ.get(name)
            if val:
                return val
        return None

    resolved_base = (
        base_url
        or _env("ESCALANE_BASE_URL", "SYSONE_BASE_URL")
        or preset["base_url"]
    )
    if backend in ("http", "custom") and not resolved_base:
        raise ValueError(
            f"backend {backend!r} requires --base-url or ESCALANE_BASE_URL"
        )
    resolved_model = model or _env("ESCALANE_MODEL", "SYSONE_MODEL") or preset["model"]
    resolved_key = api_key or _env("ESCALANE_API_KEY", "SYSONE_API_KEY")
    if backend in ("jev", "http", "custom") and not resolved_key:
        resolved_key = os.environ.get("JEV_API_KEY")
    if backend == "lmstudio" and not resolved_key:
        # LM Studio accepts optional bearer; many setups use lm-studio as dummy key.
        resolved_key = os.environ.get("LM_API_KEY") or "lm-studio"
    return resolved_base.rstrip("/"), resolved_model, resolved_key


def make_client(
    backend: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
    max_retries: int = 2,
    transport: httpx.BaseTransport | None = None,
) -> SystemOneClient:
    if backend == "mock":
        return MockSystemOne(model=model or "mock")
    resolved_base, resolved_model, resolved_key = resolve_backend(
        backend, base_url=base_url, model=model, api_key=api_key
    )
    return HttpSystemOne(
        base_url=resolved_base,
        model=resolved_model,
        api_key=resolved_key,
        timeout=timeout,
        max_retries=max_retries,
        transport=transport,
        backend=backend,
    )


def backend_reachable(backend: str, base_url: str | None = None) -> bool:
    if backend == "mock":
        return True
    preset = BACKEND_PRESETS.get(backend)
    if preset is None:
        return False
    try:
        resolved_base, _, key = resolve_backend(backend, base_url=base_url)
    except ValueError:
        return False
    if not resolved_base:
        return False
    use_key = key if backend in ("jev", "http", "custom", "lmstudio") else None
    return endpoint_reachable(resolved_base, preset["probe"], api_key=use_key)


def digest_request(payload: dict[str, Any]) -> str:
    h = hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{h}"
