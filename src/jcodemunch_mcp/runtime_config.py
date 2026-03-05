"""Runtime configuration helpers for reliability/security knobs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def parse_repo_allowlist(raw: Optional[str]) -> list[str]:
    """Parse comma-separated repo allowlist entries.

    Supported entries:
    - owner/repo
    - owner/*
    """
    if not raw:
        return []
    entries: list[str] = []
    for part in raw.split(","):
        item = part.strip()
        if item:
            entries.append(item)
    return entries


def get_repo_allowlist() -> list[str]:
    """Return configured repo allowlist from env."""
    return parse_repo_allowlist(os.environ.get("ARGENTMUNCH_REPO_ALLOWLIST"))


def default_repos_config_path() -> Path:
    """Default repos allowlist config location."""
    return Path.home() / ".argentmunch" / "repos.yaml"


def is_repo_allowed(
    repo: str,
    allowlist: Optional[list[str]] = None,
    *,
    deny_by_default: bool = False,
) -> bool:
    """Check if repo is allowed by configured allowlist.

    Empty allowlist means:
    - allow all when deny_by_default=False (backward compatibility),
    - deny all when deny_by_default=True.
    """
    if allowlist is None:
        allowlist = get_repo_allowlist()
    if not allowlist:
        return not deny_by_default
    if repo in allowlist:
        return True
    owner = repo.split("/", 1)[0] if "/" in repo else ""
    return bool(owner and f"{owner}/*" in allowlist)


def get_health_token() -> Optional[str]:
    """Health/status endpoint bearer token."""
    token = os.environ.get("ARGENTMUNCH_HEALTH_TOKEN")
    return token if token else None


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    """Parse common truthy/falsey env var values."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def get_health_local_dev_mode() -> bool:
    """Whether localhost calls can skip token auth (explicit opt-in)."""
    return parse_bool(os.environ.get("ARGENTMUNCH_HEALTH_LOCAL_DEV"), default=False)


def get_webhook_secret() -> Optional[str]:
    """GitHub webhook HMAC secret."""
    secret = os.environ.get("ARGENTMUNCH_WEBHOOK_SECRET")
    return secret if secret else None
