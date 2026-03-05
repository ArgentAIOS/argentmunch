# ArgentMunch

> Token-efficient codebase intelligence for ArgentOS and MAO agents.

**ArgentMunch** is a fork of [jCodeMunch MCP](https://github.com/jgravelle/jcodemunch-mcp), repurposed and extended for the ArgentOS ecosystem, Claude Code workflows, and the MAO multi-agent cluster.

---

## The Problem

Most AI agents explore codebases the expensive way — reading entire files, skimming thousands of irrelevant lines, repeating for every task. At scale with 17+ agents, token costs multiply fast.

| Task | Traditional | ArgentMunch |
|---|---|---|
| Find a function | ~40,000 tokens | ~200 tokens |
| Understand module API | ~15,000 tokens | ~800 tokens |
| Explore repo structure | ~200,000 tokens | ~2,000 tokens |

**80–99% token reduction for code exploration tasks.**

---

## What ArgentMunch Adds

- **ArgentOS-native integration** — pre-wired as an MCP server in argent.json
- **Multi-repo indexing** — index all active repos, query across all of them in one call
- **MAO shared endpoint** — one centralized server all 17+ MAO agents hit (Dell R750)
- **Diff awareness** — symbol change tracking, stale cache detection, webhook-triggered re-index
- **jContextMunch layer** — unified code + docs retrieval in one endpoint

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │      ArgentMunch Server      │
                    │   (Dell R750, always-on)     │
                    │                              │
                    │  ┌──────────────────────┐   │
                    │  │   Symbol Index Store  │   │
                    │  │   (tree-sitter AST)   │   │
                    │  └──────────────────────┘   │
                    └──────────┬──────────────────┘
                               │ MCP Protocol
              ┌────────────────┼────────────────┐
              │                │                │
       ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
       │ Claude Code │  │  MAO Agent  │  │  MAO Agent  │
       │  (Mac M3)   │  │  (Argent)   │  │  (Titan)    │
       └─────────────┘  └─────────────┘  └─────────────┘
              ... and 15+ more agents
```

---

## Implementation Phases

- **Phase 1** — Fork & baseline: local MVP, index ArgentOS repo, validate token savings
- **Phase 2** — Multi-repo & shared endpoint: deploy on Dell R750, wire into MAO
- **Phase 3** — Diff awareness & webhooks: auto re-index on git push, stale cache alerts
- **Phase 4** — jContextMunch layer: unified code + docs retrieval, Claude Code integration

---

## Upstream

- **jCodeMunch MCP:** https://github.com/jgravelle/jcodemunch-mcp
- **License:** See upstream — dual-use, verify before commercial use

---

## Status

🚧 **Phase 1 — Active Development**

See [ARGENTMUNCH_EPIC.md](./ARGENTMUNCH_EPIC.md) for full project spec and architecture.

---

*Part of the [ArgentOS](https://github.com/ArgentAIOS/argentos) ecosystem.*
