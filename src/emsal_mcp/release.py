"""Release module — trimmed to 2 functions (M-103).

Public entry points:

- ``final_v1_readiness`` — v1.0.0 readiness gate (used by validation gate).
- ``version`` — simple version report dict.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import __version__


def version() -> dict[str, Any]:
    """Return a simple version report dict.

    Returns:
        Dict with version, module, generated_at.
    """
    return {
        "version": __version__,
        "module": "emsal_mcp",
        "generated_at": _now(),
    }


def final_v1_readiness(cache: Any | None = None) -> dict[str, Any]:
    """Final v1.0.0 readiness gate.

    Runs the following checks directly (no longer delegates to a
    ``release_command_center`` wrapper):

    1. **Module imports** — every core module must be importable.
    2. **Stable sources** — at least one source must report ``stable``.
    3. **Smoke tests** — offline smoke, cache integrity, and per-source
       offline smoke must all pass.
    4. **No unavailable sources** — zero sources flagged ``unavailable``.

    Args:
        cache: Optional ``Cache`` instance for index/chamber checks.

    Returns:
        Dict with ok, ready, criteria, blocking_issues, recommendation,
        checks, version, generated_at.
    """
    from .sources.registry import capabilities, smoke_all_sync
    from .verification import check_cache_integrity, smoke_test_offline

    criteria: dict[str, bool] = {}
    blocking_issues: list[str] = []
    checks: dict[str, Any] = {}

    # ── 1. Module imports ───────────────────────────────────────────────
    modules_to_check = [
        "emsal_mcp.citation",
        "emsal_mcp.petition",
        "emsal_mcp.exporter",
        "emsal_mcp.udf",
        "emsal_mcp.legislation",
        "emsal_mcp.semantic",
        "emsal_mcp.chamber",
        "emsal_mcp.research",
        "emsal_mcp.safety",
        "emsal_mcp.cache",
        "emsal_mcp.models",
        "emsal_mcp.document",
        "emsal_mcp.verification",
        "emsal_mcp.citation_graph",
        "emsal_mcp.eval_metrics",
        "emsal_mcp.query_understanding",
    ]
    module_checks: dict[str, bool] = {}
    for mod in modules_to_check:
        try:
            __import__(mod)
            module_checks[mod] = True
        except Exception:
            module_checks[mod] = False
    criteria["all_modules_importable"] = all(module_checks.values())
    if not criteria["all_modules_importable"]:
        failed = [k for k, v in module_checks.items() if not v]
        blocking_issues.append(f"Not all modules are importable. Failed: {failed}")
    checks["module_imports"] = {
        "ok": criteria["all_modules_importable"],
        "passed": [k for k, v in module_checks.items() if v],
        "failed": [k for k, v in module_checks.items() if not v],
        "total": len(modules_to_check),
    }

    # ── 2. Source capabilities ──────────────────────────────────────────
    try:
        caps = capabilities()
        stable_sources = [c.get("source_id") for c in caps if c.get("status") == "stable"]
        unavailable_sources = [c.get("source_id") for c in caps if c.get("status") == "unavailable"]
        criteria["has_stable_sources"] = len(stable_sources) > 0
        criteria["no_unavailable_sources"] = len(unavailable_sources) == 0
        if not criteria["has_stable_sources"]:
            blocking_issues.append("No stable sources available.")
        if unavailable_sources:
            blocking_issues.append(f"Unavailable sources: {unavailable_sources}")
        checks["source_capabilities"] = {
            "ok": criteria["has_stable_sources"] and criteria["no_unavailable_sources"],
            "source_count": len(caps),
            "stable_sources": stable_sources,
            "unavailable_sources": unavailable_sources,
        }
    except Exception as exc:
        criteria["has_stable_sources"] = False
        criteria["no_unavailable_sources"] = False
        blocking_issues.append(f"Source capabilities check failed: {exc}")
        checks["source_capabilities"] = {"ok": False, "error": str(exc)}

    # ── 3. Smoke tests (offline + cache + source) ──────────────────────
    try:
        offline = smoke_test_offline()
        cache_check = check_cache_integrity()
        source_smoke = smoke_all_sync(online=False)
        source_ok = all(s.get("offline_ok", False) for s in source_smoke)
        smoke_ok = (
            bool(offline.get("ok"))
            and bool(cache_check.get("ok"))
            and source_ok
            and all(
                bool(t.get("ok"))
                for t in offline.get("tests", []) + cache_check.get("tests", [])
            )
        )
        criteria["release_smoke_ok"] = smoke_ok
        if not smoke_ok:
            blocking_issues.append("Release smoke test failed.")
        checks["release_smoke"] = {
            "ok": smoke_ok,
            "offline_smoke": offline,
            "cache_integrity": cache_check,
            "source_smoke": source_smoke,
            "source_smoke_ok": source_ok,
        }
    except Exception as exc:
        criteria["release_smoke_ok"] = False
        blocking_issues.append(f"Smoke tests failed: {exc}")
        checks["release_smoke"] = {"ok": False, "error": str(exc)}

    ready = all(criteria.values())

    return {
        "ok": True,
        "ready": ready,
        "criteria": criteria,
        "blocking_issues": blocking_issues,
        "recommendation": (
            "SHIP: v1.0.0 cikisa hazir." if ready
            else f"HOLD: {len(blocking_issues)} bloklayici sorun var."
        ),
        "checks": checks,
        "version": __version__,
        "generated_at": _now(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
