from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .models import build_error  # noqa: F401
from .sources.registry import capabilities, registry, smoke_all_sync
from .verification import check_cache_integrity, smoke_test_offline


def release_smoke() -> dict[str, Any]:
    """Run release smoke tests combining offline, cache, and source checks.

    Performs offline smoke tests, cache integrity verification, and per-source
    smoke tests. Returns aggregated pass/fail status.

    Returns:
        Dict with ok, version, generated_at, checks (offline, cache, source status).
    """
    offline = smoke_test_offline()
    cache = check_cache_integrity()
    source_smoke = smoke_all_sync(online=False)
    source_ok = all(s.get("offline_ok", False) for s in source_smoke)
    ok = bool(offline.get("ok")) and bool(cache.get("ok")) and source_ok and all(
        bool(t.get("ok")) for t in offline.get("tests", []) + cache.get("tests", [])
    )
    return {
        "ok": ok,
        "version": __version__,
        "generated_at": _now(),
        "checks": {
            "sources_registered": list(registry()),
            "offline_smoke": offline,
            "cache_integrity": cache,
            "source_smoke": source_smoke,
            "source_smoke_ok": source_ok,
            "citation_safety": any(t.get("name") == "safety_udf_roundtrip" and t.get("ok") for t in offline.get("tests", [])),
            "udf": any(t.get("name") == "safety_udf_roundtrip" and t.get("ok") for t in offline.get("tests", [])),
            "mcp_surface": any(t.get("name") == "imports" and t.get("ok") for t in offline.get("tests", [])),
        },
    }


def readiness_dashboard() -> dict[str, Any]:
    """Compute release readiness score from smoke tests and source capabilities.

    Aggregates risk factors (e.g. unavailable sources) and produces a
    ship/review decision based on the readiness score.

    Returns:
        Dict with ok, version, readiness_score, release_decision, smoke, risks.
    """
    smoke = release_smoke()
    risks = []
    for cap in capabilities():
        if cap.get("source_id") == "kik" and cap.get("status") == "unavailable":
            risks.append("KİK disabled/unavailable; HTTP 401 requires auth/token flow.")
    score = 100 - len(risks) * 10
    return {"ok": True, "version": __version__, "generated_at": _now(), "readiness_score": score, "release_decision": "ship" if score >= 80 else "review", "smoke": smoke, "risks": risks}


def write_history(out_dir: str | Path, dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a release history record with SHA256 integrity hash.

    Args:
        out_dir: Output directory for the history JSON file.
        dashboard: Optional pre-computed dashboard dict (runs readiness_dashboard if None).

    Returns:
        Dict with path to the written record and the record content.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    record = {"version": __version__, "generated_at": _now(), "dashboard": dashboard or readiness_dashboard()}
    record["sha256"] = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    gen_at: str = str(record["generated_at"])
    path = out / f"history-{gen_at.replace(':','').replace('.','')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path), "record": record}


def compare_history(left: str | Path, right: str | Path) -> dict[str, Any]:
    """Compare two release history records and report score delta.

    Args:
        left: Path to the older (left) history JSON file.
        right: Path to the newer (right) history JSON file.

    Returns:
        Dict with ok, score_delta, regression flag, left_score, right_score.
    """
    left_data = json.loads(Path(left).read_text(encoding="utf-8"))
    right_data = json.loads(Path(right).read_text(encoding="utf-8"))
    lscore = left_data.get("dashboard", {}).get("readiness_score", 0)
    rscore = right_data.get("dashboard", {}).get("readiness_score", 0)
    return {"ok": True, "left": str(left), "right": str(right), "score_delta": rscore - lscore, "regression": rscore < lscore, "left_score": lscore, "right_score": rscore}


def release_notes() -> str:
    """Generate markdown release notes from the current readiness dashboard.

    Returns:
        Markdown string with version, readiness, scope, and risk summary.
    """
    dash = readiness_dashboard()
    risks = "\n".join(f"- {r}" for r in dash["risks"]) or "- Bilinen bloklayıcı risk yok."
    return f"# Emsal-mcp {__version__} Release Notes\n\nReadiness: {dash['release_decision']} ({dash['readiness_score']}/100)\n\n## Kapsam\n- Resmi/public kaynak adapterları\n- Citation-safe input pack ve kontrollü taslak\n- DOCX/export bundle\n- UDF read/write\n- Smoke/dashboard/history/regression/archive\n\n## Riskler\n{risks}\n"


def archive_release(out_dir: str | Path) -> dict[str, Any]:
    """Create a release archive with dashboard, notes, and history.

    Args:
        out_dir: Output directory for the release archive.

    Returns:
        Dict with ok, out_dir, manifest (version, files list).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dashboard = readiness_dashboard()
    (out / "dashboard.json").write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "release-notes.md").write_text(release_notes(), encoding="utf-8")
    hist = write_history(out, dashboard)
    manifest = {"version": __version__, "generated_at": _now(), "files": ["dashboard.json", "release-notes.md", Path(hist["path"]).name]}
    (out / "archive-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "out_dir": str(out), "manifest": manifest}


# ── v0.13 Release Command Center ───────────────────────────────────────────


def release_command_center(cache: Any | None = None) -> dict[str, Any]:
    """Comprehensive release verification running all checks.

    Runs source smoke, cache integrity, module imports, FTS5 index status,
    chamber overview, and UDF toolkit status.  Aggregates into a single
    readiness report for release decision-making.

    Args:
        cache: Optional Cache instance for index/chamber checks.

    Returns:
        Dict with ok, overall_readiness, checks, warnings, recommended_actions.
    """
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    # 1. Release smoke (includes source and cache checks)
    try:
        checks["release_smoke"] = release_smoke()
    except Exception as exc:
        checks["release_smoke"] = build_error("CHECK_FAILED", str(exc))
        warnings.append(f"release_smoke başarısız: {exc}")

    # 2. Source capabilities
    try:
        caps = capabilities()
        checks["source_capabilities"] = {
            "ok": len(caps) > 0,
            "source_count": len(caps),
            "unavailable_sources": [
                c.get("source_id") for c in caps
                if c.get("status") == "unavailable"
            ],
            "stable_sources": [
                c.get("source_id") for c in caps
                if c.get("status") == "stable"
            ],
        }
        if checks["source_capabilities"]["unavailable_sources"]:
            warnings.append(
                f"Unavailable sources: "
                f"{', '.join(checks['source_capabilities']['unavailable_sources'])}"
            )
    except Exception as exc:
        checks["source_capabilities"] = build_error("CHECK_FAILED", str(exc))
        warnings.append(f"source_capabilities başarısız: {exc}")

    # 3. Module imports
    module_checks: dict[str, bool] = {}
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
    ]
    for mod in modules_to_check:
        try:
            __import__(mod)
            module_checks[mod] = True
        except Exception as exc:
            module_checks[mod] = False
            warnings.append(f"Module import failed: {mod} - {exc}")
    checks["module_imports"] = {
        "ok": all(module_checks.values()),
        "passed": [k for k, v in module_checks.items() if v],
        "failed": [k for k, v in module_checks.items() if not v],
        "total": len(modules_to_check),
    }

    # 4. FTS5 index status (if cache available)
    try:
        from .semantic import get_index_status
        si = get_index_status(cache=cache) if cache is not None else get_index_status()
        checks["search_index"] = si
        if not si.get("ok") or si.get("unindexed_documents", 0) > 0:
            warnings.append(
                f"Search index: {si.get('unindexed_documents', '?')} unindexed docs"
            )
    except Exception as exc:
        checks["search_index"] = build_error("CHECK_FAILED", str(exc))

    # 5. Chamber overview (if cache available)
    try:
        from .chamber import get_chamber_overview
        co = get_chamber_overview(cache=cache) if cache is not None else get_chamber_overview()
        checks["chambers"] = {
            "ok": co.get("ok", False),
            "total_chambers": co.get("total_chambers", 0),
            "total_documents": co.get("total_documents", 0),
        }
    except Exception as exc:
        checks["chambers"] = build_error("CHECK_FAILED", str(exc))

    # 6. UDF toolkit status
    try:
        from .udf import get_udf_toolkit_status
        udf_status = get_udf_toolkit_status()
        checks["udf_toolkit"] = udf_status
        if not udf_status.get("ok"):
            warnings.append(
                f"UDF toolkit not available: {udf_status.get('warnings', [])}"
            )
    except Exception as exc:
        checks["udf_toolkit"] = build_error("CHECK_FAILED", str(exc))

    # 7. Overall readiness
    check_results = [
        checks["release_smoke"].get("ok", False),
        checks["source_capabilities"].get("ok", False),
        checks["module_imports"].get("ok", False),
    ]
    passed = sum(1 for c in check_results if c)
    overall_readiness = passed / len(check_results) if check_results else 0.0

    return {
        "ok": overall_readiness >= 0.8,
        "version": __version__,
        "generated_at": _now(),
        "overall_readiness": round(overall_readiness * 100),
        "checks_passed": passed,
        "checks_total": len(check_results),
        "checks": checks,
        "warnings": warnings,
        "recommended_actions": _get_recommended_actions(warnings, overall_readiness),
    }


def version_bump(
    major: bool = False,
    minor: bool = False,
    patch: bool = True,
) -> dict[str, Any]:
    """Compute a bumped version string without modifying files.

    Reads current version from __version__ and returns the next version.

    Args:
        major: Bump major version.
        minor: Bump minor version.
        patch: Bump patch version (default).

    Returns:
        Dict with current_version, next_version, bump_type, warnings.
    """
    parts = __version__.split(".")
    if len(parts) < 3:
        parts = (["0", "1", "0"] + [""] * (5 - len(parts)))[:5]

    try:
        maj, min_, pat = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return build_error(
            "VERSION_PARSE_FAILED",
            f"Sürüm parse edilemedi: {__version__}",
            error=f"Sürüm parse edilemedi: {__version__}",
            current_version=__version__,
        )

    if sum([major, minor, patch]) != 1:
        return build_error(
            "INVALID_BUMP_FLAGS",
            "Yalnızca bir bump tipi seçin (--major, --minor, --patch).",
            error="Yalnızca bir bump tipi seçin (--major, --minor, --patch).",
            current_version=__version__,
        )

    if major:
        next_ver = f"{maj + 1}.0.0"
    elif minor:
        next_ver = f"{maj}.{min_ + 1}.0"
    else:
        next_ver = f"{maj}.{min_}.{pat + 1}"

    return {
        "ok": True,
        "current_version": __version__,
        "next_version": next_ver,
        "bump_type": "major" if major else ("minor" if minor else "patch"),
    }


def final_v1_readiness(cache: Any | None = None) -> dict[str, Any]:
    """Final v1.0.0 readiness gate.

    Combines release command center checks with additional v1 criteria:
    - All core modules importable
    - At least 1 stable source
    - Cache integrity passes
    - No blocking warnings

    Returns a go/no-go recommendation.

    Args:
        cache: Optional Cache instance.

    Returns:
        Dict with ok, ready, criteria, blocking_issues, recommendation.
    """
    cmd = release_command_center(cache=cache)

    criteria: dict[str, bool] = {}
    blocking_issues: list[str] = []

    # Criteria: all module imports pass
    mod_imports = cmd.get("checks", {}).get("module_imports", {})
    criteria["all_modules_importable"] = mod_imports.get("ok", False)
    if not criteria["all_modules_importable"]:
        blocking_issues.append("Not all modules are importable.")

    # Criteria: at least 1 stable source
    src_caps = cmd.get("checks", {}).get("source_capabilities", {})
    criteria["has_stable_sources"] = len(src_caps.get("stable_sources", [])) > 0
    if not criteria["has_stable_sources"]:
        blocking_issues.append("No stable sources available.")

    # Criteria: release smoke passes
    criteria["release_smoke_ok"] = cmd.get("checks", {}).get("release_smoke", {}).get("ok", False)
    if not criteria["release_smoke_ok"]:
        blocking_issues.append("Release smoke test failed.")

    # Criteria: no unavailable sources (KİK is expected unavailable)
    unavailable = src_caps.get("unavailable_sources", [])
    non_kik_unavailable = [s for s in unavailable if s != "kik"]
    criteria["only_kik_unavailable"] = len(non_kik_unavailable) == 0
    if non_kik_unavailable:
        blocking_issues.append(f"Non-KİK unavailable sources: {non_kik_unavailable}")

    ready = all(criteria.values())

    return {
        "ok": True,
        "ready": ready,
        "criteria": criteria,
        "blocking_issues": blocking_issues,
        "recommendation": (
            "SHIP: v1.0.0 çıkışa hazır." if ready
            else f"HOLD: {len(blocking_issues)} bloklayıcı sorun var."
        ),
        "command_center": cmd,
        "version": __version__,
        "generated_at": _now(),
    }


def generate_release_summary(cache: Any | None = None) -> dict[str, Any]:
    """Generate a human-readable release summary for the current version.

    Includes version, module inventory, source status, document counts,
    and readiness assessment.

    Args:
        cache: Optional Cache instance.

    Returns:
        Dict with ok, markdown_summary, json_summary, version.
    """
    cmd = release_command_center(cache=cache)

    # Module inventory
    module_status = cmd.get("checks", {}).get("module_imports", {})
    total_modules = module_status.get("total", 0)
    passed_modules = len(module_status.get("passed", []))

    # Source inventory
    src_status = cmd.get("checks", {}).get("source_capabilities", {})
    total_sources = src_status.get("source_count", 0)
    stable_sources = len(src_status.get("stable_sources", []))
    unavailable_sources = src_status.get("unavailable_sources", [])

    # Chamber data
    chamber_data = cmd.get("checks", {}).get("chambers", {})

    # UDF status
    udf_data = cmd.get("checks", {}).get("udf_toolkit", {})

    json_summary = {
        "version": __version__,
        "generated_at": _now(),
        "readiness": cmd.get("overall_readiness", 0),
        "modules": {
            "total": total_modules,
            "importable": passed_modules,
            "failed": total_modules - passed_modules,
        },
        "sources": {
            "total": total_sources,
            "stable": stable_sources,
            "unavailable": unavailable_sources,
        },
        "chambers": chamber_data.get("total_chambers", 0),
        "cached_documents": chamber_data.get("total_documents", 0),
        "udf_toolkit_available": udf_data.get("ok", False),
        "search_index": cmd.get("checks", {}).get("search_index", {}),
    }

    parts = [
        f"# Emsal-mcp {__version__} Release Summary",
        "",
        f"**Generated:** {_now()}",
        f"**Readiness:** {cmd.get('overall_readiness', 0)}%",
        "",
        "## Modules",
        f"- {passed_modules}/{total_modules} modules importable",
        "",
        "## Sources",
        f"- {total_sources} sources registered",
        f"- {stable_sources} stable, {len(unavailable_sources)} unavailable",
    ]
    if unavailable_sources:
        parts.append(f"- Unavailable: {', '.join(unavailable_sources)}")

    parts.extend([
        "",
        "## Data",
        f"- {json_summary['cached_documents']} cached documents",
        f"- {json_summary['chambers']} chambers profiled",
        "",
        "## UDF Toolkit",
        f"- {'Available' if udf_data.get('ok') else 'Not available'}",
        "",
        "## Warnings",
    ])
    for w in cmd.get("warnings", []):
        parts.append(f"- {w}")
    if not cmd.get("warnings"):
        parts.append("- No warnings")

    markdown = "\n".join(parts)

    return {
        "ok": True,
        "markdown_summary": markdown,
        "json_summary": json_summary,
        "version": __version__,
    }


def _get_recommended_actions(warnings: list[str], readiness: float) -> list[str]:
    """Generate recommended actions based on warnings and readiness."""
    actions: list[str] = []
    if readiness < 0.5:
        actions.append("KRİTİK: Bloklayıcı sorunları giderin.")
    elif readiness < 0.8:
        actions.append("UYARI: Orta seviye sorunlar var; release öncesi düzeltin.")
    elif readiness < 1.0:
        actions.append("BİLGİ: Küçük uyarılar var; release sonrası takip edin.")
    if not warnings and readiness >= 1.0:
        actions.append("Tüm kontroller başarılı; release onaylı.")
    return actions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
