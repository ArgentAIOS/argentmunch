"""Lightweight HTTP health endpoint for ArgentMunch."""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import urlparse

from .reindex_manager import ReindexManager
from .runtime_config import is_repo_allowed

_storage_path: Optional[str] = None
_health_token: Optional[str] = None
_health_local_dev_mode: bool = False
_webhook_secret: Optional[str] = None
_repo_allowlist: list[str] = []
_stale_threshold_minutes: int = 60
_deny_by_default_allowlist: bool = False
_reindex_manager: Optional[ReindexManager] = None


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


def _authorize_health_request(handler: BaseHTTPRequestHandler) -> tuple[bool, dict]:
    provided = (
        _extract_bearer_token(handler.headers.get("Authorization"))
        or handler.headers.get("X-ArgentMunch-Token")
        or handler.headers.get("X-Health-Token")
    )
    if _health_token:
        if not provided:
            return False, {
                "error": "Unauthorized",
                "reason": "missing_token",
                "hint": "Provide Authorization: Bearer <token>.",
            }
        if not hmac.compare_digest(provided, _health_token):
            return False, {
                "error": "Unauthorized",
                "reason": "invalid_token",
                "hint": "Provided token is invalid.",
            }
        return True, {}

    if _health_local_dev_mode and _is_local_request(handler.client_address):
        return True, {}

    return False, {
        "error": "Unauthorized",
        "reason": "token_required",
        "hint": "Set ARGENTMUNCH_HEALTH_TOKEN or enable ARGENTMUNCH_HEALTH_LOCAL_DEV=true for localhost-only dev mode.",
    }


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

            authorized, error_payload = _authorize_health_request(self)
            if not authorized:
                _json_response(self, 401, error_payload)
                return
            health = get_health_data(_storage_path)
            status = 200 if health.get("ok") else 503
            _json_response(self, status, health)
        elif parsed.path in {"/status", "/status/"}:
            from .cli import get_status_data

            authorized, error_payload = _authorize_health_request(self)
            if not authorized:
                _json_response(self, 401, error_payload)
                return
            status = get_status_data(_storage_path, stale_threshold_minutes=_stale_threshold_minutes)
            code = 200 if status.get("ok") else 503
            _json_response(self, code, status)
        else:
            _json_response(self, 404, {"error": "Not found. Use /health, /status, POST /webhook, or POST /webhook/github"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in {"/webhook", "/webhook/", "/webhook/github", "/webhook/github/"}:
            _json_response(self, 404, {"error": "Not found. Use POST /webhook"})
            return

        if not _webhook_secret:
            _json_response(
                self,
                503,
                {
                    "error": "Webhook secret not configured",
                    "hint": "Set ARGENTMUNCH_WEBHOOK_SECRET or --webhook-secret",
                },
            )
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length)
        signature = self.headers.get("X-Hub-Signature-256")

        if not _verify_github_signature(_webhook_secret, payload, signature):
            _json_response(self, 403, {"error": "Invalid webhook signature"})
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

        repo_name = ((data.get("repository") or {}).get("full_name") or "").strip().lower()
        if not repo_name:
            _json_response(self, 400, {"error": "Missing repository.full_name in webhook payload"})
            return

        if not is_repo_allowed(
            repo_name,
            _repo_allowlist,
            deny_by_default=_deny_by_default_allowlist,
        ):
            _json_response(
                self,
                403,
                {"error": f"Repository not authorized for indexing: {repo_name}", "reason": "repo_not_allowed"},
            )
            return

        if _reindex_manager is None:
            _json_response(self, 503, {"error": "Reindex manager unavailable"})
            return

        scheduled = _reindex_manager.schedule_reindex(repo_name, reason="webhook_push")
        response_payload = {
            "ok": True,
            "event": "push",
            "repo": repo_name,
            "accepted": bool(scheduled.get("accepted")),
            "reason": scheduled.get("reason"),
            "retry_after_seconds": scheduled.get("retry_after_seconds"),
            "status": _reindex_manager.get_status(repo_name),
        }
        _json_response(self, 202, response_payload)

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def run_health_server(
    host: str = "127.0.0.1",
    port: int = 9120,
    storage_path: Optional[str] = None,
    health_token: Optional[str] = None,
    health_local_dev_mode: bool = False,
    webhook_secret: Optional[str] = None,
    repo_allowlist: Optional[list[str]] = None,
    stale_threshold_minutes: int = 60,
    deny_by_default_allowlist: bool = False,
):
    """Start the health HTTP server."""
    global _storage_path, _health_token, _health_local_dev_mode, _webhook_secret, _repo_allowlist
    global _stale_threshold_minutes, _deny_by_default_allowlist, _reindex_manager

    _storage_path = storage_path
    _health_token = health_token
    _health_local_dev_mode = health_local_dev_mode
    _webhook_secret = webhook_secret
    _repo_allowlist = [r.lower() for r in (repo_allowlist or [])]
    _stale_threshold_minutes = stale_threshold_minutes
    _deny_by_default_allowlist = deny_by_default_allowlist
    _reindex_manager = ReindexManager(
        storage_path=storage_path,
        allowlist=_repo_allowlist,
        deny_by_default=deny_by_default_allowlist,
        min_interval_seconds=60,
    )

    server = HTTPServer((host, port), HealthHandler)
    print(f"ArgentMunch health server listening on http://{host}:{port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
