"""Source health monitoring with circuit breaker pattern.

Circuit breaker state machine:
    CLOSED -> (N consecutive failures) -> OPEN -> (recovery timeout) -> HALF_OPEN -> (success) -> CLOSED
                                                       (failure) -> OPEN

Per-source success/failure tracking persisted in the Cache SQLite database.
Circuit breaker is OPT-IN: sources must explicitly call record_success/record_failure
and is_circuit_open to participate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema — table created on first use
# ---------------------------------------------------------------------------

_CIRCUIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS circuit_state (
    source_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'closed',
    failure_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_failure_at TEXT,
    last_success_at TEXT,
    opened_at TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_table(cache: Any) -> None:
    """Create circuit_state table if it does not exist."""
    cache.db.execute(_CIRCUIT_TABLE_SQL)
    cache.db.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_or_create_row(cache: Any, source_id: str) -> dict[str, Any]:
    """Return existing row or insert a fresh default row and return it."""
    row = cache.db.execute(
        "SELECT * FROM circuit_state WHERE source_id=?", (source_id,)
    ).fetchone()
    if row:
        return dict(row)
    # Insert default
    cache.db.execute(
        "INSERT INTO circuit_state (source_id, state) VALUES (?, 'closed')",
        (source_id,),
    )
    cache.db.commit()
    row = cache.db.execute(
        "SELECT * FROM circuit_state WHERE source_id=?", (source_id,)
    ).fetchone()
    return dict(row)


def _update_row(cache: Any, source_id: str, **fields: Any) -> None:
    """Update specific fields for a source row."""
    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [source_id]
    cache.db.execute(
        f"UPDATE circuit_state SET {set_clause} WHERE source_id=?",
        values,
    )
    cache.db.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_success(source_id: str, cache: Any = None) -> None:
    """Record a successful call for *source_id*.

    - Increments success_count.
    - Resets consecutive_failures to 0.
    - If state was HALF_OPEN, transitions to CLOSED.
    """
    from .cache import Cache

    own_cache = cache is None
    if own_cache:
        cache = Cache()
    try:
        _ensure_table(cache)
        row = _get_or_create_row(cache, source_id)
        new_state = row["state"]
        if row["state"] == "half_open":
            new_state = "closed"
            logger.info("Circuit breaker for %s: HALF_OPEN -> CLOSED (success)", source_id)
        _update_row(
            cache,
            source_id,
            state=new_state,
            success_count=row["success_count"] + 1,
            consecutive_failures=0,
            last_success_at=_now_iso(),
        )
    finally:
        if own_cache:
            cache.close()


def record_failure(source_id: str, cache: Any = None) -> None:
    """Record a failed call for *source_id*.

    - Increments failure_count and consecutive_failures.
    - If consecutive_failures >= threshold while CLOSED, transitions to OPEN.
    - If state was HALF_OPEN, transitions back to OPEN.
    """
    from .config import config as app_config
    from .cache import Cache

    threshold = app_config.circuit_breaker_threshold
    own_cache = cache is None
    if own_cache:
        cache = Cache()
    try:
        _ensure_table(cache)
        row = _get_or_create_row(cache, source_id)
        new_consecutive = row["consecutive_failures"] + 1
        new_state = row["state"]
        opened_at = row["opened_at"]

        if row["state"] == "half_open":
            # Failure during half-open -> back to OPEN
            new_state = "open"
            opened_at = _now_iso()
            logger.info(
                "Circuit breaker for %s: HALF_OPEN -> OPEN (failure during probe)",
                source_id,
            )
        elif row["state"] == "closed" and new_consecutive >= threshold:
            new_state = "open"
            opened_at = _now_iso()
            logger.warning(
                "Circuit breaker for %s: CLOSED -> OPEN (%d consecutive failures >= %d)",
                source_id,
                new_consecutive,
                threshold,
            )

        _update_row(
            cache,
            source_id,
            state=new_state,
            failure_count=row["failure_count"] + 1,
            consecutive_failures=new_consecutive,
            last_failure_at=_now_iso(),
            opened_at=opened_at,
        )
    finally:
        if own_cache:
            cache.close()


def is_circuit_open(
    source_id: str,
    cache: Any = None,
    threshold: int | None = None,
    recovery_timeout: int | None = None,
) -> bool:
    """Check if the circuit breaker for *source_id* is blocking calls.

    - If OPEN and recovery_timeout has elapsed -> transition to HALF_OPEN, return False (allow one try).
    - If OPEN and still within timeout -> return True (block).
    - If CLOSED or HALF_OPEN -> return False (allow).

    Args:
        source_id: Source identifier.
        cache: Optional Cache instance (created if None).
        threshold: Override default threshold (for testing).
        recovery_timeout: Override default recovery timeout in seconds (for testing).
    """
    from .config import config as app_config
    from .cache import Cache

    _threshold = threshold if threshold is not None else app_config.circuit_breaker_threshold
    _recovery_timeout = recovery_timeout if recovery_timeout is not None else app_config.circuit_recovery_timeout

    own_cache = cache is None
    if own_cache:
        cache = Cache()
    try:
        _ensure_table(cache)
        row = cache.db.execute(
            "SELECT * FROM circuit_state WHERE source_id=?", (source_id,)
        ).fetchone()
        if not row:
            return False

        state = row["state"]
        if state == "closed" or state == "half_open":
            return False

        # state == "open" — check if recovery timeout elapsed
        opened_at = row["opened_at"]
        if not opened_at:
            return True

        try:
            opened_dt = datetime.fromisoformat(opened_at)
        except (ValueError, TypeError):
            return True

        now = datetime.now(timezone.utc)
        elapsed = (now - opened_dt).total_seconds()
        if elapsed >= _recovery_timeout:
            # Transition to HALF_OPEN
            _update_row(cache, source_id, state="half_open")
            logger.info(
                "Circuit breaker for %s: OPEN -> HALF_OPEN (recovery timeout elapsed: %.0fs >= %ds)",
                source_id,
                elapsed,
                _recovery_timeout,
            )
            return False  # Allow one try

        return True  # Still blocked
    finally:
        if own_cache:
            cache.close()


def get_source_health(source_id: str, cache: Any = None) -> dict[str, Any]:
    """Return health metrics for a source.

    Returns dict with:
        ok, source_id, state, failure_count, success_count,
        last_failure_at, last_success_at, consecutive_failures,
        uptime_pct, circuit_open.
    """
    from .cache import Cache

    own_cache = cache is None
    if own_cache:
        cache = Cache()
    try:
        _ensure_table(cache)
        row = cache.db.execute(
            "SELECT * FROM circuit_state WHERE source_id=?", (source_id,)
        ).fetchone()
        if not row:
            return {
                "ok": True,
                "source_id": source_id,
                "state": "closed",
                "failure_count": 0,
                "success_count": 0,
                "last_failure_at": None,
                "last_success_at": None,
                "consecutive_failures": 0,
                "uptime_pct": 100.0,
                "circuit_open": False,
            }

        d = dict(row)
        total = d["success_count"] + d["failure_count"]
        uptime_pct = round((d["success_count"] / total * 100), 1) if total > 0 else 100.0
        return {
            "ok": True,
            "source_id": source_id,
            "state": d["state"],
            "failure_count": d["failure_count"],
            "success_count": d["success_count"],
            "last_failure_at": d["last_failure_at"],
            "last_success_at": d["last_success_at"],
            "consecutive_failures": d["consecutive_failures"],
            "uptime_pct": uptime_pct,
            "circuit_open": d["state"] == "open",
        }
    finally:
        if own_cache:
            cache.close()


def get_all_sources_health(cache: Any = None) -> dict[str, Any]:
    """Return health for all registered sources.

    Returns dict with ok=True and sources dict keyed by source_id.
    """
    from .cache import Cache

    own_cache = cache is None
    if own_cache:
        cache = Cache()
    try:
        _ensure_table(cache)
        rows = cache.db.execute("SELECT source_id FROM circuit_state").fetchall()
        sources = {}
        for row in rows:
            sid = row["source_id"]
            sources[sid] = get_source_health(sid, cache=cache)
        return {
            "ok": True,
            "sources": sources,
        }
    finally:
        if own_cache:
            cache.close()


def reset_circuit(source_id: str, cache: Any = None) -> dict[str, Any]:
    """Manually reset a circuit breaker to CLOSED state.

    Returns dict with ok, source_id, state, previous_state.
    """
    from .cache import Cache

    own_cache = cache is None
    if own_cache:
        cache = Cache()
    try:
        _ensure_table(cache)
        row = cache.db.execute(
            "SELECT * FROM circuit_state WHERE source_id=?", (source_id,)
        ).fetchone()
        previous_state = row["state"] if row else "closed"
        _update_row(
            cache,
            source_id,
            state="closed",
            consecutive_failures=0,
            opened_at=None,
        )
        return {
            "ok": True,
            "source_id": source_id,
            "state": "closed",
            "previous_state": previous_state,
        }
    finally:
        if own_cache:
            cache.close()
