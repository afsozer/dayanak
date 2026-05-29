"""Optional HTTP REST API server — v2.3

Read-only endpoints that map existing emsal-mcp functions to JSON.
No state mutation by default.  Auth is optional (env EMSAL_API_TOKEN).
CORS headers included for browser access.  Single-user by default.
"""
from __future__ import annotations

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import __version__
from .cache import Cache
from .release import release_command_center
from .sources.registry import capabilities, smoke_all_sync

API_VERSION = "2.3.0"


class EmsalAPIHandler(BaseHTTPRequestHandler):
    """HTTP handler mapping URL paths to emsal-mcp functions."""

    AUTH_TOKEN = os.environ.get("EMSAL_API_TOKEN", "")

    def _check_auth(self) -> bool:
        if not self.AUTH_TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {self.AUTH_TOKEN}"

    def _send_json(self, data: object, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())

    def do_GET(self) -> None:
        if not self._check_auth():
            self._send_json({"ok": False, "error": "Unauthorized"}, 401)
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "/version":
            self._send_json({"ok": True, "version": __version__})
        elif path == "/health":
            self._send_json({"ok": True, "status": "healthy", "version": __version__})
        elif path == "/sources":
            self._send_json(capabilities())
        elif path == "/sources/smoke":
            online = params.get("online", ["false"])[0] == "true"
            results = smoke_all_sync(online=online)
            self._send_json({
                "ok": all(r.get("offline_ok", False) for r in results),
                "sources": results,
            })
        elif path == "/release/readiness":
            self._send_json(release_command_center())
        elif path == "/cache/stats":
            cache = Cache()
            try:
                self._send_json(cache.cache_stats())
            finally:
                cache.close()
        else:
            self._send_json({"ok": False, "error": "Not found"}, 404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default stderr logging in production; override to silence."""
        pass


def run_api_server(host: str = "127.0.0.1", port: int = 8765, token: str | None = None) -> None:
    """Start the HTTP API server (blocking).

    Args:
        host: Bind address.
        port: Bind port.
        token: Optional auth token.  Overrides EMSAL_API_TOKEN env var.
    """
    if token:
        EmsalAPIHandler.AUTH_TOKEN = token

    server = HTTPServer((host, port), EmsalAPIHandler)
    print(f"Emsal-mcp API server v{__version__} running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
