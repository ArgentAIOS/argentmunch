"""Tests for ArgentMunch MVP — CLI index, query, health endpoint."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jcodemunch_mcp.cli import main as cli_main, get_health_data
from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.tools.search_symbols import search_symbols
from jcodemunch_mcp.storage import IndexStore


# --- Fixtures ---

@pytest.fixture
def tmp_storage(tmp_path):
    """Temporary storage directory."""
    return str(tmp_path / "storage")


@pytest.fixture
def sample_project(tmp_path):
    """Create a minimal Python project to index."""
    project_dir = tmp_path / "sample_project"
    project_dir.mkdir()

    # Create a Python file with known symbols
    (project_dir / "calculator.py").write_text('''
"""Calculator module."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


class Calculator:
    """A simple calculator."""

    def __init__(self):
        self.history = []

    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        result = a * b
        self.history.append(result)
        return result

    def divide(self, a: int, b: int) -> float:
        """Divide a by b."""
        if b == 0:
            raise ValueError("Cannot divide by zero")
        result = a / b
        self.history.append(result)
        return result
''')

    (project_dir / "utils.py").write_text('''
"""Utility functions."""


def format_number(n: float, decimals: int = 2) -> str:
    """Format a number to string with given decimal places."""
    return f"{n:.{decimals}f}"


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(value, max_val))
''')

    return str(project_dir)


# --- Index Command Tests ---

class TestIndexCommand:
    """Tests for the index command."""

    def test_index_success(self, sample_project, tmp_storage):
        """Index a valid project successfully."""
        result = index_folder(
            path=sample_project,
            use_ai_summaries=False,
            storage_path=tmp_storage,
        )
        assert result["success"] is True
        assert result["symbol_count"] > 0
        assert result["file_count"] == 2
        assert "python" in result["languages"]

    def test_index_invalid_path(self, tmp_storage):
        """Index a non-existent path returns error."""
        result = index_folder(
            path="/nonexistent/path/to/nowhere",
            use_ai_summaries=False,
            storage_path=tmp_storage,
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower() or "error" in result.get("error", "").lower()

    def test_index_empty_folder(self, tmp_path, tmp_storage):
        """Index a folder with no source files returns error."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        (empty_dir / "readme.txt").write_text("not a source file")

        result = index_folder(
            path=str(empty_dir),
            use_ai_summaries=False,
            storage_path=tmp_storage,
        )
        assert result["success"] is False

    def test_index_cli_entrypoint(self, sample_project, tmp_storage):
        """CLI index command works."""
        exit_code = cli_main(["--storage", tmp_storage, "index", sample_project, "--no-ai"])
        assert exit_code == 0

    def test_index_incremental(self, sample_project, tmp_storage):
        """Incremental indexing after initial index."""
        # First full index
        result1 = index_folder(
            path=sample_project,
            use_ai_summaries=False,
            storage_path=tmp_storage,
        )
        assert result1["success"] is True

        # Second incremental (no changes)
        result2 = index_folder(
            path=sample_project,
            use_ai_summaries=False,
            storage_path=tmp_storage,
            incremental=True,
        )
        assert result2["success"] is True
        assert result2.get("message") == "No changes detected"


# --- Query Command Tests ---

class TestQueryCommand:
    """Tests for the query command."""

    @pytest.fixture(autouse=True)
    def _index_sample(self, sample_project, tmp_storage):
        """Index sample project before query tests."""
        self.storage = tmp_storage
        result = index_folder(
            path=sample_project,
            use_ai_summaries=False,
            storage_path=tmp_storage,
        )
        assert result["success"] is True
        self.repo = result["repo"]

    def test_query_hit(self):
        """Search finds known symbols."""
        result = search_symbols(
            repo=self.repo,
            query="add",
            storage_path=self.storage,
        )
        assert "error" not in result
        assert result["result_count"] > 0
        names = [r["name"] for r in result["results"]]
        assert "add" in names

    def test_query_miss(self):
        """Search for nonexistent symbol returns empty."""
        result = search_symbols(
            repo=self.repo,
            query="zzz_nonexistent_symbol_xyz",
            storage_path=self.storage,
        )
        assert "error" not in result
        assert result["result_count"] == 0

    def test_query_kind_filter(self):
        """Filter by kind works."""
        result = search_symbols(
            repo=self.repo,
            query="Calculator",
            kind="class",
            storage_path=self.storage,
        )
        assert result["result_count"] > 0
        for r in result["results"]:
            assert r["kind"] == "class"

    def test_query_class_methods(self):
        """Can find class methods."""
        result = search_symbols(
            repo=self.repo,
            query="multiply",
            storage_path=self.storage,
        )
        assert result["result_count"] > 0
        names = [r["name"] for r in result["results"]]
        assert "multiply" in names

    def test_query_nonexistent_repo(self):
        """Query against non-indexed repo returns error."""
        result = search_symbols(
            repo="local/fake_repo_not_indexed",
            query="anything",
            storage_path=self.storage,
        )
        assert "error" in result


# --- Health Endpoint Tests ---

class TestHealthEndpoint:
    """Tests for health check functionality."""

    def test_health_no_repos(self, tmp_storage):
        """Health with no indexed repos returns ok=True."""
        health = get_health_data(tmp_storage)
        assert health["ok"] is True
        assert health["indexed_repos_count"] == 0
        assert health["total_symbols"] == 0
        assert health["version"] == "0.1.0-mvp"

    def test_health_with_repos(self, sample_project, tmp_storage):
        """Health after indexing shows repo count and symbols."""
        index_folder(
            path=sample_project,
            use_ai_summaries=False,
            storage_path=tmp_storage,
        )
        health = get_health_data(tmp_storage)
        assert health["ok"] is True
        assert health["indexed_repos_count"] == 1
        assert health["total_symbols"] > 0
        assert health["last_indexed_at"] is not None

    def test_health_http_endpoint(self, sample_project, tmp_storage):
        """HTTP /health endpoint returns valid JSON."""
        # Index something first
        index_folder(
            path=sample_project,
            use_ai_summaries=False,
            storage_path=tmp_storage,
        )

        # Start server in background
        from jcodemunch_mcp.health_server import run_health_server
        import jcodemunch_mcp.health_server as hs
        hs._storage_path = tmp_storage
        hs._health_token = None
        hs._health_local_dev_mode = True

        from http.server import HTTPServer
        server = HTTPServer(("127.0.0.1", 0), hs.HealthHandler)
        port = server.server_address[1]

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            time.sleep(0.3)  # Let server start
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/health")
            response = conn.getresponse()
            body = response.read()

            assert response.status == 200
            data = json.loads(body)
            assert data["ok"] is True
            assert data["indexed_repos_count"] == 1
            assert data["total_symbols"] > 0

            # Test 404
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/notfound")
            response = conn.getresponse()
            assert response.status == 404
        finally:
            server.shutdown()

    def test_health_unhealthy_corrupt(self, tmp_storage):
        """Health reports ok even with no data (empty is valid)."""
        # Create storage dir with a corrupt index file
        os.makedirs(tmp_storage, exist_ok=True)
        corrupt_path = os.path.join(tmp_storage, "bad-repo.json")
        with open(corrupt_path, "w") as f:
            f.write("{invalid json")

        health = get_health_data(tmp_storage)
        # Should still be ok, corrupt files are skipped
        assert health["ok"] is True


# --- CLI Integration Tests ---

class TestCLIIntegration:
    """End-to-end CLI tests."""

    def test_cli_help(self):
        """CLI --help exits cleanly."""
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--help"])
        assert exc_info.value.code == 0

    def test_cli_list_empty(self, tmp_storage):
        """List with no repos shows empty."""
        exit_code = cli_main(["--storage", tmp_storage, "list"])
        assert exit_code == 0

    def test_cli_full_workflow(self, sample_project, tmp_storage):
        """Full workflow: index -> list -> query -> health."""
        # Index
        ec = cli_main(["--storage", tmp_storage, "index", sample_project, "--no-ai"])
        assert ec == 0

        # List
        ec = cli_main(["--storage", tmp_storage, "list"])
        assert ec == 0

        # Query
        ec = cli_main(["--storage", tmp_storage, "query", "local/sample_project", "add"])
        assert ec == 0

        # Health
        ec = cli_main(["--storage", tmp_storage, "health"])
        assert ec == 0
