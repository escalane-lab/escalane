# Tests

Offline-first suite for the SysOne Ops harness. Default `uv run pytest` must pass with **no** Ollama / LM Studio.

## Commands

```bash
# Full default suite (unit + integration; skips live)
uv run pytest -q
uv run pytest -q -m "not live"

# By marker
uv run pytest -q -m unit
uv run pytest -q -m integration

# Optional live Ollama d3:2b (skips if unreachable / not pulled)
uv run pytest -q -m live
# Optional pull during live tests:
SYSONE_LIVE_PULL=1 uv run pytest -q -m live
```

## Markers

| Marker | Meaning |
| --- | --- |
| `unit` | Pure module tests (auto-marked outside `integration/` / `live/`) |
| `integration` | Real-like offline pipeline: Fake/Mock System One + suite data + gates + dry-run executor + audit/CLI/eval |
| `live` | Optional live `/v1/systemone` against local Ollama |

## Layout

| Path | Role |
| --- | --- |
| `conftest.py` / `helpers.py` | Catalog, suite loaders, `FakeSystemOne`, audit tmp helpers |
| `test_*.py` | Unit / smoke (kept at top level) |
| `integration/` | Production-loop emulation without host mutation |
| `live/` | Optional Ollama `d3:2b` structural smoke |

## What “real-like” means

Integration tests do **not** call a live model. They drive the same loop as CLI/eval:

`state (suite) → FakeSystemOne/MockSystemOne → gates A0–A3 → dry-run executor → audit episode → optional replay`

Scenario coverage includes happy-path remediation, noul/lock veto, blast HITL, injection fail-closed, twin pairs under gold heuristics, OOD escalate, argv invariant, write kill-switch, and CLI `decide` / `run` / `replay`.
