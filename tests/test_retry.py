"""Tests for retry with exponential backoff and optional rate limiting (M-18)."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.sources.base import RateLimiter, RateLimitError, SourceClient
from emsal_mcp.config import EmsalConfig


# ── Helper: concrete SourceClient subclass for testing ──────────────────────


class DummySource(SourceClient):
    """Minimal concrete implementation for testing abstract SourceClient."""

    source_id = "dummy"
    name = "Dummy Source"

    async def search(self, query: str, limit: int = 10, **filters):
        return []

    async def get_document(self, document_id: str, **kwargs):
        from emsal_mcp.models import Document, ContentStatus

        return Document(
            source="dummy",
            document_id=document_id,
            title="Test",
            content_status=ContentStatus.METADATA_ONLY,
        )


class FailingSource(SourceClient):
    """Source that fails a configurable number of times."""

    source_id = "failing"
    name = "Failing Source"

    def __init__(self, fail_count: int = 2):
        self.fail_count = fail_count
        self.attempt = 0
        self._call_log: list[int] = []

    async def search(self, query: str, limit: int = 10, **filters):
        self.attempt += 1
        self._call_log.append(self.attempt)
        if self.attempt <= self.fail_count:
            raise RuntimeError(f"Simulated failure #{self.attempt}")
        return []

    async def get_document(self, document_id: str, **kwargs):
        return await self.search(document_id)


# ── Tests: _with_retry ──────────────────────────────────────────────────────


class TestWithRetry:
    def test_succeeds_on_first_attempt(self):
        """No retry needed — returns immediately."""
        source = DummySource()
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = asyncio.run(
            source._with_retry(operation, max_attempts=3, base_delay=0.01)
        )
        assert result == "ok"
        assert call_count == 1

    def test_succeeds_after_failures(self):
        """Fails twice then succeeds on 3rd attempt."""
        source = DummySource()
        attempt = 0

        async def operation():
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise RuntimeError(f"Fail #{attempt}")
            return "success"

        result = asyncio.run(
            source._with_retry(operation, max_attempts=5, base_delay=0.01)
        )
        assert result == "success"
        assert attempt == 3

    def test_fails_after_max_attempts(self):
        """Exhausts all attempts and raises last error."""
        source = DummySource()
        attempt = 0

        async def operation():
            nonlocal attempt
            attempt += 1
            raise RuntimeError(f"Always fails #{attempt}")

        with pytest.raises(RuntimeError, match="Always fails #3"):
            asyncio.run(
                source._with_retry(operation, max_attempts=3, base_delay=0.01)
            )
        assert attempt == 3

    def test_backoff_delay_increases_exponentially(self):
        """Verify delays follow exponential pattern."""
        source = DummySource()
        source._retry_max_attempts = 4
        source._retry_base_delay = 0.1
        source._retry_max_delay = 5.0
        source._retry_backoff_factor = 2.0

        sleep_calls: list[float] = []

        async def mock_sleep(wait: float):
            sleep_calls.append(wait)

        async def operation():
            raise RuntimeError("Always fail")

        with patch("emsal_mcp.sources.base.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(RuntimeError):
                asyncio.run(source._with_retry(operation))

        # 3 sleeps (4 attempts - 1): 0.1, 0.2, 0.4
        assert len(sleep_calls) == 3
        assert sleep_calls[0] == pytest.approx(0.1, abs=0.01)
        assert sleep_calls[1] == pytest.approx(0.2, abs=0.01)
        assert sleep_calls[2] == pytest.approx(0.4, abs=0.01)

    def test_delay_capped_at_max_delay(self):
        """Delays should never exceed max_delay."""
        source = DummySource()
        source._retry_max_attempts = 10
        source._retry_base_delay = 1.0
        source._retry_max_delay = 2.0
        source._retry_backoff_factor = 2.0

        sleep_calls: list[float] = []

        async def mock_sleep(wait: float):
            sleep_calls.append(wait)

        async def operation():
            raise RuntimeError("Always fail")

        with patch("emsal_mcp.sources.base.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(RuntimeError):
                asyncio.run(source._with_retry(operation))

        # All sleeps should be <= max_delay (2.0)
        assert all(s <= 2.0 for s in sleep_calls)
        # Later ones should be capped at 2.0
        assert sleep_calls[-1] == pytest.approx(2.0, abs=0.01)

    def test_custom_parameters_override(self):
        """Override max_attempts, base_delay, max_delay, backoff_factor."""
        source = DummySource()
        attempt = 0

        async def operation():
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise RuntimeError("fail")
            return "ok"

        result = asyncio.run(
            source._with_retry(
                operation,
                max_attempts=2,
                base_delay=0.05,
                max_delay=1.0,
                backoff_factor=3.0,
            )
        )
        assert result == "ok"
        assert attempt == 2

    def test_coro_factory_is_called_each_attempt(self):
        """coro_factory is called fresh on each attempt."""
        source = DummySource()
        factory_calls = 0
        attempt = 0

        async def operation():
            nonlocal factory_calls, attempt
            factory_calls += 1
            attempt += 1
            if attempt < 3:
                raise RuntimeError("fail")
            return "ok"

        result = asyncio.run(
            source._with_retry(operation, max_attempts=5, base_delay=0.01)
        )
        assert result == "ok"
        assert factory_calls == 3

    def test_no_sleep_on_success(self):
        """No sleep when first attempt succeeds."""
        source = DummySource()
        sleep_calls: list[float] = []

        async def mock_sleep(wait: float):
            sleep_calls.append(wait)

        async def operation():
            return "ok"

        with patch("emsal_mcp.sources.base.asyncio.sleep", side_effect=mock_sleep):
            result = asyncio.run(
                source._with_retry(operation, max_attempts=3, base_delay=0.1)
            )

        assert result == "ok"
        assert len(sleep_calls) == 0

    def test_retry_with_single_attempt(self):
        """max_attempts=1 means no retry at all."""
        source = DummySource()
        attempt = 0

        async def operation():
            nonlocal attempt
            attempt += 1
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            asyncio.run(
                source._with_retry(operation, max_attempts=1, base_delay=0.01)
            )
        assert attempt == 1


# ── Tests: RateLimiter ──────────────────────────────────────────────────────


class TestRateLimiter:
    def test_disabled_allows_all_calls(self):
        """When disabled (default), all calls should be allowed."""
        limiter = RateLimiter(enabled=False, max_calls=2, period=60.0)
        for _ in range(100):
            assert limiter.acquire("src") is True

    def test_enabled_allows_under_limit(self):
        """When enabled, calls under the limit should be allowed."""
        limiter = RateLimiter(enabled=True, max_calls=5, period=60.0)
        for _ in range(5):
            assert limiter.acquire("src") is True

    def test_enabled_blocks_over_limit(self):
        """When enabled, calls over the limit should be blocked."""
        limiter = RateLimiter(enabled=True, max_calls=3, period=60.0)
        assert limiter.acquire("src") is True
        assert limiter.acquire("src") is True
        assert limiter.acquire("src") is True
        assert limiter.acquire("src") is False

    def test_recovers_after_period(self):
        """After period expires, old calls should be evicted."""
        limiter = RateLimiter(enabled=True, max_calls=2, period=0.1)
        limiter.acquire("src")
        limiter.acquire("src")
        assert limiter.acquire("src") is False

        time.sleep(0.15)
        assert limiter.acquire("src") is True

    def test_independent_buckets_per_source(self):
        """Different sources should have independent buckets."""
        limiter = RateLimiter(enabled=True, max_calls=2, period=60.0)
        limiter.acquire("src_a")
        limiter.acquire("src_a")
        assert limiter.acquire("src_a") is False
        assert limiter.acquire("src_b") is True
        assert limiter.acquire("src_b") is True
        assert limiter.acquire("src_b") is False

    def test_wait_time_returns_zero_when_disabled(self):
        """wait_time returns 0 when disabled."""
        limiter = RateLimiter(enabled=False)
        assert limiter.wait_time("src") == 0.0

    def test_wait_time_returns_zero_when_bucket_empty(self):
        """wait_time returns 0 when bucket is empty."""
        limiter = RateLimiter(enabled=True, max_calls=5, period=60.0)
        assert limiter.wait_time("src") == 0.0

    def test_wait_time_returns_positive_when_at_limit(self):
        """wait_time returns positive seconds when at limit."""
        limiter = RateLimiter(enabled=True, max_calls=1, period=10.0)
        limiter.acquire("src")
        wait = limiter.wait_time("src")
        assert wait > 0.0
        assert wait <= 10.0

    def test_default_not_enabled(self):
        """RateLimiter should be disabled by default."""
        limiter = RateLimiter()
        assert limiter.enabled is False
        for _ in range(1000):
            assert limiter.acquire("src") is True


# ── Tests: SourceClient._with_rate_limit ─────────────────────────────────────


class TestSourceClientRateLimit:
    def test_no_limiter_allows(self):
        """Without a rate limiter, _with_rate_limit should not raise."""
        source = DummySource()
        asyncio.run(source._with_rate_limit("src"))

    def test_disabled_limiter_allows(self):
        """With a disabled rate limiter, should not raise."""
        source = DummySource()
        source._rate_limiter = RateLimiter(enabled=False, max_calls=1, period=60.0)
        asyncio.run(source._with_rate_limit("src"))

    def test_enabled_limiter_allows_under_limit(self):
        """With enabled limiter under limit, should not raise."""
        source = DummySource()
        source._rate_limiter = RateLimiter(enabled=True, max_calls=5, period=60.0)
        asyncio.run(source._with_rate_limit("src"))

    def test_enabled_limiter_raises_when_exceeded(self):
        """With enabled limiter over limit, should raise RateLimitError."""
        source = DummySource()
        source._rate_limiter = RateLimiter(enabled=True, max_calls=2, period=60.0)
        asyncio.run(source._with_rate_limit("src"))
        asyncio.run(source._with_rate_limit("src"))

        with pytest.raises(RateLimitError) as exc_info:
            asyncio.run(source._with_rate_limit("src"))
        assert exc_info.value.source == "src"
        assert exc_info.value.wait_seconds > 0.0


# ── Tests: SourceClient retry defaults ───────────────────────────────────────


class TestSourceClientRetryDefaults:
    def test_retry_disabled_by_default(self):
        """Retry should be disabled by default."""
        source = DummySource()
        assert source._retry_enabled is False

    def test_default_retry_params(self):
        """Default retry parameters should match spec."""
        source = DummySource()
        assert source._retry_max_attempts == 3
        assert source._retry_base_delay == 1.0
        assert source._retry_max_delay == 30.0
        assert source._retry_backoff_factor == 2.0

    def test_default_rate_limiter_none(self):
        """Rate limiter should be None by default."""
        source = DummySource()
        assert source._rate_limiter is None

    def test_subclass_can_override_retry_params(self):
        """Subclasses should be able to override retry parameters."""

        class CustomSource(SourceClient):
            source_id = "custom"
            name = "Custom"
            _retry_enabled = True
            _retry_max_attempts = 5
            _retry_base_delay = 0.5

            async def search(self, query, limit=10, **filters):
                return []

            async def get_document(self, document_id, **kwargs):
                from emsal_mcp.models import Document, ContentStatus

                return Document(
                    source="custom",
                    document_id=document_id,
                    title="T",
                    content_status=ContentStatus.METADATA_ONLY,
                )

        source = CustomSource()
        assert source._retry_enabled is True
        assert source._retry_max_attempts == 5
        assert source._retry_base_delay == 0.5


# ── Tests: Config overrides ─────────────────────────────────────────────────


class TestConfigOverrides:
    def test_retry_max_default(self):
        """Default retry_max_attempts should be 3."""
        cfg = EmsalConfig()
        assert cfg.retry_max_attempts == 3

    def test_retry_max_env(self):
        """EMSAL_RETRY_MAX env var should override default."""
        with patch.dict("os.environ", {"EMSAL_RETRY_MAX": "7"}):
            cfg = EmsalConfig()
            assert cfg.retry_max_attempts == 7

    def test_retry_delay_default(self):
        """Default retry_base_delay should be 1.0."""
        cfg = EmsalConfig()
        assert cfg.retry_base_delay == 1.0

    def test_retry_delay_env(self):
        """EMSAL_RETRY_DELAY env var should override default."""
        with patch.dict("os.environ", {"EMSAL_RETRY_DELAY": "0.5"}):
            cfg = EmsalConfig()
            assert cfg.retry_base_delay == 0.5

    def test_rate_limit_enabled_default(self):
        """Default rate_limit_enabled should be False."""
        cfg = EmsalConfig()
        assert cfg.rate_limit_enabled is False

    def test_rate_limit_enabled_true_variants(self):
        """Various truthy strings should enable rate limiting."""
        for val in ("1", "true", "True", "TRUE", "yes", "Yes", "YES"):
            with patch.dict("os.environ", {"EMSAL_RATE_LIMIT_ENABLED": val}):
                cfg = EmsalConfig()
                assert cfg.rate_limit_enabled is True, f"Failed for value: {val}"

    def test_rate_limit_enabled_false_variants(self):
        """Falsy strings should disable rate limiting."""
        for val in ("0", "false", "no", "", "anything"):
            with patch.dict("os.environ", {"EMSAL_RATE_LIMIT_ENABLED": val}):
                cfg = EmsalConfig()
                assert cfg.rate_limit_enabled is False, f"Failed for value: {val}"


# ── Tests: RateLimitError ───────────────────────────────────────────────────


class TestRateLimitError:
    def test_error_message(self):
        """RateLimitError should store message."""
        err = RateLimitError("Rate limit exceeded")
        assert str(err) == "Rate limit exceeded"

    def test_error_attributes(self):
        """RateLimitError should store source and wait_seconds."""
        err = RateLimitError("Rate limit exceeded", source="src", wait_seconds=5.0)
        assert err.source == "src"
        assert err.wait_seconds == 5.0

    def test_error_defaults(self):
        """Default source and wait_seconds should be empty/0."""
        err = RateLimitError("msg")
        assert err.source == ""
        assert err.wait_seconds == 0.0


# ── Tests: Import/export ────────────────────────────────────────────────────


class TestImports:
    def test_rate_limiter_importable(self):
        """RateLimiter should be importable from sources."""
        from emsal_mcp.sources import RateLimiter

        assert callable(RateLimiter)

    def test_rate_limit_error_importable(self):
        """RateLimitError should be importable from sources."""
        from emsal_mcp.sources import RateLimitError

        assert issubclass(RateLimitError, Exception)

    def test_source_client_has_retry_method(self):
        """SourceClient should have _with_retry method."""
        assert hasattr(SourceClient, "_with_retry")
        assert callable(getattr(SourceClient, "_with_retry"))

    def test_source_client_has_rate_limit_method(self):
        """SourceClient should have _with_rate_limit method."""
        assert hasattr(SourceClient, "_with_rate_limit")
        assert callable(getattr(SourceClient, "_with_rate_limit"))

    def test_config_has_retry_props(self):
        """EmsalConfig should have retry config properties."""
        cfg = EmsalConfig()
        assert hasattr(cfg, "retry_max_attempts")
        assert hasattr(cfg, "retry_base_delay")
        assert hasattr(cfg, "rate_limit_enabled")


# ── Tests: Integration — retry + rate_limit combined ────────────────────────


class TestCombinedRetryAndRateLimit:
    def test_rate_limit_blocks_before_retry(self):
        """Rate limit should block before retry even fires."""
        source = DummySource()
        source._rate_limiter = RateLimiter(enabled=True, max_calls=1, period=60.0)

        # First call succeeds
        asyncio.run(source._with_rate_limit())

        # Second call should raise RateLimitError (not retry)
        with pytest.raises(RateLimitError):
            asyncio.run(source._with_rate_limit())

    def test_retry_respects_rate_limit_per_call(self):
        """Each retry attempt should check rate limit separately when integrated."""
        source = DummySource()
        source._retry_enabled = True
        source._retry_max_attempts = 3
        source._retry_base_delay = 0.01
        source._rate_limiter = RateLimiter(enabled=True, max_calls=2, period=60.0)

        call_count = 0

        async def operation():
            """Simulates a source call that checks rate limit before executing."""
            nonlocal call_count
            call_count += 1
            # Rate limit check is OPT-IN: each operation must call it
            await source._with_rate_limit()
            if call_count < 3:
                raise RuntimeError("fail")
            return "ok"

        # Consume 1 rate limit token (total limit = 2, used = 1)
        source._rate_limiter.acquire(source.source_id)

        # Remaining: 1 token. First attempt uses it (call_count=1), second attempt
        # has call_count=2 and tries to acquire another token — that succeeds (2/2).
        # Third attempt (call_count=3) would exceed — but we only have 2 tokens.
        # Actually: first retry attempt (call_count=2) consumes last token.
        # Second retry (call_count=3) is rate-limited -> raises RateLimitError.
        with pytest.raises(RateLimitError):
            asyncio.run(
                source._with_retry(
                    operation,
                    max_attempts=3,
                    base_delay=0.01,
                )
            )