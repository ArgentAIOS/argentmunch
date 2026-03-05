# MVP Status — ArgentMunch

## ✅ Delivered

### CLI Commands
- **`argentmunch index <path>`** — Index a local repo/folder via tree-sitter AST parsing
  - Supports `--no-ai` (skip AI summaries), `--incremental` (only re-index changed files)
  - Custom storage path via `--storage`
  - Security filtering: skips secrets, binaries, symlink escapes, `.gitignore`'d files
- **`argentmunch query <repo> <query>`** — Search symbols by name, signature, summary, docstring
  - Kind filter (`--kind function|class|method|constant|type`)
  - Max results limit (`--max-results N`)
  - Weighted scoring (exact match > substring > word overlap > signature > summary > keywords)
- **`argentmunch list`** — List all indexed repositories with stats
- **`argentmunch health`** — Print health status as JSON

### HTTP Health Endpoint
- **`argentmunch serve [--port N]`** — Start HTTP server (default port 9120)
- **`GET /health`** — Returns JSON: `ok`, `version`, `indexed_repos_count`, `total_symbols`, `last_indexed_at`, per-repo breakdown
- Returns 200 when healthy, 503 when index metadata is corrupt
- 404 for all other paths

### Benchmark
- **`scripts/benchmark_mvp.py`** — Compares brute-force file scan tokens vs. symbol query tokens
- 3 scenarios: broad search, specific lookup, cross-cutting search
- Results: **99%+ token savings** across all scenarios (113x–209x reduction)
- Output: `docs/benchmarks/mvp-baseline.md`

### Tests
- **17 tests**, all passing
- Coverage: index success/failure/empty/incremental, query hit/miss/filter/methods/nonexistent, health empty/populated/HTTP/corrupt, CLI help/list/full-workflow

## ⚠️ Known Gaps

1. **No GitHub repo indexing via CLI** — `index_repo` (remote GitHub) is only available via MCP server, not CLI. MVP focuses on local folder indexing.
2. **No AI summaries in benchmark** — Benchmark runs with `--no-ai` to avoid API key dependency. AI summary quality untested in MVP.
3. **Single-repo queries only** — Each query targets one repo. Cross-repo search not yet implemented.
4. **No authentication on health endpoint** — HTTP server is unauthenticated. Fine for local use, needs auth for production.
5. **No webhook/watch mode** — Manual re-index required after code changes. Planned for Phase 2.
6. **Python 3.14 only tested** — Dependencies install cleanly on 3.14. Compatibility with 3.10-3.13 not verified.

## 📋 Next Phase Checklist

### Phase 2: Multi-Repo + Watch
- [ ] CLI `index` with GitHub URL support (reuse `index_repo`)
- [ ] Multi-repo cross-search
- [ ] File watcher for auto-reindex on save
- [ ] Webhook endpoint for CI-triggered reindex
- [ ] ArgentOS RAG Library integration (push symbols to knowledge collection)

### Phase 3: Production Hardening
- [ ] Auth on health/API endpoints
- [ ] Rate limiting
- [ ] Index size limits and cleanup
- [ ] Prometheus metrics
- [ ] Docker/systemd deployment templates

### Phase 4: Unified Code + Docs Retrieval
- [ ] Markdown/RST doc indexing alongside code
- [ ] Combined search across code symbols and documentation
- [ ] Semantic search via embeddings (complement keyword scoring)
