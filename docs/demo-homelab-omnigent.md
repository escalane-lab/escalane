# Homelab Docker demo + Omnigent ACP

**Scope:** laptop convenience automation (Docker Compose project `home`).  
**Not Phase-0:** this demo does **not** change SysOps `catalog_hash`, paper tables, or Phase-0 seed metrics. See [`HANDOFF-phase0-review-round.md`](./HANDOFF-phase0-review-round.md).

## What you get

1. **Local storyboard** — `uv run escalane demo homelab` (mock, dry-run, Acts 1–3).
2. **Optional live stack** — `demo/homelab/docker-compose.yml` + `scripts/flip_health.sh`.
3. **Omnigent Custom ACP agent** — `escalane-acp` stdio server over Decide+Act.

Catalog: [`datasets/homelab_decide/catalog.yaml`](../datasets/homelab_decide/catalog.yaml).

## Commands

```bash
# Offline storyboard
uv run escalane demo homelab

# Compose lab
make -C demo/homelab up
make -C demo/homelab flip-unhealthy
uv run escalane demo homelab --live-stack

# ACP (for Omnigent / any ACP client)
uv sync --extra acp
uv run escalane-acp
```

Omnigent registration: [`demo/homelab/omnigent.md`](../demo/homelab/omnigent.md).

## Trust model

| Layer | Role |
| --- | --- |
| Omnigent | Session UX, policies, OS sandbox around the ACP process |
| Escalane ACP | Parses prompts → Decide+Act on homelab catalog |
| Catalog + gates | Only mutator; dry-run default; dual write gate for apply |

Upstream free text is **not** authority (ADR-004). Model never authors shell argv.

## Follow-on (deferred)

- `omnigent.community.harness` plugin package wrapping the same `escalane-acp` binary
- Production MCP `request_local_ops_action` ingest surface
