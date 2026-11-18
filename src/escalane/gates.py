"""Ordered policy gates A0–A3 (L3). First failure wins."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from escalane.catalog import Catalog, Playbook


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    HITL = "hitl"
    DRY_RUN = "dry_run"
    ESCALATE = "escalate"


class GateConfig(str, Enum):
    """Ablation presets shared with eval runner."""

    A0 = "A0"  # choice + catalog membership (+ escalate)
    A1 = "A1"  # A0 + noul veto
    A2 = "A2"  # A1 + score bands
    A3 = "A3"  # A2 + per-label precision HITL


@dataclass
class PlatformPolicy:
    write_enabled: bool = False
    dry_run_only: bool = True
    noul_min: float = 0.85
    confidence_min: float = 0.90
    # When dry_run_only, mutating ALLOW becomes DRY_RUN (research default).
    promote_allow_to_dry_run: bool = True


@dataclass
class GateStep:
    name: str
    result: str  # pass | fail | skip
    value: Any = None
    threshold: Any = None
    reason: str | None = None


@dataclass
class GateResult:
    decision: Decision
    reason: str
    playbook_id: str | None
    steps: list[GateStep] = field(default_factory=list)
    bound_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "playbook_id": self.playbook_id,
            "gates": [
                {
                    "name": s.name,
                    "result": s.result,
                    "value": s.value,
                    "threshold": s.threshold,
                    "reason": s.reason,
                }
                for s in self.steps
            ],
            "bound_params": self.bound_params,
        }


def _fail(
    decision: Decision,
    reason: str,
    playbook_id: str | None,
    steps: list[GateStep],
    bound_params: dict[str, Any] | None = None,
) -> GateResult:
    return GateResult(
        decision=decision,
        reason=reason,
        playbook_id=playbook_id,
        steps=steps,
        bound_params=bound_params or {},
    )


def apply_gates(
    answers: dict[str, Any],
    catalog: Catalog,
    bound_params: dict[str, Any],
    *,
    config: GateConfig | str = GateConfig.A3,
    platform: PlatformPolicy | None = None,
    per_label_precision: dict[str, float] | None = None,
    locks_held: set[str] | None = None,
    cooldowns_active: set[str] | None = None,
    precheck_ok: bool = True,
) -> GateResult:
    """Run ordered vetoes matching harness_implementation.md §4 / ablation table."""
    cfg = GateConfig(config) if not isinstance(config, GateConfig) else config
    platform = platform or PlatformPolicy(
        write_enabled=catalog.defaults.write_enabled,
        dry_run_only=catalog.defaults.dry_run_default,
        noul_min=catalog.defaults.noul_min,
        confidence_min=catalog.defaults.confidence_min,
    )
    precision = per_label_precision or {}
    locks_held = locks_held or set()
    cooldowns_active = cooldowns_active or set()
    steps: list[GateStep] = []

    # 1. Structural
    playbook_ans = answers.get("playbook") if isinstance(answers, dict) else None
    noul_ans = answers.get("safe_to_act") if isinstance(answers, dict) else None
    blast_ans = answers.get("blast") if isinstance(answers, dict) else None
    if not isinstance(playbook_ans, dict) or "choice" not in playbook_ans:
        steps.append(GateStep("parse", "fail", reason="missing_playbook"))
        return _fail(Decision.DENY, "parse", None, steps)
    # A0+ always require playbook; A1+ require noul; A2+ require blast.
    if cfg != GateConfig.A0:
        if not isinstance(noul_ans, dict) or "noul" not in noul_ans:
            steps.append(GateStep("parse", "fail", reason="missing_noul"))
            return _fail(Decision.DENY, "parse", None, steps)
    if cfg in (GateConfig.A2, GateConfig.A3):
        if not isinstance(blast_ans, dict) or "score" not in blast_ans:
            steps.append(GateStep("parse", "fail", reason="missing_blast"))
            return _fail(Decision.DENY, "parse", None, steps)

    playbook_id = str(playbook_ans["choice"])
    steps.append(GateStep("parse", "pass", value=playbook_id))

    if playbook_id not in catalog.ids:
        steps.append(GateStep("catalog_membership", "fail", value=playbook_id))
        return _fail(Decision.DENY, "unknown_playbook", playbook_id, steps)
    steps.append(GateStep("catalog_membership", "pass", value=playbook_id))

    if playbook_id == "escalate":
        steps.append(GateStep("escalate", "pass", reason="model_escalate"))
        return _fail(Decision.ESCALATE, "model_escalate", playbook_id, steps)

    entry = catalog.get(playbook_id)

    # 2. Platform kill-switches (always for mutate paths beyond A0 membership)
    if not platform.write_enabled and not platform.dry_run_only:
        steps.append(GateStep("writes", "fail", reason="writes_disabled"))
        return _fail(Decision.DENY, "writes_disabled", playbook_id, steps, bound_params)
    steps.append(
        GateStep(
            "writes",
            "pass",
            value={"write_enabled": platform.write_enabled, "dry_run_only": platform.dry_run_only},
        )
    )

    # A0 stops after membership (+ escalate). For research smoke we still
    # return DRY_RUN when dry_run_only so executor can exercise templates.
    if cfg == GateConfig.A0:
        if platform.dry_run_only and entry.mutates:
            steps.append(GateStep("dry_run_policy", "pass", reason="a0_dry_run"))
            return GateResult(
                Decision.DRY_RUN, "a0_choice_only", playbook_id, steps, bound_params
            )
        return GateResult(Decision.ALLOW, "a0_choice_only", playbook_id, steps, bound_params)

    # 3. noul hard veto (A1+)
    noul_min = entry.noul_min if entry.noul_min is not None else platform.noul_min
    noul_val = float(noul_ans["noul"])  # type: ignore[index]
    if noul_val < noul_min:
        steps.append(GateStep("noul", "fail", value=noul_val, threshold=noul_min, reason="noul_fail"))
        return _fail(Decision.DENY, "noul_fail", playbook_id, steps, bound_params)
    steps.append(GateStep("noul", "pass", value=noul_val, threshold=noul_min))

    # 4. Confidence (A1+ structural safety — always with noul in A1+)
    conf_min = entry.confidence_min if entry.confidence_min is not None else platform.confidence_min
    conf = float(playbook_ans.get("confidence") or 0.0)
    if conf < conf_min:
        steps.append(
            GateStep("confidence", "fail", value=conf, threshold=conf_min, reason="low_confidence")
        )
        return _fail(Decision.HITL, "low_confidence", playbook_id, steps, bound_params)
    steps.append(GateStep("confidence", "pass", value=conf, threshold=conf_min))

    # 4b. Per-label precision HITL (A3 only)
    if cfg == GateConfig.A3:
        min_prec = None
        if entry.precision_gate and "min_empirical_precision" in entry.precision_gate:
            min_prec = float(entry.precision_gate["min_empirical_precision"])
        elif entry.risk_tier in ("high", "critical"):
            min_prec = 0.95
        if min_prec is not None:
            observed = precision.get(playbook_id)
            if observed is None or observed < min_prec:
                steps.append(
                    GateStep(
                        "label_precision",
                        "fail",
                        value=observed,
                        threshold=min_prec,
                        reason="label_precision",
                    )
                )
                return _fail(Decision.HITL, "label_precision", playbook_id, steps, bound_params)
            steps.append(
                GateStep("label_precision", "pass", value=observed, threshold=min_prec)
            )
        else:
            steps.append(GateStep("label_precision", "skip"))

    # 5. score bands (A2+)
    if cfg in (GateConfig.A2, GateConfig.A3):
        score = float(blast_ans["score"])  # type: ignore[index]
        if score >= entry.require_hitl_above:
            steps.append(
                GateStep(
                    "blast",
                    "fail",
                    value=score,
                    threshold=entry.require_hitl_above,
                    reason="blast_band",
                )
            )
            return _fail(Decision.HITL, "blast_band", playbook_id, steps, bound_params)
        if score > entry.auto_max_blast:
            steps.append(
                GateStep(
                    "blast",
                    "fail",
                    value=score,
                    threshold=entry.auto_max_blast,
                    reason="blast_too_high",
                )
            )
            return _fail(Decision.DENY, "blast_too_high", playbook_id, steps, bound_params)
        steps.append(
            GateStep(
                "blast",
                "pass",
                value=score,
                threshold={"auto_max": entry.auto_max_blast, "hitl_above": entry.require_hitl_above},
            )
        )

    # 6. lock / cooldown
    lock_key = _render_lock_key(entry, bound_params)
    if lock_key and lock_key in locks_held:
        steps.append(GateStep("lock", "fail", value=lock_key, reason="lock"))
        return _fail(Decision.DENY, "lock", playbook_id, steps, bound_params)
    if lock_key and lock_key in cooldowns_active:
        steps.append(GateStep("cooldown", "fail", value=lock_key, reason="cooldown"))
        return _fail(Decision.DENY, "cooldown", playbook_id, steps, bound_params)
    steps.append(GateStep("lock", "pass", value=lock_key))

    # 7. params already bound — empty mutate params fail
    if entry.mutates and entry.params_schema.get("required"):
        for req in entry.params_schema["required"]:
            if req not in bound_params:
                steps.append(GateStep("params", "fail", reason="params"))
                return _fail(Decision.DENY, "params", playbook_id, steps, bound_params)
    steps.append(GateStep("params", "pass", value=bound_params))

    # 8. prechecks
    if not precheck_ok:
        steps.append(GateStep("precheck", "fail", reason="precheck"))
        return _fail(Decision.DENY, "precheck", playbook_id, steps, bound_params)
    steps.append(GateStep("precheck", "pass"))

    if platform.dry_run_only and entry.mutates and platform.promote_allow_to_dry_run:
        steps.append(GateStep("dry_run_policy", "pass"))
        return GateResult(Decision.DRY_RUN, "dry_run_only", playbook_id, steps, bound_params)
    if not platform.write_enabled and entry.mutates:
        return _fail(Decision.DENY, "writes_disabled", playbook_id, steps, bound_params)

    return GateResult(Decision.ALLOW, "allow", playbook_id, steps, bound_params)


def _render_lock_key(entry: Playbook, bound_params: dict[str, Any]) -> str | None:
    if not entry.lock_key:
        return None
    key = entry.lock_key
    for k, v in bound_params.items():
        key = key.replace("{" + k + "}", str(v))
    return key


def blast_band_for_score(score: float, playbook: Playbook | None) -> str:
    """Map blast.score to a named band. Polarity: higher = wider / more disruptive."""
    if playbook is None:
        return "unknown"
    if score >= playbook.require_hitl_above:
        return "hitl"
    if score > playbook.auto_max_blast:
        return "deny"
    return "auto_ok"


def blast_ux_fields(
    answers: dict[str, Any],
    playbook: Playbook | None,
) -> dict[str, Any]:
    """Companion fields so blast polarity cannot be misread in CLI/episode JSON."""
    blast = answers.get("blast") if isinstance(answers, dict) else None
    score = None
    if isinstance(blast, dict) and "score" in blast:
        try:
            score = float(blast["score"])
        except (TypeError, ValueError):
            score = None
    out: dict[str, Any] = {
        "blast_polarity": "high_means_wide",
        "blast_radius_score": score,
    }
    if score is not None:
        out["blast_band"] = blast_band_for_score(score, playbook)
    return out
