"""Executor dry-run vs allow_writes kill-switch."""

from __future__ import annotations

import pytest

from escalane.executor import ExecutorError, execute, set_real_side_effect_hook


def test_dry_run_never_calls_side_effect_hook(catalog):
    called = {"n": 0}

    def hook(argv):
        called["n"] += 1
        return 0

    set_real_side_effect_hook(hook)
    try:
        obs = execute(
            catalog,
            "restart_php_fpm",
            {"host": "web-02"},
            dry_run=True,
            allow_writes=True,  # even if flagged, dry_run wins
        )
        assert obs.dry_run is True
        assert obs.side_effect_called is False
        assert called["n"] == 0
        assert obs.argv == ["systemctl", "restart", "php8.2-fpm"]
    finally:
        set_real_side_effect_hook(None)


def test_allow_writes_false_never_calls_hook(catalog):
    called = {"n": 0}

    def hook(argv):
        called["n"] += 1
        return 0

    set_real_side_effect_hook(hook)
    try:
        obs = execute(
            catalog,
            "restart_php_fpm",
            {"host": "web-02"},
            dry_run=False,
            allow_writes=False,
        )
        assert obs.dry_run is True
        assert obs.side_effect_called is False
        assert called["n"] == 0
    finally:
        set_real_side_effect_hook(None)


def test_allow_writes_path_calls_hook_only_when_enabled(catalog):
    called = {"n": 0, "argv": None}

    def hook(argv):
        called["n"] += 1
        called["argv"] = list(argv)
        return 0

    set_real_side_effect_hook(hook)
    try:
        obs = execute(
            catalog,
            "restart_php_fpm",
            {"host": "web-02"},
            dry_run=False,
            allow_writes=True,
        )
        assert obs.dry_run is False
        assert obs.side_effect_called is True
        assert called["n"] == 1
        assert called["argv"] == ["systemctl", "restart", "php8.2-fpm"]
    finally:
        set_real_side_effect_hook(None)


def test_allow_writes_without_hook_raises(catalog):
    set_real_side_effect_hook(None)
    with pytest.raises(ExecutorError, match="live writes not enabled"):
        execute(
            catalog,
            "restart_php_fpm",
            {"host": "web-02"},
            dry_run=False,
            allow_writes=True,
        )
