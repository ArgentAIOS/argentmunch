"""Tests for repos.yaml allowlist config handling."""

from __future__ import annotations

from pathlib import Path

from jcodemunch_mcp.repos_config import add_repo, load_repos_config, remove_repo


def test_load_repos_config_parses_repo_list(tmp_path: Path):
    config = tmp_path / "repos.yaml"
    config.write_text(
        "repos:\n"
        "  - argentaios/argentos\n"
        "  - repo: argentaios/argentmunch\n",
        encoding="utf-8",
    )

    loaded = load_repos_config(str(config))
    assert loaded.exists is True
    assert loaded.allowlist == ["argentaios/argentos", "argentaios/argentmunch"]


def test_load_repos_config_parses_optional_name(tmp_path: Path):
    config = tmp_path / "repos.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: argentaios/argentos\n"
        "    name: core\n",
        encoding="utf-8",
    )
    loaded = load_repos_config(str(config))
    assert loaded.repos[0].name == "core"


def test_add_and_remove_repo(tmp_path: Path):
    config = tmp_path / "repos.yaml"

    path, added = add_repo("ArgentAIOS/ArgentOS", str(config))
    assert added is True
    assert path == config

    loaded = load_repos_config(str(config))
    assert loaded.allowlist == ["argentaios/argentos"]

    _, added_again = add_repo("argentaios/argentos", str(config))
    assert added_again is False

    _, removed = remove_repo("argentaios/argentos", str(config))
    assert removed is True

    loaded = load_repos_config(str(config))
    assert loaded.allowlist == []
