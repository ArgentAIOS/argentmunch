"""Lightweight HTTP health endpoint for ArgentMunch."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from hashlib import sha256
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import urlparse

from .runtime_config import is_repo_allowed
from .tools.index_repo import index_repo

_storage_path: Optional[str] = None
_health_token: Optional[str] = None
_webhook_secret: Optional[str] = None
_repo_allowlist: list[str] = []
_stale_threshold_minutes: int = 60


def _extract_bearer_token(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token if token else None


def _is_local_request(client_address: tuple[str, int]) -> bool:
    host = (client_address[0] or "").strip()
    return host in {"127.0.0.1", "::1", "localhost"}


def _is_health_authorized(handler: BaseHTTPRequestHandler) -> bool:
    # Explicit token mode
    if _health_token:
        provided = (
            _extract_bearer_token(handler.headers.get("Authorization"))
            or handler.headers.get("X-ArgentMunch-Token")
            or handler.headers.get("X-Health-Token")
        )
        return bool(provided and hmac.compare_digest(provided, _health_token))

    # Local-safe default: without token, only local callers are allowed.
    return _is_local_request(handler.client_address)


def _verify_github_signature(secret: str, payload: bytes, signature_header: Optional[str]) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(provided, expected)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict):
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class HealthHandler(BaseHTTPRequestHandler):
    """Handle /health requests."""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/health", "/health/"}:
            from .cli import get_health_data
            if not _is_health_authorized(self):
                _json_response(
                    self,
                    401,
                    {
                        "error": "Unauthorized",
                        "hint": "Provide Authorization: Bearer <token> or call from localhost when no token is configured.",
                    },
                )
                return
            health = get_health_data(_storage_path)
            status = 200 if health.get("ok") else 503
            _json_response(self, status, health)
        elif parsed.path in {"/status", "/status/"}:
            from .cli import get_status_data
            if not _is_health_authorized(self):
                _json_response(
                    self,
                    401,
                    {
                        "error": "Unauthorized",
                        "hint": "Provide Authorization: Bearer <token> or call from localhost when no token is configured.",
                    },
                )
                return
            status = get_status_data(_storage_path, stale_threshold_minutes=_stale_threshold_minutes)
            code = 200 if status.get("ok") else 503
            _json_response(self, code, status)
        else:
            _json_response(self, 404, {"error": "Not found. Use /health, /status, or POST /webhook/github"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in {"/webhook/github", "/webhook/github/"}:
            _json_response(self, 404, {"error": "Not found. Use POST /webhook/github"})
            return

        if not _webhook_secret:
            _json_response(
                self,
                503,
                {"error": "Webhook secret not configured", "hint": "Set ARGENTMUNCH_WEBHOOK_SECRET or --webhook-secret"},
            )
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length)
        signature = self.headers.get("X-Hub-Signature-256")

        if not _verify_github_signature(_webhook_secret, payload, signature):
            _json_response(self, 401, {"error": "Invalid webhook signature"})
            return

        event = self.headers.get("X-GitHub-Event", "")
        if event != "push":
            _json_response(self, 202, {"ok": True, "ignored": True, "reason": f"event_not_supported:{event}"})
            return

        try:
            data = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "Invalid JSON payload"})
            return

        repo_name = ((data.get("repository") or {}).get("full_name") or "").strip()
        if not repo_name:
            _json_response(self, 400, {"error": "Missing repository.full_name in webhook payload"})
            return

        if not is_repo_allowed(repo_name, _repo_allowlist):
            _json_response(
                self,
                403,
                {"error": f"Repository not authorized for indexing: {repo_name}", "reason": "repo_not_allowed"},
            )
            return

        result = asyncio.run(
            index_repo(
                url=repo_name,
                use_ai_summaries=False,
                github_token=os.environ.get("GITHUB_TOKEN"),
                storage_path=_storage_path,
                incremental=True,
                allowlist=_repo_allowlist,
            )
        )
        code = 200 if result.get("success") else 502
        _json_response(
            self,
            code,
            {
                "ok": bool(result.get("success")),
                "event": "push",
                "repo": repo_name,
                "index_result": result,
            },
        )

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def run_health_server(
    host: str = "127.0.0.1",
    port: int = 9120,
    storage_path: Optional[str] = None,
    health_token: Optional[str] = None,
    webhook_secret: Optional[str] = None,
    repo_allowlist: Optional[list[str]] = None,
    stale_threshold_minutes: int = 60,
):
    """Start the health HTTP server."""
    global _storage_path, _health_token, _webhook_secret, _repo_allowlist, _stale_threshold_minutes
    _storage_path = storage_path
    _health_token = health_token
    _webhook_secret = webhook_secret
    _repo_allowlist = repo_allowlist or []
    _stale_threshold_minutes = stale_threshold_minutes

    server = HTTPServer((host, port), HealthHandler)
    print(f"ArgentMunch health server listening on http://{host}:{port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
