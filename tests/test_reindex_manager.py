"""Tests for webhook/manual reindex scheduling behavior."""

from __future__ import annotations

import asyncio
import time

import jcodemunch_mcp.reindex_manager as rm


def test_reindex_manager_rate_limits_per_repo(monkeypatch, tmp_path):
    async def _fake_index_repo(**kwargs):
        await asyncio.sleep(0.01)
        return {"success": True, "repo": kwargs["url"], "indexed_at": "2026-03-05T00:00:00+00:00"}

    monkeypatch.setattr(rm, "index_repo", _fake_index_repo)

    manager = rm.ReindexManager(
        storage_path=str(tmp_path / "store"),
        allowlist=["argentaios/argentos"],
        deny_by_default=True,
        min_interval_seconds=60,
    )

    first = manager.schedule_reindex("argentaios/argentos", reason="webhook_push")
    assert first["accepted"] is True

    deadline = time.time() + 2.0
    while time.time() < deadline:
        status = manager.get_status("argentaios/argentos")
        if not status["in_progress"]:
            break
        time.sleep(0.01)

    second = manager.schedule_reindex("argentaios/argentos", reason="webhook_push")
    assert second["accepted"] is False
    assert second["reason"] == "rate_limited"
