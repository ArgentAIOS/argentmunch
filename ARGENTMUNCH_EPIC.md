# ArgentMunch — Forking jCodeMunch for ArgentOS

## Overview

**jCodeMunch MCP** is a token-efficient MCP server for GitHub source code exploration via tree-sitter AST parsing. It pre-indexes codebases and lets AI agents retrieve exact symbols (functions, classes, methods) instead of brute-force reading entire files.

**ArgentMunch** is the proposed fork — tailored specifically for the ArgentOS ecosystem, MAO agent cluster, and Claude Code workflows.

---

## Why Fork?

### The Token Problem

Most AI agents explore repositories the expensive way:
- Open entire files → skim thousands of irrelevant lines → repeat

This is wasteful at scale. Token costs compound across every agent, every task, every session.

| Task | Traditional Approach | jCodeMunch |
|---|---|---|
| Find a function | ~40,000 tokens | ~200 tokens |
| Understand module API | ~15,000 tokens | ~800 tokens |
| Explore repo structure | ~200,000 tokens | ~2,000 tokens |

**Result: 80–99% token reduction for code exploration tasks.**

### The MAO Problem

With 17+ specialized agents in MAO, each agent independently burns tokens reading the same codebases. There's no shared code intelligence layer — every agent re-reads files it's already "seen."

ArgentMunch solves this with a **shared, persistent symbol index** that all MAO agents query from one endpoint.

---

## What ArgentMunch Adds (Over jCodeMunch)

### 1. ArgentOS-Native Integration
- Pre-wired into argent.json as an MCP server — zero setup for new agents
- Exposes as a skill (`argentmunch`) available to all agents automatically
- No per-agent configuration required

### 2. Multi-Repo Indexing
Index all active repos in one command and query across all of them:
- `sub-agents` (175+ stars)
- `context-forge` (131+ stars)
- `claude-hooks` (72+ stars)
- `ArgentAIOS/argentos`
- All MAO repos on the Dell server

Query: *"Find all functions that handle task routing across all repos"* — one call, precise results.

### 3. MAO-Aware Shared Endpoint
- Single jCodeMunch-compatible endpoint all 17+ MAO agents hit
- Centralized on the Dell R750 (persistent, always-on)
- Eliminates duplicate indexing across agents
- Cache invalidation on git push (webhook-triggered re-index)

### 4. Agentic Diff Awareness
- Tracks symbol changes between commits
- Agents know when their cached knowledge is stale
- On-demand re-index triggered by git activity
- Symbol stability IDs let agents detect breaking changes in APIs they depend on

### 5. jContextMunch Layer (Unified Retrieval)
Extends jContextMunch's hybrid approach for your specific stack:
- **Code symbols** (via jCodeMunch) + **Doc sections** (via jdocmunch) unified
- Single endpoint returns ranked context: code + relevant docs together
- Eliminates the "which tool do I use?" question for agents

### 6. Claude Code Optimization
- Pre-built index profiles for common Claude Code exploration patterns
- `--repo argentos` shorthand for fast context loading
- Reduces Claude Code's file-reading overhead on large repos significantly

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
                    │                              │
                    │  ┌──────────────────────┐   │
                    │  │   Doc Index Store     │   │
                    │  │   (jdocmunch layer)   │   │
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

## Implementation Plan

### Phase 1 — Fork & Baseline (Week 1)
- [ ] Fork `jgravelle/jcodemunch-mcp` → `ArgentAIOS/argentmunch`
- [ ] Audit codebase, understand tree-sitter integration points
- [ ] Get baseline running locally on Mac
- [ ] Index `ArgentAIOS/argentos` as first test repo
- [ ] Validate token savings against current Claude Code usage

### Phase 2 — Multi-Repo & Shared Endpoint (Week 2)
- [ ] Add multi-repo indexing support
- [ ] Deploy centralized server on Dell R750
- [ ] Wire into argent.json as default MCP server
- [ ] Connect first 3 MAO agents to shared endpoint
- [ ] Benchmark token usage before/after

### Phase 3 — Diff Awareness & Webhooks (Week 3)
- [ ] GitHub webhook integration for auto re-indexing on push
- [ ] Symbol stability tracking (detect breaking changes)
- [ ] Stale cache notification to dependent agents
- [ ] Index freshness dashboard widget

### Phase 4 — jContextMunch Layer (Week 4)
- [ ] Integrate jdocmunch for docs indexing
- [ ] Build unified retrieval endpoint
- [ ] Add to Claude Code workflow as default context tool
- [ ] Publish as ArgentOS skill to ClawHub

---

## Upstream Reference

- **GitHub:** https://github.com/jgravelle/jcodemunch-mcp
- **PyPI:** https://pypi.org/project/jcodemunch-mcp/
- **jContextMunch (orchestration layer):** https://lobehub.com/mcp/jgravelle-jcontextmunch-mcp
- **License:** Dual-use (check before forking for commercial use)

---

*Document created: 2026-03-04 | ArgentOS Workspace*
