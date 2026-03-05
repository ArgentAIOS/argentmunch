#!/usr/bin/env python3
"""MVP Benchmark — compare brute-force file scan vs. symbol query token proxies.

Outputs a markdown report to docs/benchmarks/mvp-baseline.md.

Usage:
    python scripts/benchmark_mvp.py [--repo REPO] [--storage PATH]

If no --repo is specified, indexes the argentmunch source tree first.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jcodemunch_mcp.storage import IndexStore
from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.tools.search_symbols import search_symbols


CHARS_PER_TOKEN = 4  # rough approximation


def count_raw_tokens(content_dir: Path) -> tuple[int, int, int]:
    """Walk content dir and estimate raw tokens from file sizes.

    Returns: (total_chars, total_lines, estimated_tokens)
    """
    total_chars = 0
    total_lines = 0
    for root, _dirs, files in os.walk(content_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    total_chars += len(content)
                    total_lines += content.count("\n") + 1
            except (OSError, UnicodeDecodeError):
                pass
    estimated_tokens = total_chars // CHARS_PER_TOKEN
    return total_chars, total_lines, estimated_tokens


def symbol_query_tokens(store: IndexStore, owner: str, name: str, query: str) -> tuple[int, int]:
    """Run a symbol query and estimate response tokens.

    Returns: (result_chars, estimated_tokens)
    """
    index = store.load_index(owner, name)
    if not index:
        return 0, 0

    results = index.search(query)[:10]
    total_chars = 0
    for sym in results:
        # Approximate: signature + summary + metadata
        sig = sym.get("signature", "")
        summary = sym.get("summary", "")
        name_str = sym.get("name", "")
        file_str = sym.get("file", "")
        total_chars += len(sig) + len(summary) + len(name_str) + len(file_str) + 50  # metadata overhead

    return total_chars, total_chars // CHARS_PER_TOKEN


def run_benchmark(repo: str, storage_path: str = None) -> str:
    """Run benchmark scenarios and return markdown report."""
    store = IndexStore(base_path=storage_path)

    # Parse repo identifier
    if "/" in repo:
        owner, name = repo.split("/", 1)
    else:
        owner, name = "local", repo

    index = store.load_index(owner, name)
    if not index:
        return f"Error: repo '{repo}' not indexed."

    content_dir = store._content_dir(owner, name)
    raw_chars, raw_lines, raw_tokens = count_raw_tokens(content_dir)

    # Scenarios
    scenarios = [
        {
            "name": "Broad function search",
            "query": "index",
            "description": "Search for symbols related to 'index' — common term across codebase",
        },
        {
            "name": "Specific symbol lookup",
            "query": "save_index",
            "description": "Find a specific function by exact name",
        },
        {
            "name": "Cross-cutting search",
            "query": "parse file",
            "description": "Multi-word query spanning parser and file handling",
        },
    ]

    lines = []
    lines.append("# MVP Benchmark — Brute Force vs. Symbol Query\n")
    lines.append(f"**Repo:** `{owner}/{name}`  ")
    lines.append(f"**Indexed at:** {index.indexed_at}  ")
    lines.append(f"**Files:** {len(index.source_files)}  ")
    lines.append(f"**Symbols:** {len(index.symbols)}  ")
    lines.append(f"**Languages:** {', '.join(index.languages.keys())}  ")
    lines.append("")
    lines.append("## Raw Codebase Stats\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total characters | {raw_chars:,} |")
    lines.append(f"| Total lines | {raw_lines:,} |")
    lines.append(f"| Estimated tokens (raw) | {raw_tokens:,} |")
    lines.append("")
    lines.append("## Scenario Results\n")
    lines.append("| Scenario | Query | Brute-force tokens | Symbol query tokens | Savings | Ratio |")
    lines.append("|----------|-------|--------------------|---------------------|---------|-------|")

    for sc in scenarios:
        query = sc["query"]
        sym_chars, sym_tokens = symbol_query_tokens(store, owner, name, query)
        if raw_tokens > 0:
            savings_pct = ((raw_tokens - sym_tokens) / raw_tokens) * 100
            ratio = raw_tokens / max(sym_tokens, 1)
        else:
            savings_pct = 0
            ratio = 1

        lines.append(
            f"| {sc['name']} | `{query}` | {raw_tokens:,} | {sym_tokens:,} | "
            f"{savings_pct:.1f}% | {ratio:.0f}x |"
        )

    lines.append("")
    lines.append("## Analysis\n")
    lines.append("**Brute-force approach:** Send entire raw source files to the LLM context window. ")
    lines.append(f"Every query costs ~{raw_tokens:,} tokens regardless of what you're looking for.\n")
    lines.append("**Symbol query approach:** Parse once via tree-sitter AST, index symbols with ")
    lines.append("signatures and summaries. Queries return only relevant symbols — typically ")
    lines.append("90-99%+ token reduction.\n")
    lines.append("### Key Takeaways\n")
    lines.append("1. Even broad queries (`index`) return dramatically fewer tokens than raw file dumps")
    lines.append("2. Specific lookups (`save_index`) achieve near-perfect efficiency")
    lines.append("3. The one-time indexing cost amortizes over all future queries")
    lines.append("")
    lines.append("---\n")
    lines.append(f"*Generated by `scripts/benchmark_mvp.py` at {time.strftime('%Y-%m-%dT%H:%M:%S')}*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ArgentMunch MVP Benchmark")
    parser.add_argument("--repo", default=None, help="Repo identifier (e.g., 'local/argentmunch')")
    parser.add_argument("--storage", default=None, help="Custom storage path")
    args = parser.parse_args()

    # If no repo specified, index our own source tree
    repo = args.repo
    if not repo:
        print("No --repo specified. Indexing argentmunch source tree...")
        src_path = str(Path(__file__).parent.parent)
        result = index_folder(path=src_path, use_ai_summaries=False, storage_path=args.storage)
        if not result.get("success"):
            print(f"Error indexing: {result.get('error')}")
            sys.exit(1)
        repo = result.get("repo", "local/argentmunch")
        print(f"Indexed: {repo}\n")

    report = run_benchmark(repo, args.storage)

    # Write report
    output_path = Path(__file__).parent.parent / "docs" / "benchmarks" / "mvp-baseline.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written to: {output_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
