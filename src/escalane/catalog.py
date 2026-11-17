"""Catalog load, validate, and catalog_hash (L4 registry)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class CatalogError(ValueError):
    """Invalid or incomplete playbook catalog."""


@dataclass(frozen=True)
class ExecutorSpec:
    kind: str
    unit: str | None = None
    action: str | None = None
    script: str | None = None
    binary: str | None = None
    args_template: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Playbook:
    id: str
    criteria: str
    risk_tier: str = "low"
    auto_max_blast: float = 0.8
    require_hitl_above: float = 1.5
    lock_key: str | None = None
    cooldown_seconds: int = 0
    params_schema: dict[str, Any] = field(default_factory=dict)
    prechecks: list[dict[str, Any]] = field(default_factory=list)
    postchecks: list[dict[str, Any]] = field(default_factory=list)
    executor: ExecutorSpec = field(default_factory=lambda: ExecutorSpec(kind="none"))
    precision_gate: dict[str, Any] | None = None
    noul_min: float | None = None
    confidence_min: float | None = None

    @property
    def mutates(self) -> bool:
        return self.executor.kind not in ("none", "", None)


@dataclass
class CatalogDefaults:
    confidence_min: float = 0.90
    noul_min: float = 0.85
    write_enabled: bool = False
    dry_run_default: bool = True


@dataclass
class Catalog:
    version: int
    defaults: CatalogDefaults
    playbooks: dict[str, Playbook]
    catalog_hash: str
    source_path: Path | None = None

    @property
    def ids(self) -> set[str]:
        return set(self.playbooks)

    def criteria_map(self) -> dict[str, str]:
        return {pid: p.criteria for pid, p in self.playbooks.items()}

    def get(self, playbook_id: str) -> Playbook:
        if playbook_id not in self.playbooks:
            raise CatalogError(f"unknown playbook: {playbook_id}")
        return self.playbooks[playbook_id]


def _parse_executor(raw: Any) -> ExecutorSpec:
    if raw is None:
        return ExecutorSpec(kind="none")
    if not isinstance(raw, dict):
        raise CatalogError("executor must be a mapping")
    kind = str(raw.get("kind", "none"))
    return ExecutorSpec(
        kind=kind,
        unit=raw.get("unit"),
        action=raw.get("action"),
        script=raw.get("script"),
        binary=raw.get("binary"),
        args_template=list(raw.get("args_template") or []),
    )


def _parse_playbook(raw: dict[str, Any]) -> Playbook:
    if "id" not in raw:
        raise CatalogError("playbook missing id")
    pid = str(raw["id"])
    criteria = str(raw.get("criteria") or "").strip()
    if not criteria:
        raise CatalogError(f"playbook {pid} missing criteria")
    return Playbook(
        id=pid,
        criteria=criteria,
        risk_tier=str(raw.get("risk_tier", "low")),
        auto_max_blast=float(raw.get("auto_max_blast", 0.8)),
        require_hitl_above=float(raw.get("require_hitl_above", 1.5)),
        lock_key=raw.get("lock_key"),
        cooldown_seconds=int(raw.get("cooldown_seconds", 0) or 0),
        params_schema=dict(raw.get("params_schema") or {}),
        prechecks=list(raw.get("prechecks") or []),
        postchecks=list(raw.get("postchecks") or []),
        executor=_parse_executor(raw.get("executor")),
        precision_gate=dict(raw["precision_gate"]) if raw.get("precision_gate") else None,
        noul_min=float(raw["noul_min"]) if raw.get("noul_min") is not None else None,
        confidence_min=(
            float(raw["confidence_min"]) if raw.get("confidence_min") is not None else None
        ),
    )


def catalog_hash_bytes(data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest}"


def compute_catalog_hash(path: Path) -> str:
    """SHA-256 of raw catalog file bytes (canonical recipe for README)."""
    return catalog_hash_bytes(path.read_bytes())


def load_catalog(path: str | Path) -> Catalog:
    path = Path(path)
    raw_bytes = path.read_bytes()
    data = yaml.safe_load(raw_bytes)
    if not isinstance(data, dict):
        raise CatalogError("catalog root must be a mapping")
    version = int(data.get("version", 1))
    draw = data.get("defaults") or {}
    defaults = CatalogDefaults(
        confidence_min=float(draw.get("confidence_min", 0.90)),
        noul_min=float(draw.get("noul_min", 0.85)),
        write_enabled=bool(draw.get("write_enabled", False)),
        dry_run_default=bool(draw.get("dry_run_default", True)),
    )
    playbooks_raw = data.get("playbooks")
    if not isinstance(playbooks_raw, list) or not playbooks_raw:
        raise CatalogError("catalog.playbooks must be a non-empty list")
    playbooks: dict[str, Playbook] = {}
    for item in playbooks_raw:
        if not isinstance(item, dict):
            raise CatalogError("each playbook must be a mapping")
        pb = _parse_playbook(item)
        if pb.id in playbooks:
            raise CatalogError(f"duplicate playbook id: {pb.id}")
        playbooks[pb.id] = pb
    if "escalate" not in playbooks:
        raise CatalogError("catalog must include escalate playbook")
    return Catalog(
        version=version,
        defaults=defaults,
        playbooks=playbooks,
        catalog_hash=catalog_hash_bytes(raw_bytes),
        source_path=path,
    )


def default_catalog_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    suite = root / "datasets" / "sysops_decide" / "catalog.yaml"
    if suite.is_file():
        return suite
    example = root / "src" / "escalane" / "examples" / "catalog.yaml"
    if example.is_file():
        return example
    # Installed package relative fallback
    pkg = Path(__file__).resolve().parent / "examples" / "catalog.yaml"
    return pkg


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
