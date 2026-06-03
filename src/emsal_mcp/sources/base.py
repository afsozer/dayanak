from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from pathlib import Path
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

    # Response schema validation — optional per-adapter declaration.
    # _search_response_keys : list of expected top-level JSON keys for search()
    # _get_document_response_keys : expected keys for get_document()
    # Set to None (default) to skip validation for HTML/form-based adapters.
    _search_response_keys: list[str] | None = None
    _get_document_response_keys: list[str] | None = None

    def _check_response_schema(
        self, data: dict, expected_keys: list[str] | None, context: str
    ) -> tuple[str | None, list[str]]:
        """Validate that at least one expected key exists in the response data.

        Returns ``(primary_key, warnings)`` where *primary_key* is the first
        expected key found (or ``None`` if none found), and *warnings* is a
        list of schema-drift warning strings.

        Side-effect: downgrades ``_capability_status`` to ``PARTIAL`` when the
        primary expected key is missing (one-shot — once PARTIAL, stays).
        """
        if not expected_keys:
            return None, []
        primary = expected_keys[0]
        warnings: list[str] = []
        # Check primary key presence
        if primary not in data:
            warnings.append(
                f"SCHEMA_DRIFT: {self.source_id} {context} response missing "
                f"expected key {primary!r}. Got keys: {sorted(str(k) for k in data.keys())[:12]}"
            )
            # One-shot capability downgrade
            if self._capability_status == SourceStatus.STABLE:
                self._capability_status = SourceStatus.PARTIAL
            # Still try fallback keys
            for fallback in expected_keys[1:]:
                if fallback in data:
                    warnings.append(
                        f"SCHEMA_DRIFT_FALLBACK: {self.source_id} {context} using "
                        f"fallback key {fallback!r}"
                    )
                    return fallback, warnings
            return None, warnings
        return primary, warnings

    def _schema_signature(self) -> str | None:
        """Compute a deterministic hash of the declared response keys.

        Used to detect schema declaration changes across runs.
        Returns None only when no schema keys are declared.
        """
        search = tuple(sorted(self._search_response_keys or []))
        doc = tuple(sorted(self._get_document_response_keys or []))
        if not search and not doc:
            return None
        payload = json.dumps({"search": list(search), "get_document": list(doc)}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

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
        # M-61: schema health check — report declared schema keys and drift status
        declared_keys: list[str] = list(self._search_response_keys or []) + list(
            self._get_document_response_keys or []
        )
        sig = self._schema_signature()
        if declared_keys or sig:
            # Compare against stored signature from previous run
            stored_sigs = _load_schema_sigs()
            stored = stored_sigs.get(self.source_id)
            drift_detail = None
            if sig and stored and stored != sig:
                drift_detail = (
                    f"Schema declaration changed since last smoke: "
                    f"was {stored}, now {sig}"
                )
                result.warnings.append(drift_detail)
            # Save current signature for next run
            if sig:
                stored_sigs[self.source_id] = sig
                _save_schema_sigs(stored_sigs)
            result.schema_health = {
                "schema_declared": bool(declared_keys),
                "declared_search_keys": list(self._search_response_keys or []),
                "declared_get_document_keys": list(self._get_document_response_keys or []),
                "schema_signature": sig,
                "previous_signature": stored,
                "drift_detected": self._capability_status != SourceStatus.STABLE or bool(drift_detail),
                "drift_detail": drift_detail,
            }
        return result


# ── Schema signature persistence (M-61) ──────────────────────────────────

_SCHEMA_SIG_FILENAME = ".emsal_schema_sigs.json"


def _schema_sig_path() -> Path:
    """Path to the schema signature store file."""
    return Path.home() / ".emsal_mcp" / _SCHEMA_SIG_FILENAME


def _load_schema_sigs() -> dict[str, str]:
    """Load stored schema signatures from disk. Returns {} on any error."""
    try:
        p = _schema_sig_path()
        if not p.exists():
            return {}
        result: dict[str, str] = json.loads(p.read_text(encoding="utf-8"))
        return result
    except Exception:
        return {}


def _save_schema_sigs(sigs: dict[str, str]) -> None:
    """Persist schema signatures to disk. Silently ignores IO errors."""
    try:
        p = _schema_sig_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sigs, sort_keys=True, indent=2), encoding="utf-8")
    except Exception:
        pass


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


# ── Server-side rate limiting ───────────────────────────────────────────────
# Empirically, bedesten.adalet.gov.tr enforces ~10 requests per ~30s window,
# then returns HTTP 429 with a ~27s `Retry-After`. Pacing is hardcoded HERE (in
# the MCP, not the calling agent) so behaviour is identical regardless of which
# client connects — a misbehaving agent can neither hammer the API nor stall it.
# A per-host token bucket (burst capacity, steady refill) caps throughput; a
# 429 response forces a cooldown derived from the server's own Retry-After.
# The server uses a fixed/sliding window (~10 req / ~30s), NOT a leaky bucket:
# a burst plus gradual refill still overflows the window. So we model it as a
# sliding window — at most _RL_MAX requests in any _RL_WINDOW seconds. Typical
# jobs (a search + a few fetches) run instantly; heavier jobs are paced to the
# window edge and never trip 429. A real 429 forces a cooldown from Retry-After.
# Tunable via env; disable with EMSAL_RATE_LIMIT_DISABLED=1 (e.g. for tests).
_RL_DISABLED = os.getenv("EMSAL_RATE_LIMIT_DISABLED") == "1"
_RL_MAX = int(os.getenv("EMSAL_RATE_LIMIT_MAX", "8"))             # requests per window (< observed ~10)
_RL_WINDOW = float(os.getenv("EMSAL_RATE_LIMIT_WINDOW", "31.0"))  # window seconds (> observed ~30)
_RL_MAX_COOLDOWN = 60.0  # cap on honored Retry-After (defensive)


class _SlidingWindowLimiter:
    """Async per-host sliding-window limiter with explicit 429 cooldown."""

    def __init__(self, max_requests: int, window: float) -> None:
        self.max = max_requests
        self.window = window
        self.times: deque[float] = deque()
        self.cooldown_until = 0.0
        self.lock = asyncio.Lock()

    def _evict(self, now: float) -> None:
        while self.times and now - self.times[0] >= self.window:
            self.times.popleft()

    async def acquire(self) -> None:
        async with self.lock:
            now = time.monotonic()
            if now < self.cooldown_until:
                await asyncio.sleep(self.cooldown_until - now)
                now = time.monotonic()
            self._evict(now)
            if len(self.times) >= self.max:
                wait = self.window - (now - self.times[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                    now = time.monotonic()
                self._evict(now)
            self.times.append(now)

    def penalize(self, retry_after: float) -> None:
        self.cooldown_until = max(self.cooldown_until, time.monotonic() + retry_after)
        self.times.clear()


_BUCKETS: dict[str, _SlidingWindowLimiter] = {}


def _get_bucket(host: str) -> _SlidingWindowLimiter:
    b = _BUCKETS.get(host)
    if b is None:
        b = _SlidingWindowLimiter(_RL_MAX, _RL_WINDOW)
        _BUCKETS[host] = b
    return b


async def _throttle_request(request: httpx.Request) -> None:
    if not _RL_DISABLED:
        await _get_bucket(request.url.host).acquire()


async def _throttle_response(response: httpx.Response) -> None:
    if response.status_code == 429:
        ra = response.headers.get("Retry-After")
        try:
            secs = float(ra) if ra else _RL_WINDOW
        except ValueError:
            secs = _RL_WINDOW
        _get_bucket(response.request.url.host).penalize(min(secs, _RL_MAX_COOLDOWN))


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": f"EmsalMcp/{__version__} (+https://github.com/brachindul/emsal-mcp)"},
        event_hooks={"request": [_throttle_request], "response": [_throttle_response]},
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
