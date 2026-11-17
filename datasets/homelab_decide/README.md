# Homelab decision slice (`homelab_decide`)

Catalog-bound System One playbooks for **personal homelab** Linux admin: Docker/Compose restarts, Caddy, Home Assistant, Pi-hole, Samba, careful sshd reload, tmp clear, image prune — plus **`escalate`** for lockout / storage / unknown blast.

Separate from SysOps eval catalog so `catalog_hash` there stays frozen.

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
| [`homelab_jellyfin_unhealthy.json`](../../src/escalane/examples/incidents/homelab_jellyfin_unhealthy.json) | `restart_docker_container` |
| [`homelab_compose_arr_stack.json`](../../src/escalane/examples/incidents/homelab_compose_arr_stack.json) | `docker_compose_restart_service` |
| [`homelab_pihole_ftl_down.json`](../../src/escalane/examples/incidents/homelab_pihole_ftl_down.json) | `restart_pihole` |
| [`homelab_sshd_lockout_risk.json`](../../src/escalane/examples/incidents/homelab_sshd_lockout_risk.json) | `escalate` (no alternate console / Tailscale down) |

## Try it

```bash
uv run escalane run --dry-run \
  --backend mock \
  --state src/escalane/examples/incidents/homelab_jellyfin_unhealthy.json \
  --catalog datasets/homelab_decide/catalog.yaml \
  --gate-config A0

uv run escalane run --dry-run \
  --backend mock \
  --state src/escalane/examples/incidents/homelab_sshd_lockout_risk.json \
  --catalog datasets/homelab_decide/catalog.yaml \
  --gate-config A3

# Live decision model (optional)
uv run escalane run --dry-run \
  --backend ollama --model d3:2b \
  --state src/escalane/examples/incidents/homelab_jellyfin_unhealthy.json \
  --catalog datasets/homelab_decide/catalog.yaml \
  --gate-config A3
```

Tune unit names (`caddy`, `home-assistant`, `pihole-FTL`, `ssh` vs `sshd`) to match your hosts before enabling writes. Default remains dry-run only.
