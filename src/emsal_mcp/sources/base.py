from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Callable, Coroutine, TypeVar

import httpx
from bs4 import BeautifulSoup

from emsal_mcp import __version__
from emsal_mcp.models import (
    ContentStatus,
    Document,
    SearchResult,
    SourceCapability,
    SourceSmokeResult,
    SourceStatus,
    build_error,
)

T = TypeVar("T")


class RateLimitError(Exception):
    """Raised when a rate limiter blocks a request."""

    def __init__(self, message: str, *, source: str = "", wait_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.source = source
        self.wait_seconds = wait_seconds


class RateLimiter:
    """Token-bucket rate limiter. Disabled by default.

    When disabled (default), all calls are allowed through — single-user
    assumption preserved.  When enabled, callers must call `acquire()`
    before each request; if it returns False the request should be
    rejected or queued.
    """

    def __init__(self, enabled: bool = False, max_calls: int = 10, period: float = 60.0) -> None:
        self.enabled = enabled
        self.max_calls = max_calls
        self.period = period
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def acquire(self, source_id: str) -> bool:
        """Try to acquire a token. Returns True if allowed."""
        if not self.enabled:
            return True
        now = time.monotonic()
        # Remove expired timestamps
        self._buckets[source_id] = [
            t for t in self._buckets[source_id] if now - t < self.period
        ]
        if len(self._buckets[source_id]) >= self.max_calls:
            return False
        self._buckets[source_id].append(now)
        return True

    def wait_time(self, source_id: str) -> float:
        """Seconds until next available token."""
        if not self.enabled or not self._buckets[source_id]:
            return 0.0
        now = time.monotonic()
        oldest = min(self._buckets[source_id])
        return max(0.0, self.period - (now - oldest))


class SourceClient(ABC):
    source_id: str
    name: str
    public: bool = True

    # Capability metadata — subclasses may override to add known_limitations / notes.
    _capability_status: SourceStatus = SourceStatus.STABLE
    _supports_search: bool = True
    _supports_get_document: bool = True
    _supports_full_text: bool = True
    _supports_pdf_link: bool = False
    _supports_metadata_only: bool = True
    _supports_article_search: bool = False
    _supports_type_filter: bool = False
    _supports_workflow: bool = True
    _live_smoke_recommended: bool = True
    _known_limitations: list[str] = []
    _notes: str = ""

    # Retry configuration — OPT-IN per source by setting attributes.
    _retry_enabled: bool = False
    _retry_max_attempts: int = 3
    _retry_base_delay: float = 1.0  # seconds
    _retry_max_delay: float = 30.0  # seconds
    _retry_backoff_factor: float = 2.0

    # Rate limiter — shared across sources. Default OFF (single-user assumption).
    _rate_limiter: RateLimiter | None = None

    @abstractmethod
    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]: ...

    @abstractmethod
    async def get_document(self, document_id: str, **kwargs: Any) -> Document: ...

    def capability_model(self) -> SourceCapability:
        """Return a typed SourceCapability model for this client."""
        return SourceCapability(
            source_id=self.source_id,
            display_name=self.name,
            status=self._capability_status,
            public=self.public,
            supports_search=self._supports_search,
            supports_get_document=self._supports_get_document,
            supports_full_text=self._supports_full_text,
            supports_pdf_link=self._supports_pdf_link,
            supports_metadata_only=self._supports_metadata_only,
            supports_article_search=self._supports_article_search,
            supports_type_filter=self._supports_type_filter,
            supports_workflow=self._supports_workflow,
            live_smoke_recommended=self._live_smoke_recommended,
            known_limitations=list(self._known_limitations),
            notes=self._notes,
        )

    def capabilities(self) -> dict[str, Any]:
        """Legacy dict form — kept for backward compat with callers."""
        return self.capability_model().to_legacy_dict()

    async def _with_circuit(self, coro: Any, operation: str = "search") -> Any:
        """Execute with circuit breaker protection.

        If the circuit breaker is open, returns a CIRCUIT_OPEN error dict
        without executing the coroutine.  Otherwise runs the coroutine and
        records success/failure.

        This is OPT-IN: callers must explicitly wrap their calls.
        """
        from emsal_mcp.circuit import is_circuit_open, record_success, record_failure

        if is_circuit_open(self.source_id):
            return build_error(
                "CIRCUIT_OPEN",
                f"Circuit breaker open for {self.source_id}. Try again later.",
                source=self.source_id,
            )

        try:
            result = await coro
            record_success(self.source_id)
            return result
        except Exception:
            record_failure(self.source_id)
            raise

    async def _with_retry(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, T]],
        max_attempts: int | None = None,
        base_delay: float | None = None,
        max_delay: float | None = None,
        backoff_factor: float | None = None,
    ) -> T:
        """Execute with exponential-backoff retry.

        ``coro_factory`` is a zero-argument async callable that **returns**
        the result (i.e. ``lambda: some_coro()``).  This avoids needing
        to pass pre-created coroutines that may have already started.

        Returns the result of the first successful invocation.
        Raises the last exception if all attempts fail.

        This is OPT-IN: callers must explicitly wrap their calls.
        """
        attempts = max_attempts if max_attempts is not None else self._retry_max_attempts
        delay = base_delay if base_delay is not None else self._retry_base_delay
        max_d = max_delay if max_delay is not None else self._retry_max_delay
        factor = backoff_factor if backoff_factor is not None else self._retry_backoff_factor

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await coro_factory()
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    wait = min(delay * (factor ** (attempt - 1)), max_d)
                    await asyncio.sleep(wait)

        raise last_error  # type: ignore[misc]

    async def _with_rate_limit(self, source_id: str | None = None) -> None:
        """Check rate-limit before a call.

        Raises ``RateLimitError`` if the rate limiter is enabled and the
        caller has exceeded the allowed calls within the period window.

        This is OPT-IN: callers must explicitly wrap their calls.
        """
        limiter = self._rate_limiter
        if limiter is None or not limiter.enabled:
            return
        sid = source_id or self.source_id
        if not limiter.acquire(sid):
            wait = limiter.wait_time(sid)
            raise RateLimitError(
                f"Rate limit exceeded for {sid}. Retry after {wait:.1f}s.",
                source=sid,
                wait_seconds=wait,
            )

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        """Offline-safe smoke test. Override for online-specific checks.

        Offline: verifies callable status and capability consistency.
        Online: subclass should call super() then do a lightweight search.
        """
        result = SourceSmokeResult(source_id=self.source_id)
        result.search_callable = self._supports_search
        result.get_document_callable = self._supports_get_document
        cap = self.capability_model()
        if cap.source_id != self.source_id:
            result.warnings.append(
                f"capability_model().source_id ({cap.source_id}) != self.source_id ({self.source_id})"
            )
            result.offline_ok = False
        return result


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def decode_b64(data: str) -> bytes:
    """Decode base64 with padding fix. Returns empty bytes on failure."""
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.b64decode(padded)
    except Exception:
        return b""


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": f"EmsalMcp/{__version__} (+https://github.com/fatihsozer/emsal-mcp)"},
    )


def metadata_doc(source: str, document_id: str, title: str, **kw: Any) -> Document:
    return Document(source=source, document_id=document_id, title=title, content_status=ContentStatus.METADATA_ONLY, **kw)


def check_http_response(r: httpx.Response, source: str = "") -> None:
    """Raise on non-2xx HTTP responses with structured info."""
    if r.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"HTTP {r.status_code} from {source or 'source'}: {r.url}",
            request=r.request,
            response=r,
        )
