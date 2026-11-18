"""Homelab convenience demo — argv binding + offline storyboard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from escalane.catalog import load_catalog
from escalane.demo_homelab import ACTS, DemoPaths, run_one_act, run_storyboard
from escalane.executor import render_argv
from escalane.state import bind_params, normalize_state


@pytest.fixture(scope="module")
def homelab_catalog(repo_root: Path):
    return load_catalog(repo_root / "datasets" / "homelab_decide" / "catalog.yaml")


@pytest.fixture(scope="module")
def demo_paths(repo_root: Path) -> DemoPaths:
    return DemoPaths.discover(repo_root)


def test_convenience_unhealthy_argv(homelab_catalog, demo_paths: DemoPaths):
    raw = json.loads(
        (demo_paths.incidents_dir / "homelab_convenience_unhealthy.json").read_text()
    )
    state = normalize_state(
        {
            **raw["state"],
            "_golden_choice": raw["golden_choice"],
            "_noul_safe": raw["noul_safe"],
        }
    )
    bound = bind_params(
        state,
        homelab_catalog.get("restart_docker_container"),
        catalog_allowlists=homelab_catalog.allowlists,
    )
    assert bound["container"] == "convenience-app"
    assert render_argv(homelab_catalog.get("restart_docker_container"), bound) == [
        "docker",
        "restart",
        "convenience-app",
    ]


def test_compose_home_sensor_argv(homelab_catalog, demo_paths: DemoPaths):
    raw = json.loads(
        (demo_paths.incidents_dir / "homelab_compose_home_sensor.json").read_text()
    )
    state = normalize_state(
        {
            **raw["state"],
            "_golden_choice": raw["golden_choice"],
            "_noul_safe": raw["noul_safe"],
        }
    )
    bound = bind_params(
        state,
        homelab_catalog.get("docker_compose_restart_service"),
        catalog_allowlists=homelab_catalog.allowlists,
    )
    assert bound == {"project": "home", "service": "sensor-bridge"}
    assert render_argv(homelab_catalog.get("docker_compose_restart_service"), bound) == [
        "docker",
        "compose",
        "-p",
        "home",
        "restart",
        "sensor-bridge",
    ]


def test_maintenance_twin_escalates(demo_paths: DemoPaths, tmp_path: Path):
    result = run_one_act(
        paths=demo_paths,
        incident_name="homelab_convenience_maintenance.json",
        backend="mock",
        gate_config="A3",
        audit_path=tmp_path / "act2.jsonl",
    )
    choice = result["answers"]["playbook"]["choice"]
    assert choice == "escalate"
    assert result["gate"]["decision"] == "escalate"
    assert result["execution"] is None


@pytest.mark.integration
def test_storyboard_mock_offline(repo_root: Path, tmp_path: Path, monkeypatch):
    # Redirect episodes into tmp so we do not clobber demo/homelab/episodes.
    paths = DemoPaths.discover(repo_root)
    monkeypatch.setattr(
        "escalane.demo_homelab.DemoPaths.discover",
        lambda repo_root=None: DemoPaths(
            repo_root=paths.repo_root,
            demo_root=tmp_path,
            catalog=paths.catalog,
            incidents_dir=paths.incidents_dir,
            episodes_dir=tmp_path / "episodes",
        ),
    )
    results = run_storyboard(
        backend="mock",
        gate_config="A3",
        live_stack=False,
        quiet=True,
        repo_root=repo_root,
    )
    assert len(results) == 3
    assert all(r["choice_ok"] for r in results)
    assert results[0]["argv_joined"] == "docker restart convenience-app"
    assert results[1]["gate"]["decision"] == "escalate"
    assert results[2]["argv_joined"] == "docker compose -p home restart sensor-bridge"
    for act in ACTS:
        assert (tmp_path / "episodes" / f"{act['id']}.jsonl").is_file()


@pytest.mark.live_docker
def test_flip_health_marks_unhealthy(repo_root: Path):
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    demo = repo_root / "demo" / "homelab"
    up = subprocess.run(
        ["docker", "compose", "-p", "home", "up", "-d", "--build"],
        cwd=demo,
        capture_output=True,
        text=True,
    )
    if up.returncode != 0:
        pytest.skip(f"compose up failed: {up.stderr[-500:]}")
    flip = subprocess.run(
        [str(demo / "scripts" / "flip_health.sh"), "convenience-app", "unhealthy"],
        cwd=demo,
        capture_output=True,
        text=True,
    )
    assert flip.returncode == 0, flip.stderr
    assert "unhealthy" in flip.stdout.lower() or "health=fail" in flip.stdout.lower()
