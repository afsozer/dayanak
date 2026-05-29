"""MCP server hardening utilities — input validation, error catalog, concurrency tracking.

Added in M-22.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from .models import build_error

# ── Input Validators ────────────────────────────────────────────────


def validate_non_empty(value: Any) -> tuple[bool, str | None]:
    """Check that a string value is not empty or whitespace-only."""
    if isinstance(value, str) and not value.strip():
        return False, "must not be empty"
    return True, None


def validate_positive_int(value: Any) -> tuple[bool, str | None]:
    """Check that a value is a positive integer (>= 1)."""
    if value is not None and (not isinstance(value, int) or value < 1):
        return False, "must be a positive integer"
    return True, None


def validate_range(min_val: float, max_val: float) -> Callable[[Any], tuple[bool, str | None]]:
    """Return a validator that checks value is within [min_val, max_val]."""

    def _check(value: Any) -> tuple[bool, str | None]:
        if value is not None:
            try:
                v = float(value)
            except (TypeError, ValueError):
                return False, f"must be a number between {min_val} and {max_val}"
            if v < min_val or v > max_val:
                return False, f"must be between {min_val} and {max_val}"
        return True, None

    return _check


def validate_is_dict_with_keys(*required_keys: str) -> Callable[[Any], tuple[bool, str | None]]:
    """Check that a value is a dict containing all required keys."""

    def _check(value: Any) -> tuple[bool, str | None]:
        if value is not None:
            if not isinstance(value, dict):
                return False, "must be a dict"
            missing = [k for k in required_keys if k not in value]
            if missing:
                return False, f"missing required fields: {', '.join(missing)}"
        return True, None

    return _check


# ── Validation Decorator ───────────────────────────────────────────


def validate_tool_input(**validators: Callable[[Any], tuple[bool, str | None]]) -> Callable:
    """Decorator that validates MCP tool input parameters.

    ``validators`` maps parameter names to validator functions.
    Each validator returns ``(is_valid: bool, error_msg: str | None)``.

    Usage::

        @mcp.tool()
        @validate_tool_input(query=validate_non_empty, limit=validate_positive_int)
        async def search_decisions(source: str, query: str, limit: int = 10):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            errors: list[str] = []
            for param, validator in validators.items():
                value = kwargs.get(param)
                is_valid, err_msg = validator(value)
                if not is_valid and value is not None:
                    errors.append(f"{param}: {err_msg}")
            if errors:
                return build_error("INVALID_INPUT", "; ".join(errors))
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ── Concurrency Tracking ───────────────────────────────────────────

_active_requests: int = 0  # informational counter — single-user design


def _track_request(func: Callable) -> Callable:
    """Lightweight wrapper that tracks active request count (informational)."""

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        global _active_requests
        _active_requests += 1
        try:
            return await func(*args, **kwargs)
        finally:
            _active_requests -= 1

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        global _active_requests
        _active_requests += 1
        try:
            return func(*args, **kwargs)
        finally:
            _active_requests -= 1

    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def get_active_requests() -> int:
    """Return the current number of active requests (informational)."""
    return _active_requests


# ── Error Surface Catalog ──────────────────────────────────────────

# All known error codes used in build_error() calls across the codebase.
# Keep in sync when adding new error codes.
KNOWN_ERROR_CODES: list[str] = sorted([
    "ANALYTICS_QUERY_FAILED",
    "ANALYTICS_RECORD_FAILED",
    "ARGUMENT_MAP_MISSING",
    "CHAMBER_NOT_FOUND",
    "CHECK_FAILED",
    "CIRCUIT_OPEN",
    "CLUSTER_NOT_FOUND",
    "CONVERSION_FAILED",
    "DB_QUERY_FAILED",
    "DEDUP_FAILED",
    "DEDUP_LOOKUP_FAILED",
    "DEDUP_STATS_FAILED",
    "DOC_NOT_FOUND",
    "DRAFT_DIR_NOT_FOUND",
    "DRAFT_NOT_FOUND",
    "EMPTY_DB",
    "EMPTY_DOCUMENT",
    "EXCEPTION",
    "EXPERIMENTAL_REQUIRED",
    "FETCH_FAILED",
    "FILE_NOT_FOUND",
    "GRAPH_BUILD_FAILED",
    "GRAPH_QUERY_FAILED",
    "GRAPH_STATS_FAILED",
    "INDEX_BUILD_FAILED",
    "INDEX_QUERY_FAILED",
    "INTEGRITY_CHECK_FAILED",
    "INVALID_BUMP_FLAGS",
    "INVALID_FORMAT",
    "INVALID_HYBRID_WEIGHT",
    "INVALID_INPUT",
    "MERGE_FAILED",
    "NOT_A_DIRECTORY",
    "NO_CHAMBERS_AVAILABLE",
    "NO_CHAMBERS_FOUND",
    "NO_DOCUMENTS_FOUND",
    "NO_ISSUES",
    "NO_KEYWORDS",
    "ORPHAN_CLEANUP_FAILED",
    "PACK_NOT_FOUND",
    "PARSE_FAILED",
    "READ_ERROR",
    "SEARCH_FAILED",
    "TEMPLATE_NOT_FOUND",
    "TOOLKIT_UNAVAILABLE",
    "VACUUM_FAILED",
    "VERSION_DIR_ERROR",
    "VERSION_PARSE_FAILED",
])


def get_error_codes() -> dict[str, Any]:
    """Return the full error code catalog used in the project."""
    return {
        "known_codes": KNOWN_ERROR_CODES,
        "total": len(KNOWN_ERROR_CODES),
    }
