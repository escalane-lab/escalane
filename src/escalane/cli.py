"""CLI: decide | run --dry-run | replay."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from escalane.audit import (
    AuditLog,
    episode_complete,
    load_episodes,
    new_op_id,
    replay_summary,
    validate_episode,
)
from escalane.catalog import default_catalog_path, load_catalog
from escalane.executor import execute
from escalane.gates import Decision, GateConfig, PlatformPolicy, apply_gates
from escalane.ingest import IngestError, normalize_request
from escalane.state import StateError, bind_params, normalize_state, state_digest
from escalane.systemone import (
    LIVE_BACKENDS,
    BackendError,
    Unreachable,
    backend_reachable,
    build_systemone_request,
    make_client,
    resolve_backend,
)
from escalane.verify import run_postchecks, run_prechecks


def _repo_root() -> Path:
    # Prefer cwd when running from repo; fall back to package parents.
    cwd = Path.cwd()
    if (cwd / "datasets" / "sysops_decide").exists() or (cwd / "pyproject.toml").exists():
        return cwd
    return Path(__file__).resolve().parents[2]


def _load_state_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    # Suite record shape: {id, state, golden_choice, ...}
    if isinstance(data, dict) and "state" in data and isinstance(data["state"], dict):
        state = dict(data["state"])
        meta = {
            "id": data.get("id"),
            "golden_choice": data.get("golden_choice"),
            "noul_safe": data.get("noul_safe"),
            "score_blast_gold": data.get("score_blast_gold"),
        }
        state["meta"] = {k: v for k, v in meta.items() if v is not None}
        # Also surface for MockSystemOne heuristics.
        if data.get("golden_choice") is not None:
            state["_golden_choice"] = data["golden_choice"]
        if "noul_safe" in data:
            state["_noul_safe"] = data["noul_safe"]
        if "score_blast_gold" in data:
            state["_score_blast_gold"] = data["score_blast_gold"]
        return normalize_state(state)
    return normalize_state(data)


def _make_client(args: argparse.Namespace) -> Any:
    try:
        return make_client(
            args.backend,
            base_url=args.base_url,
            model=args.model,
            timeout=float(getattr(args, "timeout", 60.0)),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _ensure_live_reachable(args: argparse.Namespace) -> None:
    """When --require-live, refuse unreachable live backends (exit non-zero)."""
    if not getattr(args, "require_live", False):
        return
    if args.backend not in LIVE_BACKENDS:
        return
    if not backend_reachable(args.backend, args.base_url):
        print(
            json.dumps(
                {
                    "error": "Unreachable",
                    "backend": args.backend,
                    "detail": "Live backend unreachable; refusing mock fallback",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)


def _platform_from_args(args: argparse.Namespace, catalog) -> PlatformPolicy:
    allow_writes = bool(getattr(args, "allow_writes", False)) and (
        os.environ.get("ALLOW_WRITE_OPERATIONS", "").lower() in ("1", "true", "yes")
    )
    dry_run = bool(getattr(args, "dry_run", True))
    if allow_writes and not dry_run:
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


def cmd_decide(args: argparse.Namespace) -> int:
    catalog_path = Path(args.catalog) if args.catalog else default_catalog_path(_repo_root())
    catalog = load_catalog(catalog_path)
    state = _load_state_file(Path(args.state))
    _ensure_live_reachable(args)
    client = _make_client(args)
    _, model, _ = resolve_backend(
        args.backend, base_url=args.base_url, model=args.model
    )
    resp = client.decide(state, catalog, model=model)

    # Bind params for the chosen playbook when known; else empty until gates pick.
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
    if choice and choice in catalog.ids and choice != "escalate":
        pre = run_prechecks(catalog.get(choice), bound, state=state)
        pre_ok = pre.ok

    platform = _platform_from_args(args, catalog)
    gate = apply_gates(
        resp.answers,
        catalog,
        bound,
        config=GateConfig(args.gate_config),
        platform=platform,
        precheck_ok=pre_ok,
    )

    out = {
        "model": resp.model,
        "catalog_hash": catalog.catalog_hash,
        "answers": resp.answers,
        "gate": gate.to_dict(),
        "request_questions": list(build_systemone_request(state, catalog, model)["questions"]),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))

    if args.audit:
        audit = AuditLog(args.audit)
        op_id = new_op_id()
        ep = episode_complete(
            op_id=op_id,
            catalog_hash=catalog.catalog_hash,
            model=resp.model,
            state_digest=state_digest(state),
            answers=resp.answers,
            gate_result=gate.to_dict(),
            playbook_id=gate.playbook_id,
            bound_params=bound,
            decision=gate.decision.value,
            usage=resp.usage,
        )
        audit.append(ep)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    # Force dry-run unless dual-gated allow-writes.
    if not args.allow_writes:
        args.dry_run = True
    catalog_path = Path(args.catalog) if args.catalog else default_catalog_path(_repo_root())
    catalog = load_catalog(catalog_path)
    state = _load_state_file(Path(args.state))
    _ensure_live_reachable(args)
    client = _make_client(args)
    _, model, _ = resolve_backend(
        args.backend, base_url=args.base_url, model=args.model
    )
    resp = client.decide(state, catalog, model=model)

    choice = None
    if isinstance(resp.answers.get("playbook"), dict):
        choice = resp.answers["playbook"].get("choice")
    bound: dict[str, Any] = {}
    if choice and choice in catalog.ids and choice != "escalate":
        try:
            bound = bind_params(state, catalog.get(choice))
        except StateError as exc:
            print(json.dumps({"error": "bind_params", "detail": str(exc)}), file=sys.stderr)
            bound = {}

    pre = None
    pre_ok = True
    if choice and choice in catalog.ids and choice != "escalate":
        pre = run_prechecks(catalog.get(choice), bound, state=state)
        pre_ok = pre.ok

    platform = _platform_from_args(args, catalog)
    gate = apply_gates(
        resp.answers,
        catalog,
        bound,
        config=GateConfig(args.gate_config),
        platform=platform,
        precheck_ok=pre_ok,
    )

    observation = None
    verify = None
    if gate.decision in (Decision.ALLOW, Decision.DRY_RUN) and gate.playbook_id:
        observation = execute(
            catalog,
            gate.playbook_id,
            bound,
            dry_run=True if gate.decision == Decision.DRY_RUN else bool(args.dry_run),
            allow_writes=bool(args.allow_writes)
            and os.environ.get("ALLOW_WRITE_OPERATIONS", "").lower() in ("1", "true", "yes"),
        )
        verify = run_postchecks(catalog.get(gate.playbook_id), bound, state=state)

    result = {
        "model": resp.model,
        "catalog_hash": catalog.catalog_hash,
        "answers": resp.answers,
        "gate": gate.to_dict(),
        "execution": observation.to_dict() if observation else None,
        "verify": verify.to_dict() if verify else (pre.to_dict() if pre else None),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))

    audit_path = args.audit
    if audit_path:
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
            verify=verify.to_dict() if verify else None,
            usage=resp.usage,
        )
        missing = validate_episode(ep)
        if missing:
            print(f"warning: episode missing fields: {missing}", file=sys.stderr)
        audit.append(ep)
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    episodes = load_episodes(Path(args.episode))
    summary = replay_summary(episodes)
    print(json.dumps({"count": len(summary), "episodes": summary}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="escalane", description="Escalane Decide+Act research harness")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--backend",
            choices=["mock", "ollama", "lmstudio", "jev", "http", "custom"],
            default=os.environ.get("ESCALANE_BACKEND")
            or os.environ.get("SYSONE_BACKEND", "mock"),
            help="mock | ollama | lmstudio | jev | http/custom (ESCALANE_BASE_URL)",
        )
        sp.add_argument(
            "--base-url",
            default=None,
            help="Override server base (defaults: ollama :11434, lmstudio :1234, jev api.typesafe.ai)",
        )
        sp.add_argument(
            "--model",
            default=None,
            help="Decision model id (LM Studio: use the loaded decision-model identifier)",
        )
        sp.add_argument(
            "--timeout",
            type=float,
            default=60.0,
            help="HTTP timeout seconds for live System One decide",
        )
        sp.add_argument(
            "--require-live",
            action="store_true",
            help="Exit non-zero if live backend unreachable (never fall back to mock)",
        )
        sp.add_argument("--catalog", default=None)
        sp.add_argument("--state", required=True)
        sp.add_argument("--gate-config", choices=["A0", "A1", "A2", "A3"], default="A3")
        sp.add_argument("--audit", default=None, help="Append episode JSONL path")

    d = sub.add_parser("decide", help="Pack System One questions and apply gates")
    add_common(d)
    d.set_defaults(func=cmd_decide)

    r = sub.add_parser("run", help="Decide + dry-run execute catalog template")
    add_common(r)
    r.add_argument("--dry-run", action="store_true", default=True)
    r.add_argument("--allow-writes", action="store_true", default=False)
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("replay", help="Summarize episode JSONL")
    rp.add_argument("--episode", required=True)
    rp.set_defaults(func=cmd_replay)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in ("decide", "run"):
            # Optional ingest rejection when state file itself embeds command keys at top.
            if args.command == "decide" or args.command == "run":
                pass
        code = args.func(args)
    except (IngestError, StateError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from exc
    except (Unreachable, BackendError) as exc:
        # Live decide failures (incl. --require-live unreachable probe path).
        # Never include API keys in error payloads.
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "detail": str(exc),
                    "backend": getattr(exc, "backend", None) or getattr(args, "backend", None),
                    "status_code": getattr(exc, "status_code", None),
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
