"""M-12 Argument Builder — transforms petition pack's argument-map into
structured argument chains: claim -> supporting authority -> counter-argument space.

Safety invariants:
- No metadata_only leak: only petition_ready authorities in supporting_authorities
- No fabrication: missing support produces a warning, never invents connections
- Citation-safe: all cited documents must pass citation_check
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import ContentStatus, Document, build_error
from .safety import citation_check


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COUNTER_ARGUMENT_PLACEHOLDER = "{{KARSI_ARGUMAN_BOSLUK}}"
MIN_CONTENT_LENGTH = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_pack_json(pack_dir: Path, filename: str) -> dict[str, Any]:
    """Load a JSON file from the pack directory."""
    path = pack_dir / filename
    if not path.exists():
        return {}
    try:
        result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def _parse_argument_map(md_text: str) -> list[dict[str, str]]:
    """Parse an argument-map.md file and extract argument entries.

    The auto-generated argument-map.md has sections like:

        ## Authority Map

        - [READY] **citation_label** (source:doc_id)
          - Classification: petition_ready
          - Content Status: full_text

        ## Research Leads

        - Verify `source:doc_id` from official source

    We extract individual argument entries from the ``Authority Map`` section.
    Each entry represents a claim derived from the authority's classification.
    """
    entries: list[dict[str, str]] = []

    # Split by "- " list items that contain classification info
    # or by "## " sections for structured extraction
    lines = md_text.splitlines()
    current_section = ""

    for line in lines:
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith("## "):
            current_section = stripped[3:].strip().lower()
            continue

        # Extract matter/issue from header area
        if stripped.startswith("**Matter**:"):
            continue
        if stripped.startswith("**Issue**:"):
            continue

        # Parse authority list items (e.g., "- [READY] **label** (source:doc_id)")
        authority_match = re.match(
            r"^-\s+\[(\w+)\]\s+\*\*(.+?)\*\*\s+\((.+?)\)",
            stripped,
        )
        if authority_match:
            tag = authority_match.group(1).upper()
            citation_label = authority_match.group(2)
            source_ref = authority_match.group(3)
            entries.append({
                "tag": tag,
                "citation_label": citation_label,
                "source_ref": source_ref,
                "classification": "",
                "content_status": "",
                "section": current_section,
            })
            continue

        # Parse classification/status sub-items
        class_match = re.match(r"^-\s+Classification:\s+(.+)", stripped)
        if class_match and entries:
            entries[-1]["classification"] = class_match.group(1).strip()
            continue

        status_match = re.match(r"^-\s+Content Status:\s+(.+)", stripped)
        if status_match and entries:
            entries[-1]["content_status"] = status_match.group(1).strip()
            continue

        action_match = re.match(r"^-\s+Action:\s+(.+)", stripped)
        if action_match and entries:
            entries[-1]["action"] = action_match.group(1).strip()
            continue

    return entries


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text for relevance matching.

    Uses simple word splitting; no NLP dependency.
    Filters out short tokens and common Turkish/English stop words.
    """
    stop_words = {
        "ve", "ile", "için", "bir", "bu", "da", "de", "mi", "mı", "mu",
        "mü", "ki", "olan", "olarak", "gibi", "daha", "çok", "az",
        "the", "of", "and", "or", "is", "in", "to", "for", "a", "an",
        "that", "this", "with", "on", "at", "by", "from", "as", "be",
    }
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{3,}", text.lower())
    return {w for w in words if w not in stop_words}


def _keyword_overlap_score(text_a: str, text_b: str) -> float:
    """Compute keyword overlap ratio between two text strings.

    Returns a float in [0.0, 1.0] representing the Jaccard-like overlap
    of meaningful keywords.
    """
    kw_a = _extract_keywords(text_a)
    kw_b = _extract_keywords(text_b)
    if not kw_a or not kw_b:
        return 0.0
    intersection = kw_a & kw_b
    union = kw_a | kw_b
    return len(intersection) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Core: build_argument_chain
# ---------------------------------------------------------------------------

def build_argument_chain(
    pack_dir: str | Path,
    cache: Any | None = None,
) -> dict[str, Any]:
    """Build structured argument chains from a petition pack.

    Reads ``petition-pack.json`` and ``argument-map.md`` from *pack_dir*
    and produces a list of argument chains with:

    - ``claim`` — the legal claim/argument derived from the authority map
    - ``supporting_authorities`` — **only** petition_ready docs (citation-safe)
    - ``research_leads`` — research_lead_only docs for further investigation
    - ``counter_argument`` — empty placeholder for attorney to fill
    - ``strength`` — 0.0–1.0 score based on supporting evidence
    - ``warnings`` — non-fatal issues (e.g. no support found)

    Safety invariants enforced:
    - **No metadata_only leak**: only petition_ready in supporting_authorities
    - **No fabrication**: missing support → warning, never invent connections
    - **Citation-safe**: all cited docs pass citation_check

    Args:
        pack_dir: Path to a petition pack directory (from v0.7+).
        cache: Optional Cache instance for history logging.

    Returns:
        Dict with ok, pack_dir, arguments, overall_strength, warnings.
    """
    pack_path = Path(pack_dir)

    # ── Validate pack directory ──────────────────────────────────────────
    if not pack_path.exists():
        return build_error(
            "PACK_NOT_FOUND",
            f"Pack directory not found: {pack_dir}",
        )

    pack_meta_path = pack_path / "petition-pack.json"
    if not pack_meta_path.exists():
        return build_error(
            "PACK_NOT_FOUND",
            "petition-pack.json not found in pack_dir",
        )

    pack_meta = _load_pack_json(pack_path, "petition-pack.json")
    argument_map_path = pack_path / "argument-map.md"

    if not argument_map_path.exists():
        return build_error(
            "ARGUMENT_MAP_MISSING",
            "argument-map.md not found in pack_dir",
        )

    # ── Load pack data ───────────────────────────────────────────────────
    brief = _load_pack_json(pack_path, "petition-brief.json")
    argument_map_text = argument_map_path.read_text(encoding="utf-8")
    counts = pack_meta.get("classification_counts", {})
    matter = pack_meta.get("matter", "")
    issue = pack_meta.get("issue", "")

    # ── Build authority lookup ───────────────────────────────────────────
    # Map document_key -> authority info from petition-brief.json
    authorities = brief.get("authorities", [])
    auth_by_key: dict[str, dict[str, Any]] = {}
    for auth in authorities:
        key = f"{auth.get('source', '')}:{auth.get('document_id', '')}"
        auth_by_key[key] = auth

    # ── Parse argument map entries ───────────────────────────────────────
    map_entries = _parse_argument_map(argument_map_text)

    # ── Build structured argument chains ─────────────────────────────────
    warnings: list[str] = []
    arguments: list[dict[str, Any]] = []

    # Group entries by unique citation (avoid duplicate claims)
    seen_claims: set[str] = set()

    for entry in map_entries:
        classification = entry.get("classification", "")
        source_ref = entry.get("source_ref", "")
        citation_label = entry.get("citation_label", "")

        # Build a claim text from the entry
        claim_text = f"{citation_label} ({source_ref})"

        # Deduplicate
        if claim_text in seen_claims:
            continue
        seen_claims.add(claim_text)

        supporting_authorities: list[dict[str, Any]] = []
        research_leads: list[dict[str, Any]] = []
        entry_warnings: list[str] = []

        auth_info = auth_by_key.get(source_ref, {})

        if classification == "petition_ready":
            # ── SAFETY: citation_check before adding to supporting ──────
            doc = _reconstruct_document(auth_info, pack_path, source_ref)
            if doc is not None:
                check = citation_check(doc)
                if check.ok:
                    supporting_authorities.append({
                        "document_id": auth_info.get("document_id", ""),
                        "source": auth_info.get("source", ""),
                        "title": auth_info.get("title", ""),
                        "citation_label": auth_info.get("citation_label", ""),
                        "relevance": _assess_relevance(claim_text, auth_info),
                        "content_status": auth_info.get("content_status", ""),
                    })
                else:
                    entry_warnings.append(
                        f"Citation check failed for {source_ref}: "
                        f"{'; '.join(check.reasons)}"
                    )
            else:
                entry_warnings.append(
                    f"Could not reconstruct document for {source_ref}"
                )

        elif classification in ("research_lead_only", "citation_only"):
            # These go into research_leads, NOT supporting_authorities
            research_leads.append({
                "document_id": auth_info.get("document_id", ""),
                "source": auth_info.get("source", ""),
                "title": auth_info.get("title", ""),
                "citation_label": auth_info.get("citation_label", ""),
                "classification": classification,
                "action": entry.get("action", "Verify from official source"),
            })

        elif classification == "excluded":
            entry_warnings.append(
                f"Authority {source_ref} is excluded and cannot be used"
            )

        # ── SAFETY: No fabrication — warn if no support found ───────────
        if not supporting_authorities and classification != "excluded":
            entry_warnings.append(
                f"No petition_ready authority found for claim: {claim_text}"
            )

        # Score strength
        strength_result = score_argument(
            claim_text=claim_text,
            authorities=supporting_authorities,
            cache=cache,
        )
        strength = strength_result.get("score", 0.0)

        arguments.append({
            "claim": claim_text,
            "supporting_authorities": supporting_authorities,
            "research_leads": research_leads,
            "counter_argument": COUNTER_ARGUMENT_PLACEHOLDER,
            "strength": strength,
            "warnings": entry_warnings,
        })

    # ── Compute overall strength ─────────────────────────────────────────
    if arguments:
        overall_strength = round(
            sum(a["strength"] for a in arguments) / len(arguments), 2
        )
    else:
        overall_strength = 0.0
        warnings.append("No arguments found in argument-map.md")

    # ── Build pack-level warnings ────────────────────────────────────────
    petition_ready_count = counts.get("petition_ready", 0)
    if petition_ready_count == 0:
        warnings.append(
            "No petition_ready authorities in pack; all claims lack support"
        )

    # ── Verify safety invariant: no metadata_only in supporting ──────────
    for arg in arguments:
        for auth in arg["supporting_authorities"]:
            cs = auth.get("content_status", "")
            if cs in ("metadata_only", "pdf_link_only", "unavailable"):
                warnings.append(
                    f"SAFETY VIOLATION: {auth['document_id']} has "
                    f"content_status={cs} in supporting_authorities"
                )

    # ── Log to cache if provided ─────────────────────────────────────────
    if cache is not None:
        try:
            cache.log("build_argument_chain", {
                "pack_dir": str(pack_dir),
                "argument_count": len(arguments),
                "overall_strength": overall_strength,
            })
        except Exception:
            pass  # non-critical

    return {
        "ok": True,
        "pack_dir": str(pack_dir),
        "matter": matter,
        "issue": issue,
        "arguments": arguments,
        "overall_strength": overall_strength,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Core: score_argument
# ---------------------------------------------------------------------------

def score_argument(
    claim_text: str,
    authorities: list[dict[str, Any]],
    cache: Any | None = None,
) -> dict[str, Any]:
    """Score how well an argument is supported by authorities.

    Scoring criteria (0.0–1.0):
    - Count of supporting petition_ready documents (higher = better)
    - Content availability (full_text > metadata_only)
    - Quote usability (quote_usable flag)
    - Keyword overlap between claim and authority text

    Args:
        claim_text: The legal claim/argument text.
        authorities: List of authority dicts (must be petition_ready only).
        cache: Optional Cache instance.

    Returns:
        Dict with ok, score, factors, supporting_count, warnings.
    """
    warnings: list[str] = []
    factors: list[dict[str, Any]] = []

    if not authorities:
        return {
            "ok": True,
            "score": 0.0,
            "factors": [],
            "supporting_count": 0,
            "warnings": ["No supporting authorities provided"],
        }

    # ── Factor 1: Count of supporting docs (0.0–0.4) ────────────────────
    count = len(authorities)
    count_score = min(count / 5.0, 1.0) * 0.4
    factors.append({
        "name": "support_count",
        "value": count,
        "score": round(count_score, 2),
    })

    # ── Factor 2: Content availability (0.0–0.3) ────────────────────────
    full_text_count = sum(
        1 for a in authorities
        if a.get("content_status") in ("full_text", "html_markdown")
    )
    content_ratio = full_text_count / count if count else 0.0
    content_score = content_ratio * 0.3
    factors.append({
        "name": "content_availability",
        "value": f"{full_text_count}/{count}",
        "score": round(content_score, 2),
    })

    # ── Factor 3: Citation safety (0.0–0.3) ─────────────────────────────
    safe_count = sum(
        1 for a in authorities
        if a.get("content_status") not in ("metadata_only", "unavailable")
    )
    safety_ratio = safe_count / count if count else 0.0
    safety_score = safety_ratio * 0.3
    factors.append({
        "name": "citation_safety",
        "value": f"{safe_count}/{count}",
        "score": round(safety_score, 2),
    })

    # ── Total score ──────────────────────────────────────────────────────
    total = round(count_score + content_score + safety_score, 2)
    total = max(0.0, min(1.0, total))

    return {
        "ok": True,
        "score": total,
        "factors": factors,
        "supporting_count": count,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# get_argument_strength_report
# ---------------------------------------------------------------------------

def get_argument_strength_report(
    pack_dir: str | Path,
    cache: Any | None = None,
) -> dict[str, Any]:
    """Generate an overall argument strength report for a petition pack.

    Calls ``build_argument_chain`` internally and computes aggregate metrics.

    Args:
        pack_dir: Path to petition pack directory.
        cache: Optional Cache instance.

    Returns:
        Dict with ok, overall_strength, argument_count, classification_distribution,
        strength_distribution, recommendations, warnings.
    """
    chain_result = build_argument_chain(pack_dir, cache=cache)
    if not chain_result.get("ok"):
        return chain_result

    arguments = chain_result.get("arguments", [])
    overall_strength = chain_result.get("overall_strength", 0.0)

    # ── Classification distribution ──────────────────────────────────────
    pack_meta = _load_pack_json(Path(pack_dir), "petition-pack.json")
    counts = pack_meta.get("classification_counts", {})

    # ── Strength distribution ────────────────────────────────────────────
    strong = sum(1 for a in arguments if a["strength"] >= 0.7)
    moderate = sum(1 for a in arguments if 0.3 <= a["strength"] < 0.7)
    weak = sum(1 for a in arguments if a["strength"] < 0.3)

    # ── Recommendations ──────────────────────────────────────────────────
    recommendations: list[str] = []
    if overall_strength < 0.3:
        recommendations.append(
            "Overall argument strength is low. Consider acquiring more "
            "petition_ready authorities with full text content."
        )
    if weak > strong:
        recommendations.append(
            f"More weak arguments ({weak}) than strong ones ({strong}). "
            "Focus on strengthening key claims."
        )
    no_support = sum(
        1 for a in arguments
        if not a["supporting_authorities"]
    )
    if no_support > 0:
        recommendations.append(
            f"{no_support} argument(s) have no supporting authorities. "
            "Verify or acquire petition_ready documents for these claims."
        )

    return {
        "ok": True,
        "pack_dir": str(pack_dir),
        "overall_strength": overall_strength,
        "argument_count": len(arguments),
        "classification_distribution": counts,
        "strength_distribution": {
            "strong": strong,
            "moderate": moderate,
            "weak": weak,
        },
        "recommendations": recommendations,
        "warnings": chain_result.get("warnings", []),
    }


# ---------------------------------------------------------------------------
# render_arguments_to_markdown
# ---------------------------------------------------------------------------

def render_arguments_to_markdown(
    pack_dir: str | Path,
    out_path: str | Path | None = None,
) -> str:
    """Render argument chains as a readable markdown document.

    Args:
        pack_dir: Path to petition pack directory.
        out_path: Optional output file path.  If None, only returns the
            markdown string without writing to disk.

    Returns:
        Markdown string of rendered arguments.
    """
    chain_result = build_argument_chain(pack_dir)
    if not chain_result.get("ok"):
        return f"# Argument Chain Error\n\n{chain_result.get('message', 'Unknown error')}\n"

    arguments = chain_result.get("arguments", [])
    overall_strength = chain_result.get("overall_strength", 0.0)
    matter = chain_result.get("matter", "")
    issue = chain_result.get("issue", "")

    lines = [
        "# Argument Chain Report",
        "",
        f"**Matter**: {matter}" if matter else "",
        f"**Issue**: {issue}" if issue else "",
        f"**Overall Strength**: {overall_strength:.0%}",
        f"**Argument Count**: {len(arguments)}",
        "",
        "---",
        "",
    ]

    for idx, arg in enumerate(arguments, 1):
        strength_pct = f"{arg['strength']:.0%}"
        lines.append(f"## {idx}. {arg['claim']}")
        lines.append("")
        lines.append(f"**Strength**: {strength_pct}")
        lines.append("")

        # Supporting authorities
        supp = arg.get("supporting_authorities", [])
        if supp:
            lines.append("### Supporting Authorities (petition_ready)")
            lines.append("")
            for auth in supp:
                lines.append(f"- **{auth.get('citation_label', auth.get('title', ''))}**")
                lines.append(f"  - Source: `{auth.get('source', '')}:{auth.get('document_id', '')}`")
                lines.append(f"  - Relevance: {auth.get('relevance', 'unknown')}")
                lines.append("")
        else:
            lines.append("*No supporting petition_ready authorities.*")
            lines.append("")

        # Research leads
        leads = arg.get("research_leads", [])
        if leads:
            lines.append("### Research Leads")
            lines.append("")
            for lead in leads:
                lines.append(f"- `{lead.get('source', '')}:{lead.get('document_id', '')}`")
                lines.append(f"  - Classification: {lead.get('classification', '')}")
                lines.append(f"  - Action: {lead.get('action', 'Verify from official source')}")
            lines.append("")

        # Counter-argument placeholder
        lines.append("### Karşı Argüman")
        lines.append("")
        lines.append("```")
        lines.append(arg.get("counter_argument", COUNTER_ARGUMENT_PLACEHOLDER))
        lines.append("```")
        lines.append("")

        # Warnings
        entry_warnings = arg.get("warnings", [])
        if entry_warnings:
            lines.append("### Warnings")
            lines.append("")
            for w in entry_warnings:
                lines.append(f"- ⚠️ {w}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Footer
    lines.append("> Bu belge emsal-mcp tarafından otomatik olarak oluşturulmuştur.")
    lines.append("> Karşı argüman bölümleri avukat tarafından doldurulmalıdır.")

    md = "\n".join(lines)

    # Write to file if output path provided
    if out_path is not None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")

    return md


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _reconstruct_document(
    auth_info: dict[str, Any],
    pack_path: Path,
    source_ref: str,
) -> Document | None:
    """Reconstruct a Document from brief authority info for citation_check.

    Attempts to load full text from source-documents directory if available.
    Returns None if reconstruction fails.
    """
    if not auth_info:
        return None

    doc_id = auth_info.get("document_id", "")
    source = auth_info.get("source", "")
    title = auth_info.get("title", "")
    content_status_str = auth_info.get("content_status", "metadata_only")

    try:
        content_status = ContentStatus(content_status_str)
    except ValueError:
        content_status = ContentStatus.METADATA_ONLY

    # Try to load full text from source-documents/
    full_text = None
    markdown = None
    src_dir = pack_path / "source-documents"
    if src_dir.exists():
        # Look for matching source document file
        for md_file in src_dir.glob("*.md"):
            try:
                file_text = md_file.read_text(encoding="utf-8")
                if doc_id in file_text or source_ref in md_file.stem:
                    # Extract content after ## Content section
                    content_match = re.search(
                        r"## Content\n\n(.+)", file_text, re.DOTALL
                    )
                    if content_match:
                        text = content_match.group(1).strip()
                        if text and text != "*No full text content available.*":
                            if content_status in (
                                ContentStatus.FULL_TEXT,
                                ContentStatus.HTML_MARKDOWN,
                            ):
                                full_text = text
                            else:
                                markdown = text
                    break
            except OSError:
                continue

    return Document(
        source=source,
        document_id=doc_id,
        title=title or doc_id,
        court=auth_info.get("court"),
        chamber=auth_info.get("chamber"),
        decision_date=auth_info.get("decision_date"),
        esas_no=auth_info.get("esas_no"),
        karar_no=auth_info.get("karar_no"),
        source_url=auth_info.get("source_url"),
        content_status=content_status,
        full_text=full_text,
        markdown=markdown,
    )


def _assess_relevance(
    claim_text: str,
    auth_info: dict[str, Any],
) -> str:
    """Assess relevance level of an authority to a claim.

    Returns 'high', 'medium', or 'low' based on keyword overlap
    and content availability.
    """
    title = auth_info.get("title", "")
    combined_auth_text = f"{title} {auth_info.get('court', '')} {auth_info.get('chamber', '')}"

    overlap = _keyword_overlap_score(claim_text, combined_auth_text)

    if overlap >= 0.3:
        return "high"
    elif overlap >= 0.1:
        return "medium"
    else:
        return "low"
