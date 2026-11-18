"""State normalize, scrub, and bind_params (L1)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from escalane.catalog import Playbook, stable_json


class StateError(ValueError):
    """Invalid state or param binding."""


# Fields that look like imperative command authority (ADR-003/004).
_FORBIDDEN_KEYS = frozenset(
    {
        "command",
        "shell",
        "bash",
        "argv",
        "cmdline",
        "cmd",
        "exec",
        "script_body",
        "raw_command",
    }
)

_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")

# ADR-005 slot types (x-escalane-slot).
SLOT_TYPES = frozenset(
    {"host", "unit", "container", "service", "project", "path", "job_id"}
)
SLOT_KEY = "x-escalane-slot"


def state_digest(state: dict[str, Any]) -> str:
    digest = hashlib.sha256(stable_json(state).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _walk_forbidden(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_l = str(key).lower()
            if key_l in _FORBIDDEN_KEYS:
                raise StateError(
                    f"forbidden command-like field at {path}.{key}"
                    if path
                    else f"forbidden command-like field: {key}"
                )
            _walk_forbidden(value, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _walk_forbidden(item, f"{path}[{i}]")


def normalize_state(raw: Any) -> dict[str, Any]:
    """Normalize evidence blob; reject raw command-like authority fields."""
    if raw is None:
        raise StateError("state is required")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StateError("state string must be JSON object") from exc
    if not isinstance(raw, dict):
        raise StateError("state must be an object")
    _walk_forbidden(raw)
    # Shallow copy; callers should not mutate after decide.
    return dict(raw)


def _schema_type_ok(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


def _validate_path_slot(value: str, prop: dict[str, Any]) -> None:
    if "\x00" in value or ".." in value:
        raise StateError("path param rejected (traversal or NUL)")
    prefixes = prop.get("x-escalane-path-prefixes")
    if isinstance(prefixes, list) and prefixes:
        if not any(value == p or value.startswith(str(p).rstrip("/") + "/") for p in prefixes):
            raise StateError("path param outside allowed prefixes")


def _allowed_for_slot(
    slot: str,
    value: str,
    *,
    prop: dict[str, Any],
    catalog_allowlists: dict[str, list[str]] | None,
) -> None:
    """Enforce playbook enum (narrowest) then catalog allowlists for the slot."""
    enum_vals = prop.get("enum")
    if isinstance(enum_vals, list) and enum_vals:
        if value not in enum_vals:
            raise StateError(f"param value {value!r} not in enum allowlist")
        return
    if catalog_allowlists and slot in catalog_allowlists:
        allowed = catalog_allowlists[slot]
        if allowed and value not in allowed:
            raise StateError(
                f"param value {value!r} not in catalog allowlist for slot {slot!r}"
            )


def validate_bound_params(
    params: dict[str, Any],
    playbook: Playbook,
    *,
    catalog_allowlists: dict[str, list[str]] | None = None,
) -> None:
    """Act-time validation (ADR-003/005): schema, enum, slot allowlists, path rules."""
    schema = playbook.params_schema or {}
    if not schema:
        return
    if schema.get("type") and schema.get("type") != "object":
        raise StateError("params_schema type must be object")
    required = list(schema.get("required") or [])
    properties = dict(schema.get("properties") or {})
    for key in required:
        if key not in params:
            raise StateError(f"missing required param: {key}")
    for key, value in params.items():
        if key not in properties:
            raise StateError(f"unexpected param: {key}")
        prop = properties[key]
        expected = prop.get("type")
        if expected and not _schema_type_ok(value, expected):
            raise StateError(f"param {key} type mismatch")
        pattern = prop.get("pattern")
        if pattern and isinstance(value, str):
            if not re.fullmatch(pattern, value):
                raise StateError(f"param {key} failed pattern")
        enum_vals = prop.get("enum")
        if isinstance(enum_vals, list) and enum_vals and value not in enum_vals:
            raise StateError(f"param {key} value {value!r} not in enum allowlist")
        slot = prop.get(SLOT_KEY)
        if slot is not None:
            if slot not in SLOT_TYPES:
                raise StateError(f"unknown x-escalane-slot: {slot}")
            if not isinstance(value, str):
                raise StateError(f"slot {slot} requires string value")
            if slot == "path":
                _validate_path_slot(value, prop)
            _allowed_for_slot(
                str(slot),
                value,
                prop=prop,
                catalog_allowlists=catalog_allowlists,
            )
        elif isinstance(enum_vals, list) and enum_vals:
            # enum without slot still enforced above
            pass
        elif catalog_allowlists and key in ("container", "service", "project", "unit", "host"):
            # Implicit slot from common param names when catalog lists that type.
            implied = key if key != "host" else "host"
            if implied in catalog_allowlists and catalog_allowlists[implied]:
                if not isinstance(value, str) or value not in catalog_allowlists[implied]:
                    raise StateError(
                        f"param {key} value {value!r} not in catalog allowlist "
                        f"for slot {implied!r}"
                    )


def _validate_against_schema(
    params: dict[str, Any],
    schema: dict[str, Any],
    *,
    catalog_allowlists: dict[str, list[str]] | None = None,
) -> None:
    """Schema-only helper for tests; production paths use validate_bound_params."""
    from escalane.catalog import Playbook as _Playbook

    pb = _Playbook(id="_tmp", criteria="tmp", params_schema=schema)
    validate_bound_params(params, pb, catalog_allowlists=catalog_allowlists)


def bind_params(
    state: dict[str, Any],
    playbook: Playbook,
    *,
    catalog_allowlists: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Bind params from inventory / alert labels only (ADR-003); allowlists (ADR-005)."""
    if not playbook.mutates:
        return {}
    inventory = state.get("inventory") if isinstance(state.get("inventory"), dict) else {}
    alert = state.get("alert") if isinstance(state.get("alert"), dict) else {}
    labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}

    schema = playbook.params_schema or {}
    properties = dict(schema.get("properties") or {})
    required = list(schema.get("required") or [])
    bound: dict[str, Any] = {}

    # Prefer inventory, then alert labels.
    sources = [inventory, labels]
    for key in properties:
        for src in sources:
            if key in src and key not in bound:
                bound[key] = src[key]
                break

    # Common host fallback.
    if "host" in properties and "host" not in bound:
        for src in sources:
            if "host" in src:
                bound["host"] = src["host"]
                break

    for key in required:
        if key not in bound:
            raise StateError(f"cannot bind required param {key} from state")

    if "host" in bound and isinstance(bound["host"], str):
        if not _HOST_RE.match(bound["host"]):
            raise StateError("invalid host param")

    validate_bound_params(bound, playbook, catalog_allowlists=catalog_allowlists)
    return bound


def extract_model_free_text(answers: dict[str, Any]) -> list[str]:
    """Collect strings that must never appear in argv (model free text / choice)."""
    out: list[str] = []
    playbook = answers.get("playbook") if isinstance(answers, dict) else None
    if isinstance(playbook, dict):
        choice = playbook.get("choice")
        if isinstance(choice, str) and choice:
            out.append(choice)
    return out
