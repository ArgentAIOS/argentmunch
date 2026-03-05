"""Phase 2 reliability tests: allowlist, webhook auth, and reindex triggers."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from http.client import HTTPConnection

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
