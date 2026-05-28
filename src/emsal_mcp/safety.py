from __future__ import annotations

import hashlib
import re
from .models import CitationCheck, ContentStatus, Document, InputPack, SafetyState


def citation_check(doc: Document) -> CitationCheck:
    """Enforce citation safety: full_text/html_markdown + nonempty text + minimum provenance."""
    reasons: list[str] = []
    if doc.content_status not in {ContentStatus.FULL_TEXT, ContentStatus.HTML_MARKDOWN}:
        reasons.append(f"content_status={doc.content_status}; tam metin yok")
    if not doc.text.strip():
        reasons.append("belge metni boş")
    if not (doc.decision_date or doc.esas_no or doc.karar_no or doc.source_url):
        reasons.append("atıf için asgari metadata zayıf")
    ok = not reasons
    safety_state = SafetyState.SAFE if ok else SafetyState.UNSAFE
    return CitationCheck(ok=ok, quoteUsable=ok, draftUsable=ok, reasons=reasons, safety_state=safety_state)


def exact_quote(doc: Document, phrase: str, context: int = 180) -> str:
    """Only returns text if phrase exists verbatim; no paraphrase/no invention."""
    text = doc.text
    m = re.search(re.escape(phrase), text, flags=re.IGNORECASE)
    if not m:
        raise ValueError("İstenen ibare belge metninde aynen bulunamadı; quote üretilemez.")
    return text[max(0, m.start() - context) : min(len(text), m.end() + context)]


def build_input_pack(matter: str, issue: str, documents: list[Document]) -> InputPack:
    """Filter unsafe docs and build InputPack with stable pack_id."""
    safe: list[Document] = []
    excluded: list[dict[str, str]] = []
    warnings: list[str] = []
    for doc in documents:
        check = citation_check(doc)
        if check.ok:
            doc.safety_state = SafetyState.SAFE
            safe.append(doc)
        else:
            doc.safety_state = SafetyState.UNSAFE
            excluded.append({
                "document_id": doc.document_id,
                "source": doc.source,
                "reason": "; ".join(check.reasons),
            })
    warnings.append("Bu pack yalnızca citation-safe belgeleri içerir; eksik metadata uydurulmaz.")
    pack = InputPack(
        matter=matter,
        issue=issue,
        documents=safe,
        safe_citations=[d.citation_label() for d in safe],
        excluded=excluded,
        warnings=warnings,
    )
    return pack


def verify_document_hash(doc: Document) -> bool:
    """Verify document content hash matches stored hash."""
    if doc.content_hash is None:
        return True  # No hash to verify
    text = doc.text
    if not text:
        return doc.content_hash is None
    computed = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    return computed == doc.content_hash
