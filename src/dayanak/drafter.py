from __future__ import annotations

import re

from .models import Draft, InputPack


def assemble_draft(pack: InputPack, kind: str, body_markdown: str, extra_citations: list[str] | None = None) -> Draft:
    """Assemble a controlled draft from safe InputPack only.

    - No invented citations: only uses citations from the pack
    - Includes warnings if body contains citation-like patterns
    """
    # Check for citation-like patterns in body
    warnings: list[str] = []
    citation_patterns = [
        (r'\d{4}/\d+', "Yıl/sayı formatı"),
        (r'Esas\s*No', "Esas numarası"),
        (r'Karar\s*No', "Karar numarası"),
        (r'Yargıtay\s+\d+\.\s+Daire', "Yargıtay dairesi"),
        (r'Danıştay\s+\d+\.\s+Daire', "Danıştay dairesi"),
        (r'Anayasa\s+Mahkemesi', "AYM referansı"),
    ]

    for pattern, desc in citation_patterns:
        if re.search(pattern, body_markdown):
            warnings.append(f"Metinde {desc} kalıbı bulundu; doğrulama gerekir.")

    # Merge citations from pack and extras
    all_citations = list(pack.safe_citations)
    if extra_citations:
        for c in extra_citations:
            if c not in all_citations:
                all_citations.append(c)

    return Draft(
        kind=kind,
        body_markdown=body_markdown,
        citations=all_citations,
        warnings=warnings,
        pack_id=pack.id,
    )


def validate_draft_body(body_markdown: str, pack: InputPack) -> list[str]:
    """Validate draft body doesn't contain fabricated citations."""
    issues: list[str] = []

    # Check if body references documents not in the pack
    doc_refs = re.findall(r'(\d{4}/\d+)', body_markdown)
    pack_nums = set()
    for doc in pack.documents:
        if doc.esas_no:
            pack_nums.add(doc.esas_no)
        if doc.karar_no:
            pack_nums.add(doc.karar_no)

    for ref in doc_refs:
        if ref not in pack_nums and pack_nums:
            issues.append(f"Metinde {ref} referansı var ama pack'te yok.")

    return issues
