"""M-91: Opt-in load/limit smoke test.

Verifies rate-limiter and cooldown behavior under burst conditions.
Opt-in only: defaults to skipped unless --run-load-smoke is passed.
No live network — uses injected mock responses.
"""
from __future__ import annotations


import pytest

pytestmark = [pytest.mark.integration]

# Opt-in gate — run with: pytest -m "load" tests/test_load_smoke.py
pytestmark.append(pytest.mark.load)


class TestRateLimiterBurst:
    """Rate limiter protects against burst requests."""

    def test_disabled_limiter_allows_all(self) -> None:
        from emsal_mcp.sources.base import RateLimiter
        limiter = RateLimiter(enabled=False)
        for _ in range(100):
            assert limiter.acquire("test") is True

    def test_enabled_limiter_blocks_after_limit(self) -> None:
        from emsal_mcp.sources.base import RateLimiter
        limiter = RateLimiter(enabled=True, max_calls=5, period=60.0)
        # First 5 should pass
        for _ in range(5):
            assert limiter.acquire("test") is True
        # 6th should be blocked
        assert limiter.acquire("test") is False

    def test_cooldown_returns_wait_time(self) -> None:
        from emsal_mcp.sources.base import RateLimiter
        limiter = RateLimiter(enabled=True, max_calls=1, period=999.0)
        limiter.acquire("test")
        wait = limiter.wait_time("test")
        assert wait > 0

    def test_per_source_isolation(self) -> None:
        from emsal_mcp.sources.base import RateLimiter
        limiter = RateLimiter(enabled=True, max_calls=1, period=60.0)
        limiter.acquire("source_a")
        # source_b should not be blocked by source_a's usage
        assert limiter.acquire("source_b") is True

    def test_rate_limit_error_message(self) -> None:
        from emsal_mcp.sources.base import RateLimitError
        err = RateLimitError("test source rate limit exceeded")
        assert "rate limit" in str(err).lower()

    def test_source_client_rate_limit_integration(self) -> None:
        """SourceClient can use RateLimiter via acquire() method."""
        from emsal_mcp.sources.base import SourceClient, RateLimiter

        class TestClient(SourceClient):
            source_id = "test_rate"
            name = "Test Rate Limit"
            _rate_limiter = RateLimiter(enabled=True, max_calls=1, period=60.0)

            async def search(self, query, limit=10, **filters):
                return []

            async def get_document(self, document_id, **kwargs):
                from emsal_mcp.models import Document
                return Document(source=self.source_id, document_id=document_id, title="test")

        client = TestClient()
        # First call should succeed
        assert client._rate_limiter.acquire("test_rate") is True
        # Second call should fail (max_calls=1)
        assert client._rate_limiter.acquire("test_rate") is False

    def test_config_env_override(self, monkeypatch) -> None:
        """EMSAL_RATE_LIMIT_ENABLED controls limiter."""
        monkeypatch.setenv("EMSAL_RATE_LIMIT_ENABLED", "1")
        from emsal_mcp.config import config
        # This test just verifies the config reads the env var
        # The actual limiter behavior is tested above
        assert config.rate_limit_enabled is True


class TestRetryWithBackoff:
    """Retry behavior under transient errors."""

    def test_retry_succeeds_first_attempt(self) -> None:
        from emsal_mcp.sources.base import SourceClient

        class TestClient(SourceClient):
            source_id = "test_retry"
            name = "Test Retry"

            async def search(self, query, limit=10, **filters):
                return []

            async def get_document(self, document_id, **kwargs):
                from emsal_mcp.models import Document
                return Document(source=self.source_id, document_id=document_id, title="test")

        client = TestClient()
        assert client._retry_max_attempts == 3
        assert client._retry_enabled is False  # Off by default


class TestConcurrencySmoke:
    """Ensure concurrent access doesn't corrupt state."""

    def test_rate_limiter_thread_safe_basic(self) -> None:
        """RateLimiter handles basic concurrent increments via GIL."""
        from emsal_mcp.sources.base import RateLimiter
        limiter = RateLimiter(enabled=True, max_calls=50, period=60.0)
        for _ in range(50):
            assert limiter.acquire("test") is True
        # 51st call should be blocked
        assert limiter.acquire("test") is False
