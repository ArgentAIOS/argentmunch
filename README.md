# ArgentMunch

> ⚠️ **NOT PRODUCTION-READY** — Pre-release, under active development. Do not use in production environments.

Token-efficient codebase intelligence for ArgentOS and MAO agents.

**ArgentMunch** is a fork of [jCodeMunch MCP](https://github.com/jgravelle/jcodemunch-mcp), repurposed and extended for the ArgentOS ecosystem, Claude Code workflows, and the MAO multi-agent cluster (17+ agents).

---

## Project Purpose

Most AI agents explore codebases the expensive way — reading entire files, skimming thousands of irrelevant lines, repeating for every agent and every task. At scale, token costs compound fast.

ArgentMunch uses **tree-sitter AST parsing** to pre-index codebases so agents retrieve exact symbols (functions, classes, methods) instead of reading whole files.

| Task | Traditional | ArgentMunch |
|---|---|---|
| Find a function | ~40,000 tokens | ~200 tokens |
| Understand module API | ~15,000 tokens | ~800 tokens |
| Explore repo structure | ~200,000 tokens | ~2,000 tokens |

**80–99% token reduction for code exploration tasks.**

With 17+ MAO agents all hitting a shared ArgentMunch endpoint, the savings multiply across every agent, every session.

---

## Local Run Instructions

### Requirements

- Python 3.10+
- pip / uv

### Install

```bash
cd /Users/sem/code/argentmunch
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run the MCP server

```bash
argentmunch-mcp
```

Server starts on `http://localhost:8765` by default.

---

## Index + Query Quickstart

### Index a local repo

```bash
argentmunch-mcp index --path /Users/sem/code/argentos
```

### Index a GitHub repo

```bash
argentmunch-mcp index --repo ArgentAIOS/argentos
```

### Query for a symbol

```bash
argentmunch-mcp query --symbol "memory_store" --repo argentos
```

### Multi-repo index (Phase 2)

```bash
argentmunch-mcp index --config ~/.argentmunch/repos.yaml
```

---

## MCP Config (Claude Code / Claude Desktop)

Add to your MCP server config:

```json
{
  "mcpServers": {
    "argentmunch": {
      "command": "argentmunch-mcp",
      "env": {
        "GITHUB_TOKEN": "ghp_...",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

---

## Health Endpoint

Once running, check server health at:

```
GET http://localhost:8765/health
```

Response:
```json
{
  "status": "ok",
  "indexed_repos": ["argentos", "sub-agents"],
  "index_freshness": "2026-03-04T22:00:00Z",
  "version": "0.1.0-argentmunch"
}
```

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │      ArgentMunch Server      │
                    │   (Dell R750, always-on)     │
                    │                              │
                    │  ┌──────────────────────┐   │
                    │  │   Symbol Index Store  │   │
                    │  │   ~/.code-index/      │   │
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

## Docs

- [Full Project Epic](./ARGENTMUNCH_EPIC.md)
- [Roadmap](./docs/ROADMAP.md)
- [Security Policy](./SECURITY.md)
- [License Check](./LICENSE_CHECK.md)
- [Upstream Architecture](./ARCHITECTURE.md)

---

## Upstream

- **jCodeMunch MCP:** https://github.com/jgravelle/jcodemunch-mcp
- **License:** See [LICENSE_CHECK.md](./LICENSE_CHECK.md) — ⚠️ pending legal review

---

*Part of the [ArgentOS](https://github.com/ArgentAIOS/argentos) ecosystem.*
