"""Phase 2 reliability tests: allowlist, webhook auth, and health auth."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from http.client import HTTPConnection

import pytest

import jcodemunch_mcp.health_server as hs
from jcodemunch_mcp.tools.index_repo import index_repo


@pytest.mark.asyncio
async def test_index_repo_rejects_repo_not_in_allowlist():
    result = await index_repo(
        url="octocat/hello-world",
        use_ai_summaries=False,
        allowlist=["argentaios/argentos"],
    )
    assert result["success"] is False
    assert result["reason"] == "repo_not_allowed"
    assert "not authorized" in result["error"].lower()


def _start_server(
    *,
    health_token: str | None = None,
    webhook_secret: str | None = None,
    repo_allowlist: list[str] | None = None,
):
    from http.server import HTTPServer

    hs._storage_path = None
    hs._health_token = health_token
    hs._webhook_secret = webhook_secret
    hs._repo_allowlist = repo_allowlist or []
    hs._stale_threshold_minutes = 60
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

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/status", headers={"Authorization": "Bearer secret-token"})
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 200
        assert "stale_threshold_minutes" in body
    finally:
        server.shutdown()


def test_webhook_rejects_invalid_signature():
    server = _start_server(webhook_secret="whsec-test")
    port = server.server_address[1]
    payload = {"repository": {"full_name": "argentaios/argentos"}}

    try:
        status, body = _post_json(
            port,
            "/webhook/github",
            payload,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=bad",
            },
        )
        assert status == 401
        assert body["error"] == "Invalid webhook signature"
    finally:
        server.shutdown()


def test_webhook_requires_allowlisted_repo(monkeypatch: pytest.MonkeyPatch):
    server = _start_server(webhook_secret="whsec-test", repo_allowlist=["argentaios/argentos"])
    port = server.server_address[1]
    payload = {"repository": {"full_name": "other/repo"}}
    digest = hmac.new(b"whsec-test", json.dumps(payload).encode("utf-8"), hashlib.sha256).hexdigest()

    async def _fake_index_repo(**kwargs):
        return {"success": True, "repo": kwargs["url"]}

    monkeypatch.setattr(hs, "index_repo", _fake_index_repo)

    try:
        status, body = _post_json(
            port,
            "/webhook/github",
            payload,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": f"sha256={digest}",
            },
        )
        assert status == 403
        assert body["reason"] == "repo_not_allowed"
    finally:
        server.shutdown()


def test_webhook_triggers_incremental_reindex(monkeypatch: pytest.MonkeyPatch):
    server = _start_server(webhook_secret="whsec-test", repo_allowlist=["argentaios/argentos"])
    port = server.server_address[1]
    payload = {"repository": {"full_name": "argentaios/argentos"}}
    digest = hmac.new(b"whsec-test", json.dumps(payload).encode("utf-8"), hashlib.sha256).hexdigest()

    captured: dict = {}

    async def _fake_index_repo(**kwargs):
        captured.update(kwargs)
        return {"success": True, "repo": kwargs["url"], "incremental": kwargs.get("incremental")}

    monkeypatch.setattr(hs, "index_repo", _fake_index_repo)

    try:
        status, body = _post_json(
            port,
            "/webhook/github",
            payload,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": f"sha256={digest}",
            },
        )
        assert status == 200
        assert body["ok"] is True
        assert captured["url"] == "argentaios/argentos"
        assert captured["incremental"] is True
        assert captured["allowlist"] == ["argentaios/argentos"]
    finally:
        server.shutdown()
