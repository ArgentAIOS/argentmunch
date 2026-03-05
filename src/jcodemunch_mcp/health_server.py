"""Lightweight HTTP health endpoint for ArgentMunch."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional


_storage_path: Optional[str] = None


class HealthHandler(BaseHTTPRequestHandler):
    """Handle /health requests."""

    def do_GET(self):
        if self.path == "/health" or self.path == "/health/":
            from .cli import get_health_data
            health = get_health_data(_storage_path)
            status = 200 if health.get("ok") else 503
            body = json.dumps(health, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            body = json.dumps({"error": "Not found. Use /health"}).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def run_health_server(port: int = 9120, storage_path: Optional[str] = None):
    """Start the health HTTP server."""
    global _storage_path
    _storage_path = storage_path

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"ArgentMunch health server listening on http://0.0.0.0:{port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
