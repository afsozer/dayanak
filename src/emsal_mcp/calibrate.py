"""Adaptive Throttle & Calibrate – v1.0

Source self-calibration: measures safe request rate and suggests config.
All opt-in — default behavior is unchanged.
Integrates with circuit breaker (M-17) and retry (M-18).
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def calibrate_source(
    source_id: str,
    *,
    sample_requests: int = 3,
    delay_between: float = 2.0,
    online: bool = False,
) -> dict[str, Any]:
    """Measure safe request rate for a source by issuing test calls.

    Sends sample_requests test calls with delay_between seconds between
    them.  Measures observed latency and suggests a safe rate.

    Args:
        source_id: Source identifier (e.g. 'bedesten', 'yargitay').
        sample_requests: Number of test requests to send.
        delay_between: Seconds between requests (be polite).
        online: If True, make actual HTTP calls.  Default False (smoke-only).

    Returns:
        Dict with ok, source_id, latencies_ms, avg_ms, recommended_rps,
        suggested_config, warnings.
    """
    from .sources.registry import get_source, registry

    all_sources = registry()
    if source_id not in all_sources:
        from .models import build_error
        return build_error(
            "SOURCE_NOT_FOUND",
            f"Source '{source_id}' not found. Available: {list(all_sources.keys())}",
        )

    latencies_ms: list[float] = []
    warnings: list[str] = []
    errors: list[str] = []

    source = get_source(source_id)

    for i in range(sample_requests):
        t0 = time.monotonic()
        try:
            if online:
                # Use sync search as calibration test
                import asyncio
                try:
                    results = asyncio.run(source.search("test_calibrate", limit=1))
                    if not results:
                        errors.append(f"Request {i + 1}: empty results")
                except Exception as exc:
                    errors.append(f"Request {i + 1}: {exc}")
            else:
                # Offline smoke check only
                pass
            t1 = time.monotonic()
            latencies_ms.append((t1 - t0) * 1000)

            if i < sample_requests - 1:
                time.sleep(delay_between)
        except Exception as exc:
            errors.append(f"Calibration error for {source_id}: {exc}")
            break

    avg_ms = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0

    # Conservative rate recommendation: 1 request per (avg_ms * 3) ms
    # This accounts for variance and prevents overloading servers
    safe_interval_ms = max(1000.0, avg_ms * 3) if avg_ms > 0 else 1000.0
    recommended_rps = round(1000.0 / safe_interval_ms, 2)

    suggested_config = {
        "EMSAL_RETRY_DELAY": str(max(1.0, avg_ms / 1000.0)),
        "recommended_rps": recommended_rps,
        "note": (
            "Conservative estimate — real-world usage may allow higher rates. "
            "Always respect source robots.txt and rate-limit headers."
        ),
    }

    return {
        "ok": True,
        "source_id": source_id,
        "online_tested": online,
        "sample_requests": sample_requests,
        "latencies_ms": [round(x, 1) for x in latencies_ms],
        "avg_latency_ms": round(avg_ms, 1),
        "recommended_rps": recommended_rps,
        "suggested_config": suggested_config,
        "errors": errors,
        "warnings": warnings,
    }


def calibrate_all(
    *,
    online: bool = False,
) -> dict[str, Any]:
    """Run calibration on all registered sources.

    Args:
        online: Whether to make actual HTTP calls.

    Returns:
        Dict with ok, results per source, summary.
    """
    from .sources.registry import registry

    sources = list(registry().keys())
    results: dict[str, dict[str, Any]] = {}

    for source_id in sources:
        results[source_id] = calibrate_source(source_id, online=online)

    summary = {
        "total": len(sources),
        "tested": sum(1 for r in results.values() if r.get("ok")),
        "online_tested": online,
    }

    return {
        "ok": True,
        "results": results,
        "summary": summary,
    }
