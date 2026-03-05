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

## Quick Start

### Requirements

- Python 3.10+
- pip

### Install

```bash
cd argentmunch
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

### Index a Local Repo

```bash
argentmunch index /path/to/your/repo --no-ai

# Example output:
# ✓ Indexed 37 files, 358 symbols
#   Repo: local/argentmunch
#   Languages: python(37)
```

### Query Symbols

```bash
argentmunch query local/argentmunch "search_symbols"

# Example output:
# Search: 'search_symbols' in local/argentmunch
# Found: 4 results (2.2ms)
#
#   1. [function] search_symbols
#      File: src/jcodemunch_mcp/tools/search_symbols.py:11
#      Score: 35
```

Filter by kind:

```bash
argentmunch query local/argentmunch "Calculator" --kind class
```

### List Indexed Repos

```bash
argentmunch list

# Indexed repositories: 1
#   • local/argentmunch
#     Files: 37, Symbols: 358
```

### Health Check (CLI)

```bash
argentmunch health
# { "ok": true, "version": "0.1.0-mvp", "indexed_repos_count": 1, ... }
```

### Multi-Repo Index Run

```bash
# Optional: enforce explicit GitHub repo allowlist
export ARGENTMUNCH_REPO_ALLOWLIST="argentaios/argentos,argentaios/*"

argentmunch index-repos \
  argentaios/argentos \
  https://github.com/argentaios/argentmunch \
  --incremental
```

### Health Check (HTTP)

```bash
# Start the health server
argentmunch serve --port 9120

# In another terminal:
curl http://localhost:9120/health
```

Response:
```json
{
  "ok": true,
  "version": "0.1.0-mvp",
  "indexed_repos_count": 1,
  "total_symbols": 358,
  "last_indexed_at": "2026-03-04T23:10:05.822416",
  "repos": [
    {
      "repo": "local/argentmunch",
      "symbol_count": 358,
      "file_count": 37
    }
  ]
}
```

Returns 200 when healthy, 503 when index metadata is corrupt.

### Index Freshness Status

```bash
argentmunch status --stale-threshold-minutes 30

# or over HTTP:
curl http://127.0.0.1:9120/status
```

### Secure Health + Webhook Configuration

```bash
# Optional but recommended in shared environments:
export ARGENTMUNCH_HEALTH_TOKEN="replace-me"
export ARGENTMUNCH_WEBHOOK_SECRET="replace-me"

# Repo allowlist (empty => allow all, for backward compatibility)
export ARGENTMUNCH_REPO_ALLOWLIST="argentaios/argentos,argentaios/*"

# Stale threshold for /status and `argentmunch status`
export ARGENTMUNCH_STALE_THRESHOLD_MINUTES=60
```

By default, `argentmunch serve` now binds to `127.0.0.1` (local-safe default).  
When `ARGENTMUNCH_HEALTH_TOKEN` is set, `/health` and `/status` require `Authorization: Bearer <token>`.

Webhook trigger simulation:

```bash
payload='{"repository":{"full_name":"argentaios/argentos"}}'
sig=$(printf '%s' "$payload" | openssl dgst -sha256 -hmac "$ARGENTMUNCH_WEBHOOK_SECRET" | sed 's/^.* //')

curl -X POST http://127.0.0.1:9120/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -H "X-Hub-Signature-256: sha256=$sig" \
  -d "$payload"
```

---

## MCP Server Mode

ArgentMunch also runs as an MCP server for Claude Code / Claude Desktop:

```bash
argentmunch-mcp
```

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

## Benchmark

Run the benchmark to compare brute-force file scans vs. symbol queries:

```bash
python scripts/benchmark_mvp.py
```

Results (indexing ArgentMunch's own codebase):

| Scenario | Brute-force | Symbol query | Savings |
|----------|-------------|--------------|---------|
| Broad search (`index`) | 59,738 tokens | 441 tokens | 99.3% (135x) |
| Specific lookup (`save_index`) | 59,738 tokens | 286 tokens | 99.5% (209x) |
| Cross-cutting (`parse file`) | 59,738 tokens | 531 tokens | 99.1% (113x) |

Full report: [`docs/benchmarks/mvp-baseline.md`](./docs/benchmarks/mvp-baseline.md)

---

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/test_mvp.py -v
```

17 tests covering: index success/failure/empty/incremental, query hit/miss/filter/methods, health empty/populated/HTTP/corrupt, CLI integration.

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

- [MVP Status](./docs/MVP_STATUS.md)
- [Full Project Epic](./ARGENTMUNCH_EPIC.md)
- [Roadmap](./docs/ROADMAP.md)
- [Benchmarks](./docs/benchmarks/mvp-baseline.md)
- [Security Policy](./SECURITY.md)
- [License Check](./LICENSE_CHECK.md)
- [Upstream Architecture](./ARCHITECTURE.md)

---

## Upstream

- **jCodeMunch MCP:** https://github.com/jgravelle/jcodemunch-mcp
- **License:** See [LICENSE_CHECK.md](./LICENSE_CHECK.md) — ⚠️ pending legal review

---

*Part of the [ArgentOS](https://github.com/ArgentAIOS/argentos) ecosystem.*
