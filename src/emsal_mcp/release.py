from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .sources.registry import capabilities, registry, smoke_all_sync
from .verification import check_cache_integrity, smoke_test_offline


def release_smoke() -> dict[str, Any]:
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
    smoke = release_smoke()
    risks = []
    for cap in capabilities():
        if cap.get("source_id") == "kik" and cap.get("status") == "unavailable":
            risks.append("KİK disabled/unavailable; HTTP 401 requires auth/token flow.")
    score = 100 - len(risks) * 10
    return {"ok": True, "version": __version__, "generated_at": _now(), "readiness_score": score, "release_decision": "ship" if score >= 80 else "review", "smoke": smoke, "risks": risks}


def write_history(out_dir: str | Path, dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    record = {"version": __version__, "generated_at": _now(), "dashboard": dashboard or readiness_dashboard()}
    record["sha256"] = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    path = out / f"history-{record['generated_at'].replace(':','').replace('.','')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path), "record": record}


def compare_history(left: str | Path, right: str | Path) -> dict[str, Any]:
    left_data = json.loads(Path(left).read_text(encoding="utf-8"))
    right_data = json.loads(Path(right).read_text(encoding="utf-8"))
    lscore = left_data.get("dashboard", {}).get("readiness_score", 0)
    rscore = right_data.get("dashboard", {}).get("readiness_score", 0)
    return {"ok": True, "left": str(left), "right": str(right), "score_delta": rscore - lscore, "regression": rscore < lscore, "left_score": lscore, "right_score": rscore}


def release_notes() -> str:
    dash = readiness_dashboard()
    risks = "\n".join(f"- {r}" for r in dash["risks"]) or "- Bilinen bloklayıcı risk yok."
    return f"# Emsal-mcp {__version__} Release Notes\n\nReadiness: {dash['release_decision']} ({dash['readiness_score']}/100)\n\n## Kapsam\n- Resmi/public kaynak adapterları\n- Citation-safe input pack ve kontrollü taslak\n- DOCX/export bundle\n- UDF read/write\n- Smoke/dashboard/history/regression/archive\n\n## Riskler\n{risks}\n"


def archive_release(out_dir: str | Path) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dashboard = readiness_dashboard()
    (out / "dashboard.json").write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "release-notes.md").write_text(release_notes(), encoding="utf-8")
    hist = write_history(out, dashboard)
    manifest = {"version": __version__, "generated_at": _now(), "files": ["dashboard.json", "release-notes.md", Path(hist["path"]).name]}
    (out / "archive-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "out_dir": str(out), "manifest": manifest}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
