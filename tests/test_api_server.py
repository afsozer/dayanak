"""Tests for the HTTP REST API server (M-33)."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

import json
import threading
import time
import urllib.request
import urllib.error

from emsal_mcp import __version__


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_server(port: int = 0, token: str | None = None):
    """Start the API server in a daemon thread, return (server, actual_port)."""
    from emsal_mcp.api_server import EmsalAPIHandler
    from http.server import HTTPServer

    if token:
        EmsalAPIHandler.AUTH_TOKEN = token
    else:
        EmsalAPIHandler.AUTH_TOKEN = ""

    server = HTTPServer(("127.0.0.1", port), EmsalAPIHandler)
    actual_port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)  # let server bind
    return server, actual_port


def _get(url: str, token: str | None = None) -> dict:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _get_raw(url: str, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVersionEndpoint:
    def test_version_returns_ok_and_version(self):
        server, port = _start_server()
        try:
            data = _get(f"http://127.0.0.1:{port}/version")
            assert data["ok"] is True
            assert data["version"] == __version__
        finally:
            server.shutdown()

    def test_version_json_content_type(self):
        from http.client import HTTPConnection
        server, port = _start_server()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/version")
            resp = conn.getresponse()
            ct = resp.getheader("Content-Type", "")
            assert "application/json" in ct
            conn.close()
        finally:
            server.shutdown()


class TestHealthEndpoint:
    def test_health_returns_healthy(self):
        server, port = _start_server()
        try:
            data = _get(f"http://127.0.0.1:{port}/health")
            assert data["ok"] is True
            assert data["status"] == "healthy"
            assert data["version"] == __version__
        finally:
            server.shutdown()


class TestSourcesEndpoint:
    def test_sources_returns_list(self):
        server, port = _start_server()
        try:
            data = _get(f"http://127.0.0.1:{port}/sources")
            assert isinstance(data, list)
            assert len(data) > 0
            # Each entry should have source_id
            for cap in data:
                assert "source_id" in cap
        finally:
            server.shutdown()


class TestSourcesSmokeEndpoint:
    def test_smoke_returns_ok_and_sources(self):
        server, port = _start_server()
        try:
            data = _get(f"http://127.0.0.1:{port}/sources/smoke")
            assert "ok" in data
            assert "sources" in data
            assert isinstance(data["sources"], list)
        finally:
            server.shutdown()

    def test_smoke_online_param(self):
        server, port = _start_server()
        try:
            data = _get(f"http://127.0.0.1:{port}/sources/smoke?online=false")
            assert "sources" in data
        finally:
            server.shutdown()


class TestReleaseReadiness:
    def test_readiness_returns_command_center(self):
        server, port = _start_server()
        try:
            data = _get(f"http://127.0.0.1:{port}/release/readiness")
            assert "ok" in data
            assert "checks" in data
        finally:
            server.shutdown()


class TestCacheStats:
    def test_cache_stats_returns_dict(self):
        server, port = _start_server()
        try:
            data = _get(f"http://127.0.0.1:{port}/cache/stats")
            assert "schema_version" in data
            assert "db_path" in data
        finally:
            server.shutdown()


class TestNotFound:
    def test_nonexistent_returns_404(self):
        server, port = _start_server()
        try:
            status, data = _get_raw(f"http://127.0.0.1:{port}/nonexistent")
            assert status == 404
            assert data["ok"] is False
            assert data["error"] == "Not found"
        finally:
            server.shutdown()


class TestAuth:
    def test_unauthorized_with_token(self):
        server, port = _start_server(token="secret123")
        try:
            status, data = _get_raw(f"http://127.0.0.1:{port}/version", token=None)
            assert status == 401
            assert data["ok"] is False
            assert data["error"] == "Unauthorized"
        finally:
            server.shutdown()

    def test_authorized_with_correct_token(self):
        server, port = _start_server(token="secret123")
        try:
            status, data = _get_raw(f"http://127.0.0.1:{port}/version", token="secret123")
            assert status == 200
            assert data["ok"] is True
        finally:
            server.shutdown()

    def test_authorized_with_wrong_token(self):
        server, port = _start_server(token="secret123")
        try:
            status, data = _get_raw(f"http://127.0.0.1:{port}/version", token="wrong")
            assert status == 401
        finally:
            server.shutdown()

    def test_no_token_allows_all(self):
        server, port = _start_server(token=None)
        try:
            status, data = _get_raw(f"http://127.0.0.1:{port}/version")
            assert status == 200
            assert data["ok"] is True
        finally:
            server.shutdown()


class TestCORS:
    def test_cors_headers_present(self):
        from http.client import HTTPConnection
        server, port = _start_server()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/version")
            resp = conn.getresponse()
            assert resp.getheader("Access-Control-Allow-Origin") == "*"
            conn.close()
        finally:
            server.shutdown()

    def test_options_preflight(self):
        from http.client import HTTPConnection
        server, port = _start_server()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("OPTIONS", "/version")
            resp = conn.getresponse()
            assert resp.status == 204
            assert resp.getheader("Access-Control-Allow-Origin") == "*"
            assert resp.getheader("Access-Control-Allow-Methods") is not None
            conn.close()
        finally:
            server.shutdown()


class TestCLIImport:
    def test_api_app_importable(self):
        from emsal_mcp.cli import api_app
        assert api_app is not None

    def test_api_serve_command_exists(self):
        from emsal_mcp.cli import api_app
        # Check that 'serve' is a registered command
        commands = [cmd.name for cmd in api_app.registered_commands]
        assert "serve" in commands


class TestAPIServerModule:
    def test_api_version_constant(self):
        from emsal_mcp.api_server import API_VERSION
        assert API_VERSION == "2.3.0"

    def test_handler_class_exists(self):
        from emsal_mcp.api_server import EmsalAPIHandler
        assert EmsalAPIHandler is not None

    def test_run_api_server_function_exists(self):
        from emsal_mcp.api_server import run_api_server
        assert callable(run_api_server)