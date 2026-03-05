"""Phase 2 reliability tests: allowlist, webhook auth, and reindex triggers."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection

import pytest

import jcodemunch_mcp.cli as cli
import jcodemunch_mcp.health_server as hs
from jcodemunch_mcp.runtime_config import is_repo_allowed


class _FakeManager:
    def __init__(self, accepted: bool = True, reason: str = "scheduled"):
        self.accepted = accepted
        self.reason = reason
        self.calls: list[tuple[str, str]] = []

    def schedule_reindex(self, repo: str, reason: str = "manual") -> dict:
        self.calls.append((repo, reason))
        payload = {"accepted": self.accepted, "reason": self.reason, "repo": repo}
        if self.reason == "rate_limited":
            payload["retry_after_seconds"] = 42
        return payload

    def get_status(self, repo: str) -> dict:
        return {
            "repo": repo,
            "in_progress": self.accepted,
            "last_reindexed_at": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
        }


def _start_server(
    *,
    health_token: str | None = None,
    webhook_secret: str | None = None,
    repo_allowlist: list[str] | None = None,
    deny_by_default_allowlist: bool = False,
    manager: _FakeManager | None = None,
):
    from http.server import HTTPServer

    hs._storage_path = None
    hs._health_token = health_token
    hs._health_local_dev_mode = False
    hs._webhook_secret = webhook_secret
    hs._repo_allowlist = repo_allowlist or []
    hs._stale_threshold_minutes = 60
    hs._deny_by_default_allowlist = deny_by_default_allowlist
    hs._reindex_manager = manager
    server = HTTPServer(("127.0.0.1", 0), hs.HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _post_json(port: int, path: str, payload: dict, headers: dict[str, str]) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    final_headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    final_headers.update(headers)
    conn.request("POST", path, body=body, headers=final_headers)
    response = conn.getresponse()
    content = json.loads(response.read())
    conn.close()
    return response.status, content


def test_allowlist_strict_accept_and_reject():
    allowlist = ["argentaios/argentos"]
    assert is_repo_allowed("argentaios/argentos", allowlist, deny_by_default=True) is True
    assert is_repo_allowed("other/repo", allowlist, deny_by_default=True) is False


def test_health_endpoint_requires_token_when_configured():
    server = _start_server(health_token="secret-token")
    port = server.server_address[1]

    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/health")
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 401
        assert body["error"] == "Unauthorized"
        assert body["reason"] == "missing_token"

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/health", headers={"Authorization": "Bearer wrong-token"})
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 401
        assert body["reason"] == "invalid_token"

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/status", headers={"Authorization": "Bearer secret-token"})
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 200
        assert body["threshold_config_used"]["stale_threshold_minutes"] == 60
        assert body["indexed_repos_count"] == 0
        assert body["total_symbols"] == 0
        assert body["last_indexed_at"] is None
        assert body["stale"] is False
    finally:
        server.shutdown()


def test_health_endpoint_requires_token_by_default_without_local_dev_override():
    server = _start_server()
    port = server.server_address[1]
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/health")
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 401
        assert body["reason"] == "token_required"
    finally:
        server.shutdown()


def test_health_endpoint_allows_localhost_when_local_dev_mode_enabled():
    from http.server import HTTPServer

    hs._storage_path = None
    hs._health_token = None
    hs._health_local_dev_mode = True
    hs._webhook_secret = None
    hs._repo_allowlist = []
    hs._stale_threshold_minutes = 60
    hs._deny_by_default_allowlist = False
    hs._reindex_manager = _FakeManager()
    server = HTTPServer(("127.0.0.1", 0), hs.HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/health")
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 200
        assert body["ok"] is True
    finally:
        server.shutdown()


def test_status_staleness_threshold_computation(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=120)).isoformat()
    fresh = (now - timedelta(minutes=10)).isoformat()

    def _fake_health_data(_storage_path=None):
        return {
            "ok": True,
            "version": "0.1.0-mvp",
            "indexed_repos_count": 2,
            "total_symbols": 30,
            "last_indexed_at": fresh,
            "repos": [
                {"repo": "local/stale", "symbol_count": 10, "file_count": 2, "indexed_at": old},
                {"repo": "local/fresh", "symbol_count": 20, "file_count": 3, "indexed_at": fresh},
            ],
        }

    monkeypatch.setattr(cli, "get_health_data", _fake_health_data)
    status = cli.get_status_data(stale_threshold_minutes=60)
    assert status["indexed_repos_count"] == 2
    assert status["total_symbols"] == 30
    assert status["last_indexed_at"] == fresh
    assert status["stale"] is True
    assert status["threshold_config_used"]["stale_threshold_minutes"] == 60
    assert status["stale_repos_count"] == 1

    status_relaxed = cli.get_status_data(stale_threshold_minutes=180)
    assert status_relaxed["stale"] is False
    assert status_relaxed["stale_repos_count"] == 0


def test_webhook_rejects_invalid_signature_with_403():
    server = _start_server(webhook_secret="whsec-test", manager=_FakeManager())
    port = server.server_address[1]
    payload = {"repository": {"full_name": "argentaios/argentos"}}

    try:
        status, body = _post_json(
            port,
            "/webhook",
            payload,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=bad",
            },
        )
        assert status == 403
        assert body["error"] == "Invalid webhook signature"
    finally:
        server.shutdown()


def test_webhook_requires_allowlisted_repo():
    manager = _FakeManager()
    server = _start_server(
        webhook_secret="whsec-test",
        repo_allowlist=["argentaios/argentos"],
        deny_by_default_allowlist=True,
        manager=manager,
    )
    port = server.server_address[1]
    payload = {"repository": {"full_name": "other/repo"}}
    digest = hmac.new(b"whsec-test", json.dumps(payload).encode("utf-8"), hashlib.sha256).hexdigest()

    try:
        status, body = _post_json(
            port,
            "/webhook",
            payload,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": f"sha256={digest}",
            },
        )
        assert status == 403
        assert body["reason"] == "repo_not_allowed"
        assert manager.calls == []
    finally:
        server.shutdown()


def test_webhook_triggers_async_reindex_and_returns_202():
    manager = _FakeManager(accepted=True, reason="scheduled")
    server = _start_server(
        webhook_secret="whsec-test",
        repo_allowlist=["argentaios/argentos"],
        deny_by_default_allowlist=True,
        manager=manager,
    )
    port = server.server_address[1]
    payload = {"repository": {"full_name": "argentaios/argentos"}}
    digest = hmac.new(b"whsec-test", json.dumps(payload).encode("utf-8"), hashlib.sha256).hexdigest()

    try:
        status, body = _post_json(
            port,
            "/webhook",
            payload,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": f"sha256={digest}",
            },
        )
        assert status == 202
        assert body["accepted"] is True
        assert body["reason"] == "scheduled"
        assert manager.calls == [("argentaios/argentos", "webhook_push")]
    finally:
        server.shutdown()


def test_webhook_rate_limit_response_is_safe():
    manager = _FakeManager(accepted=False, reason="rate_limited")
    server = _start_server(
        webhook_secret="whsec-test",
        repo_allowlist=["argentaios/argentos"],
        deny_by_default_allowlist=True,
        manager=manager,
    )
    port = server.server_address[1]
    payload = {"repository": {"full_name": "argentaios/argentos"}}
    digest = hmac.new(b"whsec-test", json.dumps(payload).encode("utf-8"), hashlib.sha256).hexdigest()

    try:
        status, body = _post_json(
            port,
            "/webhook",
            payload,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": f"sha256={digest}",
            },
        )
        assert status == 202
        assert body["accepted"] is False
        assert body["reason"] == "rate_limited"
        assert body["retry_after_seconds"] == 42
    finally:
        server.shutdown()
