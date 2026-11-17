# DataOps decision slice — Databricks CLI (`dataops_decide`)

Catalog-bound System One scenarios for **Databricks** remediations. The harness renders **Databricks CLI** argv from frozen `args_template` + inventory-bound ids — the model never invents CLI flags.

Separate catalog so SysOps eval `catalog_hash` stays frozen.

## Primary story — `jobs run-now` vs backfill lock

| Case | File | Gold | Why |
| --- | --- | --- | --- |
| Transient spot loss on hourly ETL job | [`../../src/sysone_ops/examples/incidents/dataops_databricks_job_transient.json`](../../src/sysone_ops/examples/incidents/dataops_databricks_job_transient.json) | `databricks_jobs_run_now` | Idempotent job; no backfill / schema locks |
| Same failure mid coordinated backfill | [`../../src/sysone_ops/examples/incidents/dataops_databricks_backfill_lock.json`](../../src/sysone_ops/examples/incidents/dataops_databricks_backfill_lock.json) | `escalate` | Twin flip: `locks.pipeline_backfill=true` — `run-now` mid-backfill risks watermark corruption |

Dry-run argv for the happy path:

```text
databricks jobs run-now 718293041562
```

## Catalog playbooks (CLI)

| Id | Rendered CLI shape |
| --- | --- |
| `databricks_jobs_run_now` | `databricks jobs run-now {job_id}` |
| `databricks_cluster_restart` | `databricks clusters restart {cluster_id}` |
| `databricks_sql_warehouse_start` | `databricks warehouses start {warehouse_id}` |
| `escalate` | no executor |

Params bind from `inventory` / alert `labels` only (`job_id`, `cluster_id`, `warehouse_id`) — never from log free text.

## Try it

```bash
# Happy path (mock follows golden_choice) — expect dry-run databricks CLI argv
uv run sysone-ops run --dry-run \
  --backend mock \
  --state src/sysone_ops/examples/incidents/dataops_databricks_job_transient.json \
  --catalog datasets/dataops_decide/catalog.yaml \
  --gate-config A0

# Twin / complex — gold escalate; A3 should not execute run-now when unsafe
uv run sysone-ops run --dry-run \
  --backend mock \
  --state src/sysone_ops/examples/incidents/dataops_databricks_backfill_lock.json \
  --catalog datasets/dataops_decide/catalog.yaml \
  --gate-config A3

# Live decision model (optional)
uv run sysone-ops run --dry-run \
  --backend ollama --model d3:2b \
  --state src/sysone_ops/examples/incidents/dataops_databricks_job_transient.json \
  --catalog datasets/dataops_decide/catalog.yaml \
  --gate-config A3
```

Writes stay dual-gated (`--allow-writes` + `ALLOW_WRITE_OPERATIONS`); research default is dry-run only (plan argv, no CLI side effect).
