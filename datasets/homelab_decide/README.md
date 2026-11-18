# Homelab decision slice (`homelab_decide`)

Catalog-bound System One playbooks for **personal homelab** Linux admin: Docker/Compose restarts, Caddy, Home Assistant, Pi-hole, Samba, careful sshd reload, tmp clear, image prune — plus **`escalate`** for lockout / storage / unknown blast.

Separate from SysOps eval catalog so `catalog_hash` there stays frozen.

**ADR-005 allowlists:** top-level `allowlists` plus per-param `x-escalane-slot` / `enum` for containers, compose projects, and services. Pattern-legal but off-list nouns (e.g. `evil-app`) fail at bind and again at execute.

## Playbooks → argv

| Id | Example dry-run argv |
| --- | --- |
| `restart_docker_container` | `docker restart jellyfin` |
| `docker_compose_restart_service` | `docker compose -p media restart sonarr` |
| `restart_caddy` | `systemctl restart caddy` |
| `restart_homeassistant` | `systemctl restart home-assistant` |
| `restart_pihole` | `systemctl restart pihole-FTL` |
| `restart_samba` | `systemctl restart smbd` |
| `clear_homelab_tmp` | `/bin/sh scripts/homelab/clear_tmp.sh --host=…` |
| `docker_image_prune_unused` | `docker image prune -f` |
| `reload_sshd_config` | `systemctl reload ssh` |
| `escalate` | (none) |

Params bind from `inventory` / alert `labels` only. Executor kind `cli` uses catalog `binary` + `args_template` (same pattern as Databricks).

## Example incidents

| File | Gold |
| --- | --- |
| [`homelab_convenience_unhealthy.json`](../../src/escalane/examples/incidents/homelab_convenience_unhealthy.json) | `restart_docker_container` (demo Act 1) |
| [`homelab_convenience_maintenance.json`](../../src/escalane/examples/incidents/homelab_convenience_maintenance.json) | `escalate` (demo Act 2 twin) |
| [`homelab_compose_home_sensor.json`](../../src/escalane/examples/incidents/homelab_compose_home_sensor.json) | `docker_compose_restart_service` (demo Act 3) |
| [`homelab_jellyfin_unhealthy.json`](../../src/escalane/examples/incidents/homelab_jellyfin_unhealthy.json) | `restart_docker_container` |
| [`homelab_compose_arr_stack.json`](../../src/escalane/examples/incidents/homelab_compose_arr_stack.json) | `docker_compose_restart_service` |
| [`homelab_pihole_ftl_down.json`](../../src/escalane/examples/incidents/homelab_pihole_ftl_down.json) | `restart_pihole` |
| [`homelab_sshd_lockout_risk.json`](../../src/escalane/examples/incidents/homelab_sshd_lockout_risk.json) | `escalate` (no alternate console / Tailscale down) |

## Packaged demo (recommended)

```bash
# Offline Acts 1–3 (mock, dry-run) — see demo/homelab/
uv run escalane demo homelab

# Optional live Docker stack (compose project `home`)
make -C demo/homelab up
uv run escalane demo homelab --live-stack

# Omnigent Custom ACP — docs/demo-homelab-omnigent.md
uv sync --extra acp && uv run escalane-acp
```

This demo is **not** Phase-0 SysOps seed eval; it does not touch `sysops_decide` `catalog_hash`.

## Try it (single incident)

```bash
uv run escalane run --dry-run \
  --backend mock \
  --state src/escalane/examples/incidents/homelab_convenience_unhealthy.json \
  --catalog datasets/homelab_decide/catalog.yaml \
  --gate-config A3

uv run escalane run --dry-run \
  --backend mock \
  --state src/escalane/examples/incidents/homelab_sshd_lockout_risk.json \
  --catalog datasets/homelab_decide/catalog.yaml \
  --gate-config A3

# Live decision model (optional)
uv run escalane run --dry-run \
  --backend ollama --model d3:2b \
  --state src/escalane/examples/incidents/homelab_convenience_unhealthy.json \
  --catalog datasets/homelab_decide/catalog.yaml \
  --gate-config A3
```

Tune unit names (`caddy`, `home-assistant`, `pihole-FTL`, `ssh` vs `sshd`) to match your hosts before enabling writes. Default remains dry-run only.
