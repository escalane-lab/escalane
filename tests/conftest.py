"""Shared fixtures for offline harness tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from escalane.audit import AuditLog
from escalane.catalog import load_catalog
from escalane.state import normalize_state

from helpers import (
    REPO_ROOT,
    SUITE_DIR,
    FakeSystemOne,
    load_jsonl,
    state_from_suite_record,
)

SUITE_CATALOG = SUITE_DIR / "catalog.yaml"
EXAMPLE_CATALOG = REPO_ROOT / "src" / "escalane" / "examples" / "catalog.yaml"
PHP_502_EXAMPLE = REPO_ROOT / "src" / "escalane" / "examples" / "incidents" / "php_502.json"

# Re-export for tests that import from conftest.
__all__ = [
    "FakeSystemOne",
    "load_jsonl",
    "state_from_suite_record",
    "REPO_ROOT",
    "SUITE_DIR",
]


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001
    """Auto-mark tests by directory so -m unit/integration/live works."""
    for item in items:
        path = Path(str(item.fspath)).as_posix()
        if "/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/live/" in path:
            item.add_marker(pytest.mark.live)
        else:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def suite_dir() -> Path:
    return SUITE_DIR


@pytest.fixture(scope="session")
def suite_catalog_path() -> Path:
    return SUITE_CATALOG if SUITE_CATALOG.is_file() else EXAMPLE_CATALOG


@pytest.fixture(scope="session")
def catalog(suite_catalog_path: Path):
    return load_catalog(suite_catalog_path)


@pytest.fixture(scope="session")
def suite_states(suite_dir: Path) -> list[dict[str, Any]]:
    path = suite_dir / "states.jsonl"
    return load_jsonl(path) if path.is_file() else []


@pytest.fixture(scope="session")
def suite_states_by_id(suite_states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in suite_states}


@pytest.fixture(scope="session")
def suite_twins(suite_dir: Path) -> list[dict[str, Any]]:
    path = suite_dir / "twins.jsonl"
    return load_jsonl(path) if path.is_file() else []


@pytest.fixture(scope="session")
def suite_injection(suite_dir: Path) -> list[dict[str, Any]]:
    path = suite_dir / "injection.jsonl"
    return load_jsonl(path) if path.is_file() else []


@pytest.fixture
def load_suite_state(suite_states_by_id: dict[str, dict[str, Any]]):
    def _load(state_id: str) -> dict[str, Any]:
        if state_id not in suite_states_by_id:
            raise KeyError(f"unknown suite state id: {state_id}")
        return state_from_suite_record(suite_states_by_id[state_id])

    return _load


@pytest.fixture
def php_state() -> dict:
    return {
        "alert": {
            "alertname": "Http502High",
            "labels": {"host": "web-02", "pool": "www"},
        },
        "metrics": {"phpfpm_idle_processes": 0},
        "locks": {"db_migrate": False, "host_maintenance": False},
        "inventory": {"host": "web-02", "role": "app"},
        "log_excerpts": [{"source": "php-fpm", "lines": ["max_children"]}],
        "_golden_choice": "restart_php_fpm",
        "_noul_safe": True,
        "_score_blast_gold": 0.3,
    }


@pytest.fixture
def php_502_state(repo_root: Path) -> dict[str, Any]:
    """Suite-shaped php incident from examples/incidents/php_502.json."""
    path = PHP_502_EXAMPLE
    if not path.is_file():
        pytest.skip("php_502 example missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "state" in data:
        return state_from_suite_record(data)
    return normalize_state(data)


@pytest.fixture
def audit_log_path(tmp_path: Path) -> Path:
    return tmp_path / "episodes.jsonl"


@pytest.fixture
def audit_log(audit_log_path: Path) -> AuditLog:
    return AuditLog(audit_log_path)


@pytest.fixture
def fake_systemone() -> FakeSystemOne:
    return FakeSystemOne()


@pytest.fixture
def high_precision(catalog) -> dict[str, float]:
    return {pid: 0.99 for pid in catalog.ids if pid != "escalate"}
