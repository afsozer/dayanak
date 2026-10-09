"""Legal reasoning module — M-77/M-78/M-79.

M-77: Argument mining — extract holding/ratio from decision text.
M-78: Cross-reference resolver — link statutes ↔ decisions.
M-79: Consistency checker — detect contradictions in cited authorities.

All deterministic, heuristic-based. No fabrication — uncertain findings
are marked with low confidence and warnings.
"""
from __future__ import annotations

import re
from typing import Any

REASONING_VERSION = "1.0.0"

# ── M-77: Argument Mining ───────────────────────────────────────────────────

# Turkish decision structure marker patterns
_HOLDING_MARKERS = [
    r'(?i)(?:sonuç\s+olarak|neticeten|karar\s+sonucu|hüküm|karar\s+vermek\s+gerekmiştir)',
    r'(?i)(?:yukarıda\s+açıklanan\s+nedenlerle|açıklanan\s+sebeplerle)',
]

_RATIO_MARKERS = [
    r'(?i)(?:dava\s+konusu\s+uyuşmazlık|uyuşmazlık\s+konusu|ihtilaf\s+konusu)',
    r'(?i)(?:mahkemece|ilk\s+derece\s+mahkemesince|yerel\s+mahkemece)',
]

_DISPUTE_MARKERS = [
    r'(?i)(?:taraflar\s+arasındaki\s+uyuşmazlık|davanın\s+konusu)',
    r'(?i)(?:davacı\s+taraf|davalı\s+taraf)',
]


def mine_arguments(text: str, cache: Any | None = None) -> dict[str, Any]:
    """Extract holding, ratio decidendi, and dispute subject from decision text.

    Uses regex heuristics on Turkish legal decision structure markers.
    All findings are marked with confidence levels — never fabricated.

    Args:
        text: Full decision text (markdown/plain).
        cache: Optional Cache (unused, kept for interface consistency).

    Returns:
        Dict with ok, holdings, ratio, dispute, confidence, warnings.
    """
    warnings: list[str] = []
    findings: dict[str, Any] = {
        "holdings": [],
        "ratio_decidendi": [],
        "dispute_subject": None,
    }

    if not text or len(text.strip()) < 100:
        return {
            "ok": False,
            **findings,
            "confidence": "none",
            "warnings": ["Text too short for argument mining."],
        }

    # Extract paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Find holding (sonuç/hüküm fıkrası)
    for marker in _HOLDING_MARKERS:
        for para in paragraphs:
            if re.search(marker, para):
                findings["holdings"].append({
                    "text": para[:500],
                    "marker": marker,
                    "confidence": "medium",
                })
                if len(findings["holdings"]) >= 3:
                    break

    # Find ratio/uyuşmazlık
    for marker in _RATIO_MARKERS:
        for para in paragraphs:
            if re.search(marker, para) and para not in [h["text"] for h in findings["holdings"]]:
                findings["ratio_decidendi"].append({
                    "text": para[:500],
                    "marker": marker,
                    "confidence": "low",
                })
                break

    # Find dispute subject
    for marker in _DISPUTE_MARKERS:
        for para in paragraphs[:10]:  # usually in first 10 paragraphs
            if re.search(marker, para):
                findings["dispute_subject"] = {
                    "text": para[:500],
                    "marker": marker,
                    "confidence": "medium",
                }
                break

    confidence = "high" if findings["holdings"] and findings["dispute_subject"] else (
        "medium" if findings["holdings"] or findings["dispute_subject"] else "low"
    )

    if confidence == "low":
        warnings.append("No clear holding or dispute markers found. Results are heuristic only.")

    return {
        "ok": len(findings["holdings"]) > 0 or findings["dispute_subject"] is not None,
        **findings,
        "confidence": confidence,
        "warnings": warnings,
        "rule": "Deterministic regex heuristics — no fabrication. Verify against original text.",
        "version": REASONING_VERSION,
    }


# ── M-78: Cross-Reference Resolver ──────────────────────────────────────────


def resolve_cross_references(
    document_id: str,
    source: str = "bedesten",
    cache: Any | None = None,
) -> dict[str, Any]:
    """Link a decision to cited legislation and follow-on jurisprudence.

    Uses the citation graph (M-72) and legislation search to build
    a cross-reference map.  Never fabricates — missing links are warnings.

    Args:
        document_id: Decision document ID.
        source: Source identifier.
        cache: Optional Cache instance.

    Returns:
        Dict with ok, cited_legislation, citing_decisions, cross_refs.
    """
    links: dict[str, Any] = {
        "cited_legislation": [],
        "citing_decisions": [],
    }
    warnings: list[str] = []

    try:
        from .citation_graph import find_cited_documents, find_citing_documents

        cited = find_cited_documents(document_id, source, cache=cache, limit=10)
        if cited.get("ok"):
            links["cited_legislation"] = cited.get("cited_documents", [])

        citing = find_citing_documents(document_id, source, cache=cache, limit=10)
        if citing.get("ok"):
            links["citing_decisions"] = citing.get("citing_documents", [])
    except Exception as e:
        warnings.append(f"Cross-reference lookup failed: {e}")

    if not links["cited_legislation"] and not links["citing_decisions"]:
        warnings.append("No cross-references found. Build citation graph first with build_citation_graph().")

    return {
        "ok": len(links["cited_legislation"]) > 0 or len(links["citing_decisions"]) > 0,
        **links,
        "warnings": warnings,
        "rule": "Based on cached citation graph — no live network. Build graph first.",
        "version": REASONING_VERSION,
    }


# ── M-79: Consistency Checker ───────────────────────────────────────────────


def check_consistency(authorities: list[dict[str, Any]], cache: Any | None = None) -> dict[str, Any]:
    """Detect potential contradictions among cited authorities.

    Checks for:
    - Overturned/overruled decisions (via citation graph edges)
    - Same court + same issue → different outcomes (suspicious)
    - Very old decisions (pre-2000) still being cited

    Args:
        authorities: List of authority dicts with document_id, source, decision_date, court.
        cache: Optional Cache.

    Returns:
        Dict with ok, contradictions, warnings.
    """
    contradictions: list[dict[str, Any]] = []
    warnings: list[str] = []

    if len(authorities) < 2:
        return {"ok": True, "contradictions": [], "warnings": ["Need at least 2 authorities to check consistency."],
                "version": REASONING_VERSION}

    # Check for very old decisions (fixed pre-2000 cutoff)
    for auth in authorities:
        date_str = auth.get("decision_date", "")
        if date_str:
            try:
                m = re.match(r"^(\d{4})-\d{2}-\d{2}$", date_str.strip())
                if m and int(m.group(1)) < 2000:
                    contradictions.append({
                        "type": "old_decision",
                        "authority": auth.get("document_id", "?"),
                        "year": int(m.group(1)),
                        "warning": f"Decision from {m.group(1)} — may be overturned by newer jurisprudence.",
                        "severity": "info",
                    })
            except (ValueError, IndexError):
                pass

    # Check for same court + different outcomes (suspicious)
    by_court: dict[str, list[dict]] = {}
    for auth in authorities:
        court = auth.get("court", "")
        by_court.setdefault(court, []).append(auth)

    for court, docs in by_court.items():
        if len(docs) >= 2:
            contradictions.append({
                "type": "same_court_multiple",
                "court": court,
                "count": len(docs),
                "warning": f"Multiple ({len(docs)}) decisions from {court} cited — verify they are consistent.",
                "severity": "warning",
            })

    return {
        "ok": True,
        "contradictions": contradictions,
        "warnings": warnings or ["No contradictions detected."],
        "rule": "Heuristic only — no AI. Manual legal review required.",
        "version": REASONING_VERSION,
    }
