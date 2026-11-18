# Homelab convenience demo

Laptop-runnable **Docker / home convenience** storyboard for Escalane Decide+Act.
Uses [`datasets/homelab_decide/catalog.yaml`](../../datasets/homelab_decide/catalog.yaml) — **not** the frozen SysOps Phase-0 eval catalog.

## Acts

| Act | Incident | Expected |
| --- | --- | --- |
| 1 | `homelab_convenience_unhealthy.json` | `restart_docker_container` → `docker restart convenience-app` |
| 2 | `homelab_convenience_maintenance.json` | `escalate` (maintenance lock) |
| 3 | `homelab_compose_home_sensor.json` | `docker_compose_restart_service` → `docker compose -p home restart sensor-bridge` |

Default backend is **mock** (offline). Writes stay **dry-run** unless dual-gated.

## Quick start (no Docker required)

```bash
# from repo root
uv run escalane demo homelab

# or
make -C demo/homelab demo
```

Episodes land in `demo/homelab/episodes/act{1,2,3}.jsonl`.

## Live stack (optional)

```bash
make -C demo/homelab up
make -C demo/homelab flip-unhealthy
uv run escalane demo homelab --live-stack
```

Compose project name is **`home`**. Containers: `convenience-app`, compose service `sensor-bridge`.
Optional MQTT profile: `docker compose -p home --profile mqtt up -d`.

## Omnigent

See [omnigent.md](./omnigent.md) and [`docs/demo-homelab-omnigent.md`](../../docs/demo-homelab-omnigent.md).
