"""Append-only JSONL episode packages (L6)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from escalane import __version__

SCHEMA = "escalane.audit.v1"

REQUIRED_EPISODE_FIELDS = frozenset(
    {
        "schema",
        "event",
        "op_id",
        "ts",
        "harness_version",
        "catalog_hash",
        "model",
        "caller",
        "state_digest",
        "questions",
        "answers",
        "gates",
        "decision",
        "playbook_id",
        "bound_params",
    }
)


def new_op_id() -> str:
    return str(uuid.uuid4())


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_event(
    event: str,
    *,
    op_id: str,
    catalog_hash: str,
    model: str,
    caller: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    record = {
        "schema": SCHEMA,
        "event": event,
        "op_id": op_id,
        "ts": _ts(),
        "harness_version": __version__,
        "catalog_hash": catalog_hash,
        "model": model,
        "caller": caller
        or {"surface": "cli", "principal": "cli:local", "attenuated": True},
    }
    record.update(extra)
    return record


def episode_complete(
    *,
    op_id: str,
    catalog_hash: str,
    model: str,
    state_digest: str,
    answers: dict[str, Any],
    gate_result: dict[str, Any],
    playbook_id: str | None,
    bound_params: dict[str, Any],
    decision: str,
    questions: list[str] | None = None,
    execution: dict[str, Any] | None = None,
    verify: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    caller: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = make_event(
        "episode.complete",
        op_id=op_id,
        catalog_hash=catalog_hash,
        model=model,
        caller=caller,
        state_digest=state_digest,
        questions=questions or ["playbook", "safe_to_act", "blast"],
        answers=answers,
        gates=gate_result.get("gates", []),
        decision=decision,
        playbook_id=playbook_id,
        bound_params=bound_params,
        execution=execution,
        verify=verify,
        usage=usage,
    )
    if extra:
        record.update(extra)
    return record


def validate_episode(record: dict[str, Any]) -> list[str]:
    missing = sorted(REQUIRED_EPISODE_FIELDS - set(record))
    return missing


class AuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._buffer: list[dict[str, Any]] = []

    def append(self, record: dict[str, Any]) -> None:
        self._buffer.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._buffer)


def load_episodes(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def replay_summary(episodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for ep in episodes:
        if ep.get("event") != "episode.complete":
            continue
        summary.append(
            {
                "op_id": ep.get("op_id"),
                "decision": ep.get("decision"),
                "playbook_id": ep.get("playbook_id"),
                "model": ep.get("model"),
                "catalog_hash": ep.get("catalog_hash"),
                "ts": ep.get("ts"),
            }
        )
    return summary
