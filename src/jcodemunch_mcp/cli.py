"""ArgentMunch CLI - standalone commands for indexing, querying, and health."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .tools.index_folder import index_folder
from .tools.search_symbols import search_symbols
from .tools.list_repos import list_repos
from .storage import IndexStore


def cmd_index(args: argparse.Namespace) -> int:
    """Index a local repository path."""
    path = args.path
    storage = args.storage or None
    ai = not args.no_ai
    incremental = args.incremental

    print(f"Indexing: {path}")
    print(f"  AI summaries: {ai}")
    print(f"  Incremental: {incremental}")
    if storage:
        print(f"  Storage: {storage}")

    result = index_folder(
        path=path,
        use_ai_summaries=ai,
        storage_path=storage,
        incremental=incremental,
    )

    if not result.get("success"):
        print(f"\n✗ Error: {result.get('error', 'unknown')}", file=sys.stderr)
        return 1

    print(f"\n✓ Indexed {result.get('file_count', '?')} files, "
          f"{result.get('symbol_count', '?')} symbols")
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


def cmd_query(args: argparse.Namespace) -> int:
    """Query symbols in an indexed repo."""
    repo = args.repo
    query = args.query
    storage = args.storage or None
    kind = args.kind
    max_results = args.max_results

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

    print(f"Search: '{query}' in {result.get('repo', '?')}")
    print(f"Found: {count} results ({meta.get('timing_ms', '?')}ms)")
    print()

    if not results:
        print("  No matching symbols found.")
        return 0

    for i, sym in enumerate(results, 1):
        print(f"  {i}. [{sym['kind']}] {sym['name']}")
        print(f"     File: {sym['file']}:{sym.get('line', '?')}")
        sig = sym.get("signature", "")
        if sig:
            # Truncate long signatures
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

    if meta.get("tokens_saved"):
        print(f"  Token savings: ~{meta['tokens_saved']:,} tokens this query")

    if args.json:
        print(f"\n{json.dumps(result, indent=2)}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List indexed repos."""
    storage = args.storage or None
    result = list_repos(storage_path=storage)

    repos = result.get("repos", [])
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
        print()

    if args.json:
        print(f"\n{json.dumps(result, indent=2)}")

    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Print health status as JSON (also available via HTTP endpoint)."""
    storage = args.storage or None
    health = get_health_data(storage)
    print(json.dumps(health, indent=2))
    return 0 if health.get("ok") else 1


def get_health_data(storage_path: Optional[str] = None) -> dict:
    """Generate health check data."""
    try:
        store = IndexStore(base_path=storage_path)
        repos = store.list_repos()

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


def cmd_serve(args: argparse.Namespace) -> int:
    """Start HTTP health endpoint server."""
    from .health_server import run_health_server
    port = args.port
    storage = args.storage or None
    print(f"Starting ArgentMunch health server on port {port}...")
    run_health_server(port=port, storage_path=storage)
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
    p_index = subparsers.add_parser("index", help="Index a local repo/folder")
    p_index.add_argument("path", help="Path to local folder")
    p_index.add_argument("--no-ai", action="store_true", help="Skip AI summaries")
    p_index.add_argument("--incremental", "-i", action="store_true",
                         help="Only re-index changed files")
    p_index.set_defaults(func=cmd_index)

    # query
    p_query = subparsers.add_parser("query", help="Search symbols in an indexed repo")
    p_query.add_argument("repo", help="Repository name (e.g., 'local/myrepo')")
    p_query.add_argument("query", help="Search query")
    p_query.add_argument("--kind", "-k", choices=["function", "class", "method", "constant", "type"],
                         help="Filter by symbol kind")
    p_query.add_argument("--max-results", "-n", type=int, default=10,
                         help="Max results (default: 10)")
    p_query.set_defaults(func=cmd_query)

    # list
    p_list = subparsers.add_parser("list", help="List indexed repositories")
    p_list.set_defaults(func=cmd_list)

    # health
    p_health = subparsers.add_parser("health", help="Show health status (JSON)")
    p_health.set_defaults(func=cmd_health)

    # serve
    p_serve = subparsers.add_parser("serve", help="Start HTTP health endpoint")
    p_serve.add_argument("--port", "-p", type=int, default=9120,
                         help="Port (default: 9120)")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
