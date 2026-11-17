_This is a submission for the [MLH x DEV Writing Challenge](https://dev.to/mlh-hackathon)_

I spent [MLH Global Hack Week: Builders Week (Nov 6–12, 2026)](https://ghw.mlh.com/events/builders-week) fighting a pattern that still shows up in “AI Ops” demos: an LLM that *talks* about fixing a host, then invents the shell command that would do it.

This is a builder story — process and trust boundaries, not a preprint.

## What I Built

**Escalane** is a product framing for SysOps automation: **Decide+Act**. The model chooses *what* kind of fix fits; a harness is the only thing that *runs*. The implementation lives in this repo as **`escalane`**.

**System One** is the decision backend — it answers typed questions (which playbook, safe to mutate, blast radius) over a scrubbed state blob. It does not get a free tool belt.

Why not “Agent = LLM + tools”? In SysOps, a “tool” is often a shell-shaped surface. Free tool-calling collapses three jobs that should not share a brain:

- **Judgment** — which remediation class fits?
- **Authority** — is it safe to mutate *this* host *now*?
- **Execution** — exact argv, locks, dry-run, verify

When the model authors commands, prompt-injected telemetry becomes a remote-code path. I wanted a closed action space: pick a playbook id (or escalate), answer safety questions, and let harness-owned **catalog templates** render argv from **state-bound** params — never from model free text.

One simple loop:

- **Ingest** — symptoms only; reject command-like fields
- **Decide** — System One returns typed answers (choice / noul / score)
- **Gates** — ordered vetoes; fail closed on low confidence
- **Catalog act** — template argv only, or escalate / HITL

Research default is dry-run. Writes need dual consent: CLI `--allow-writes` *and* `ALLOW_WRITE_OPERATIONS=true`. Fail-closed `--require-live` refuses silent mock fallback when you asked for a live backend.

Lesson that stuck: **harness > model swap**. Changing the decision model does not fix unsafe argv authorship. Grammar ≠ semantic safety.

## Demo

No public deploy yet — the usable path today is a local CLI walkthrough. Dry-run is the default research posture (nothing mutates a host unless you intentionally unlock writes).

Offline decide (no host mutation):

```bash
uv sync
uv run escalane decide \
  --backend mock \
  --state src/escalane/examples/incidents/php_502.json \
  --catalog datasets/sysops_decide/catalog.yaml \
  --gate-config A3
```

Trimmed output from that exact command on the seed PHP 502 incident:

```json
{
  "model": "mock",
  "playbook": "restart_php_fpm",
  "noul": 0.95,
  "blast_score": 0.3,
  "gate_decision": "hitl",
  "gate_reason": "label_precision",
  "dry_run_only": true
}
```

The model picked a catalog playbook. A3 still routed to **HITL** (conservative label-precision) instead of executing — dry-run only, no argv invented by the model.

When a live backend is up (e.g. Ollama), the same path works with `--backend ollama` and `--require-live` if you want fail-closed instead of pretending.

<!-- Upload docs/blog/assets/escalane-dev-cover.jpg as the DEV cover image.
     Optional second media: paste a terminal screenshot of the command above. -->

Public links:

- Harness map in-repo: `docs/harness-architecture.md`
- System One wire format: [Decisions (System One)](https://lmstudio.ai/docs/developer/jev-compat/systemone)
- Cover / flow assets (local): `docs/blog/assets/escalane-dev-cover.jpg`, `docs/blog/assets/escalane-flow-cover.svg`
- <!-- Uncomment when public: Repo: https://github.com/… -->

## Partner Technologies

I did **not** build on an MLH partner stack for this project — honesty over checkbox.

What I actually used:

- **Python** + `uv` for the `escalane` CLI and harness
- **httpx** for HTTP to local decision backends
- **Ollama / LM Studio** for local System One–style decision models (when the eGPU / APU cooperated)
- A **custom Decide→Gates→Act harness** with a seed SysOps catalog and mock backend for offline plumbing

Challenges that felt real during the week: model pulls and DNS hiccups, an eGPU busy with chat models so decision models lived on a second box, and the constant trap of “CI green on mock” teaching wiring instead of decision quality. The claim fence and `--require-live` exist so I stop lying to myself.

We measured gate postures against ungated / free tool-calling baselines on a seed suite — enough to see that catalog membership alone is not enough under injection-shaped prompts. Full metrics stay out of this post; they belong in a later paper draft.

This is a **research harness**, not a production-certified remediator. Conservative gates will HITL more than a demo agent that always “just runs the fix.”

## Hackathon Experience

Builders Week felt like permission to ship the *shape* of the idea without pretending it was finished science. I built mostly solo, with community Discord as ambient company — other people grinding on their own weird stacks late into the night.

What I’ll remember: sticky-note clarity. *The model chooses; the harness is the only thing that runs.* Locking the CLI path (`decide` / `run` / `replay`), a seed catalog, and the Decide→Gates→Act skeleton mattered more than chasing a flashy demo that shells out from a prompt.

What matured after the week was still builder work: params-from-state as a hard rule, gate postures that are usable (deny-all is a failed product, not a safety win), and fail-closed live backends.

If you are also fighting “LLM with bash privileges,” I would love to hear how you drew the trust boundary.
