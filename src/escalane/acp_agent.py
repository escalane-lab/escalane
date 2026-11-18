"""Escalane Homelab ACP agent — Omnigent Custom ACP / any ACP client over stdio.

Decide+Act only: no open shell tools. Mutations go through the homelab catalog
after gates (dry-run by default).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from typing import Any
from uuid import uuid4

from escalane.demo_homelab import (
    ACTS,
    DemoPaths,
    format_act_summary,
    run_one_act,
    run_storyboard,
)


def _require_acp():
    try:
        from acp import (  # noqa: F401
            Agent,
            InitializeResponse,
            NewSessionResponse,
            PromptResponse,
            run_agent,
        )
        from acp.schema import AgentMessageChunk, TextContentBlock  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "ACP support requires the optional extra: "
            "uv sync --extra acp  (package agent-client-protocol)"
        ) from exc


def _prompt_text(prompt: list[Any]) -> str:
    parts: list[str] = []
    for block in prompt:
        if isinstance(block, dict):
            text = block.get("text", "")
        else:
            text = getattr(block, "text", "") or ""
        if text:
            parts.append(str(text))
    return "\n".join(parts).strip()


def _resolve_act_ids(text: str) -> list[str] | str:
    """Return act id list, 'all', or 'help'."""
    lower = text.lower().strip()
    if not lower or lower in ("help", "?", "hi", "hello"):
        return "help"
    if lower in ("demo", "storyboard", "all", "run all", "run demo"):
        return "all"
    if "maintenance" in lower or re.search(r"\bact\s*2\b", lower):
        return ["act2"]
    if re.search(r"\bact\s*1\b", lower) or (
        "convenience" in lower and "maintenance" not in lower
    ):
        return ["act1"]
    if re.search(r"\bact\s*3\b", lower) or "sensor" in lower or "compose" in lower:
        return ["act3"]
    if "unhealthy" in lower or "restart" in lower:
        return ["act1"]
    if "escalate" in lower:
        return ["act2"]
    # JSON state blob → treat as custom one-shot via act1 runner path later
    if lower.startswith("{") and '"state"' in lower:
        return "json"
    return "help"


HELP_TEXT = """Escalane Homelab ACP agent (Decide+Act, dry-run by default).

No shell tools — catalog playbooks only after gates.

Prompts:
  act1 / unhealthy / restart   → convenience-app restart
  act2 / maintenance / escalate → host_maintenance twin
  act3 / compose / sensor      → docker compose restart sensor-bridge
  demo / storyboard / all      → Acts 1–3
  help                         → this message

Env:
  ESCALANE_BACKEND=mock|ollama|...
  ESCALANE_MODEL=...
  ESCALANE_GATE_CONFIG=A3
  ESCALANE_ACP_APPLY=1         → allow writes (also needs ALLOW_WRITE_OPERATIONS=true)
"""


class EscalaneHomelabAgent:
    """Structural ACP Agent: initialize / new_session / prompt (+ on_connect)."""

    def __init__(
        self,
        *,
        backend: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        gate_config: str | None = None,
        allow_writes: bool = False,
        repo_root: Any = None,
    ) -> None:
        self._conn = None
        self.backend = backend or os.environ.get("ESCALANE_BACKEND", "mock")
        self.model = model or os.environ.get("ESCALANE_MODEL")
        self.base_url = base_url or os.environ.get("ESCALANE_BASE_URL")
        self.gate_config = gate_config or os.environ.get("ESCALANE_GATE_CONFIG", "A3")
        env_apply = os.environ.get("ESCALANE_ACP_APPLY", "").lower() in ("1", "true", "yes")
        self.allow_writes = allow_writes or env_apply
        self.paths = DemoPaths.discover(repo_root)
        self.sessions: dict[str, dict[str, Any]] = {}

    def on_connect(self, conn) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities=None,
        client_info=None,
        **kwargs: Any,
    ):
        from acp import InitializeResponse
        from acp.schema import AgentCapabilities, Implementation

        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(load_session=False),
            agent_info=Implementation(name="escalane-homelab", version="0.1.0"),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list | None = None,
        **kwargs: Any,
    ):
        from acp import NewSessionResponse

        sid = uuid4().hex
        self.sessions[sid] = {"cwd": cwd}
        return NewSessionResponse(session_id=sid)

    async def _emit(self, session_id: str, text: str) -> None:
        from acp.schema import AgentMessageChunk, TextContentBlock

        if self._conn is None:
            return
        chunk = AgentMessageChunk(content=TextContentBlock(type="text", text=text))
        await self._conn.session_update(session_id=session_id, update=chunk, source="escalane")

    async def prompt(self, session_id: str, prompt: list, **kwargs: Any):
        from acp import PromptResponse

        text = _prompt_text(prompt)
        resolved = _resolve_act_ids(text)

        if resolved == "help":
            await self._emit(session_id, HELP_TEXT)
            return PromptResponse(stop_reason="end_turn")

        if resolved == "json":
            await self._emit(
                session_id,
                "Inline JSON state prompts are reserved; use act1/act2/act3 or storyboard.",
            )
            return PromptResponse(stop_reason="end_turn")

        if resolved == "all":
            await self._emit(session_id, "Running homelab storyboard (Acts 1–3), dry-run…\n")
            results = await asyncio.to_thread(
                run_storyboard,
                backend=self.backend,
                model=self.model,
                base_url=self.base_url,
                gate_config=self.gate_config,
                live_stack=False,
                allow_writes=self.allow_writes,
                quiet=True,
                repo_root=self.paths.repo_root,
            )
            for r in results:
                await self._emit(session_id, format_act_summary(r) + "\n---\n")
            ok = all(r.get("choice_ok") for r in results)
            await self._emit(session_id, f"storyboard_ok={ok}\n")
            return PromptResponse(stop_reason="end_turn")

        act_by_id = {a["id"]: a for a in ACTS}
        for act_id in resolved:
            act = act_by_id[act_id]
            await self._emit(session_id, f"Running {act_id}: {act['title']}…\n")
            audit = self.paths.episodes_dir / f"acp_{act_id}.jsonl"
            self.paths.episodes_dir.mkdir(parents=True, exist_ok=True)
            result = await asyncio.to_thread(
                run_one_act,
                paths=self.paths,
                incident_name=act["incident"],
                backend=self.backend,
                model=self.model,
                base_url=self.base_url,
                gate_config=self.gate_config,
                allow_writes=self.allow_writes,
                dry_run=not self.allow_writes,
                audit_path=audit,
            )
            choice = None
            if isinstance(result["answers"].get("playbook"), dict):
                choice = result["answers"]["playbook"].get("choice")
            result["act"] = act_id
            result["expected_choice"] = act["expected_choice"]
            result["choice_ok"] = choice == act["expected_choice"]
            argv = (result.get("execution") or {}).get("argv") or []
            result["argv_joined"] = " ".join(argv) if argv else ""
            await self._emit(session_id, format_act_summary(result) + "\n")

        return PromptResponse(stop_reason="end_turn")


async def _async_main(argv: list[str] | None = None) -> None:
    _require_acp()
    from acp import run_agent

    parser = argparse.ArgumentParser(prog="escalane-acp", description="Escalane Homelab ACP agent")
    parser.add_argument("--backend", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--gate-config", default=None)
    parser.add_argument("--allow-writes", action="store_true", default=False)
    args = parser.parse_args(argv)
    agent = EscalaneHomelabAgent(
        backend=args.backend,
        model=args.model,
        base_url=args.base_url,
        gate_config=args.gate_config,
        allow_writes=args.allow_writes,
    )
    await run_agent(agent)


def main(argv: list[str] | None = None) -> None:
    asyncio.run(_async_main(argv))


if __name__ == "__main__":
    main()
