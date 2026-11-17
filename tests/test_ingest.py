"""Ingest request normalize (reject raw command authority)."""

from __future__ import annotations

import pytest

from escalane.ingest import IngestError, normalize_request


def test_normalize_request_ok(php_state):
    out = normalize_request({"state": php_state, "principal": "test"})
    assert out["attenuated"] is True
    assert out["state"]["inventory"]["host"] == "web-02"
    assert out["principal"] == "test"


def test_normalize_request_rejects_command_keys(php_state):
    with pytest.raises(IngestError, match="raw command"):
        normalize_request({"command": "rm -rf /", "state": php_state})
    with pytest.raises(IngestError):
        normalize_request({"argv": ["id"], "state": php_state})
