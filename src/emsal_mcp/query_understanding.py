"""Legal query understanding — M-70.

Deterministic normalisation of Turkish legal query shorthand:
  - "İYUK 11" → "2577 sayılı Kanun madde 11"
  - "HMK 190" → "6100 sayılı Kanun madde 190"

Synonym / term expansion from a curated Turkish legal dictionary.
Court / chamber extraction from query text.
No fabrication — all mappings are hardcoded and deterministic.
"""
from __future__ import annotations

import re
from typing import Any

QUERY_UNDERSTANDING_VERSION = "1.0.0"

# ── Legislation abbreviation → full norm ─────────────────────────────────────
# Format: { abbreviation_lower: (kanun_no, display_name) }
_LAW_ABBREV: dict[str, tuple[str, str]] = {
    "iyuk":     ("2577", "İdari Yargılama Usulü Kanunu"),
    "hmk":      ("6100", "Hukuk Muhakemeleri Kanunu"),
    "tck":      ("5237", "Türk Ceza Kanunu"),
    "cmk":      ("5271", "Ceza Muhakemesi Kanunu"),
    "tbk":      ("6098", "Türk Borçlar Kanunu"),
    "tmk":      ("4721", "Türk Medeni Kanunu"),
    "iik":      ("2004", "İcra ve İflas Kanunu"),
    "kvkk":     ("6698", "Kişisel Verilerin Korunması Kanunu"),
    "fsek":     ("5846", "Fikir ve Sanat Eserleri Kanunu"),
    "ttk":      ("6102", "Türk Ticaret Kanunu"),
    "sgk":      ("5510", "Sosyal Sigortalar ve Genel Sağlık Sigortası Kanunu"),
    "iskanunu": ("4857", "İş Kanunu"),
    "imarkhk":  ("556",  "Markaların Korunması Hakkında KHK"),
}

# ── Synonym / term expansion (deterministic) ─────────────────────────────────
_SYNONYMS: dict[str, list[str]] = {
    "tazminat":     ["tazminat", "zarar", "maddi tazminat", "manevi tazminat"],
    "kira":         ["kira", "kiralayan", "kiracı", "kira bedeli", "tahliye"],
    "işçi":         ["işçi", "işveren", "iş akdi", "kıdem tazminatı", "ihbar tazminatı"],
    "sözleşme":     ["sözleşme", "akit", "mukavele", "sözleşme ihlali"],
    "boşanma":      ["boşanma", "evlilik birliği", "nafaka", "velayet"],
    "icra":         ["icra", "icra takibi", "haciz", "iflas"],
    "mülkiyet":     ["mülkiyet", "mülkiyet hakkı", "taşınmaz", "gayrimenkul"],
    "miras":        ["miras", "mirasçılık", "vasiyetname", "tereke"],
    "ceza":         ["ceza", "suç", "mahkumiyet", "hapis"],
    "idari":        ["idari", "idare", "idari işlem", "iptal davası"],
}


# ── Public API ───────────────────────────────────────────────────────────────


def _tr_lower(text: str) -> str:
    """Turkish-safe lowercasing — İ→i, I→ı."""
    return text.translate(str.maketrans("İI", "iı")).lower()


def normalize_law_ref(query: str) -> dict[str, Any]:
    """Replace common law abbreviations with full numbered references.

    Example: "İYUK 11 uyarınca" → "2577 (İdari Yargılama Usulü Kanunu) m.11 uyarınca"

    Args:
        query: Raw query text.

    Returns:
        Dict with normalized_query, replacements made, warnings.
    """
    replacements: list[dict[str, str]] = []
    result = query
    query_lower = _tr_lower(query)

    # Primary pattern: "İYUK 11" or "HMK md 190" or "İİK m.200"
    # Build pattern from lowercase keys, match against Turkish-lowered query
    abbrev_keys = [re.escape(k) for k in _LAW_ABBREV]
    full_pat = re.compile(
        r'\b(' + '|'.join(abbrev_keys) + r')\b'
        r'\s*(?:md\.?|m\.|madde\s*)?\s*(\d+(?:[/-]\d+)?)\b',
    )

    for m in full_pat.finditer(query_lower):
        abbr = m.group(1)
        article = m.group(2)
        if abbr in _LAW_ABBREV:
            kanun_no, name = _LAW_ABBREV[abbr]
            orig = query[m.start():m.end()]
            normalized = f"{kanun_no} ({name}) m.{article}"
            replacements.append({"original": orig, "normalized": normalized})
            # Actually replace in the result string
            result = result[:m.start()] + normalized + result[m.end():]
            # Re-sync query_lower after replacement
            query_lower = _tr_lower(result)

    # Secondary pattern: bare abbreviation without article — only if NOT
    # already replaced by the article-aware pass above.
    if not replacements:
        for abbr_key in _LAW_ABBREV:
            idx = query_lower.find(abbr_key)
            while idx >= 0:
                before = idx == 0 or not query_lower[idx - 1].isalpha()
                after = idx + len(abbr_key) >= len(query_lower) or not query_lower[idx + len(abbr_key)].isalpha()
                if before and after:
                    kanun_no, name = _LAW_ABBREV[abbr_key]
                    result = result[:idx] + f"{kanun_no} ({name})" + result[idx + len(abbr_key):]
                    query_lower = _tr_lower(result)
                    break
                idx = query_lower.find(abbr_key, idx + 1)

    warnings_list: list[str] = []
    if replacements:
        warnings_list.append(
            f"{len(replacements)} law reference(s) normalized (deterministic mapping). "
            "Verify exact article numbers against current legislation."
        )

    return {
        "ok": True,
        "original_query": query,
        "normalized_query": result.strip(),
        "replacements": replacements,
        "warnings": warnings_list,
        "rule": "Deterministic — no fabrication. Hardcoded abbreviation map.",
    }


def expand_query_terms(query: str) -> dict[str, Any]:
    """Expand query with legal synonyms from the curated dictionary.

    Example: "kira" → adds "kiralayan", "kiracı", "tahliye" as OR terms.

    Args:
        query: Raw query text.

    Returns:
        Dict with expanded_query, added_terms, warnings.
    """
    tokens = re.findall(r'\b\w+\b', query.lower())
    added: set[str] = set()
    for token in tokens:
        if token in _SYNONYMS:
            added.update(_SYNONYMS[token])

    # Remove the original tokens from the expanded set
    added.difference_update(tokens)

    if not added:
        return {
            "ok": True,
            "original_query": query,
            "expanded_query": query,
            "added_terms": [],
            "warnings": [],
        }

    expanded = f"{query} {' '.join(added)}"

    return {
        "ok": True,
        "original_query": query,
        "expanded_query": expanded,
        "added_terms": sorted(added),
        "warnings": [
            f"{len(added)} synonym(s) added (deterministic dictionary). "
            "Expansion is heuristic — review results for relevance."
        ],
        "rule": "Deterministic — no fabrication. Hardcoded synonym dictionary.",
    }


def extract_query_filters(query: str) -> dict[str, Any]:
    """Extract court/chamber filters from query text.

    Example: "Yargıtay 3. Hukuk Dairesi sözleşme ihlali" → court=Yargıtay, chamber=3. Hukuk Dairesi

    Args:
        query: Raw query text.

    Returns:
        Dict with filters (court, chamber, extracted_text), confidence.
    """
    filters: dict[str, str] = {}
    extracted: list[dict[str, str]] = []

    # Court patterns
    _COURT_PATTERNS = [
        (r'\bYargıtay\b', "Yargitay"),
        (r'\bDanıştay\b', "Danistay"),
        (r'\bAnayasa\s+Mahkemesi\b', "Anayasa Mahkemesi"),
        (r'\bAYM\b', "Anayasa Mahkemesi"),
        (r'\bUyuşmazlık\s+Mahkemesi\b', "Uyusmazlik"),
        (r'\bSayıştay\b', "Sayistay"),
    ]

    for pattern, court_name in _COURT_PATTERNS:
        m = re.search(pattern, query, re.IGNORECASE)
        if m:
            filters["court"] = court_name
            extracted.append({"type": "court", "value": court_name, "raw": m.group(0)})
            break

    # Chamber patterns
    chamber_pat = re.compile(r'(\d+[.]?\s*(?:Hukuk|Ceza)\s+Dairesi)', re.IGNORECASE)
    m = chamber_pat.search(query)
    if m:
        filters["chamber"] = m.group(1).strip()
        extracted.append({"type": "chamber", "value": m.group(1).strip(), "raw": m.group(0)})

    return {
        "ok": True,
        "filters": filters,
        "extracted": extracted,
        "confidence": "high" if len(extracted) >= 2 else ("medium" if extracted else "low"),
        "warnings": [] if extracted else ["No court/chamber pattern detected in query."],
    }
