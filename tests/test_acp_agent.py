"""Optional ACP agent smoke (requires --extra acp)."""

from __future__ import annotations

import pytest

pytest.importorskip("acp")

from escalane.acp_agent import EscalaneHomelabAgent, _prompt_text, _resolve_act_ids


@pytest.mark.acp
def test_resolve_act_ids():
    assert _resolve_act_ids("help") == "help"
    assert _resolve_act_ids("storyboard") == "all"
    assert _resolve_act_ids("act1") == ["act1"]
    assert _resolve_act_ids("maintenance window") == ["act2"]
    assert _resolve_act_ids("compose sensor") == ["act3"]


@pytest.mark.acp
def test_acp_prompt_act1(repo_root, tmp_path):
    import asyncio

    from acp.schema import TextContentBlock
    from escalane.demo_homelab import DemoPaths

    async def _run() -> str:
        paths = DemoPaths.discover(repo_root)
        agent = EscalaneHomelabAgent(
            backend="mock",
            gate_config="A3",
            repo_root=repo_root,
        )
        agent.paths = DemoPaths(
            repo_root=paths.repo_root,
            demo_root=tmp_path,
            catalog=paths.catalog,
            incidents_dir=paths.incidents_dir,
            episodes_dir=tmp_path / "episodes",
        )
        emitted: list[str] = []

        class _Conn:
            async def session_update(self, session_id, update, **kwargs):
                content = getattr(update, "content", None)
                emitted.append(getattr(content, "text", "") if content else "")

        agent.on_connect(_Conn())
        init = await agent.initialize(protocol_version=1)
        assert init.protocol_version == 1
        session = await agent.new_session(cwd=str(tmp_path))
        resp = await agent.prompt(
            session.session_id,
            [TextContentBlock(type="text", text="act1")],
        )
        assert resp.stop_reason == "end_turn"
        return "\n".join(emitted)

    joined = asyncio.run(_run())
    assert "choice=restart_docker_container" in joined
    assert "docker restart convenience-app" in joined


@pytest.mark.acp
def test_prompt_text_helpers():
    from acp.schema import TextContentBlock

    assert _prompt_text([TextContentBlock(type="text", text="act2")]) == "act2"
    assert _prompt_text([{"text": "hi"}]) == "hi"
