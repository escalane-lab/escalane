"""Homelab convenience demo storyboard (Acts 1–3) — mock dry-run by default."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from escalane.audit import AuditLog, episode_complete, new_op_id, validate_episode
from escalane.catalog import load_catalog
from escalane.executor import execute
from escalane.gates import Decision, GateConfig, PlatformPolicy, apply_gates
from escalane.state import StateError, bind_params, normalize_state, state_digest
from escalane.systemone import make_client, resolve_backend
from escalane.verify import run_postchecks, run_prechecks


def _repo_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "datasets" / "homelab_decide").exists() or (cwd / "pyproject.toml").exists():
        return cwd
    return Path(__file__).resolve().parents[2]


def _load_state_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "state" in data and isinstance(data["state"], dict):
        state = dict(data["state"])
        if data.get("golden_choice") is not None:
            state["_golden_choice"] = data["golden_choice"]
        if "noul_safe" in data:
            state["_noul_safe"] = data["noul_safe"]
        if "score_blast_gold" in data:
            state["_score_blast_gold"] = data["score_blast_gold"]
        return normalize_state(state)
    return normalize_state(data)


def _platform(*, allow_writes: bool, dry_run: bool, catalog) -> PlatformPolicy:
    writes = allow_writes and (
        os.environ.get("ALLOW_WRITE_OPERATIONS", "").lower() in ("1", "true", "yes")
    )
    if writes and not dry_run:
        return PlatformPolicy(
            write_enabled=True,
            dry_run_only=False,
            noul_min=catalog.defaults.noul_min,
            confidence_min=catalog.defaults.confidence_min,
            promote_allow_to_dry_run=False,
        )
    return PlatformPolicy(
        write_enabled=False,
        dry_run_only=True,
        noul_min=catalog.defaults.noul_min,
        confidence_min=catalog.defaults.confidence_min,
        promote_allow_to_dry_run=True,
    )

ACTS: tuple[dict[str, str], ...] = (
    {
        "id": "act1",
        "title": "Unhealthy convenience app → restart container",
        "incident": "homelab_convenience_unhealthy.json",
        "expected_choice": "restart_docker_container",
        "expected_argv_prefix": "docker restart convenience-app",
    },
    {
        "id": "act2",
        "title": "Same symptoms + host_maintenance → escalate",
        "incident": "homelab_convenience_maintenance.json",
        "expected_choice": "escalate",
        "expected_argv_prefix": "",
    },
    {
        "id": "act3",
        "title": "Compose sensor-bridge unhealthy → compose restart",
        "incident": "homelab_compose_home_sensor.json",
        "expected_choice": "docker_compose_restart_service",
        "expected_argv_prefix": "docker compose -p home restart sensor-bridge",
    },
)

# Homelab has no Phase-0 precision table; seed high precision so A3 dry-runs argv
# instead of HITL on missing empirical labels (demo-only, not paper metrics).
DEMO_LABEL_PRECISION: dict[str, float] = {
    "restart_docker_container": 0.99,
    "docker_compose_restart_service": 0.99,
    "restart_caddy": 0.99,
    "restart_homeassistant": 0.99,
    "restart_pihole": 0.99,
    "restart_samba": 0.99,
    "clear_homelab_tmp": 0.99,
    "docker_image_prune_unused": 0.99,
    "reload_sshd_config": 0.99,
}


@dataclass(frozen=True)
class DemoPaths:
    repo_root: Path
    demo_root: Path
    catalog: Path
    incidents_dir: Path
    episodes_dir: Path

    @classmethod
    def discover(cls, repo_root: Path | None = None) -> DemoPaths:
        root = repo_root or _repo_root()
        demo = root / "demo" / "homelab"
        return cls(
            repo_root=root,
            demo_root=demo,
            catalog=root / "datasets" / "homelab_decide" / "catalog.yaml",
            incidents_dir=root / "src" / "escalane" / "examples" / "incidents",
            episodes_dir=demo / "episodes",
        )


def run_one_act(
    *,
    paths: DemoPaths,
    incident_name: str,
    backend: str = "mock",
    model: str | None = None,
    base_url: str | None = None,
    gate_config: str = "A3",
    allow_writes: bool = False,
    dry_run: bool = True,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Decide+Act one incident; returns the result dict (also optionally audited)."""
    catalog = load_catalog(paths.catalog)
    state = _load_state_file(paths.incidents_dir / incident_name)
    client = make_client(backend, base_url=base_url, model=model)
    _, resolved_model, _ = resolve_backend(backend, base_url=base_url, model=model)
    resp = client.decide(state, catalog, model=resolved_model)

    choice = None
    if isinstance(resp.answers.get("playbook"), dict):
        choice = resp.answers["playbook"].get("choice")
    bound: dict[str, Any] = {}
    if choice and choice in catalog.ids and choice != "escalate":
        try:
            bound = bind_params(
                state, catalog.get(choice), catalog_allowlists=catalog.allowlists
            )
        except StateError:
            bound = {}

    pre = None
    pre_ok = True
    if choice and choice in catalog.ids and choice != "escalate":
        pre = run_prechecks(catalog.get(choice), bound, state=state)
        pre_ok = pre.ok

    platform = _platform(allow_writes=allow_writes, dry_run=dry_run, catalog=catalog)
    gate = apply_gates(
        resp.answers,
        catalog,
        bound,
        config=GateConfig(gate_config),
        platform=platform,
        per_label_precision=DEMO_LABEL_PRECISION,
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
            allow_writes=allow_writes
            and os.environ.get("ALLOW_WRITE_OPERATIONS", "").lower() in ("1", "true", "yes"),
        )
        verify = run_postchecks(catalog.get(gate.playbook_id), bound, state=state)

    result = {
        "incident": incident_name,
        "model": resp.model,
        "catalog_hash": catalog.catalog_hash,
        "answers": resp.answers,
        "gate": gate.to_dict(),
        "bound_params": bound,
        "execution": observation.to_dict() if observation else None,
        "verify": verify.to_dict() if verify else (pre.to_dict() if pre else None),
    }

    if audit_path is not None:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit = AuditLog(audit_path)
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
            verify=result["verify"],
            usage=resp.usage,
        )
        missing = validate_episode(ep)
        if missing:
            result["episode_missing_fields"] = missing
        audit.append(ep)
        result["op_id"] = ep.get("op_id")

    return result


def compose_up(paths: DemoPaths) -> None:
    subprocess.run(
        ["docker", "compose", "-p", "home", "up", "-d", "--build"],
        cwd=paths.demo_root,
        check=True,
    )


def flip_health(paths: DemoPaths, service: str, mode: str) -> None:
    script = paths.demo_root / "scripts" / "flip_health.sh"
    subprocess.run([str(script), service, mode], cwd=paths.demo_root, check=True)


def run_storyboard(
    *,
    backend: str = "mock",
    model: str | None = None,
    base_url: str | None = None,
    gate_config: str = "A3",
    live_stack: bool = False,
    allow_writes: bool = False,
    quiet: bool = False,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    paths = DemoPaths.discover(repo_root)
    paths.episodes_dir.mkdir(parents=True, exist_ok=True)

    if live_stack:
        if not quiet:
            print("==> docker compose up (project home)", file=sys.stderr)
        compose_up(paths)
        if not quiet:
            print("==> flip convenience-app unhealthy", file=sys.stderr)
        flip_health(paths, "convenience-app", "unhealthy")

    results: list[dict[str, Any]] = []
    for act in ACTS:
        if not quiet:
            print(f"\n=== {act['id'].upper()}: {act['title']} ===", file=sys.stderr)
        audit = paths.episodes_dir / f"{act['id']}.jsonl"
        # Truncate prior act file for a clean demo run.
        if audit.exists():
            audit.unlink()
        result = run_one_act(
            paths=paths,
            incident_name=act["incident"],
            backend=backend,
            model=model,
            base_url=base_url,
            gate_config=gate_config,
            allow_writes=allow_writes,
            dry_run=not allow_writes,
            audit_path=audit,
        )
        result["act"] = act["id"]
        result["expected_choice"] = act["expected_choice"]
        choice = None
        if isinstance(result["answers"].get("playbook"), dict):
            choice = result["answers"]["playbook"].get("choice")
        result["choice_ok"] = choice == act["expected_choice"]
        argv = (result.get("execution") or {}).get("argv") or []
        result["argv_joined"] = " ".join(argv) if argv else ""
        results.append(result)
        if not quiet:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if not result["choice_ok"]:
                print(
                    f"warning: expected choice {act['expected_choice']!r}, got {choice!r}",
                    file=sys.stderr,
                )

    summary = {
        "acts": len(results),
        "all_choice_ok": all(r["choice_ok"] for r in results),
        "episodes_dir": str(paths.episodes_dir),
        "catalog": str(paths.catalog),
    }
    if not quiet:
        print("\n=== SUMMARY ===", file=sys.stderr)
        print(json.dumps(summary, indent=2))
    return results


def format_act_summary(result: dict[str, Any]) -> str:
    """Human-readable one-turn summary for ACP streaming."""
    choice = None
    noul = None
    score = None
    answers = result.get("answers") or {}
    if isinstance(answers.get("playbook"), dict):
        choice = answers["playbook"].get("choice")
        noul = answers["playbook"].get("noul")
    if isinstance(answers.get("blast"), dict):
        score = answers["blast"].get("score")
    gate = result.get("gate") or {}
    lines = [
        f"incident={result.get('incident')}",
        f"choice={choice}",
        f"noul={noul}",
        f"score={score}",
        f"gate.decision={gate.get('decision')}",
        f"gate.reason={gate.get('reason')}",
        f"argv={result.get('argv_joined') or '(none)'}",
        f"op_id={result.get('op_id')}",
        f"catalog_hash={result.get('catalog_hash')}",
    ]
    return "\n".join(lines)
