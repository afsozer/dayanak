"""Structured draft generation — M-80.

Template-based petition/opinion generation where every sentence is
linked to a citation-safe source.  Unverifiable statements are
marked [DOĞRULANMADI].
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import build_error

STRUCTURED_DRAFT_VERSION = "1.0.0"

# Placeholder for unverified claims
_UNVERIFIED_MARKER = "[DOĞRULANMADI]"


def generate_structured_draft(
    matter: str,
    issue: str,
    sections: list[dict[str, Any]] | None = None,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a structured petition draft with citation-linked claims.

    Each section is a dict with:
      - heading: Section title
      - claims: List of {statement, authority_doc_id, authority_source}
        where authority is a cached petition_ready document.
        If authority is None/empty, statement is marked [DOĞRULANMADI].

    Args:
        matter: Legal matter.
        issue: Legal issue.
        sections: Optional list of section dicts.
        out_path: Optional output path for the draft.

    Returns:
        Dict with ok, markdown, verified_count, unverified_count, out_path.
    """
    warnings: list[str] = []

    if sections is None:
        sections = [
            {
                "heading": "DAVA KONUSU",
                "claims": [
                    {"statement": f"{issue} hakkında dava açılmıştır.", "authority_doc_id": "", "authority_source": ""},
                ],
            },
            {
                "heading": "HUKUKİ DAYANAKLAR",
                "claims": [
                    {"statement": "{{HUKUKI_DAYANAK_1}}", "authority_doc_id": "", "authority_source": ""},
                    {"statement": "{{HUKUKI_DAYANAK_2}}", "authority_doc_id": "", "authority_source": ""},
                ],
            },
            {
                "heading": "SONUÇ VE İSTEM",
                "claims": [
                    {"statement": "{{TALEP_SONUCU}}", "authority_doc_id": "", "authority_source": ""},
                ],
            },
        ]

    lines = [
        f"# {matter}",
        "",
        "> **UYARI:** Bu belge yapay zeka destekli bir taslaktır. Hukuki geçerlilik için "
        "bir avukat tarafından incelenmeli ve onaylanmalıdır.",
        "",
    ]

    verified = 0
    unverified = 0
    footnote_idx = 0
    footnotes: list[str] = []

    for section in sections:
        heading = section.get("heading", "")
        claims = section.get("claims", [])

        lines.append(f"## {heading}")
        lines.append("")

        for claim in claims:
            statement = claim.get("statement", "")
            doc_id = claim.get("authority_doc_id", "")
            source = claim.get("authority_source", "")

            if doc_id and source:
                verified += 1
                footnote_idx += 1
                lines.append(f"{statement} [^{footnote_idx}]")
                footnotes.append(f"[^{footnote_idx}]: {source}/{doc_id}")
            elif "{{" in statement:
                # Placeholder — intentional, not unverified
                lines.append(statement)
            else:
                unverified += 1
                lines.append(f"{_UNVERIFIED_MARKER}: {statement}")
                warnings.append(f"Unverifiable claim: '{statement[:80]}...'")

        lines.append("")

    # Add footnotes section
    if footnotes:
        lines.append("## KAYNAKÇA")
        lines.append("")
        for fn in footnotes:
            lines.append(fn)
        lines.append("")

    markdown = "\n".join(lines)

    result: dict[str, Any] = {
        "ok": True,
        "markdown": markdown,
        "verified_count": verified,
        "unverified_count": unverified,
        "total_claims": verified + unverified,
        "warnings": warnings,
        "version": STRUCTURED_DRAFT_VERSION,
    }

    if out_path:
        p = Path(out_path)
        p.write_text(markdown, encoding="utf-8")
        result["out_path"] = str(p)

    return result
