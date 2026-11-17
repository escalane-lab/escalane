# Publishing this post via DevRelay

[DevRelay](https://devrelay.com/) is the MLH MCP gateway that can stage a **private DEV draft** (`create_article` with `published: false`). Nick Taylor’s public [dev.to MCP](https://dev.to/nickytonline/introducing-the-devto-mcp-server-42jg) is read-only and cannot create posts.

## One-time setup (this machine)

Already done:

- Binary: `~/.devrelay/bin/dev_mlh_mcp_server` (v0.1.27)
- Cursor MCP entry: `devrelay-gateway` in `~/.cursor/mcp.json`

You still need:

```bash
devrelay login
```

Sign in with the **MLH account** that has **DEV linked** in the MLH profile. Then **restart Cursor** so the MCP server loads in the agent session.

## Stage the Builders Week article

After login + restart, ask the agent to:

1. Read `docs/blog/devto-paste-ready.md`
2. Call DevRelay `create_article` with:
   - title: `Catalog-bound Decide+Act: why free tool-calling felt wrong for SysOps writes`
   - `published: false`
   - tags: `mlhacks`, `ai`, `python`, `security`
   - body: paste-ready markdown
3. Return the **`edit_url`** for review (do not treat the temp slug `url` as broken)
4. You upload `docs/blog/assets/escalane-dev-cover.jpg` in the DEV editor
5. You publish only when ready (`published: true` needs an explicit yes)

Do not set `ai_disclosure_level` manually — DevRelay defaults to `some_ai`.
