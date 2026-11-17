"""Pre/postcheck runners — stub + simple allowlisted hooks (L5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from escalane.catalog import Playbook


@dataclass
class CheckResult:
    id: str
    ok: bool
    detail: str = ""
    stub: bool = True


@dataclass
class VerifyResult:
    ok: bool
    checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [
                {"id": c.id, "ok": c.ok, "detail": c.detail, "stub": c.stub} for c in self.checks
            ],
        }


def run_prechecks(
    playbook: Playbook,
    bound_params: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
) -> VerifyResult:
    """Deterministic prechecks. Shell types are stubbed (always pass in dry research)."""
    return _run_checks(playbook.prechecks, bound_params, state=state, phase="pre")


def run_postchecks(
    playbook: Playbook,
    bound_params: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
) -> VerifyResult:
    return _run_checks(playbook.postchecks, bound_params, state=state, phase="post")


def _run_checks(
    checks: list[dict[str, Any]],
    bound_params: dict[str, Any],
    *,
    state: dict[str, Any] | None,
    phase: str,
) -> VerifyResult:
    results: list[CheckResult] = []
    for raw in checks:
        cid = str(raw.get("id") or f"{phase}_check")
        ctype = str(raw.get("type") or "stub")
        if ctype == "metric" and state is not None:
            # Simple metric equality against state.metrics when query is a key hint.
            metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
            # Prefer explicit state_key if present.
            key = raw.get("state_key")
            if key and key in metrics:
                expected = raw.get("expect")
                ok = metrics[key] == expected if expected is not None else True
                results.append(
                    CheckResult(id=cid, ok=bool(ok), detail=f"metric:{key}", stub=False)
                )
                continue
        if ctype == "lock_absent" and state is not None:
            locks = state.get("locks") if isinstance(state.get("locks"), dict) else {}
            lock_name = raw.get("lock")
            ok = not bool(locks.get(lock_name)) if lock_name else True
            results.append(CheckResult(id=cid, ok=ok, detail=f"lock:{lock_name}", stub=False))
            continue
        # shell / http / ansible stubs — research prototype does not contact hosts.
        results.append(
            CheckResult(
                id=cid,
                ok=True,
                detail=f"stub:{ctype}; params={sorted(bound_params)}",
                stub=True,
            )
        )
    ok = all(c.ok for c in results) if results else True
    return VerifyResult(ok=ok, checks=results)
