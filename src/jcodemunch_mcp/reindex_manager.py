"""Async reindex queue with per-repo rate limiting and status tracking."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .tools.index_repo import index_repo


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReindexManager:
    """Background reindex coordinator."""

    def __init__(
        self,
        *,
        storage_path: Optional[str] = None,
        allowlist: Optional[list[str]] = None,
        deny_by_default: bool = False,
        min_interval_seconds: int = 60,
    ):
        self.storage_path = storage_path
        self.allowlist = allowlist or []
        self.deny_by_default = deny_by_default
        self.min_interval_seconds = max(1, min_interval_seconds)
        self._lock = threading.Lock()
        self._last_trigger_ts: dict[str, float] = {}
        self._status: dict[str, dict] = {}
        self._status_path = self._resolve_status_path(storage_path)
        self._load_status()

    @staticmethod
    def _resolve_status_path(storage_path: Optional[str]) -> Path:
        base = Path(storage_path).expanduser().resolve() if storage_path else (Path.home() / ".code-index")
        base.mkdir(parents=True, exist_ok=True)
        return base / "reindex-status.json"

    def _load_status(self) -> None:
        if not self._status_path.exists():
            return
        try:
            data = json.loads(self._status_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._status = data
        except Exception:
            self._status = {}

    def _persist_status(self) -> None:
        tmp = self._status_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._status, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._status_path)

    def get_status(self, repo: str) -> dict:
        """Get tracked status for a repo."""
        with self._lock:
            item = dict(self._status.get(repo, {}))
            item.setdefault("repo", repo)
            item.setdefault("in_progress", False)
            item.setdefault("last_reindexed_at", None)
            item.setdefault("last_success_at", None)
            item.setdefault("last_failure_at", None)
            item.setdefault("last_error", None)
            return item

    def get_all_status(self) -> dict[str, dict]:
        """Get statuses for all known repos."""
        with self._lock:
            return {k: dict(v) for k, v in self._status.items()}

    def schedule_reindex(self, repo: str, reason: str = "manual") -> dict:
        """Schedule background reindex if allowed by rate-limit/in-progress guards."""
        now_ts = time.time()
        now_iso = _utc_now_iso()

        with self._lock:
            status = self._status.setdefault(
                repo,
                {
                    "repo": repo,
                    "in_progress": False,
                    "last_reindexed_at": None,
                    "last_success_at": None,
                    "last_failure_at": None,
                    "last_error": None,
                    "last_reason": None,
                },
            )

            if status.get("in_progress"):
                return {"accepted": False, "reason": "in_progress", "repo": repo}

            last_ts = self._last_trigger_ts.get(repo)
            if last_ts is not None:
                age = now_ts - last_ts
                if age < self.min_interval_seconds:
                    retry_after = int(self.min_interval_seconds - age)
                    return {
                        "accepted": False,
                        "reason": "rate_limited",
                        "repo": repo,
                        "retry_after_seconds": max(1, retry_after),
                    }

            self._last_trigger_ts[repo] = now_ts
            status["in_progress"] = True
            status["last_reason"] = reason
            status["last_queued_at"] = now_iso
            self._persist_status()

        thread = threading.Thread(target=self._run_reindex, args=(repo,), daemon=True)
        thread.start()
        return {"accepted": True, "reason": "scheduled", "repo": repo}

    def _run_reindex(self, repo: str) -> None:
        now_iso = _utc_now_iso()
        try:
            result = asyncio.run(
                index_repo(
                    url=repo,
                    use_ai_summaries=False,
                    storage_path=self.storage_path,
                    incremental=True,
                    allowlist=self.allowlist,
                    deny_by_default=self.deny_by_default,
                )
            )
        except Exception as e:
            result = {"success": False, "error": str(e)}

        with self._lock:
            status = self._status.setdefault(repo, {"repo": repo})
            status["in_progress"] = False
            status["last_result"] = result
            if result.get("success"):
                indexed_at = result.get("indexed_at") or now_iso
                status["last_reindexed_at"] = indexed_at
                status["last_success_at"] = indexed_at
                status["last_error"] = None
            else:
                status["last_failure_at"] = now_iso
                status["last_error"] = result.get("error") or "unknown_error"
            self._persist_status()


def attach_reindex_status(repos: list[dict], storage_path: Optional[str] = None) -> list[dict]:
    """Merge persisted reindex status into repo list output."""
    status_path = ReindexManager._resolve_status_path(storage_path)
    try:
        raw = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    except Exception:
        raw = {}

    merged: list[dict] = []
    for repo in repos:
        repo_name = repo.get("repo", "")
        st = raw.get(repo_name, {}) if isinstance(raw, dict) else {}
        item = dict(repo)
        item["in_progress"] = bool(st.get("in_progress", False))
        item["last_success_at"] = st.get("last_success_at")
        item["last_failure_at"] = st.get("last_failure_at")
        item["last_error"] = st.get("last_error")
        item["last_reindexed_at"] = st.get("last_reindexed_at") or repo.get("indexed_at")
        merged.append(item)
    return merged
