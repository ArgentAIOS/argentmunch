# ArgentMunch — Roadmap

## Phase 1 — MVP Local Indexing ← *Current*

Goal: Get a working local instance indexing the ArgentOS codebase with measurable token savings.

- [x] Fork jCodeMunch baseline
- [x] Safety/legal/security scaffolding
- [ ] Rename internals from `jcodemunch_mcp` → `argentmunch`
- [ ] Get baseline running locally on Mac (Python env setup)
- [ ] Index `ArgentAIOS/argentos` as first test repo
- [ ] Index `webdevtodayjason/sub-agents` as second repo
- [ ] Validate token savings vs current Claude Code usage
- [ ] Document local run instructions

---

## Phase 2 — Multi-Repo & Shared MAO Endpoint

Goal: One server all 17+ MAO agents query. No more duplicate indexing.

- [ ] Add multi-repo indexing support (index N repos in one config)
- [ ] Deploy centralized ArgentMunch server on Dell R750
- [ ] Wire into `argent.json` as default MCP server for all agents
- [ ] Connect first 3 MAO agents to shared endpoint
- [ ] Benchmark token usage before/after across agent cluster
- [ ] Document MAO integration guide

---

## Phase 3 — Webhook Re-Index & Diff Awareness

Goal: Index stays fresh automatically. Agents know when their knowledge is stale.

- [ ] GitHub webhook integration — auto re-index on push to indexed repos
- [ ] Symbol stability tracking — detect breaking API changes between commits
- [ ] Stale cache notification — agents receive invalidation signals
- [ ] Index freshness dashboard widget for ArgentOS dashboard
- [ ] Operator alerting when re-index fails

---

## Phase 4 — Unified Code + Docs Retrieval (jContextMunch Layer)

Goal: One endpoint returns ranked code symbols AND relevant docs together.

- [ ] Integrate jdocmunch for documentation indexing
- [ ] Build unified retrieval endpoint (code + docs in single response)
- [ ] Add to Claude Code workflow as default context tool
- [ ] `--repo argentos` shorthand for fast context loading
- [ ] Publish as ArgentOS skill to ClawHub

---

*Last updated: 2026-03-04*
