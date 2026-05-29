"""v0.10 Legislation (Mevzuat) module — search, classify, verify, format.

Provides a dedicated layer for Turkish legislation operations:
  - search_legislation         — search Mevzuat source with type filters
  - get_legislation_document   — fetch full document with citation check
  - search_legislation_articles — search articles within a document
  - get_legislation_article_tree — build part/section/article hierarchy
  - get_legislation_gerekce    — extract GENEL GEREKCE / MADDE GEREKCELERI
  - get_legislation_source_status — aggregate source health
  - format_legislation_citation — format legislation citations
  - get_legislation_types      — list known Turkish legislation types

Never fabricates — missing data produces warnings.
All functions accept ``sources_override`` for test injection.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from .models import ContentStatus, Document, SearchResult
from .safety import citation_check
from .sources.registry import capabilities as get_capabilities, smoke_all_sync


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEGISLATION_VERSION = "0.10.0"

# Turkish legislation types and their detection patterns.
# Order matters: more specific patterns precede broader ones.
_LEGISLATION_TYPE_PATTERNS: list[tuple[str, str, str]] = [
    ("khk", "Kanun Hükmünde Kararname", r"\b(?:Kanun\s+H[üu]km[üu]nde\s+Kararname|KHK)\b"),
    ("cbk", "Cumhurbaşkanlığı Kararnamesi", r"\bCumhurba[şs]kanl[ıi][ğg][ıi]\s+Kararname"),
    ("kanun", "Kanun", r"\bKanun"),
    ("yonetmelik", "Yönetmelik", r"\bY[öo]netmel[ıi][kğ]"),
    ("teblig", "Tebliğ", r"\bTebli[ğg]"),
    ("genelge", "Genelge", r"\bGenelge"),
    ("yonerge", "Yönerge", r"\bY[öo]nerge"),
    ("tuzuk", "Tüzük", r"\bT[üu]z[üu]k"),
    ("uluslararasi", "Uluslararası Anlaşma", r"\b(?:Uluslararas[ıi]\s+(?:Anla[sş]ma|S[öo]zle[sş]me))"),
    ("anayasa", "Anayasa", r"\bAnayasa"),
    ("other", "Diğer Mevzuat", ""),
]

_NO_INVENTION_BLOCK = (
    "Yasak: Bu modül hiçbir surette mevzuat numarası, madde numarası, "
    "yürürlük durumu veya resmi gazete bilgisi uydurmaz. "
    "Eksik bilgiler uyarı olarak bildirilir, tamamlanmaz."
)

# Article patterns for Turkish legislation text
_ARTICLE_RE = re.compile(
    r"^MADDE\s+(\d+(?:\s*/\s*[A-Z])?)\s*[-–—]\s*(.*?)(?=^MADDE\s+\d|\Z)",
    re.MULTILINE | re.DOTALL,
)
_PART_RE = re.compile(r"^([İIİ]?KİNCİ|[ÜUÜ]?ÇÜNCÜ|[DÖD]?RDÜNCÜ|[BE]?ŞİNCİ|[AL]?TINCI|[YE]?DİNCİ|[SEK]?İZİNCİ|[DO]?KUZUNCU|[ON]UNCU|[Bİ]?RİNCİ)\s+KISIM", re.MULTILINE)
_SECTION_RE = re.compile(r"^([İIİ]?KİNCİ|[ÜUÜ]?ÇÜNCÜ|[DÖD]?RDÜNCÜ|[BE]?ŞİNCİ|[AL]?TINCI|[YE]?DİNCİ|[SEK]?İZİNCİ|[DO]?KUZUNCU|[ON]UNCU|[Bİ]?RİNCİ)\s+B[ÖO]L[ÜU]M", re.MULTILINE)

_GENEL_GEREKCE_RE = re.compile(
    r"(?:^|\n)GENEL\s+GEREK[ÇC]E\s*\n(.*?)(?=(?:^|\n)MADDE\s+GEREK[ÇC]ELER[İI]|(?:^|\n)MADDE\s+\d|\Z)",
    re.DOTALL,
)
_MADDE_GEREKCELERI_RE = re.compile(
    r"(?:^|\n)MADDE\s+GEREK[ÇC]ELER[İI]\s*\n(.*?)(?=\Z)",
    re.DOTALL,
)
_SINGLE_MADDE_GEREKCE_RE = re.compile(
    r"Madde\s+(\d+(?:\s*/\s*[A-Z])?)\s*[-–—]\s*(.*?)(?=Madde\s+\d|\Z)",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_type(title: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify a legislation document into a type category."""
    combined = title
    if metadata:
        for key in ("mevzuatTur", "documentType", "type", "itemType"):
            val = metadata.get(key)
            if isinstance(val, str) and val.strip():
                combined = f"{combined} {val}"
            elif isinstance(val, dict):
                desc = val.get("description") or val.get("name") or ""
                if desc:
                    combined = f"{combined} {desc}"

    for type_id, display_name, pattern in _LEGISLATION_TYPE_PATTERNS:
        if type_id == "other":
            continue
        if pattern and re.search(pattern, combined, re.IGNORECASE):
            return {
                "type_id": type_id,
                "display_name": display_name,
                "confidence": "high" if re.search(pattern, title, re.IGNORECASE) else "medium",
            }
    return {"type_id": "other", "display_name": "Diğer Mevzuat", "confidence": "low"}


def _resolve_source(
    source: str | None,
    sources_override: dict[str, Any] | None,
) -> Any | None:
    """Resolve a source client from override or registry. Returns client or None."""
    if sources_override and source in (sources_override or {}):
        return sources_override[source]
    if sources_override and "mevzuat" in sources_override:
        return sources_override["mevzuat"]
    from .sources.registry import get_source as _get_source
    try:
        return _get_source(source or "mevzuat")
    except KeyError:
        return None


def _fetch_doc(
    document_id: str,
    source: str | None,
    sources_override: dict[str, Any] | None,
) -> tuple[Document | None, str | None]:
    """Fetch a document from source. Returns (doc, error_msg)."""
    client = _resolve_source(source, sources_override)
    if client is None:
        return None, f"Kaynak bulunamadı: {source or 'mevzuat'}"
    import asyncio
    try:
        doc = asyncio.run(client.get_document(document_id))
        return doc, None
    except Exception as exc:
        return None, f"Belge alınamadı: {exc}"


def _parse_articles(text: str) -> list[dict[str, Any]]:
    """Parse MADDE entries from legislation text. Returns list of {number, raw_text, text}."""
    articles: list[dict[str, Any]] = []
    for m in _ARTICLE_RE.finditer(text):
        num = m.group(1).strip()
        body = m.group(2).strip()
        articles.append({
            "number": num,
            "raw_text": f"MADDE {num} - {body}",
            "text": body,
        })
    return articles


def _build_tree(articles: list[dict[str, Any]], full_text: str) -> dict[str, Any]:
    """Build part/section/article tree from flat article list + full text.

    When no PART or SECTION markers exist, returns empty parts list.
    """
    lines = full_text.splitlines()
    parts: list[dict[str, Any]] = []
    current_part: dict[str, Any] | None = None
    current_section: dict[str, Any] | None = None
    article_index = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Part header
        part_m = _PART_RE.match(stripped)
        if part_m:
            current_part = {"title": stripped, "sections": []}
            current_section = None
            parts.append(current_part)
            continue

        # Section header
        section_m = _SECTION_RE.match(stripped)
        if section_m:
            current_section = {"title": stripped, "articles": []}
            if current_part is None:
                current_part = {"title": "", "sections": []}
                parts.append(current_part)
            current_part["sections"].append(current_section)
            continue

        # Article
        art_m = re.match(r"^MADDE\s+(\d+)", stripped)
        if art_m and article_index < len(articles):
            art = articles[article_index]
            article_index += 1
            article_entry = {
                "number": art["number"],
                "title": stripped[:120],
                "preview": art["text"][:200],
            }
            if current_section is not None:
                current_section["articles"].append(article_entry)
            elif current_part is not None:
                # Add directly to part — create a default section if none exists
                if not current_part["sections"]:
                    current_part["sections"].append({"title": "", "articles": []})
                current_part["sections"][-1]["articles"].append(article_entry)
            else:
                # No part header seen yet — create a default part
                current_part = {"title": "", "sections": [{"title": "", "articles": [article_entry]}]}
                parts.append(current_part)

    return {"parts": parts}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_legislation(
    query: str,
    sources: list[str] | None = None,
    legislation_type: str | None = None,
    limit: int = 10,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search legislation via the Mevzuat source.

    Args:
        query: Search phrase.
        sources: Source IDs to search (default: ["mevzuat"]).
        legislation_type: Optional filter (e.g. "Kanun", "Yönetmelik").
        limit: Max results.
        sources_override: Dict mapping source_id -> fake client for tests.

    Returns:
        Dict with ok, query, sources, legislation_type, total_results,
        results, warnings, recommended_next_steps, version, rule.
    """
    warnings: list[str] = []
    source_list = sources or ["mevzuat"]
    all_results: list[dict[str, Any]] = []

    for src_id in source_list:
        client = _resolve_source(src_id, sources_override)
        if client is None:
            warnings.append(f"Kaynak bulunamadı: {src_id}")
            continue

        filters: dict[str, Any] = {}
        if legislation_type:
            type_upper = legislation_type.upper().replace(" ", "")
            turkish_normalized = (
                type_upper.replace("İ", "I").replace("Ş", "S").replace("Ğ", "G")
                .replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
            )
            filters["type"] = turkish_normalized

        import asyncio
        try:
            raw = asyncio.run(client.search(query, limit=limit, **filters))
        except Exception as exc:
            warnings.append(f"{src_id} araması başarısız: {exc}")
            continue

        for r in raw:
            classification = _classify_type(
                r.title or "",
                r.metadata if isinstance(r.metadata, dict) else None,
            )
            all_results.append({
                "document_id": r.document_id,
                "source": r.source,
                "title": r.title,
                "legislation_no": r.karar_no,
                "gazette_date": r.decision_date,
                "legislation_type": classification["display_name"],
                "legislation_type_id": classification["type_id"],
                "type_confidence": classification["confidence"],
                "summary": r.summary,
                "content_status": r.content_status.value,
                "court": r.court,
            })

    ok = len(all_results) > 0 and not any("bulunamadı" in w for w in warnings)

    recommended: list[str] = []
    if not all_results:
        recommended.append("Farklı bir sorgu veya mevzuat türü deneyin.")
    if warnings:
        recommended.append("Uyarıları kontrol edin; eksik metadata alanlarını doğrulayın.")
    if not recommended:
        recommended.append("Mevzuat araması tamamlandı.")

    return {
        "ok": ok,
        "query": query,
        "sources": source_list,
        "legislation_type": legislation_type,
        "total_results": len(all_results),
        "results": all_results,
        "warnings": warnings,
        "recommended_next_steps": recommended,
        "version": LEGISLATION_VERSION,
        "rule": _NO_INVENTION_BLOCK,
    }


def get_legislation_document(
    document_id: str,
    source: str | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get a full legislation document from the Mevzuat source.

    Args:
        document_id: Mevzuat document ID.
        source: Source ID (default: "mevzuat").
        sources_override: Dict mapping source_id -> fake client for tests.

    Returns:
        Dict with ok, document_id, title, citation_check, article_count,
        legislation_type, content_status, etc.
    """
    warnings: list[str] = []
    doc, error = _fetch_doc(document_id, source, sources_override)
    if error:
        return {
            "ok": False,
            "error": error,
            "document_id": document_id,
            "document": None,
            "warnings": [error],
            "version": LEGISLATION_VERSION,
            "rule": _NO_INVENTION_BLOCK,
        }

    classification = _classify_type(
        doc.title or "",
        doc.metadata if isinstance(doc.metadata, dict) else None,
    )
    safety = citation_check(doc)
    text = doc.text or ""
    articles = _parse_articles(text) if text.strip() else []

    return {
        "ok": True,
        "document_id": doc.document_id,
        "source": doc.source,
        "title": doc.title,
        "legislation_no": doc.karar_no,
        "gazette_date": doc.decision_date,
        "legislation_type": classification["display_name"],
        "legislation_type_id": classification["type_id"],
        "type_confidence": classification["confidence"],
        "content_status": doc.content_status.value,
        "content_hash": doc.content_hash,
        "citation_check": {
            "ok": safety.ok,
            "quote_usable": doc.quote_usable,
            "draft_usable": doc.draft_usable,
            "warnings": safety.reasons,
        },
        "article_count": len(articles),
        "text_length": len(text),
        "warnings": warnings,
        "recommended_next_steps": (
            ["Tam metin mevcut; alıntı için kullanılabilir."]
            if doc.quote_usable else ["Tam metin mevcut değil; resmi kaynaktan doğrulayın."]
        ),
        "version": LEGISLATION_VERSION,
        "rule": _NO_INVENTION_BLOCK,
    }


def search_legislation_articles(
    document_id: str,
    article_number: str | None = None,
    article_query: str | None = None,
    source: str | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search articles within a legislation document.

    Args:
        document_id: Mevzuat document ID.
        article_number: Optional specific article number to retrieve.
        article_query: Optional keyword/phrase to search in article text.
        source: Source ID (default: "mevzuat").
        sources_override: Dict mapping source_id -> fake client for tests.

    Returns:
        Dict with ok, matching_articles, total_articles_found, etc.
    """
    warnings: list[str] = []
    doc, error = _fetch_doc(document_id, source, sources_override)
    if error:
        return {
            "ok": False,
            "error": error,
            "document_id": document_id,
            "matching_articles": [],
            "total_articles_found": 0,
            "warnings": [error],
            "recommended_next_steps": [error],
            "version": LEGISLATION_VERSION,
            "rule": _NO_INVENTION_BLOCK,
        }

    text = doc.text or ""
    if not text.strip():
        warnings.append("Belge içeriği mevcut değil; madde araması yapılamaz.")
        return {
            "ok": False,
            "document_id": document_id,
            "source": doc.source,
            "title": doc.title,
            "article_number": article_number,
            "article_query": article_query,
            "total_articles_found": 0,
            "matching_articles": [],
            "content_status": doc.content_status.value,
            "warnings": warnings,
            "recommended_next_steps": ["Belgenin tam metnini resmi kaynaktan edinin."],
            "version": LEGISLATION_VERSION,
            "rule": _NO_INVENTION_BLOCK,
        }

    if doc.content_status == ContentStatus.METADATA_ONLY:
        warnings.append("Belge metadata_only durumunda; içerik sınırlı olabilir.")

    all_articles = _parse_articles(text)
    matching = []

    for art in all_articles:
        if article_number and art["number"] != article_number:
            continue
        if article_query and article_query.lower() not in art["text"].lower():
            continue
        matching.append({
            "number": art["number"],
            "text": art["text"],
            "preview": art["text"][:300],
        })

    return {
        "ok": len(matching) > 0,
        "document_id": document_id,
        "source": doc.source,
        "title": doc.title,
        "article_number": article_number,
        "article_query": article_query,
        "total_articles_found": len(all_articles),
        "matching_articles": matching,
        "content_status": doc.content_status.value,
        "warnings": warnings + (
            [f"{article_number} numaralı madde bulunamadı."]
            if article_number and not matching else []
        ),
        "recommended_next_steps": (
            [f"{len(matching)} madde bulundu."]
            if matching else [f"{article_number or article_query or 'Belirtilen'} numaralı madde bulunamadı."]
        ),
        "version": LEGISLATION_VERSION,
        "rule": _NO_INVENTION_BLOCK,
    }


def get_legislation_article_tree(
    document_id: str,
    source: str | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a hierarchical part/section/article tree from legislation text.

    Args:
        document_id: Mevzuat document ID.
        source: Source ID (default: "mevzuat").
        sources_override: Dict mapping source_id -> fake client for tests.

    Returns:
        Dict with ok, article_count, section_count, part_count, tree,
        flat_article_list, etc.
    """
    warnings: list[str] = []
    doc, error = _fetch_doc(document_id, source, sources_override)
    if error:
        return {
            "ok": False,
            "error": error,
            "document_id": document_id,
            "article_count": 0,
            "section_count": 0,
            "part_count": 0,
            "tree": {"parts": []},
            "flat_article_list": [],
            "warnings": [error],
            "recommended_next_steps": [error],
            "version": LEGISLATION_VERSION,
            "rule": _NO_INVENTION_BLOCK,
        }

    text = doc.text or ""
    if not text.strip():
        warnings.append("Belge içeriği mevcut değil.")
        return {
            "ok": False,
            "document_id": document_id,
            "source": doc.source,
            "title": doc.title,
            "article_count": 0,
            "section_count": 0,
            "part_count": 0,
            "tree": {"parts": []},
            "flat_article_list": [],
            "warnings": warnings,
            "recommended_next_steps": ["Belge içeriği mevcut değil."],
            "version": LEGISLATION_VERSION,
            "rule": _NO_INVENTION_BLOCK,
        }

    articles = _parse_articles(text)
    tree = _build_tree(articles, text)
    parts = tree.get("parts", [])

    # Detect if hierarchy markers actually exist in the text
    has_parts = bool(_PART_RE.search(text))
    has_sections = bool(_SECTION_RE.search(text))

    part_count = len(parts) if has_parts else 0
    section_count = sum(len(p.get("sections", [])) for p in parts) if has_sections else 0

    flat: list[dict[str, Any]] = []
    for p in parts:
        for s in p.get("sections", []):
            for a in s.get("articles", []):
                flat.append({
                    "number": a["number"],
                    "preview": a.get("preview", ""),
                    "parent_part": p.get("title") or None,
                    "parent_section": s.get("title") or None,
                })

    return {
        "ok": True,
        "document_id": document_id,
        "source": doc.source,
        "title": doc.title,
        "article_count": len(articles),
        "section_count": section_count,
        "part_count": part_count,
        "tree": tree,
        "flat_article_list": flat,
        "warnings": warnings,
        "recommended_next_steps": (
            [f"{len(articles)} madde, {part_count} kısım, {section_count} bölüm bulundu."]
            if articles else ["Madde yapısı bulunamadı."]
        ),
        "version": LEGISLATION_VERSION,
        "rule": _NO_INVENTION_BLOCK,
    }


def get_legislation_gerekce(
    document_id: str,
    source: str | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract GENEL GEREKCE and MADDE GEREKCELERI from legislation text.

    Args:
        document_id: Mevzuat document ID.
        source: Source ID (default: "mevzuat").
        sources_override: Dict mapping source_id -> fake client for tests.

    Returns:
        Dict with ok, found, genel_gerekce, madde_gerekceleri, raw_text, etc.
    """
    warnings: list[str] = []
    doc, error = _fetch_doc(document_id, source, sources_override)
    if error:
        return {
            "ok": False,
            "error": error,
            "document_id": document_id,
            "found": False,
            "genel_gerekce": None,
            "madde_gerekceleri": None,
            "raw_text": None,
            "warnings": [error],
            "recommended_next_steps": [error],
            "version": LEGISLATION_VERSION,
            "rule": _NO_INVENTION_BLOCK,
        }

    text = doc.text or ""
    if not text.strip():
        return {
            "ok": False,
            "document_id": document_id,
            "source": doc.source,
            "title": doc.title,
            "found": False,
            "genel_gerekce": None,
            "madde_gerekceleri": None,
            "raw_text": None,
            "warnings": ["Belge içeriği mevcut değil."],
            "recommended_next_steps": ["Belge içeriği mevcut değil."],
            "version": LEGISLATION_VERSION,
            "rule": _NO_INVENTION_BLOCK,
        }

    # Extract GENEL GEREKCE
    genel_gerekce_raw: str | None = None
    gg_m = _GENEL_GEREKCE_RE.search(text)
    if gg_m:
        genel_gerekce_raw = gg_m.group(1).strip()

    # Extract MADDE GEREKCELERI
    madde_gerekceleri_raw: str | None = None
    mg_m = _MADDE_GEREKCELERI_RE.search(text)
    if mg_m:
        madde_gerekceleri_raw = mg_m.group(1).strip()

    # Parse individual article gerekceleri
    madde_gerekceleri_list: list[dict[str, str]] | None = None
    if madde_gerekceleri_raw:
        madde_gerekceleri_list = []
        for m in _SINGLE_MADDE_GEREKCE_RE.finditer(madde_gerekceleri_raw):
            madde_gerekceleri_list.append({
                "article": m.group(1).strip(),
                "gerekce": m.group(2).strip(),
            })

    found = genel_gerekce_raw is not None or madde_gerekceleri_raw is not None
    if not found:
        warnings.append("Metinde GENEL GEREKÇE veya MADDE GEREKÇELERİ bulunamadı.")

    return {
        "ok": found,
        "document_id": document_id,
        "source": doc.source,
        "title": doc.title,
        "found": found,
        "genel_gerekce": genel_gerekce_raw,
        "madde_gerekceleri": madde_gerekceleri_list,
        "raw_text": text[:2000] if len(text) > 2000 else text,
        "warnings": warnings,
        "recommended_next_steps": (
            ["Gerekçe metni bulundu; doğrudan alıntılanabilir."]
            if found else ["Gerekçe metni bulunamadı; resmi kaynaktan doğrulayın."]
        ),
        "version": LEGISLATION_VERSION,
        "rule": _NO_INVENTION_BLOCK,
    }


def get_legislation_source_status(
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check Mevzuat source health via smoke tests.

    Args:
        sources_override: Unused (kept for interface consistency).

    Returns:
        Dict with ok, overall_ok, healthy_sources, degraded_sources, etc.
    """
    warnings: list[str] = []

    smoke_results: list[dict[str, Any]] = []
    try:
        smoke_results = smoke_all_sync(online=False)
    except Exception as exc:
        warnings.append(f"smoke_all_sync çağrısı başarısız: {exc}")

    caps: list[dict[str, Any]] = []
    try:
        caps = get_capabilities()
    except Exception as exc:
        warnings.append(f"capabilities çağrısı başarısız: {exc}")

    # Filter only legislation-relevant sources
    legislation_sources = {"mevzuat"}
    healthy: list[str] = []
    degraded: list[str] = []

    for sr in smoke_results:
        sid = sr.get("source_id", "")
        if sid not in legislation_sources:
            continue
        if sr.get("offline_ok", False):
            healthy.append(sid)
        else:
            degraded.append(sid)

    overall_ok = len(degraded) == 0 and len(healthy) > 0

    return {
        "ok": overall_ok,
        "sources": [
            {
                "source_id": c.get("source_id", c.get("source", "")),
                "display_name": c.get("display_name", ""),
                "status": c.get("status", "unknown"),
            }
            for c in caps
            if c.get("source_id") in legislation_sources or c.get("source") in legislation_sources
        ],
        "overall_ok": overall_ok,
        "source_count": len(healthy) + len(degraded),
        "healthy_sources": healthy,
        "degraded_sources": degraded,
        "warnings": warnings,
        "recommended_next_steps": (
            ["Tüm kaynaklar sağlıklı."]
            if overall_ok else ["Bazı kaynaklar sağlıksız; daha sonra tekrar deneyin."]
        ),
        "version": LEGISLATION_VERSION,
        "rule": _NO_INVENTION_BLOCK,
    }


def format_legislation_citation(
    document: dict[str, Any] | Document,
    style: Literal["full", "short", "article"] = "full",
) -> dict[str, Any]:
    """Format a legislation citation from document metadata.

    Args:
        document: Document dict or Document model.
        style: 'full', 'short', or 'article'.

    Returns:
        Dict with formatted_citation, style, warnings, etc.
    """
    warnings: list[str] = []
    meta_for_type: dict[str, Any] | None = None

    if isinstance(document, Document):
        title = document.title or ""
        leg_no = document.karar_no or ""
        gazette_date = document.decision_date or ""
        meta_for_type = document.metadata if isinstance(document.metadata, dict) else None
    elif isinstance(document, dict):
        title = document.get("title", "")
        leg_no = document.get("legislation_no") or document.get("karar_no", "")
        gazette_date = document.get("gazette_date") or document.get("decision_date", "")
        meta_for_type = document.get("metadata") if isinstance(document.get("metadata"), dict) else None
    else:
        return {"error": "Geçersiz belge formatı; Document modeli veya dict gerekli."}

    classification = _classify_type(title, meta_for_type)
    leg_type = classification["display_name"]

    if not title:
        warnings.append("Mevzuat başlığı eksik.")
    if not leg_no:
        warnings.append("Mevzuat numarası eksik.")
    if not gazette_date:
        warnings.append("Resmi Gazete tarihi eksik.")

    if style == "full":
        parts = [leg_type]
        if leg_no:
            parts.append(f"No: {leg_no}")
        if gazette_date:
            parts.append(f"RG: {gazette_date}")
        parts.append(f'"{title}"' if title else "")
        formatted = " ".join(p for p in parts if p)
    elif style == "short":
        formatted = f"{leg_type} No: {leg_no}" if leg_no else f"{leg_type}: {title}" if title else "Bilinmeyen Mevzuat"
    elif style == "article":
        base = f"{leg_type} No: {leg_no}" if leg_no else leg_type
        formatted = f"{base}, {{MADDE}}"
    else:
        formatted = f"{leg_type} No: {leg_no}" if leg_no else title
        warnings.append(f"Bilinmeyen stil: '{style}'; 'short' kullanıldı.")

    return {
        "formatted_citation": formatted,
        "style": style,
        "legislation_no": leg_no,
        "gazette_date": gazette_date,
        "legislation_type": leg_type,
        "title": title,
        "warnings": warnings,
    }


def get_legislation_types() -> list[dict[str, str]]:
    """Return the list of known Turkish legislation types with IDs."""
    return [
        {"type_id": tid, "display_name": name}
        for tid, name, _ in _LEGISLATION_TYPE_PATTERNS
    ]
