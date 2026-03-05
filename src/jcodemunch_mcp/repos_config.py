"""Repo allowlist config helpers for multi-repo indexing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .runtime_config import default_repos_config_path


@dataclass
class RepoEntry:
    """One repo config entry."""

    repo: str
    name: str | None = None


@dataclass
class ReposConfig:
    """Loaded repos config."""

    path: Path
    repos: list[RepoEntry]
    exists: bool

    @property
    def allowlist(self) -> list[str]:
        return [entry.repo for entry in self.repos]


def _normalize_repo(value: str) -> str:
    repo = value.strip().strip("\"'").removesuffix(".git")
    if "github.com/" in repo:
        repo = repo.split("github.com/", 1)[1]
    repo = repo.strip("/")
    if repo.count("/") != 1:
        raise ValueError(f"Invalid repo identifier: {value!r}")
    return repo.lower()


def _parse_line_list(lines: list[str]) -> list[RepoEntry]:
    repos: list[RepoEntry] = []
    pending: RepoEntry | None = None

    def flush_pending() -> None:
        nonlocal pending
        if pending is not None:
            repos.append(pending)
            pending = None

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("repos:"):
            continue
        if line.startswith("name:") and pending is not None:
            pending.name = line.split(":", 1)[1].strip().strip("\"'")
            continue
        if not line.startswith("-"):
            continue
        flush_pending()
        value = line[1:].strip()
        name: str | None = None
        if value.startswith("repo:"):
            value = value.split(":", 1)[1].strip()
        elif "repo:" in value and "name:" in value:
            # Support inline form: - repo: owner/repo name: label
            chunks = value.split("name:", 1)
            value = chunks[0].split("repo:", 1)[1].strip()
            name = chunks[1].strip().strip("\"'")
        if not value:
            continue
        pending = RepoEntry(repo=_normalize_repo(value), name=name)

    flush_pending()
    return repos


def load_repos_config(path: str | None = None) -> ReposConfig:
    """Load repos.yaml from disk.

    Supports a minimal YAML shape:
    repos:
      - owner/repo
      - repo: owner/other
    """
    cfg_path = Path(path).expanduser().resolve() if path else default_repos_config_path()
    if not cfg_path.exists():
        return ReposConfig(path=cfg_path, repos=[], exists=False)

    content = cfg_path.read_text(encoding="utf-8", errors="replace")
    repos = _parse_line_list(content.splitlines())
    return ReposConfig(path=cfg_path, repos=repos, exists=True)


def save_repos_config(entries: list[RepoEntry], path: str | None = None) -> Path:
    """Write repos config in stable deterministic format."""
    cfg_path = Path(path).expanduser().resolve() if path else default_repos_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["repos:"]
    for entry in sorted(entries, key=lambda e: e.repo):
        if entry.name:
            lines.append(f"  - repo: {entry.repo}")
            lines.append(f"    name: {entry.name}")
        else:
            lines.append(f"  - {entry.repo}")
    lines.append("")
    cfg_path.write_text("\n".join(lines), encoding="utf-8")
    return cfg_path


def add_repo(repo: str, path: str | None = None) -> tuple[Path, bool]:
    """Add repo to config. Returns (path, added)."""
    cfg = load_repos_config(path)
    normalized = _normalize_repo(repo)
    existing = {entry.repo for entry in cfg.repos}
    if normalized in existing:
        return cfg.path, False
    cfg.repos.append(RepoEntry(repo=normalized))
    save_repos_config(cfg.repos, str(cfg.path))
    return cfg.path, True


def remove_repo(repo: str, path: str | None = None) -> tuple[Path, bool]:
    """Remove repo from config. Returns (path, removed)."""
    cfg = load_repos_config(path)
    normalized = _normalize_repo(repo)
    remaining = [entry for entry in cfg.repos if entry.repo != normalized]
    removed = len(remaining) != len(cfg.repos)
    save_repos_config(remaining, str(cfg.path))
    return cfg.path, removed
