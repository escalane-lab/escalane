# Escalane

**Escalane = Decide + Act** (vs *Agent = LLM + tools*). Tagline: *the model chooses; the harness is the only thing that runs.*

Research prototype: a **catalog-bound SysOps harness** for System One decision models (`choice` / `noul` / `score`). The model answers typed decisions only; the harness alone may mutate via catalog templates after ordered gates—and dry-run is the default.

Installable package / CLI: **`escalane`**. Public home: [github.com/escalane-lab/escalane](https://github.com/escalane-lab/escalane).  
Docs / site: [escalane-lab.github.io/escalane-docs](https://escalane-lab.github.io/escalane-docs/).

## Setup (uv)

Requires Python **≥3.11** (`.python-version` pins 3.12).

```bash
uv sync
uv run pytest -q                 # unit + integration (offline; no Ollama)
uv run pytest -q -m integration  # real-like pipeline only
uv run pytest -q -m "not live"   # CI-safe (excludes optional live)
uv run pytest -q -m live         # optional Ollama d3:2b — skips if down
uv run escalane --help
```

See [`tests/README.md`](tests/README.md) for markers and what “real-like” offline means.

Add deps with `uv add <pkg>` / `uv add --dev <pkg>` — `uv.lock` is the source of truth (no parallel `requirements.txt`).

## Quick start

```bash
# Mock decide (offline)
uv run escalane decide \
  --backend mock \
  --state src/escalane/examples/incidents/php_502.json \
  --catalog datasets/sysops_decide/catalog.yaml \
  --gate-config A3

# Dry-run execute (never mutates host)
uv run escalane run --dry-run \
  --backend mock \
  --state src/escalane/examples/incidents/php_502.json

# Optional: Ollama System One (default model d3:2b) — skip if eGPU is busy
# Library: https://ollama.com/library/d3  (needs ollama serve; pull when free)
uv run escalane decide \
  --backend ollama \
  --model d3:2b \
  --state src/escalane/examples/incidents/php_502.json

# Preferred when Ollama eGPU is occupied: LM Studio on AMD APU (:1234)
# Load a *decision* model in LM Studio (not a chat LLM), then:
uv run escalane decide \
  --backend lmstudio \
  --model <lmstudio-decision-model-id> \
  --state src/escalane/examples/incidents/php_502.json
```

Env overrides: `ESCALANE_BACKEND`, `ESCALANE_BASE_URL`, `ESCALANE_MODEL`, `ESCALANE_API_KEY` / `LM_API_KEY` (legacy `SYSONE_*` still accepted).

Write kill-switch: real writes require both `--allow-writes` and `ALLOW_WRITE_OPERATIONS=true`. The research prototype still refuses live host remediations without an injected test hook.

## Layout

| Path | Role |
| --- | --- |
| `src/escalane/` | Installable harness (catalog, state, systemone, gates, executor, verify, audit, cli) |
| `datasets/sysops_decide/` | Decision suite (Phase 0 seed; schema ready for v0.1) |
| `eval/sysops_decide/` | Eval runner smoke (mock A0 vs A3); path for Phases A–C |
| [`docs/harness-architecture.md`](docs/harness-architecture.md) | Clear Escalane harness map (layers ↔ code) |
| `tests/` | Offline unit + integration; optional `@pytest.mark.live` |

## Eval smoke

```bash
uv run python eval/sysops_decide/runner.py --backend mock --subset injection
```

