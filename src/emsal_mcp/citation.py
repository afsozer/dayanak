"""v0.6 Citation verification and formatting for Turkish legal citations.

Never fabricates missing date/chamber/E/K numbers; missing fields produce
warnings and lower confidence scores.  Tests inject fake sources via
``cache`` and ``sources_override`` parameters — no live network calls.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Literal

from .cache import Cache
from .models import Document, build_error


# ---------------------------------------------------------------------------
# Candidate extraction patterns
# ---------------------------------------------------------------------------

# Court names (Turkish legal system)
_COURT_PATTERNS: list[tuple[str, str]] = [
    (r"Yarg[ıi]tay", "Yargıtay"),
    (r"Dan[ıi].tay", "Danıştay"),
    (r"Anayasa\s+Mahkemesi|AYM", "Anayasa Mahkemesi"),
    (r"Say[ıi].tay", "Sayıştay"),
    (r"Rekabet\s+Kurulu|Rekabet\s+Kurumu", "Rekabet Kurulu"),
    (r"T[ıi]caret\s+Mahkemesi", "Ticaret Mahkemesi"),
    (r"[İi]cra\s+Hukuk\s+Mahkemesi", "İcra Hukuk Mahkemesi"),
    (r"Asliye\s+Hukuk", "Asliye Hukuk Mahkemesi"),
    (r"Asliye\s+Ceza", "Asliye Ceza Mahkemesi"),
    (r"[İş]g?li?\s+Mahkemesi", "İş Mahkemesi"),
]

# Chamber / daire hints
_CHAMBER_PATTERNS: list[tuple[str, str]] = [
    (r"(\d+)\.\s*(?:Hukuk|Ceza|Ticaret|İş|İdare)\s*(?:Dairesi|Genel\s+Kurulu|Kurulu)", None),
    (r"Hukuk\s+(?:Genel\s+)?Kurulu", None),
    (r"Ceza\s+(?:Genel\s+)?Kurulu", None),
    (r"(\d+)\.\s*Daire(?:si)?", None),
    (r"(Birinci|[İi]kinci|[Üü]çüncü|D[öo]rdüncü|[Beş]inci|[Altı]ncı|[Yed]inci|[Sek]inci|[Dok]inci|[On])\s+(?:Hukuk|Ceza)?\s*(?:Dairesi)?", None),
]

# Esas (case) number: YYYY/NNNNN or YYYY/NNNNN E or similar
_ESAS_PATTERN = re.compile(
    r"(?:Esas\s*(?:No|Numaras[ıi])?)\s*[:.]?\s*(\d{4}/\d+(?:\s*[EeKk])?)",
    re.IGNORECASE,
)

# Karar (decision) number: NN/NNNNN or similar
_KARAR_PATTERN = re.compile(
    r"(?:Karar\s*(?:No|Numaras[ıi])?)\s*[:.]?\s*(\d+/\d+)",
    re.IGNORECASE,
)

# Standalone year/case number patterns (common in Turkish citations)
_STANDALONE_ESAS = re.compile(
    r"\b(\d{4}/\d{3,6})\b"
)

_STANDALONE_KARAR = re.compile(
    r"\b(\d{1,3}/\d{3,6})\b"
)

# Date patterns (Turkish formats)
_DATE_PATTERNS: list[tuple[str, str]] = [
    (r"(\d{1,2})[./](\d{1,2})[./](\d{4})", "dmy"),   # DD.MM.YYYY
    (r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", "ymd"),  # YYYY-MM-DD
    (r"(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+(\d{4})", "my"),
]

# Document-id-like references (e.g., "bedesten:12345", "yargitay-2024/12345")
_DOC_ID_PATTERN = re.compile(
    r"\b([a-z]+[_-]?\d{4,}[/]\d+|\w+:\d{4,})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class CitationCandidate:
    """A potential legal citation extracted from text."""

    __slots__ = (
        "raw_text", "court", "chamber", "date", "esas_no", "karar_no",
        "document_id_ref", "confidence", "warnings", "position",
    )

    def __init__(
        self,
        raw_text: str,
        court: str | None = None,
        chamber: str | None = None,
        date: str | None = None,
        esas_no: str | None = None,
        karar_no: str | None = None,
        document_id_ref: str | None = None,
        confidence: Literal["high", "medium", "low"] = "medium",
        warnings: list[str] | None = None,
        position: int = 0,
    ) -> None:
        self.raw_text = raw_text
        self.court = court
        self.chamber = chamber
        self.date = date
        self.esas_no = esas_no
        self.karar_no = karar_no
        self.document_id_ref = document_id_ref
        self.confidence = confidence
        self.warnings = warnings or []
        self.position = position

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "court": self.court,
            "chamber": self.chamber,
            "date": self.date,
            "esas_no": self.esas_no,
            "karar_no": self.karar_no,
            "document_id_ref": self.document_id_ref,
            "confidence": self.confidence,
            "warnings": self.warnings,
            "position": self.position,
        }


class VerificationFinding:
    """A single verification result for a citation candidate."""

    __slots__ = ("candidate", "matched", "match_score", "matched_document", "warnings")

    def __init__(
        self,
        candidate: CitationCandidate,
        matched: bool = False,
        match_score: float = 0.0,
        matched_document: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.candidate = candidate
        self.matched = matched
        self.match_score = match_score
        self.matched_document = matched_document
        self.warnings = warnings or []

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "candidate": self.candidate.to_dict(),
            "matched": self.matched,
            "match_score": self.match_score,
        }
        if self.matched_document:
            d["matched_document"] = self.matched_document
        if self.warnings:
            d["warnings"] = self.warnings
        return d


# ---------------------------------------------------------------------------
# Candidate extraction
# ---------------------------------------------------------------------------

def _detect_court(text: str) -> str | None:
    """Detect court name from text."""
    for pattern, name in _COURT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return None


def _detect_chamber(text: str) -> str | None:
    """Detect chamber/daire from text."""
    for pattern, _ in _CHAMBER_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None


def _detect_date(text: str) -> str | None:
    """Detect date from text.  Returns ISO-ish string or None."""
    # Try explicit date patterns
    for pattern, fmt in _DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            if fmt == "dmy":
                return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
            elif fmt == "ymd":
                return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
            elif fmt == "my":
                month_map = {
                    "ocak": "01", "şubat": "02", "mart": "03", "nisan": "04",
                    "mayıs": "05", "haziran": "06", "temmuz": "07", "ağustos": "08",
                    "eylül": "09", "ekim": "10", "kasım": "11", "aralık": "12",
                }
                month = month_map.get(m.group(1).lower(), "01")
                return f"{m.group(2)}-{month}-01"
    return None


def _detect_esas_no(text: str) -> str | None:
    """Detect esas (case) number."""
    m = _ESAS_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    m = _STANDALONE_ESAS.search(text)
    if m:
        return m.group(1)
    return None


def _detect_karar_no(text: str) -> str | None:
    """Detect karar (decision) number."""
    m = _KARAR_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    # Try standalone pattern only if explicitly near "karar" context
    if re.search(r"karar", text, re.IGNORECASE):
        m = _STANDALONE_KARAR.search(text)
        if m:
            return m.group(1)
    return None


def _detect_doc_id_ref(text: str) -> str | None:
    """Detect document-id-like reference."""
    m = _DOC_ID_PATTERN.search(text)
    if m:
        return m.group(1)
    return None


def _compute_confidence(candidate: CitationCandidate) -> Literal["high", "medium", "low"]:
    """Compute confidence based on available fields."""
    score = 0
    if candidate.court:
        score += 3
    if candidate.chamber:
        score += 2
    if candidate.date:
        score += 2
    if candidate.esas_no:
        score += 2
    if candidate.karar_no:
        score += 2

    if score >= 7:
        return "high"
    elif score >= 4:
        return "medium"
    else:
        return "low"


def _compute_warnings(candidate: CitationCandidate) -> list[str]:
    """Compute warnings for missing metadata fields."""
    warnings: list[str] = []
    if not candidate.court:
        warnings.append("Mahkeme bilgisi tespit edilemedi.")
    if not candidate.chamber:
        warnings.append("Daire/bölüm bilgisi tespit edilemedi.")
    if not candidate.date:
        warnings.append("Karar tarihi tespit edilemedi.")
    if not candidate.esas_no:
        warnings.append("Esas numarası tespit edilemedi.")
    if not candidate.karar_no:
        warnings.append("Karar numarası tespit edilemedi.")
    return warnings


def extract_citation_candidates(
    text: str,
    *,
    limit: int = 5,
) -> list[CitationCandidate]:
    """Extract citation candidates from text using regex patterns.

    Scans the text for Turkish legal citation patterns and returns
    candidates ranked by field completeness.  Never fabricates missing
    metadata; missing fields produce warnings and lower confidence.

    Args:
        text: Input text to scan for citations.
        limit: Maximum number of candidates to return.

    Returns:
        List of CitationCandidate objects, sorted by confidence (descending).
    """
    candidates: list[CitationCandidate] = []

    # Strategy 1: Find sentence/line spans containing court names
    lines = text.split("\n")
    for line_no, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 10:
            continue

        court = _detect_court(line_stripped)
        if court is None:
            continue

        chamber = _detect_chamber(line_stripped)
        date = _detect_date(line_stripped)
        esas_no = _detect_esas_no(line_stripped)
        karar_no = _detect_karar_no(line_stripped)
        doc_id_ref = _detect_doc_id_ref(line_stripped)

        cand = CitationCandidate(
            raw_text=line_stripped[:500],
            court=court,
            chamber=chamber,
            date=date,
            esas_no=esas_no,
            karar_no=karar_no,
            document_id_ref=doc_id_ref,
            position=line_no,
        )
        cand.warnings = _compute_warnings(cand)
        cand.confidence = _compute_confidence(cand)
        candidates.append(cand)

    # Strategy 2: Find standalone esas/karar patterns in full text
    if not candidates:
        for m in _STANDALONE_ESAS.finditer(text):
            context_start = max(0, m.start() - 100)
            context_end = min(len(text), m.end() + 100)
            context = text[context_start:context_end]

            court = _detect_court(context)
            date = _detect_date(context)
            chamber = _detect_chamber(context)

            cand = CitationCandidate(
                raw_text=context.strip()[:500],
                court=court,
                chamber=chamber,
                date=date,
                esas_no=m.group(1),
                position=m.start(),
            )
            cand.warnings = _compute_warnings(cand)
            cand.confidence = _compute_confidence(cand)
            candidates.append(cand)

    # Deduplicate by (court, esas_no, karar_no) key
    seen: set[tuple[str | None, str | None, str | None]] = set()
    unique: list[CitationCandidate] = []
    for c in candidates:
        key = (c.court, c.esas_no, c.karar_no)
        if key not in seen:
            seen.add(key)
            unique.append(c)

    # Sort by confidence (high > medium > low), then by field count
    conf_order = {"high": 0, "medium": 1, "low": 2}
    unique.sort(key=lambda c: (conf_order.get(c.confidence, 3), -sum(1 for f in [c.court, c.chamber, c.date, c.esas_no, c.karar_no] if f)))

    return unique[:int(limit)]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_legal_citation(
    source: dict[str, Any] | Document | None = None,
    *,
    document_id: str | None = None,
    style: Literal["petition", "parenthetical", "short"] = "petition",
    refetch: bool = False,
    cache: Cache | None = None,
    source_client: Any | None = None,
) -> dict[str, Any]:
    """Format a legal citation from document metadata.

    Uses only existing metadata; never fabricates date/chamber/esas/karar.
    Missing fields produce warnings and lower confidence.

    Args:
        source: Document dict, Document model, or None (look up by document_id).
        document_id: Document ID to look up if source is None.
        style: Formatting style — 'petition', 'parenthetical', or 'short'.
        refetch: If True, attempt to re-fetch from source.
        cache: Optional Cache instance for lookups.
        source_client: Optional source client for re-fetching.

    Returns:
        Dict with formatted_citation, warnings, confidence, quote_usable,
        draft_usable, content_status, source_url, metadata fields.
    """
    warnings: list[str] = []
    meta: dict[str, Any] = {}

    # Resolve document
    doc: Document | None = None
    if isinstance(source, Document):
        doc = source
    elif isinstance(source, dict):
        # Try to build from dict
        try:
            doc = Document(**source)
        except Exception:
            # Partial dict — extract what we can
            meta = source
    elif source is None and document_id:
        # Look up from cache
        c = cache or Cache()
        try:
            # Search for document in cache v2
            rows = c.db.execute(
                "SELECT * FROM documents_v2 WHERE document_id=? LIMIT 1",
                (document_id,),
            ).fetchone()
            if rows:
                meta = dict(rows)
        finally:
            if cache is None:
                c.close()

    # Extract metadata fields
    if doc:
        court = doc.court
        chamber = doc.chamber
        date = doc.decision_date
        esas_no = doc.esas_no
        karar_no = doc.karar_no
        source_url = doc.source_url
        content_status = doc.content_status.value if doc.content_status else "unknown"
        quote_usable = doc.quote_usable
        draft_usable = doc.draft_usable
        source_id = doc.source
        doc_id = doc.document_id
    else:
        court = meta.get("court")
        chamber = meta.get("chamber")
        date = meta.get("decision_date")
        esas_no = meta.get("esas_no")
        karar_no = meta.get("karar_no")
        source_url = meta.get("source_url")
        content_status = meta.get("content_status", "unknown")
        quote_usable = meta.get("quote_usable", False)
        draft_usable = meta.get("draft_usable", False)
        source_id = meta.get("source", "")
        doc_id = meta.get("document_id", document_id or "")

    # Check for missing fields
    if not court:
        warnings.append("Mahkeme bilgisi eksik; kaynaktan doğrulayın.")
    if not chamber:
        warnings.append("Daire bilgisi eksik.")
    if not date:
        warnings.append("Karar tarihi eksik.")
    if not esas_no:
        warnings.append("Esas numarası eksik.")
    if not karar_no:
        warnings.append("Karar numarası eksik.")
    if not source_url:
        warnings.append("Kaynak URL eksik; resmi doğrulama yapılamaz.")

    # Format citation based on style
    if style == "petition":
        parts: list[str] = []
        if court:
            parts.append(court)
        if chamber:
            parts.append(chamber)
        if esas_no:
            parts.append(f"E.{esas_no}")
        if karar_no:
            parts.append(f"K.{karar_no}")
        if date:
            parts.append(f"Tarihi: {date}")
        formatted = ", ".join(parts) if parts else f"{source_id}:{doc_id}"

    elif style == "parenthetical":
        parts = []
        if court:
            parts.append(court)
        if chamber:
            parts.append(chamber)
        if date:
            parts.append(date)
        if esas_no and karar_no:
            parts.append(f"E.{esas_no}, K.{karar_no}")
        elif esas_no:
            parts.append(f"E.{esas_no}")
        elif karar_no:
            parts.append(f"K.{karar_no}")
        formatted = f"({', '.join(parts)})" if parts else f"({source_id}:{doc_id})"

    elif style == "short":
        if court:
            _SHORT_COURT_MAP = {
                "Yargıtay": "Ygt.",
                "Danıştay": "Dst.",
                "Anayasa Mahkemesi": "AYM",
                "Sayıştay": "Sst.",
                "Rekabet Kurulu": "RK",
            }
            short_court = _SHORT_COURT_MAP.get(court)
            if not short_court:
                short_court = court.replace("Mahkemesi", "Mhk.").replace("Kurulu", "Krl.").replace("Dairesi", "D.")
            parts = [short_court]
            if esas_no:
                parts.append(esas_no)
            formatted = " ".join(parts)
        else:
            formatted = f"{source_id}:{doc_id}"
    else:
        warnings.append(f"Bilinmeyen format: '{style}'; 'petition' kullanıldı.")
        formatted = f"{court or ''} {esas_no or ''}".strip() or f"{source_id}:{doc_id}"

    # Compute confidence
    fields_present = sum(1 for f in [court, chamber, date, esas_no, karar_no] if f)
    if fields_present >= 5:
        confidence = "high"
    elif fields_present >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "formatted_citation": formatted,
        "style": style,
        "court": court,
        "chamber": chamber,
        "date": date,
        "esas_no": esas_no,
        "karar_no": karar_no,
        "document_id": doc_id,
        "source": source_id,
        "source_url": source_url,
        "content_status": content_status,
        "quote_usable": quote_usable,
        "draft_usable": draft_usable,
        "confidence": confidence,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Verification pipeline
# ---------------------------------------------------------------------------

def _search_local_cache(
    cache: Cache,
    candidate: CitationCandidate,
    *,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Search local cache for a candidate citation."""
    conditions: list[str] = []
    params: list[Any] = []

    if candidate.court:
        conditions.append("court LIKE ?")
        params.append(f"%{candidate.court}%")
    if candidate.esas_no:
        conditions.append("esas_no LIKE ?")
        params.append(f"%{candidate.esas_no}%")
    if candidate.karar_no:
        conditions.append("karar_no LIKE ?")
        params.append(f"%{candidate.karar_no}%")
    if source:
        conditions.append("source = ?")
        params.append(source)

    if not conditions:
        return []

    where = " WHERE " + " AND ".join(conditions)
    sql = f"SELECT * FROM documents_v2{where} LIMIT 10"
    rows = cache.db.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _score_metadata_match(candidate: CitationCandidate, doc: dict[str, Any]) -> float:
    """Score how well a cached document matches a citation candidate."""
    score = 0.0
    total = 0.0

    if candidate.court and doc.get("court"):
        total += 3.0
        if candidate.court.lower() in doc["court"].lower() or doc["court"].lower() in candidate.court.lower():
            score += 3.0
        else:
            score += 0.5  # partial

    if candidate.chamber and doc.get("chamber"):
        total += 2.0
        if candidate.chamber.lower() in doc["chamber"].lower():
            score += 2.0

    if candidate.esas_no and doc.get("esas_no"):
        total += 3.0
        if candidate.esas_no == doc["esas_no"]:
            score += 3.0
        elif candidate.esas_no in doc["esas_no"] or doc["esas_no"] in candidate.esas_no:
            score += 2.0

    if candidate.karar_no and doc.get("karar_no"):
        total += 3.0
        if candidate.karar_no == doc["karar_no"]:
            score += 3.0
        elif candidate.karar_no in doc["karar_no"] or doc["karar_no"] in candidate.karar_no:
            score += 2.0

    if candidate.date and doc.get("decision_date"):
        total += 2.0
        if candidate.date == doc["decision_date"]:
            score += 2.0

    return round(score / total, 4) if total > 0 else 0.0


def _live_search_fake(
    candidate: CitationCandidate,
    source_client: Any | None = None,
    *,
    cache: Cache | None = None,
) -> list[dict[str, Any]]:
    """Attempt live search for a candidate.

    In production this would call source_client.search(); tests inject
    a fake client or return empty results.
    """
    if source_client is None:
        return []

    try:
        import asyncio
        query_parts = [p for p in [candidate.court, candidate.esas_no, candidate.karar_no] if p]
        query = " ".join(query_parts)
        if not query:
            return []
        results = asyncio.run(source_client.search(query, limit=3))
        return [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in results]
    except Exception:
        return []


def verify_legal_citation(
    text: str | None = None,
    *,
    file_path: str | Path | None = None,
    source: str | None = None,
    limit: int = 5,
    fetch: int = 3,
    no_live: bool = False,
    live_only: bool = False,
    min_score: float = 1.0,
    strategy_debug: bool = False,
    cache: Cache | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify legal citations found in text or file.

    Pipeline: load text → extract candidates → search local cache (unless
    live_only) → live search (unless no_live) → rank by metadata match score →
    optionally fetch docs → return structured result.

    Args:
        text: Text content to verify.  Mutually exclusive with file_path.
        file_path: Path to file to read.  Mutually exclusive with text.
        source: Filter cache/live search to a specific source.
        limit: Max candidates to extract.
        fetch: Max documents to fetch for top candidates.
        no_live: Skip live search (cache-only mode).
        live_only: Skip local cache search.
        min_score: Minimum match score threshold.
        strategy_debug: Include extraction/search strategy details.
        cache: Optional Cache instance.
        sources_override: Optional dict mapping source_id to fake client.

    Returns:
        Dict with candidates, search_attempts, matched_documents,
        formatted_citations, verification_findings, warnings,
        recommended_next_steps, timing.
    """
    t0 = time.time()
    warnings: list[str] = []
    search_attempts: list[dict[str, Any]] = []
    matched_documents: list[dict[str, Any]] = []
    formatted_citations: list[dict[str, Any]] = []
    verification_findings: list[dict[str, Any]] = []
    strategy_debug_info: dict[str, Any] = {}

    # --- Phase 1: Load text ---
    if file_path:
        fp = Path(file_path)
        if not fp.exists():
            return build_error(
                "FILE_NOT_FOUND",
                f"Dosya bulunamadı: {fp}",
                error=f"Dosya bulunamadı: {fp}",
                candidates=[],
                search_attempts=[],
                matched_documents=[],
                formatted_citations=[],
                verification_findings=[],
                warnings=[f"Dosya bulunamadı: {fp}"],
                recommended_next_steps=["Dosya yolunu kontrol edin."],
                timing={"elapsed_ms": round((time.time() - t0) * 1000, 1)},
            )
        text = fp.read_text(encoding="utf-8")
    elif text is None:
        return build_error(
            "INVALID_INPUT",
            "Metin veya dosya yolu belirtilmedi.",
            error="Metin veya dosya yolu belirtilmedi.",
            candidates=[],
            search_attempts=[],
            matched_documents=[],
            formatted_citations=[],
            verification_findings=[],
            warnings=["Metin veya dosya yolu belirtilmedi."],
            recommended_next_steps=["text veya file_path parametresi verin."],
            timing={"elapsed_ms": round((time.time() - t0) * 1000, 1)},
        )

    # --- Phase 2: Extract candidates ---
    candidates = extract_citation_candidates(text, limit=limit)
    strategy_debug_info["extraction_count"] = len(candidates)
    strategy_debug_info["text_length"] = len(text)

    if not candidates:
        return {
            "ok": True,
            "candidates": [],
            "search_attempts": [],
            "matched_documents": [],
            "formatted_citations": [],
            "verification_findings": [],
            "warnings": ["Metinde hukuki referans kalıbı bulunamadı."],
            "recommended_next_steps": [
                "Farklı bir metin deneyin.",
                "Referans kalıplarını kontrol edin.",
            ],
            "timing": {"elapsed_ms": round((time.time() - t0) * 1000, 1)},
        }

    # --- Phase 3: Search local cache (unless live_only) ---
    c = cache or Cache()
    own_cache = cache is None
    try:
        for cand in candidates:
            if live_only:
                search_attempts.append({
                    "candidate": cand.to_dict(),
                    "method": "live_only",
                    "skipped_local": True,
                })
                continue

            local_results = _search_local_cache(c, cand, source=source)
            search_attempts.append({
                "candidate": cand.to_dict(),
                "method": "local_cache",
                "results_count": len(local_results),
            })
            matched_documents.extend(local_results)
    finally:
        if own_cache:
            c.close()

    # --- Phase 4: Live search (unless no_live) ---
    if not no_live:
        for cand in candidates[:fetch]:
            effective_override = sources_override or {}
            # Determine source client
            client = None
            if source and source in effective_override:
                client = effective_override[source]
            elif effective_override:
                client = next(iter(effective_override.values()), None)

            live_results = _live_search_fake(cand, source_client=client)
            search_attempts.append({
                "candidate": cand.to_dict(),
                "method": "live_search",
                "results_count": len(live_results),
                "source": source,
            })
            matched_documents.extend(live_results)

    # --- Phase 5: Rank by metadata match score ---
    seen_ids: set[str] = set()
    unique_matched: list[dict[str, Any]] = []
    for doc in matched_documents:
        doc_key = f"{doc.get('source', '')}:{doc.get('document_id', '')}"
        if doc_key not in seen_ids:
            seen_ids.add(doc_key)
            unique_matched.append(doc)
    matched_documents = unique_matched

    # Score each matched document against candidates
    scored_docs: list[tuple[float, dict[str, Any], CitationCandidate | None]] = []
    for doc in matched_documents:
        best_score = 0.0
        best_cand: CitationCandidate | None = None
        for cand in candidates:
            s = _score_metadata_match(cand, doc)
            if s > best_score:
                best_score = s
                best_cand = cand
        scored_docs.append((best_score, doc, best_cand))

    scored_docs.sort(key=lambda x: x[0], reverse=True)

    # --- Phase 6: Format top matches ---
    for score, doc, cand in scored_docs[:fetch]:
        if score < min_score:
            continue

        fmt = format_legal_citation(doc, style="petition", cache=cache)
        formatted_citations.append(fmt)

        finding = VerificationFinding(
            candidate=cand or CitationCandidate(raw_text=""),
            matched=True,
            match_score=score,
            matched_document={
                "source": doc.get("source"),
                "document_id": doc.get("document_id"),
                "title": doc.get("title"),
                "court": doc.get("court"),
                "chamber": doc.get("chamber"),
                "decision_date": doc.get("decision_date"),
                "esas_no": doc.get("esas_no"),
                "karar_no": doc.get("karar_no"),
                "source_url": doc.get("source_url"),
                "content_status": doc.get("content_status"),
            },
        )
        verification_findings.append(finding.to_dict())

    # --- Phase 7: Unmatched candidates ---
    matched_cand_ids = {f["candidate"]["raw_text"] for f in verification_findings}
    for cand in candidates:
        if cand.raw_text not in matched_cand_ids:
            finding = VerificationFinding(
                candidate=cand,
                matched=False,
                match_score=0.0,
                warnings=cand.warnings,
            )
            verification_findings.append(finding.to_dict())

    # --- Phase 8: Warnings and next steps ---
    for cand in candidates:
        warnings.extend(cand.warnings)

    recommended_next_steps: list[str] = []
    unmatched = [f for f in verification_findings if not f.get("matched")]
    if unmatched:
        recommended_next_steps.append(
            f"{len(unmatched)} doğrulanamamış referans var; resmi kaynaklardan kontrol edin."
        )
    matched = [f for f in verification_findings if f.get("matched")]
    if matched:
        recommended_next_steps.append(
            f"{len(matched)} referans doğrulandı."
        )
    low_conf = [c for c in candidates if c.confidence == "low"]
    if low_conf:
        recommended_next_steps.append(
            f"{len(low_conf)} düşük güvenilirlikli referans; eksik metadata alanlarını tamamlayın."
        )
    if not recommended_next_steps:
        recommended_next_steps.append("Doğrulama tamamlandı.")

    elapsed = round((time.time() - t0) * 1000, 1)

    return {
        "ok": True,
        "candidates": [c.to_dict() for c in candidates],
        "search_attempts": search_attempts,
        "matched_documents": matched_documents[:fetch * 2],
        "formatted_citations": formatted_citations,
        "verification_findings": verification_findings,
        "warnings": warnings,
        "recommended_next_steps": recommended_next_steps,
        "timing": {"elapsed_ms": elapsed},
        **(({"strategy_debug": strategy_debug_info} if strategy_debug else {})),
    }
