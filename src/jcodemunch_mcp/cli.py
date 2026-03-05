"""ArgentMunch CLI - standalone commands for indexing, querying, and health."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from .reindex_manager import ReindexManager, attach_reindex_status
from .repos_config import add_repo, load_repos_config, remove_repo
from .runtime_config import get_health_token, get_repo_allowlist, get_webhook_secret, is_repo_allowed
from .storage import IndexStore
from .tools.index_folder import index_folder
from .tools.index_repo import index_repo
from .tools.list_repos import list_repos
from .tools.search_symbols import search_symbols


def _effective_repo_allowlist(config_path: Optional[str]) -> tuple[list[str], bool]:
    """Resolve allowlist and enforcement mode.

    If config exists, enforce deny-by-default against config allowlist.
    Otherwise fallback to env allowlist (non-strict for backward compatibility).
    """
    cfg = load_repos_config(config_path)
    if cfg.exists:
        return cfg.allowlist, True
    return get_repo_allowlist(), False


def cmd_index(args: argparse.Namespace) -> int:
    """Index local folder or multiple GitHub repos from config."""
    storage = args.storage or None
    ai = not args.no_ai
    incremental = args.incremental

    if args.config:
        cfg = load_repos_config(args.config)
        if not cfg.exists:
            print(f"✗ Error: repos config not found: {cfg.path}", file=sys.stderr)
            return 1
        if not cfg.repos:
            print(f"✗ Error: repos config is empty: {cfg.path}", file=sys.stderr)
            return 1

        allowlist = cfg.allowlist
        failed = 0
        results = []
        print(f"Indexing {len(cfg.repos)} repo(s) from {cfg.path}")

        for entry in cfg.repos:
            result = asyncio.run(
                index_repo(
                    url=entry.repo,
                    use_ai_summaries=ai,
                    storage_path=storage,
                    incremental=incremental,
                    allowlist=allowlist,
                    deny_by_default=True,
                )
            )
            results.append(result)
            if result.get("success"):
                print(f"✓ {entry.repo}: indexed ({result.get('symbol_count', '?')} symbols)")
            else:
                failed += 1
                print(f"✗ {entry.repo}: {result.get('error', 'unknown error')}", file=sys.stderr)

        if args.json:
            print(json.dumps({"results": results, "failed": failed, "total": len(results)}, indent=2))
        return 0 if failed == 0 else 1

    if not args.path:
        print("✗ Error: path is required when --config is not provided", file=sys.stderr)
        return 1

    print(f"Indexing: {args.path}")
    print(f"  AI summaries: {ai}")
    print(f"  Incremental: {incremental}")
    if storage:
        print(f"  Storage: {storage}")

    result = index_folder(
        path=args.path,
        use_ai_summaries=ai,
        storage_path=storage,
        incremental=incremental,
    )

    if not result.get("success"):
        print(f"\n✗ Error: {result.get('error', 'unknown')}", file=sys.stderr)
        return 1

    print(f"\n✓ Indexed {result.get('file_count', '?')} files, {result.get('symbol_count', '?')} symbols")
    print(f"  Repo: {result.get('repo', '?')}")
    print(f"  Indexed at: {result.get('indexed_at', '?')}")

    langs = result.get("languages", {})
    if langs:
        print(f"  Languages: {', '.join(f'{k}({v})' for k, v in langs.items())}")

    warnings = result.get("warnings", [])
    if warnings:
        print(f"\n  Warnings ({len(warnings)}):")
        for w in warnings[:10]:
            print(f"    - {w}")
        if len(warnings) > 10:
            print(f"    ... and {len(warnings) - 10} more")

    if args.json:
        print(f"\n{json.dumps(result, indent=2)}")

    return 0


def _render_query_results(search_label: str, count: int, timing_ms: float | str, results: list[dict]) -> None:
    print(f"Search: {search_label}")
    print(f"Found: {count} results ({timing_ms}ms)")
    print()
    if not results:
        print("  No matching symbols found.")
        return

    for i, sym in enumerate(results, 1):
        print(f"  {i}. [{sym['kind']}] {sym['name']}")
        print(f"     Repo: {sym['repo']}")
        print(f"     File: {sym['file']}:{sym.get('line', '?')}")
        sig = sym.get("signature", "")
        if sig:
            if len(sig) > 100:
                sig = sig[:97] + "..."
            print(f"     Sig:  {sig}")
        summary = sym.get("summary", "")
        if summary:
            if len(summary) > 120:
                summary = summary[:117] + "..."
            print(f"     {summary}")
        print(f"     Score: {sym.get('score', 0)}")
        print()


def _query_all_repos(query: str, max_results: int, kind: Optional[str], storage: Optional[str]) -> dict:
    store = IndexStore(base_path=storage)
    indexed = store.list_repos()
    combined: list[dict] = []
    timing_total = 0.0

    for repo_meta in indexed:
        repo_name = repo_meta.get("repo", "")
        result = search_symbols(
            repo=repo_name,
            query=query,
            kind=kind,
            max_results=max_results,
            storage_path=storage,
        )
        if "error" in result:
            continue
        timing_total += float((result.get("_meta") or {}).get("timing_ms", 0.0))
        for item in result.get("results", []):
            merged = dict(item)
            merged["repo"] = repo_name
            combined.append(merged)

    combined.sort(key=lambda r: r.get("score", 0), reverse=True)
    final = combined[:max_results]
    return {
        "query": query,
        "result_count": len(final),
        "results": final,
        "_meta": {"timing_ms": round(timing_total, 1), "repos_scanned": len(indexed)},
    }


def cmd_query(args: argparse.Namespace) -> int:
    """Query symbols in one repo or across all indexed repos."""
    storage = args.storage or None
    kind = args.kind
    max_results = args.max_results

    if args.all:
        query = args.query if args.query is not None else args.repo_or_query
        if not query:
            print("✗ Error: query text is required", file=sys.stderr)
            return 1

        result = _query_all_repos(query=query, max_results=max_results, kind=kind, storage=storage)
        _render_query_results(
            search_label=f"'{query}' across all repos",
            count=result.get("result_count", 0),
            timing_ms=(result.get("_meta") or {}).get("timing_ms", "?"),
            results=result.get("results", []),
        )
        if args.json:
            print(f"\n{json.dumps(result, indent=2)}")
        return 0

    repo = args.repo_or_query
    query = args.query
    if not repo or not query:
        print("✗ Error: usage is `argentmunch query <repo> <query>` or `argentmunch query --all <query>`", file=sys.stderr)
        return 1

    result = search_symbols(
        repo=repo,
        query=query,
        kind=kind,
        max_results=max_results,
        storage_path=storage,
    )

    if "error" in result:
        print(f"✗ Error: {result['error']}", file=sys.stderr)
        return 1

    results = result.get("results", [])
    count = result.get("result_count", 0)
    meta = result.get("_meta", {})

    enriched = []
    for item in results:
        out = dict(item)
        out["repo"] = result.get("repo", repo)
        enriched.append(out)

    _render_query_results(
        search_label=f"'{query}' in {result.get('repo', '?')}",
        count=count,
        timing_ms=meta.get("timing_ms", "?"),
        results=enriched,
    )

    if meta.get("tokens_saved"):
        print(f"  Token savings: ~{meta['tokens_saved']:,} tokens this query")

    if args.json:
        print(f"\n{json.dumps(result, indent=2)}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List indexed repos with reindex status."""
    storage = args.storage or None
    result = list_repos(storage_path=storage)

    repos = attach_reindex_status(result.get("repos", []), storage)
    count = result.get("count", 0)

    print(f"Indexed repositories: {count}")
    print()

    if not repos:
        print("  No repos indexed yet. Use 'argentmunch index <path>' to start.")
        return 0

    for repo in repos:
        print(f"  • {repo['repo']}")
        print(f"    Files: {repo['file_count']}, Symbols: {repo['symbol_count']}")
        print(f"    Languages: {', '.join(repo.get('languages', {}).keys())}")
        print(f"    Indexed: {repo['indexed_at']}")
        print(f"    Last reindexed: {repo.get('last_reindexed_at')}")
        print(f"    Reindex in progress: {repo.get('in_progress', False)}")
        if repo.get("last_error"):
            print(f"    Last reindex error: {repo['last_error']}")
        print()

    if args.json:
        print(f"\n{json.dumps({**result, 'repos': repos}, indent=2)}")

    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Print health status as JSON (also available via HTTP endpoint)."""
    storage = args.storage or None
    health = get_health_data(storage)
    print(json.dumps(health, indent=2))
    return 0 if health.get("ok") else 1


def _safe_parse_iso8601(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def get_status_data(
    storage_path: Optional[str] = None,
    stale_threshold_minutes: Optional[int] = None,
) -> dict:
    """Generate index freshness/status payload."""
    if stale_threshold_minutes is None:
        stale_threshold_minutes = int(os.environ.get("ARGENTMUNCH_STALE_THRESHOLD_MINUTES", "60"))

    health = get_health_data(storage_path)
    now = datetime.now(timezone.utc)
    threshold = timedelta(minutes=stale_threshold_minutes)

    repos_status = []
    stale_count = 0
    newest_age_seconds: Optional[int] = None
    total_symbols = 0
    last_indexed_at = health.get("last_indexed_at")

    for repo in health.get("repos", []):
        indexed_raw = repo.get("indexed_at")
        indexed_dt = _safe_parse_iso8601(indexed_raw)
        total_symbols += int(repo.get("symbol_count", 0))
        age_seconds: Optional[int] = None
        stale = True
        if indexed_dt:
            age_seconds = max(0, int((now - indexed_dt).total_seconds()))
            stale = age_seconds > int(threshold.total_seconds())
            if newest_age_seconds is None or age_seconds < newest_age_seconds:
                newest_age_seconds = age_seconds
        if stale:
            stale_count += 1
        repos_status.append(
            {
                "repo": repo.get("repo"),
                "indexed_at": indexed_raw,
                "age_seconds": age_seconds,
                "stale": stale,
                "symbol_count": repo.get("symbol_count", 0),
                "file_count": repo.get("file_count", 0),
            }
        )

    return {
        "ok": health.get("ok", False),
        "version": health.get("version"),
        "total_symbols": total_symbols,
        "last_indexed_at": last_indexed_at,
        "stale": stale_count > 0,
        "stale_threshold_minutes": stale_threshold_minutes,
        "threshold_config_used": {
            "stale_threshold_minutes": stale_threshold_minutes,
            "source_env": "ARGENTMUNCH_STALE_THRESHOLD_MINUTES",
        },
        "indexed_repos_count": health.get("indexed_repos_count", 0),
        "stale_repos_count": stale_count,
        "fresh_repos_count": max(0, health.get("indexed_repos_count", 0) - stale_count),
        "newest_index_age_seconds": newest_age_seconds,
        "repos": repos_status,
    }


def get_health_data(storage_path: Optional[str] = None) -> dict:
    """Generate health check data."""
    try:
        store = IndexStore(base_path=storage_path)
        repos = attach_reindex_status(store.list_repos(), storage_path)

        total_symbols = sum(r.get("symbol_count", 0) for r in repos)
        last_indexed = None
        if repos:
            last_indexed = max(r.get("indexed_at", "") for r in repos)

        return {
            "ok": True,
            "version": "0.1.0-mvp",
            "indexed_repos_count": len(repos),
            "total_symbols": total_symbols,
            "last_indexed_at": last_indexed,
            "repos": [
                {
                    "repo": r["repo"],
                    "symbol_count": r.get("symbol_count", 0),
                    "file_count": r.get("file_count", 0),
                    "indexed_at": r.get("indexed_at"),
                    "last_reindexed_at": r.get("last_reindexed_at"),
                    "in_progress": r.get("in_progress", False),
                }
                for r in repos
            ],
        }
    except Exception as e:
        return {
            "ok": False,
            "version": "0.1.0-mvp",
            "error": str(e),
            "indexed_repos_count": 0,
            "total_symbols": 0,
            "last_indexed_at": None,
        }


def cmd_status(args: argparse.Namespace) -> int:
    """Print index freshness/status as JSON."""
    storage = args.storage or None
    status = get_status_data(storage, stale_threshold_minutes=args.stale_threshold_minutes)
    print(json.dumps(status, indent=2))
    return 0 if status.get("ok") else 1


def cmd_index_repos(args: argparse.Namespace) -> int:
    """Index multiple GitHub repositories in one run."""
    storage = args.storage or None
    ai = not args.no_ai
    incremental = args.incremental
    allowlist, deny_by_default = _effective_repo_allowlist(args.config)

    results = []
    failed = 0
    for repo in args.repos:
        result = asyncio.run(
            index_repo(
                url=repo,
                use_ai_summaries=ai,
                storage_path=storage,
                incremental=incremental,
                allowlist=allowlist,
                deny_by_default=deny_by_default,
            )
        )
        results.append(result)
        if result.get("success"):
            print(f"✓ {repo}: indexed ({result.get('symbol_count', '?')} symbols)")
        else:
            failed += 1
            print(f"✗ {repo}: {result.get('error', 'unknown error')}", file=sys.stderr)

    summary = {
        "total": len(results),
        "succeeded": len(results) - failed,
        "failed": failed,
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    return 0 if failed == 0 else 1


def cmd_repos_list(args: argparse.Namespace) -> int:
    cfg = load_repos_config(args.config)
    print(f"Config: {cfg.path}")
    if not cfg.exists:
        print("  (file does not exist yet)")
        return 0
    if not cfg.repos:
        print("  (no repositories configured)")
        return 0
    for entry in cfg.repos:
        suffix = f" ({entry.name})" if entry.name else ""
        print(f"  - {entry.repo}{suffix}")
    return 0


def cmd_repos_add(args: argparse.Namespace) -> int:
    path, added = add_repo(args.repo, args.config)
    if added:
        print(f"Added {args.repo} to allowlist: {path}")
    else:
        print(f"Repo already in allowlist: {args.repo} ({path})")
    return 0


def cmd_repos_remove(args: argparse.Namespace) -> int:
    path, removed = remove_repo(args.repo, args.config)
    if removed:
        print(f"Removed {args.repo} from allowlist: {path}")
        return 0
    print(f"Repo not present in allowlist: {args.repo} ({path})")
    return 1


def cmd_reindex(args: argparse.Namespace) -> int:
    allowlist, deny_by_default = _effective_repo_allowlist(args.config)
    repo_name = args.repo.lower()
    if not is_repo_allowed(repo_name, allowlist, deny_by_default=deny_by_default):
        print(
            json.dumps(
                {
                    "accepted": False,
                    "repo": repo_name,
                    "reason": "repo_not_allowed",
                    "error": f"Repository not authorized for indexing: {repo_name}",
                },
                indent=2,
            )
        )
        return 1

    manager = ReindexManager(
        storage_path=args.storage or None,
        allowlist=allowlist,
        deny_by_default=deny_by_default,
        min_interval_seconds=60,
    )
    result = manager.schedule_reindex(repo_name, reason="manual_cli")
    print(json.dumps(result, indent=2))
    return 0 if result.get("accepted") else 1


def cmd_serve(args: argparse.Namespace) -> int:
    """Start HTTP health endpoint server."""
    from .health_server import run_health_server

    port = args.port
    host = args.host
    storage = args.storage or None
    health_token = args.health_token or get_health_token()
    webhook_secret = args.webhook_secret or get_webhook_secret()
    allowlist, deny_by_default = _effective_repo_allowlist(args.repos_config)
    stale_threshold_minutes = args.stale_threshold_minutes
    print(f"Starting ArgentMunch health server on {host}:{port}...")
    run_health_server(
        host=host,
        port=port,
        storage_path=storage,
        health_token=health_token,
        webhook_secret=webhook_secret,
        repo_allowlist=allowlist,
        stale_threshold_minutes=stale_threshold_minutes,
        deny_by_default_allowlist=deny_by_default,
    )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="argentmunch",
        description="ArgentMunch — Token-efficient code indexing and retrieval",
    )
    parser.add_argument("--storage", "-s", help="Custom storage path (default: ~/.code-index/)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # index
    p_index = subparsers.add_parser("index", help="Index a local folder or repos from config")
    p_index.add_argument("path", nargs="?", help="Path to local folder")
    p_index.add_argument("--config", help="repos.yaml file for multi-repo GitHub indexing")
    p_index.add_argument("--no-ai", action="store_true", help="Skip AI summaries")
    p_index.add_argument("--incremental", "-i", action="store_true", help="Only re-index changed files")
    p_index.set_defaults(func=cmd_index)

    # index-repos (legacy)
    p_index_repos = subparsers.add_parser("index-repos", help="Index multiple GitHub repos")
    p_index_repos.add_argument("repos", nargs="+", help="Repo URLs or owner/repo identifiers")
    p_index_repos.add_argument("--config", help="Optional repos.yaml to enforce allowlist")
    p_index_repos.add_argument("--no-ai", action="store_true", help="Skip AI summaries")
    p_index_repos.add_argument("--incremental", "-i", action="store_true", help="Only re-index changed files")
    p_index_repos.set_defaults(func=cmd_index_repos)

    # query
    p_query = subparsers.add_parser("query", help="Search symbols in one repo or across all repos")
    p_query.add_argument("repo_or_query", help="Repo name (or query when --all)")
    p_query.add_argument("query", nargs="?", help="Search query")
    p_query.add_argument("--all", action="store_true", help="Search across all indexed repos")
    p_query.add_argument("--kind", "-k", choices=["function", "class", "method", "constant", "type"], help="Filter by symbol kind")
    p_query.add_argument("--max-results", "-n", type=int, default=10, help="Max results (default: 10)")
    p_query.set_defaults(func=cmd_query)

    # list
    p_list = subparsers.add_parser("list", help="List indexed repositories")
    p_list.set_defaults(func=cmd_list)

    # repos allowlist
    p_repos = subparsers.add_parser("repos", help="Manage repos allowlist config")
    p_repos.add_argument("--config", help="repos.yaml path (default ~/.argentmunch/repos.yaml)")
    repos_sub = p_repos.add_subparsers(dest="repos_cmd", required=True)

    p_repos_list = repos_sub.add_parser("list", help="List configured allowlisted repos")
    p_repos_list.set_defaults(func=cmd_repos_list)

    p_repos_add = repos_sub.add_parser("add", help="Add repo to allowlist")
    p_repos_add.add_argument("repo", help="Repo identifier (owner/repo)")
    p_repos_add.set_defaults(func=cmd_repos_add)

    p_repos_remove = repos_sub.add_parser("remove", help="Remove repo from allowlist")
    p_repos_remove.add_argument("repo", help="Repo identifier (owner/repo)")
    p_repos_remove.set_defaults(func=cmd_repos_remove)

    # reindex
    p_reindex = subparsers.add_parser("reindex", help="Trigger async incremental reindex for one repo")
    p_reindex.add_argument("repo", help="Repo identifier (owner/repo)")
    p_reindex.add_argument("--config", help="Optional repos.yaml for strict allowlist enforcement")
    p_reindex.set_defaults(func=cmd_reindex)

    # health
    p_health = subparsers.add_parser("health", help="Show health status (JSON)")
    p_health.set_defaults(func=cmd_health)

    # status
    p_status = subparsers.add_parser("status", help="Show index freshness status (JSON)")
    p_status.add_argument(
        "--stale-threshold-minutes",
        type=int,
        default=int(os.environ.get("ARGENTMUNCH_STALE_THRESHOLD_MINUTES", "60")),
        help="Stale threshold in minutes (default: ARGENTMUNCH_STALE_THRESHOLD_MINUTES or 60)",
    )
    p_status.set_defaults(func=cmd_status)

    # serve
    p_serve = subparsers.add_parser("serve", help="Start HTTP health endpoint")
    p_serve.add_argument("--host", default=os.environ.get("ARGENTMUNCH_HEALTH_HOST", "127.0.0.1"), help="Bind host (default: ARGENTMUNCH_HEALTH_HOST or 127.0.0.1)")
    p_serve.add_argument("--port", "-p", type=int, default=9120, help="Port (default: 9120)")
    p_serve.add_argument("--repos-config", default=None, help="repos.yaml path (default ~/.argentmunch/repos.yaml)")
    p_serve.add_argument("--health-token", default=None, help="Health/status auth token (default: ARGENTMUNCH_HEALTH_TOKEN)")
    p_serve.add_argument("--webhook-secret", default=None, help="GitHub webhook secret (default: ARGENTMUNCH_WEBHOOK_SECRET)")
    p_serve.add_argument(
        "--stale-threshold-minutes",
        type=int,
        default=int(os.environ.get("ARGENTMUNCH_STALE_THRESHOLD_MINUTES", "60")),
        help="Stale threshold in minutes for /status (default env or 60)",
    )
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
