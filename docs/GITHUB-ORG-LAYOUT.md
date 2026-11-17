# Escalane GitHub org layout

Org: [escalane-lab](https://github.com/escalane-lab)

These four repos were created **private** on 2026-11-16 with an empty README only. No monorepo history was pushed and no code was split. This monorepo (`sys_one_ops`) stays the working tree until an explicit extract/publish step.

The harness repo is named `sysone-ops` so it matches the installable package and CLI (`pyproject.toml`, `sysone-ops`). `escalane-harness` was the other candidate and was not created.

| Repo | URL | Visibility | Will contain |
| --- | --- | --- | --- |
| `escalane-paper` | https://github.com/escalane-lab/escalane-paper | private | Article source |
| `sysone-ops` | https://github.com/escalane-lab/sysone-ops | private | Library / harness |
| `escalane-repro` | https://github.com/escalane-lab/escalane-repro | private | Experiment reproduction |
| `escalane-docs` | https://github.com/escalane-lab/escalane-docs | private | Docs and site branding |

## Path mapping

| Monorepo path | Destination repo | Notes |
| --- | --- | --- |
| `papers/escalane/main.tex`, `references.bib`, `Makefile`, `README.md`, `figures/` | `escalane-paper` | LaTeX article. Leave build products local (`*.aux`, `*.log`, `*.fls`, `main.pdf`, and similar). |
| `papers/escalane/review1.md` | `escalane-paper` | Review notes stay with the draft while the repo is private. |
| `src/sysone_ops/` | `sysone-ops` | Installable harness (catalog, state, gates, executor, verify, audit, CLI) and examples. |
| `tests/` | `sysone-ops` | Offline unit and integration tests; optional live marker. |
| `pyproject.toml`, `uv.lock`, `.python-version` | `sysone-ops` | Package metadata. Root `README.md` harness sections move with the library. |
| `datasets/` (`sysops_decide`, `homelab_decide`, `dataops_decide`) | `sysone-ops` | Canonical catalogs and suite seeds the harness tests against. |
| `eval/sysops_decide/` (`runner.py`, `metrics.py`) | `sysone-ops` | Eval runner source. Omit `results/` and `episodes/` dumps. |
| `scripts/smoke_d3.py` | `sysone-ops` | Optional live smoke. |
| `repro/escalane/` (`notebooks/`, `scripts/`, `src/escalane/`, `data/`, `DATASHEET.md`, `pyproject.toml`, `Makefile`, `README.md`) | `escalane-repro` | Phase-0 reproduction package. Vendored `data/sysops_decide/` is a snapshot of the suite seed. Omit `.venv/` and generated `results/` until a release snapshot is chosen. |
| `docs/README.md`, `docs/harness-architecture.md`, `docs/arc42/` | `escalane-docs` | Architecture docs and ADRs. |
| `site/` | `escalane-docs` | Astro marketing and branding site. |
| `.github/workflows/pages.yml` | `escalane-docs` | GitHub Pages workflow for `site/`. Retarget the base path when the site leaves this monorepo. |

## Stays in the monorepo for now

| Path | Why |
| --- | --- |
| `notes/`, `research_articles/`, `chat_session.md` | Working research notes, not a publishable repo. |
| `docs/HANDOFF-phase0-review-round.md` | Session handoff, not product docs. |
| `scripts/homelab/` | Machine-local helper. |
| `.cursor/`, `.claude/` | Editor and agent config. |

Extract is a later step: copy the paths above into the matching repo (fresh history is fine), keep this monorepo as the place edits land until that cutover, then flip visibility when a repo is ready to be public.
