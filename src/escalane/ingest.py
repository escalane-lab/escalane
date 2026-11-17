"""L0 request normalize — reject raw command authority (ADR-004)."""

from __future__ import annotations

from typing import Any

from escalane.state import StateError, normalize_state


class IngestError(ValueError):
    """Rejected or malformed inbound request."""


_RAW_COMMAND_KEYS = frozenset(
    {"command", "shell", "bash", "argv", "cmdline", "cmd", "exec", "raw_command"}
)


def normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    """Normalize CLI/webhook-shaped request; strip/reject command fields."""
    if not isinstance(request, dict):
        raise IngestError("request must be an object")
    for key in request:
        if str(key).lower() in _RAW_COMMAND_KEYS:
            raise IngestError(f"reject raw command field: {key}")
    state_raw = request.get("state")
    if state_raw is None and "incident" in request:
        state_raw = request["incident"]
    try:
        state = normalize_state(state_raw if state_raw is not None else request.get("evidence"))
    except StateError as exc:
        raise IngestError(str(exc)) from exc
    return {
        "op_id": request.get("op_id"),
        "alert_id": request.get("alert_id"),
        "service_id": request.get("service_id"),
        "principal": request.get("principal", "cli:local"),
        "surface": request.get("surface", "cli"),
        "state": state,
        "attenuated": True,
    }
