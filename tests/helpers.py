"""Offline test helpers shared by unit + integration suites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from escalane.state import normalize_state
from escalane.systemone import MockSystemOne, make_answers

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_DIR = REPO_ROOT / "datasets" / "sysops_decide"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def state_from_suite_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Build a decide-ready state from a suite JSONL record."""
    state = dict(rec["state"])
    state["_golden_choice"] = rec.get("golden_choice")
    if "noul_safe" in rec:
        state["_noul_safe"] = rec["noul_safe"]
    if "score_blast_gold" in rec:
        state["_score_blast_gold"] = rec["score_blast_gold"]
    state["meta"] = {
        "id": rec.get("id"),
        "golden_choice": rec.get("golden_choice"),
        "noul_safe": rec.get("noul_safe"),
        "score_blast_gold": rec.get("score_blast_gold"),
    }
    return normalize_state(state)


class FakeSystemOne(MockSystemOne):
    """Scripted MockSystemOne for integration scenarios (offline)."""

    @classmethod
    def scripted(
        cls,
        answers_by_id: dict[str, dict[str, Any]] | None = None,
        *,
        default_choice: str = "escalate",
        model: str = "fake",
    ) -> FakeSystemOne:
        client = cls(default_choice=default_choice, model=model)
        for sid, answers in (answers_by_id or {}).items():
            client.register_state_id(sid, answers)
        return client

    def script(
        self,
        state_id: str,
        choice: str,
        catalog,
        *,
        noul: float = 0.95,
        score: float = 0.3,
        confidence: float = 0.95,
    ) -> None:
        self.register_state_id(
            state_id,
            make_answers(choice, catalog, noul=noul, score=score, confidence=confidence),
        )
