"""Shared offline episode runner mirroring CLI / eval loop."""

from __future__ import annotations

from typing import Any

from escalane.audit import AuditLog, episode_complete, new_op_id, validate_episode
from escalane.executor import execute
from escalane.gates import Decision, GateConfig, PlatformPolicy, apply_gates
from escalane.state import StateError, bind_params, state_digest
from escalane.systemone import SystemOneClient
from escalane.verify import run_postchecks, run_prechecks


def run_episode(
    state: dict[str, Any],
    client: SystemOneClient,
    catalog,
    *,
    gate_config: GateConfig | str = GateConfig.A2,
    platform: PlatformPolicy | None = None,
    per_label_precision: dict[str, float] | None = None,
    locks_held: set[str] | None = None,
    cooldowns_active: set[str] | None = None,
    audit: AuditLog | None = None,
    forbidden_substrings: list[str] | None = None,
    model_free_text: list[str] | None = None,
    allow_writes: bool = False,
    dry_run: bool = True,
    model: str = "fake",
) -> dict[str, Any]:
    """Ingested state → System One → gates → optional dry-run exec → audit episode."""
    resp = client.decide(state, catalog, model=model)
    choice = None
    if isinstance(resp.answers.get("playbook"), dict):
        choice = resp.answers["playbook"].get("choice")

    bound: dict[str, Any] = {}
    if choice and choice in catalog.ids and choice != "escalate":
        try:
            bound = bind_params(state, catalog.get(choice))
        except StateError:
            bound = {}

    pre_ok = True
    pre = None
    if choice and choice in catalog.ids and choice != "escalate":
        pre = run_prechecks(catalog.get(choice), bound, state=state)
        pre_ok = pre.ok

    platform = platform or PlatformPolicy(
        write_enabled=False,
        dry_run_only=True,
        noul_min=catalog.defaults.noul_min,
        confidence_min=catalog.defaults.confidence_min,
        promote_allow_to_dry_run=True,
    )
    gate = apply_gates(
        resp.answers,
        catalog,
        bound,
        config=gate_config,
        platform=platform,
        per_label_precision=per_label_precision,
        locks_held=locks_held,
        cooldowns_active=cooldowns_active,
        precheck_ok=pre_ok,
    )

    observation = None
    verify = None
    if gate.decision in (Decision.ALLOW, Decision.DRY_RUN) and gate.playbook_id:
        observation = execute(
            catalog,
            gate.playbook_id,
            bound,
            dry_run=True if gate.decision == Decision.DRY_RUN else dry_run,
            allow_writes=allow_writes,
            forbidden_substrings=forbidden_substrings,
            model_free_text=model_free_text,
        )
        verify = run_postchecks(catalog.get(gate.playbook_id), bound, state=state)

    ep = episode_complete(
        op_id=new_op_id(),
        catalog_hash=catalog.catalog_hash,
        model=resp.model,
        state_digest=state_digest(state),
        answers=resp.answers,
        gate_result=gate.to_dict(),
        playbook_id=gate.playbook_id,
        bound_params=bound,
        decision=gate.decision.value,
        execution=observation.to_dict() if observation else None,
        verify=verify.to_dict() if verify else (pre.to_dict() if pre else None),
        usage=resp.usage,
    )
    missing = validate_episode(ep)
    if audit is not None:
        audit.append(ep)

    return {
        "episode": ep,
        "missing_fields": missing,
        "answers": resp.answers,
        "gate": gate,
        "bound": bound,
        "observation": observation,
        "verify": verify,
        "choice": choice,
    }
