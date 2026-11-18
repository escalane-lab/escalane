# Register Escalane Homelab with Omnigent (Custom ACP)

Escalane speaks **Agent Client Protocol** over stdio. Omnigent drives it as a
[Custom ACP agent](https://omnigent.ai/docs/build/harnesses/configuration#custom-acp-agents)
([Custom Agents overview](https://omnigent.ai/docs/use/custom-agents))
— not as a coding harness plugin (that package split is a follow-on).

## Prerequisites

```bash
# from repo root
uv sync --extra acp --group dev
# Omnigent install: https://omnigent.ai/quickstart/install
```

## User config (`~/.omnigent/config.yaml`)

```yaml
acp:
  agents:
    - name: Escalane Homelab
      command: uv run --directory /ABS/PATH/TO/sys_one_ops escalane-acp
```

Replace `/ABS/PATH/TO/sys_one_ops` with this checkout. Omnigent derives harness id
`acp:escalane-homelab`.

Or use the setup UI: **configure harnesses → Custom ACP agent → Add**.

## Run

```bash
omni run --harness acp:escalane-homelab
```

In the session, try prompts: `act1`, `act2`, `maintenance`, `storyboard`.

## Safety defaults

- Escalane remains **dry-run** unless `ESCALANE_ACP_APPLY=1` **and**
  `ALLOW_WRITE_OPERATIONS=true`.
- No shell/bash tools are exposed; only catalog playbooks after gates.
- For dry-run demos, Omnigent does not need Docker socket write access.

## Optional agent YAML

```yaml
spec_version: 1
name: escalane_homelab_ops
prompt: |
  You are Escalane Homelab. Run Decide+Act on convenience-automation incidents.
  Prefer act1 / act2 / act3 / storyboard prompts. Never invent shell commands.

executor:
  type: omnigent
  config:
    harness: acp:escalane-homelab

os_env:
  type: caller_process
  cwd: .
  sandbox:
    type: none   # dry-run demo; tighten when enabling apply + Docker
```

## Harness plugin (out of scope for v1)

A future `omnigent-escalane` package could register via
`omnigent.community.harness` entry points
([harness plugin design](https://github.com/omnigent-ai/omnigent/blob/main/designs/harness-plugin-interface.md)).
Custom ACP is the supported in-house path today; see
[`docs/demo-homelab-omnigent.md`](../../docs/demo-homelab-omnigent.md).
