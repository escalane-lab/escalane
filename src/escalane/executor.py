"""Template executor — catalog + bound_params only; dry-run default (L4)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from escalane.catalog import Catalog, Playbook
from escalane.state import StateError, validate_bound_params

_SAFE_TOKEN = re.compile(r"^[a-zA-Z0-9_./:@+-]+$")


class ExecutorError(ValueError):
    """Unsafe or invalid execution plan."""


@dataclass
class Observation:
    ok: bool
    exit_code: int | None
    stdout_digest: str
    stderr_digest: str
    started_at: str
    finished_at: str
    adapter: str
    playbook_id: str
    bound_params: dict[str, Any]
    dry_run: bool
    argv: list[str] = field(default_factory=list)
    plan: str | None = None
    side_effect_called: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "stdout_digest": self.stdout_digest,
            "stderr_digest": self.stderr_digest,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "adapter": self.adapter,
            "playbook_id": self.playbook_id,
            "bound_params": self.bound_params,
            "dry_run": self.dry_run,
            "argv": list(self.argv),
            "plan": self.plan,
            "side_effect_called": self.side_effect_called,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_argv(playbook: Playbook, bound_params: dict[str, Any]) -> list[str]:
    """Build argv from catalog executor template + bound params only."""
    ex = playbook.executor
    kind = ex.kind
    if kind == "none":
        return []
    if kind == "systemd":
        unit = ex.unit
        action = ex.action or "restart"
        if not unit or not _SAFE_TOKEN.match(unit) or not _SAFE_TOKEN.match(action):
            raise ExecutorError("invalid systemd unit/action")
        host = bound_params.get("host")
        if host is not None and not isinstance(host, str):
            raise ExecutorError("host must be string")
        # Host is metadata for remote adapters; local dry-run argv is systemctl only.
        return ["systemctl", action, unit]
    if kind == "script":
        script = ex.script or f"scripts/{playbook.id}.sh"
        if not _SAFE_TOKEN.match(script.replace("/", "")):
            # Allow path separators already checked loosely
            if ".." in script or script.startswith("-"):
                raise ExecutorError("unsafe script path")
        argv = ["/bin/sh", script]
        for key in sorted(bound_params):
            val = bound_params[key]
            if not isinstance(val, str) or not _SAFE_TOKEN.match(val):
                raise ExecutorError(f"unsafe script param: {key}")
            argv.append(f"--{key}={val}")
        return argv
    if kind in ("cli", "databricks"):
        # Fixed CLI from catalog binary + args_template; params only fill {placeholders}.
        binary = ex.binary or ("databricks" if kind == "databricks" else None)
        if not binary or not _SAFE_TOKEN.match(binary) or "/" in binary:
            raise ExecutorError(f"{kind} executor requires a safe binary name")
        if not ex.args_template:
            raise ExecutorError(f"{kind} executor requires args_template")
        argv = [binary]
        for part in ex.args_template:
            if not isinstance(part, str) or not part:
                raise ExecutorError(f"invalid {kind} args_template token")
            if "{" in part:
                try:
                    rendered = part.format(**bound_params)
                except KeyError as exc:
                    raise ExecutorError(f"{kind} template missing param: {exc}") from exc
            else:
                rendered = part
            if not _SAFE_TOKEN.match(rendered):
                raise ExecutorError(f"unsafe {kind} argv token: {rendered!r}")
            argv.append(rendered)
        return argv
    if kind in ("ansible", "kubectl"):
        # Stub interfaces — document catalog fields; dry-run only.
        return [kind, "check-mode", playbook.id]
    raise ExecutorError(f"unsupported executor kind: {kind}")


def assert_argv_invariant(
    argv: list[str],
    *,
    forbidden_substrings: list[str] | None = None,
    model_free_text: list[str] | None = None,
) -> None:
    """Unauthorized argv count must be 0 — no injection payloads / attacker hosts.

    Model choice ids are catalog keys, not argv tokens; any model_free_text that
    is not identical to a catalog-rendered token (e.g. systemd unit) must not
    appear as a free-form substring with spaces or hostile markers.
    """
    joined = " ".join(argv)
    for needle in forbidden_substrings or []:
        if needle and needle in joined:
            raise ExecutorError(f"argv invariant violated: contains {needle!r}")
    for needle in model_free_text or []:
        if not needle:
            continue
        # Allow exact argv tokens that happen to equal a bound/catalog token.
        if needle in argv:
            continue
        if " " in needle or needle.upper().startswith("IGNORE") or needle in joined:
            if needle in joined and needle not in argv:
                raise ExecutorError(f"argv invariant violated: model free-text {needle!r}")


# Hook for tests to prove dry-run never mutates.
_REAL_SIDE_EFFECT: Callable[[list[str]], int] | None = None


def set_real_side_effect_hook(hook: Callable[[list[str]], int] | None) -> None:
    global _REAL_SIDE_EFFECT
    _REAL_SIDE_EFFECT = hook


def execute(
    catalog: Catalog,
    playbook_id: str,
    bound_params: dict[str, Any],
    *,
    dry_run: bool = True,
    allow_writes: bool = False,
    forbidden_substrings: list[str] | None = None,
    model_free_text: list[str] | None = None,
) -> Observation:
    started = _now()
    if playbook_id not in catalog.ids:
        raise ExecutorError(f"unknown playbook: {playbook_id}")
    playbook = catalog.get(playbook_id)
    # ADR-005: re-check nouns at Act time (callers must not skip bind validation).
    try:
        validate_bound_params(
            bound_params, playbook, catalog_allowlists=catalog.allowlists
        )
    except StateError as exc:
        raise ExecutorError(f"bound_params rejected at execute: {exc}") from exc
    argv = render_argv(playbook, bound_params)
    assert_argv_invariant(
        argv,
        forbidden_substrings=forbidden_substrings,
        model_free_text=model_free_text,
    )
    side_effect = False
    exit_code: int | None = 0
    stdout = ""
    stderr = ""
    plan = " ".join(argv) if argv else "(none)"

    if dry_run or not allow_writes or playbook.executor.kind == "none":
        # Dry-run path: never call real side effect.
        finished = _now()
        return Observation(
            ok=True,
            exit_code=0,
            stdout_digest=_digest(stdout or plan),
            stderr_digest=_digest(stderr),
            started_at=started,
            finished_at=finished,
            adapter=playbook.executor.kind,
            playbook_id=playbook_id,
            bound_params=dict(bound_params),
            dry_run=True,
            argv=argv,
            plan=plan,
            side_effect_called=False,
        )

    # Real writes — only when explicitly dual-gated; still catalog template only.
    if _REAL_SIDE_EFFECT is not None:
        exit_code = _REAL_SIDE_EFFECT(argv)
        side_effect = True
    else:
        # Prototype refuses live host remediations without an injected hook.
        raise ExecutorError("live writes not enabled in research prototype")

    finished = _now()
    return Observation(
        ok=exit_code == 0,
        exit_code=exit_code,
        stdout_digest=_digest(stdout),
        stderr_digest=_digest(stderr),
        started_at=started,
        finished_at=finished,
        adapter=playbook.executor.kind,
        playbook_id=playbook_id,
        bound_params=dict(bound_params),
        dry_run=False,
        argv=argv,
        plan=plan,
        side_effect_called=side_effect,
    )
