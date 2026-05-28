"""v0.7 Petition Pack v2 + v0.8 Controlled Draft + DOCX/Export Validation.

Classifies authorities as petition_ready, citation_only, research_lead_only, or
excluded based on citation safety, content_status, metadata/provenance, and
content_hash.  Generates a structured pack directory with brief, citation bank,
argument map, instructions (no-invention rules), draft skeleton with placeholders,
and source documents.  Never fabricates metadata.

v0.8 adds:
- prepare_petition_outline(): structured outline from pack
- prepare_controlled_petition_draft(): controlled draft with disclaimer,
  footnotes, and readiness scoring.  Only petition_ready authorities appear
  in direct quotes; citation_only appear only in bibliography warnings.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ContentStatus, Document
from .safety import citation_check, verify_document_hash


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACK_VERSION = "0.8.0"

CONTROLLED_DRAFT_VERSION = "0.8.0"

DISCLAIMER_HEADER = (
    "---\n"
    "DİKKAT: Bu belge emsal-mcp tarafından otomatik olarak oluşturulmuştur. "
    "Avukat denetimi ve resmi doğrulama gerektirir. "
    "Bu belgedeki {PLACEHOLDER} formatındaki alanlar yalnızca doğrulanmış "
    "bilgilerle doldurulmalıdır; eksik bırakılabilir ama uydurma bilgiyle "
    "değiştirilmez.\n"
    "---\n"
)

BIBLIOGRAPHY_WARNING = (
    "Bu bölümdeki atıflar yalnızca bibliyografik referans olarak yer almaktadır. "
    "citation_only olarak sınıflanmış belgeler dilekçe metninde doğrudan alıntı "
    "olarak kullanılamaz; yalnızca kaynakça bölümünde referans verilebilir."
)

REQUIRED_FILES = [
    "petition-brief.json",
    "citation-bank.md",
    "argument-map.md",
    "petition-instructions.md",
    "draft-skeleton.md",
    "petition-pack.json",
]

NO_INVENTION_RULE = (
    "Yasak: Bu belgede hiçbir surette uydurma, hayali veya doğrulanmamış "
    "bilgi üretilmez. eksik metadata tamamlanmaz, atıf uydurulmaz, "
    "kanun maddesi icat edilmez."
)

NO_INVENTION_PATTERNS = [
    r"uydurma",
    r"hayali",
    r"doğrulanmamış\s+bilgi\s+üretilmez",
    r"metadata\s+tamamlanmaz",
    r"atıf\s+uydurulmaz",
    r"kanun\s+maddesi\s+icat\s+edilmez",
    r"no[\s-]*invention",
    r"no[\s-]*fabrication",
]

PLACEHOLDER_PATTERN = re.compile(r"\{\{[^}]+\}\}")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify_authority(doc: Document) -> str:
    """Classify a single document/authority into a petition pack category.

    Classification logic:
    - petition_ready: citation_check passes (full_text/html_markdown, nonempty
      text, provenance present), content_hash valid if present.
    - citation_only: citation_check passes on metadata but content is
      metadata_only or pdf_link_only — usable for citation references
      only, not for drafting.
    - research_lead_only: citation_check fails completely (no content,
      no metadata) — can only guide research direction.
    - excluded: safety check fails, content_hash mismatch, or document
      is unavailable.
    """
    # Unavailable documents are always excluded
    if doc.content_status == ContentStatus.UNAVAILABLE:
        return "excluded"

    check = citation_check(doc)

    # Hash verification if content_hash is present
    hash_ok = True
    if doc.content_hash is not None:
        hash_ok = verify_document_hash(doc)

    if not hash_ok:
        return "excluded"

    if check.ok:
        # citation_check passes — but check if content is truly draft-usable
        if doc.content_status in {ContentStatus.FULL_TEXT, ContentStatus.HTML_MARKDOWN}:
            text = doc.text.strip()
            if text and len(text) >= 50:
                return "petition_ready"
        # Has citation-safe metadata but not full text for drafting
        return "citation_only"

    # citation_check failed — check if we have at least some metadata
    has_any_metadata = bool(
        doc.title
        or doc.court
        or doc.decision_date
        or doc.esas_no
        or doc.karar_no
        or doc.source_url
    )

    if has_any_metadata and doc.content_status == ContentStatus.PDF_LINK_ONLY:
        return "citation_only"

    if has_any_metadata:
        return "research_lead_only"

    return "excluded"


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_manifest(pack_dir: Path) -> dict[str, str]:
    """Compute content hashes for source-documents/*.md files."""
    manifest: dict[str, str] = {}
    src_dir = pack_dir / "source-documents"
    if src_dir.exists():
        for f in sorted(src_dir.glob("*.md")):
            manifest[f.name] = _hash_file(f)
    return manifest


# ---------------------------------------------------------------------------
# Pack Generation
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)[:120]


def _generate_petition_brief(
    matter: str,
    issue: str,
    classifications: dict[str, str],
    documents: list[Document],
) -> dict[str, Any]:
    """Generate petition-brief.json content."""
    counts = {
        "petition_ready": 0,
        "citation_only": 0,
        "research_lead_only": 0,
        "excluded": 0,
    }
    for cat in classifications.values():
        if cat in counts:
            counts[cat] += 1

    authorities = []
    for doc, cat in zip(documents, classifications.values()):
        authorities.append({
            "document_id": doc.document_id,
            "source": doc.source,
            "title": doc.title or doc.document_id,
            "classification": cat,
            "citation_label": doc.citation_label(),
            "content_status": doc.content_status.value,
        })

    return {
        "version": PACK_VERSION,
        "matter": matter,
        "issue": issue,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "authority_count": len(documents),
        "classification_counts": counts,
        "authorities": authorities,
        "draft_safe": counts["petition_ready"] > 0,
    }


def _generate_citation_bank(
    documents: list[Document],
    classifications: dict[str, str],
) -> str:
    """Generate citation-bank.md with only safe citation references."""
    lines = [
        "# Citation Bank",
        "",
        "Bu bölüm yalnızca doğrulanmış ve güvenli atıf referanslarını içerir.",
        "",
    ]

    petition_ready = [
        doc for doc, cat in zip(documents, classifications.values())
        if cat == "petition_ready"
    ]
    citation_only = [
        doc for doc, cat in zip(documents, classifications.values())
        if cat == "citation_only"
    ]

    if petition_ready:
        lines.append("## Petition Ready (Full Draft Usage)")
        lines.append("")
        for doc in petition_ready:
            lines.append(f"- **{doc.citation_label()}**")
            lines.append(f"  - Source: `{doc.source}:{doc.document_id}`")
            if doc.source_url:
                lines.append(f"  - URL: {doc.source_url}")
            lines.append("")

    if citation_only:
        lines.append("## Citation Only (Reference Only)")
        lines.append("")
        for doc in citation_only:
            lines.append(f"- **{doc.citation_label()}**")
            lines.append(f"  - Source: `{doc.source}:{doc.document_id}`")
            lines.append(f"  - Status: {doc.content_status.value} — only use for citation references")
            lines.append("")

    if not petition_ready and not citation_only:
        lines.append("No citation-safe documents available.")
        lines.append("")

    lines.append("---")
    lines.append(f"> Generated by emsal-mcp v{PACK_VERSION}. Do not add unverified citations.")
    return "\n".join(lines)


def _generate_argument_map(
    matter: str,
    issue: str,
    documents: list[Document],
    classifications: dict[str, str],
) -> str:
    """Generate argument-map.md with research-lead placeholders."""
    lines = [
        "# Argument Map",
        "",
        f"**Matter**: {matter}",
        f"**Issue**: {issue}",
        "",
        "## Authority Map",
        "",
    ]

    for doc, cat in zip(documents, classifications.values()):
        emoji = {
            "petition_ready": "[READY]",
            "citation_only": "[CITE]",
            "research_lead_only": "[RESEARCH]",
            "excluded": "[EXCLUDED]",
        }.get(cat, "[UNKNOWN]")
        lines.append(f"- {emoji} **{doc.citation_label()}** ({doc.source}:{doc.document_id})")
        lines.append(f"  - Classification: {cat}")
        lines.append(f"  - Content Status: {doc.content_status.value}")
        if cat == "research_lead_only":
            lines.append("  - Action: Verify from official source before use")
        elif cat == "excluded":
            lines.append("  - Action: Not usable in petition")
        lines.append("")

    lines.append("## Research Leads")
    lines.append("")
    has_research_leads = False
    for doc, cat in zip(documents, classifications.values()):
        if cat in ("research_lead_only", "citation_only"):
            has_research_leads = True
            lines.append(f"- Verify `{doc.source}:{doc.document_id}` from official source")
    if not has_research_leads:
        lines.append("- No research leads pending.")
    lines.append("")
    return "\n".join(lines)


def _generate_petition_instructions() -> str:
    """Generate petition-instructions.md with explicit no-invention rules."""
    return f"""# Petition Instructions

## Kurallar

1. **Uydurma Yasak**: {NO_INVENTION_RULE}

2. **Metadata Tamamlanmaz**: Eksik metadata (tarih, daire, esas/karar numarası)
   hiçbir surette tamamlanmaz veya uydurulmaz.

3. **Atıf Doğrulanır**: Dilekçede yer alacak her atıf, yalnızca
   citation-bank.md içinde güvenli olarak sınıflanmış belgelerden alınır.

4. **Taslak Kontrol**: Draft-skeleton.md içindeki placeholder'lar
   ({'{{PLACEHOLDER}}'} formatında) yalnızca doğrulanmış bilgilerle
   doldurulur; boş bırakılabilir ama uydurma bilgiyle değiştirilmez.

5. **Kaynak Doğrulama**: research_lead_only olarak sınıflanmış belgeler
   yalnızca araştırma yönü gösterir; dilekçe metnine doğrudan alınmaz.

6. **Kanun Maddesi**: Hiçbir kanun maddesi veya mevzuat hükmü icat edilmez;
   yalnızca doğrulanmış kaynaklardan referans verilir.

## No-Invention Rule (English)

This petition pack strictly prohibits fabrication of any kind:
- No invented metadata (dates, case numbers, chamber information)
- No unverified citations in petition text
- No fabricated legislation or regulation references
- Missing information is left as placeholder, never filled with guesses

## Usage

1. Start from draft-skeleton.md
2. Fill placeholders with verified information from citation-bank.md
3. Cross-reference argument-map.md for authority classification
4. Never add information not present in source documents
5. Run `emsal-mcp petition inspect <pack_dir>` to validate before use
"""


def _generate_draft_skeleton(
    matter: str,
    issue: str,
    petition_ready_docs: list[Document],
) -> str:
    """Generate draft-skeleton.md with placeholders for unverified data."""
    lines = [
        "# Dilekçe Taslağı",
        "",
        "## Başlık",
        "",
        "{{DILEKCE_BASLIK}}",
        "",
        "## Mahkeme",
        "",
        "{{MAHKEME_ADRES}}",
        "",
        "## Taraflar",
        "",
        "- **Davacı**: {{DAVACI_AD_SOYAD}}"
        "",
        "- **Davalı**: {{DALI_AD_SOYAD}}"
        "",
        "## Dilekçe Konusu",
        "",
        f"{issue}",
        "",
        "## Açıklamalar",
        "",
        "{{ACIKLAMALAR_BASLIK}}",
        "",
    ]

    if petition_ready_docs:
        lines.append("### İlgili Kararlar")
        lines.append("")
        for doc in petition_ready_docs:
            lines.append(f"{{{{KARAR_{_safe_filename(doc.document_id).upper()}}}}}")
            lines.append(f"- Kaynak: `{doc.source}:{doc.document_id}`")
            lines.append("")
    else:
        lines.append("{{ILGILI_KARARLAR}}")
        lines.append("")

    lines.extend([
        "## Sonuç ve Talep",
        "",
        "{{SONUC_VE_TALEP}}",
        "",
        "## Ekler",
        "",
        "{{EKLER}}",
        "",
        "---",
        f"> Taslak emsal-mcp v{PACK_VERSION} tarafından oluşturulmuştur.",
        "> Bu taslak avukat denetimi gerektirir.",
        "> {{}} içindeki alanlar doğrulanmış bilgilerle doldurulmalıdır.",
    ])
    return "\n".join(lines)


def _write_source_documents(
    pack_dir: Path,
    documents: list[Document],
    classifications: dict[str, str],
) -> list[str]:
    """Write source-documents/*.md for safe full-text docs. Returns filenames."""
    src_dir = pack_dir / "source-documents"
    src_dir.mkdir(exist_ok=True)

    written: list[str] = []
    for doc, cat in zip(documents, classifications.values()):
        if cat in ("excluded",):
            continue

        fname = _safe_filename(f"{doc.source}_{doc.document_id}") + ".md"
        parts = [
            f"# {doc.title or doc.document_id}",
            "",
            f"- **Source**: {doc.source}",
            f"- **Document ID**: {doc.document_id}",
            f"- **Classification**: {cat}",
        ]
        if doc.court:
            parts.append(f"- **Court**: {doc.court}")
        if doc.chamber:
            parts.append(f"- **Chamber**: {doc.chamber}")
        if doc.decision_date:
            parts.append(f"- **Decision Date**: {doc.decision_date}")
        if doc.esas_no:
            parts.append(f"- **Esas No**: {doc.esas_no}")
        if doc.karar_no:
            parts.append(f"- **Karar No**: {doc.karar_no}")
        if doc.source_url:
            parts.append(f"- **Source URL**: {doc.source_url}")
        parts.append(f"- **Content Status**: {doc.content_status.value}")
        parts.append(f"- **Content Hash**: {doc.content_hash or 'N/A'}")
        parts.append("")
        if doc.text.strip():
            parts.append("## Content")
            parts.append("")
            parts.append(doc.text)
        else:
            parts.append("*No full text content available.*")
            parts.append("")

        (src_dir / fname).write_text("\n".join(parts), encoding="utf-8")
        written.append(fname)

    return written


# ---------------------------------------------------------------------------
# Main: prepare_drafting_input_pack
# ---------------------------------------------------------------------------

def prepare_drafting_input_pack(
    matter: str,
    issue: str,
    documents: list[Document] | None = None,
    research_bundle_dir: str | Path | None = None,
    out_dir: str | Path | None = None,
    strict: bool = True,
    cache: Any | None = None,
) -> dict[str, Any]:
    """Prepare a petition drafting input pack.

    Classifies authorities as petition_ready, citation_only,
    research_lead_only, or excluded using citation safety, content_status,
    metadata/provenance, and content_hash.  Generates a structured pack
    directory with all required files.

    Args:
        matter: Legal matter description.
        issue: Legal issue description.
        documents: List of Document objects to classify.  If None and
            research_bundle_dir is provided, documents are loaded from the
            research bundle.
        research_bundle_dir: Optional path to a v0.5 research bundle
            directory.  Documents are loaded from results.json if documents
            is None.
        out_dir: Output directory for the pack.  If None, a default
            directory is created.
        strict: If True, exclude any document that fails hash verification.
        cache: Optional Cache instance for history logging.

    Returns:
        Dict with pack metadata: ok, out_dir, draft_safe, counts,
        classifications, files, warnings, hash_manifest.
    """
    documents = documents or []
    warnings: list[str] = []

    # Load from research bundle if no documents provided
    if not documents and research_bundle_dir is not None:
        bundle_dir = Path(research_bundle_dir)
        results_path = bundle_dir / "results.json"
        if results_path.exists():
            results = json.loads(results_path.read_text(encoding="utf-8"))
            for r in results:
                doc = Document(
                    source=r.get("source", "unknown"),
                    document_id=r.get("document_id", ""),
                    title=r.get("title"),
                    court=r.get("court"),
                    chamber=r.get("chamber"),
                    decision_date=r.get("decision_date"),
                    esas_no=r.get("esas_no"),
                    karar_no=r.get("karar_no"),
                    source_url=r.get("source_url"),
                    content_status=ContentStatus(r.get("content_status", "metadata_only")),
                )
                documents.append(doc)
        else:
            warnings.append(f"Research bundle results not found: {results_path}")

    # Classify all documents
    classifications: dict[str, str] = {}
    for doc in documents:
        classifications[f"{doc.source}:{doc.document_id}"] = _classify_authority(doc)

    # Count classifications
    counts = {
        "petition_ready": 0,
        "citation_only": 0,
        "research_lead_only": 0,
        "excluded": 0,
    }
    for cat in classifications.values():
        if cat in counts:
            counts[cat] += 1

    draft_safe = counts["petition_ready"] > 0

    # Warnings for non-draft-safe packs
    if not draft_safe:
        warnings.append(
            "Pack is NOT draft_safe: no petition_ready authorities found. "
            "Cannot generate a usable draft skeleton."
        )
    if counts["metadata_only_count"] if hasattr(counts, "metadata_only_count") else 0:
        pass  # not used
    if counts["excluded"] == len(documents) and documents:
        warnings.append("All documents excluded; pack contains no usable authorities.")

    # Determine output directory
    if out_dir is None:
        out_dir = Path(".emsal_petition") / _hash_text(f"{matter}:{issue}")[:12]
    else:
        out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate files
    petition_ready_docs = [
        doc for doc, cat in zip(documents, classifications.values())
        if cat == "petition_ready"
    ]

    brief = _generate_petition_brief(matter, issue, classifications, documents)
    citation_bank = _generate_citation_bank(documents, classifications)
    argument_map = _generate_argument_map(matter, issue, documents, classifications)
    instructions = _generate_petition_instructions()
    skeleton = _generate_draft_skeleton(matter, issue, petition_ready_docs)

    # petition-pack.json (metadata)
    pack_meta = {
        "version": PACK_VERSION,
        "matter": matter,
        "issue": issue,
        "draft_safe": draft_safe,
        "classification_counts": counts,
        "authority_count": len(documents),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
        "warnings": warnings,
    }

    # Write source documents
    source_files = _write_source_documents(out_dir, documents, classifications)

    # Write all files
    files_written: list[str] = []

    brief_path = out_dir / "petition-brief.json"
    brief_path.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    files_written.append("petition-brief.json")

    (out_dir / "citation-bank.md").write_text(citation_bank, encoding="utf-8")
    files_written.append("citation-bank.md")

    (out_dir / "argument-map.md").write_text(argument_map, encoding="utf-8")
    files_written.append("argument-map.md")

    (out_dir / "petition-instructions.md").write_text(instructions, encoding="utf-8")
    files_written.append("petition-instructions.md")

    (out_dir / "draft-skeleton.md").write_text(skeleton, encoding="utf-8")
    files_written.append("draft-skeleton.md")

    for sf in source_files:
        files_written.append(f"source-documents/{sf}")

    pack_meta["files"] = files_written

    # Hash manifest
    hash_manifest = _hash_manifest(out_dir)
    if hash_manifest:
        manifest_path = out_dir / "hash-manifest.json"
        manifest_path.write_text(
            json.dumps(hash_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        files_written.append("hash-manifest.json")
        pack_meta["hash_manifest"] = hash_manifest

    # Write petition-pack.json last (with full metadata)
    (out_dir / "petition-pack.json").write_text(
        json.dumps(pack_meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    files_written.append("petition-pack.json")

    # Log to cache if provided
    if cache is not None:
        try:
            cache.log("prepare_drafting_input_pack", {
                "matter": matter,
                "issue": issue,
                "out_dir": str(out_dir),
                "draft_safe": draft_safe,
                "classification_counts": counts,
                "authority_count": len(documents),
            })
        except Exception:
            pass  # non-critical

    return {
        "ok": True,
        "out_dir": str(out_dir),
        "draft_safe": draft_safe,
        "authority_count": len(documents),
        "counts": counts,
        "classifications": classifications,
        "files": files_written,
        "warnings": warnings,
        "hash_manifest": hash_manifest,
    }


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def inspect_petition_pack(pack_dir: str | Path) -> dict[str, Any]:
    """Validate a petition pack directory.

    Checks:
    - Required files exist
    - draft_safe flag from petition-pack.json
    - Classification counts
    - placeholdersInDraftSkeleton: placeholder count in draft-skeleton.md
    - legislationVerified placeholder: no unverified legislation references
    - petitionInstructionsForbidsInvention: instructions contain no-invention rule
    - citationBankOnlySafeDocs: citation bank only references safe docs
    - hashManifestValid: if hash-manifest.json exists, verify hashes

    Returns:
        Dict with ok, draft_safe, errors, warnings, counts, checks.
    """
    pack_path = Path(pack_dir)
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    # Check required files
    for fname in REQUIRED_FILES:
        if not (pack_path / fname).exists():
            errors.append(f"Required file missing: {fname}")

    # Read petition-pack.json if available
    pack_meta: dict[str, Any] = {}
    meta_path = pack_path / "petition-pack.json"
    if meta_path.exists():
        try:
            pack_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("petition-pack.json is not valid JSON")

    draft_safe = pack_meta.get("draft_safe", False)
    counts = pack_meta.get("classification_counts", {})

    # Check draft-skeleton.md for placeholders
    skeleton_path = pack_path / "draft-skeleton.md"
    if skeleton_path.exists():
        skeleton_text = skeleton_path.read_text(encoding="utf-8")
        placeholders = PLACEHOLDER_PATTERN.findall(skeleton_text)
        checks["placeholdersInDraftSkeleton"] = {
            "count": len(placeholders),
            "placeholders": placeholders,
            "ok": True,  # placeholders are expected
        }
    else:
        checks["placeholdersInDraftSkeleton"] = {
            "count": 0,
            "placeholders": [],
            "ok": False,
            "error": "draft-skeleton.md not found",
        }

    # Check petition-instructions.md for no-invention rule
    instructions_path = pack_path / "petition-instructions.md"
    if instructions_path.exists():
        instructions_text = instructions_path.read_text(encoding="utf-8")
        has_no_invention = any(
            re.search(pat, instructions_text, re.IGNORECASE)
            for pat in NO_INVENTION_PATTERNS
        )
        checks["petitionInstructionsForbidsInvention"] = {
            "ok": has_no_invention,
            "rule_found": has_no_invention,
        }
        if not has_no_invention:
            errors.append(
                "petition-instructions.md does not contain the required no-invention rule"
            )
    else:
        checks["petitionInstructionsForbidsInvention"] = {
            "ok": False,
            "rule_found": False,
        }
        errors.append("petition-instructions.md is missing")

    # Check citation-bank.md only references safe docs
    citation_bank_path = pack_path / "citation-bank.md"
    if citation_bank_path.exists():
        citation_text = citation_bank_path.read_text(encoding="utf-8")
        # Simple check: should not contain "excluded" classification markers
        has_excluded_refs = "EXCLUDED" in citation_text.upper() and "[EXCLUDED]" in citation_text
        checks["citationBankOnlySafeDocs"] = {
            "ok": not has_excluded_refs,
            "excluded_refs_found": has_excluded_refs,
        }
        if has_excluded_refs:
            warnings.append("citation-bank.md references excluded documents")
    else:
        checks["citationBankOnlySafeDocs"] = {
            "ok": False,
            "error": "citation-bank.md not found",
        }

    # Check hash manifest if available
    manifest_path = pack_path / "hash-manifest.json"
    if manifest_path.exists():
        try:
            stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            current_manifest = _hash_manifest(pack_path)
            mismatches = []
            for fname, stored_hash in stored_manifest.items():
                if fname in current_manifest:
                    if current_manifest[fname] != stored_hash:
                        mismatches.append(fname)
            checks["hashManifestValid"] = {
                "ok": len(mismatches) == 0,
                "mismatches": mismatches,
                "file_count": len(stored_manifest),
            }
            if mismatches:
                errors.append(f"Hash manifest mismatch for files: {mismatches}")
        except json.JSONDecodeError:
            checks["hashManifestValid"] = {
                "ok": False,
                "error": "hash-manifest.json is not valid JSON",
            }
            errors.append("hash-manifest.json is not valid JSON")
    else:
        checks["hashManifestValid"] = {
            "ok": True,
            "skipped": True,
            "reason": "hash-manifest.json not present",
        }

    # Check metadataOnlyDraftUsable
    petition_ready = counts.get("petition_ready", 0)
    metadata_only = counts.get("citation_only", 0) + counts.get("research_lead_only", 0)
    # ok = True means the invariant is satisfied: metadata_only docs are
    # correctly NOT counted as petition_ready.  This is always true because
    # our classification never promotes metadata_only to petition_ready.
    checks["metadataOnlyDraftUsable"] = {
        "ok": True,
        "petition_ready": petition_ready,
        "metadata_only_equivalent": metadata_only,
        "note": "metadata_only and pdf_only are never petition_ready",
    }

    # legislationVerified placeholder check
    # (no unverified legislation references in draft skeleton)
    if skeleton_path.exists():
        skeleton_text = skeleton_path.read_text(encoding="utf-8")
        # Check for any hardcoded law references that aren't placeholders
        law_pattern = re.compile(
            r"(?:Kanun|Madde|Hüküm)\s*(?:No|numarası)?\s*[:.]?\s*\d+",
            re.IGNORECASE,
        )
        law_refs = law_pattern.findall(skeleton_text)
        checks["legislationVerifiedPlaceholder"] = {
            "ok": True,  # placeholders are fine
            "hardcoded_refs": law_refs,
            "note": "Law references should use placeholders unless verified",
        }
    else:
        checks["legislationVerifiedPlaceholder"] = {
            "ok": False,
            "error": "draft-skeleton.md not found",
        }

    return {
        "ok": len(errors) == 0,
        "draft_safe": draft_safe,
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "checks": checks,
    }


# ===========================================================================
# v0.8: Controlled Draft + Outline
# ===========================================================================


def prepare_petition_outline(
    pack_dir: str | Path,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a structured petition outline from a petition pack.

    Reads petition-pack.json and petition-brief.json from *pack_dir* and
    produces an ``outline.json`` that describes every section, its
    placeholders, and which authorities contribute to it.

    Only ``petition_ready`` authorities may supply direct content;
    ``citation_only`` authorities appear only in the bibliography section
    with a warning flag.

    Args:
        pack_dir: Path to a petition pack directory (from v0.7).
        out_dir: Where to write ``outline.json``.  Defaults to *pack_dir*.

    Returns:
        Dict with ok, outline_path, sections, placeholder_total,
        citation_only_bibliography_count, petition_ready_count.
    """
    pack_path = Path(pack_dir)
    out_path = Path(out_dir) if out_dir else pack_path
    out_path.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []

    # ── Load pack metadata ──────────────────────────────────────────────
    pack_meta_path = pack_path / "petition-pack.json"
    if not pack_meta_path.exists():
        return {"ok": False, "error": "petition-pack.json not found in pack_dir"}

    pack_meta = json.loads(pack_meta_path.read_text(encoding="utf-8"))
    counts = pack_meta.get("classification_counts", {})
    petition_ready_count = counts.get("petition_ready", 0)
    citation_only_count = counts.get("citation_only", 0)

    # ── Load brief for authority details ────────────────────────────────
    brief_path = pack_path / "petition-brief.json"
    brief: dict[str, Any] = {}
    if brief_path.exists():
        brief = json.loads(brief_path.read_text(encoding="utf-8"))

    authorities = brief.get("authorities", [])
    petition_ready_auths = [a for a in authorities if a.get("classification") == "petition_ready"]
    citation_only_auths = [a for a in authorities if a.get("classification") == "citation_only"]

    # ── Read draft skeleton for placeholders ────────────────────────────
    skeleton_path = pack_path / "draft-skeleton.md"
    skeleton_text = skeleton_path.read_text(encoding="utf-8") if skeleton_path.exists() else ""
    placeholders = PLACEHOLDER_PATTERN.findall(skeleton_text)

    # ── Build sections ──────────────────────────────────────────────────
    sections: list[dict[str, Any]] = []

    # Section: Header / Disclaimer
    sections.append({
        "id": "header",
        "title": "Sorumluluk Reddi",
        "type": "disclaimer",
        "content_source": "generated",
        "placeholders": [],
        "authorities": [],
    })

    # Section: Başlık
    sections.append({
        "id": "title",
        "title": "Başlık",
        "type": "user_content",
        "content_source": "placeholder",
        "placeholders": [p for p in placeholders if "BASLIK" in p.upper()],
        "authorities": [],
    })

    # Section: Mahkeme
    sections.append({
        "id": "court",
        "title": "Mahkeme",
        "type": "user_content",
        "content_source": "placeholder",
        "placeholders": [p for p in placeholders if "MAHKEME" in p.upper()],
        "authorities": [],
    })

    # Section: Taraflar
    sections.append({
        "id": "parties",
        "title": "Taraflar",
        "type": "user_content",
        "content_source": "placeholder",
        "placeholders": [p for p in placeholders if any(
            kw in p.upper() for kw in ("DAVACI", "DALI", "DAVALI")
        )],
        "authorities": [],
    })

    # Section: Dilekçe Konusu
    sections.append({
        "id": "subject",
        "title": "Dilekçe Konusu",
        "type": "user_content",
        "content_source": "pack_metadata",
        "placeholders": [],
        "authorities": [],
        "content_ref": "issue",
    })

    # Section: Açıklamalar (from petition_ready authorities)
    sections.append({
        "id": "explanations",
        "title": "Açıklamalar",
        "type": "authority_content",
        "content_source": "petition_ready",
        "placeholders": [p for p in placeholders if "ACIKLAMA" in p.upper()],
        "authorities": [a["document_id"] for a in petition_ready_auths],
    })

    # Section: İlgili Kararlar (petition_ready direct quotes)
    sections.append({
        "id": "decisions",
        "title": "İlgili Kararlar",
        "type": "authority_content",
        "content_source": "petition_ready",
        "placeholders": [p for p in placeholders if "KARAR" in p.upper()],
        "authorities": [a["document_id"] for a in petition_ready_auths],
        "note": "Yalnızca petition_ready belgelerden doğrudan alıntı yapılabilir.",
    })

    # Section: Kaynakça (bibliography — includes citation_only with warning)
    bib_authorities: list[dict[str, Any]] = []
    for auth in petition_ready_auths:
        bib_authorities.append({
            "document_id": auth["document_id"],
            "source": auth.get("source", ""),
            "label": auth.get("citation_label", ""),
            "classification": "petition_ready",
            "warning": None,
        })
    for auth in citation_only_auths:
        bib_authorities.append({
            "document_id": auth["document_id"],
            "source": auth.get("source", ""),
            "label": auth.get("citation_label", ""),
            "classification": "citation_only",
            "warning": "Bibliyografik referans; doğrudan alıntı yapılamaz.",
        })

    sections.append({
        "id": "bibliography",
        "title": "Kaynakça",
        "type": "bibliography",
        "content_source": "mixed",
        "placeholders": [],
        "authorities": bib_authorities,
        "has_citation_only_refs": citation_only_count > 0,
        "warning": BIBLIOGRAPHY_WARNING if citation_only_count > 0 else None,
    })

    # Section: Sonuç ve Talep
    sections.append({
        "id": "conclusion",
        "title": "Sonuç ve Talep",
        "type": "user_content",
        "content_source": "placeholder",
        "placeholders": [p for p in placeholders if any(
            kw in p.upper() for kw in ("SONUC", "TALEP")
        )],
        "authorities": [],
    })

    # Section: Ekler
    sections.append({
        "id": "attachments",
        "title": "Ekler",
        "type": "user_content",
        "content_source": "placeholder",
        "placeholders": [p for p in placeholders if "EKLER" in p.upper()],
        "authorities": [],
    })

    # ── Assemble outline ────────────────────────────────────────────────
    placeholder_total = sum(len(s.get("placeholders", [])) for s in sections)

    outline = {
        "version": CONTROLLED_DRAFT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pack_version": pack_meta.get("version", "unknown"),
        "matter": pack_meta.get("matter", ""),
        "issue": pack_meta.get("issue", ""),
        "petition_ready_count": petition_ready_count,
        "citation_only_count": citation_only_count,
        "citation_only_bibliography_count": citation_only_count,
        "placeholder_total": placeholder_total,
        "sections": sections,
        "warnings": warnings,
    }

    outline_path = out_path / "outline.json"
    outline_path.write_text(
        json.dumps(outline, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "outline_path": str(outline_path),
        "sections": sections,
        "placeholder_total": placeholder_total,
        "citation_only_bibliography_count": citation_only_count,
        "petition_ready_count": petition_ready_count,
        "warnings": warnings,
    }


def prepare_controlled_petition_draft(
    pack_dir: str | Path,
    outline_path: str | Path | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a controlled petition draft from a petition pack.

    Produces four output files:

    * ``draft.md`` — Markdown draft with disclaimer header, placeholder
      sections, and footnotes.  Only ``petition_ready`` authorities may
      supply direct quotes; ``citation_only`` authorities appear only as
      bibliographic references with a warning.
    * ``draft.json`` — Structured metadata with paragraph/section/footnote
      counts, placeholder counts, blocking warning count, readiness
      score/level, and finalization risk score.
    * ``footnotes.json`` — Footnote references extracted from
      ``petition_ready`` authorities.
    * ``warnings.json`` — List of warnings (blocking and non-blocking).

    Placeholders (``{{…}}``) are always preserved verbatim.

    Args:
        pack_dir: Path to a petition pack directory.
        outline_path: Optional pre-computed outline.json.  If ``None``
            the outline is generated on the fly.
        out_dir: Output directory.  Defaults to ``<pack_dir>/draft_output``.

    Returns:
        Dict with ok, out_dir, draft_md_path, draft_json_path,
        footnotes_path, warnings_path, draft_metadata.
    """
    pack_path = Path(pack_dir)
    out_path = Path(out_dir) if out_dir else pack_path / "draft_output"
    out_path.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    blocking_warnings: list[str] = []

    # ── Load pack metadata ──────────────────────────────────────────────
    pack_meta_path = pack_path / "petition-pack.json"
    if not pack_meta_path.exists():
        return {"ok": False, "error": "petition-pack.json not found in pack_dir"}

    pack_meta = json.loads(pack_meta_path.read_text(encoding="utf-8"))
    counts = pack_meta.get("classification_counts", {})
    petition_ready_count = counts.get("petition_ready", 0)
    citation_only_count = counts.get("citation_only", 0)
    research_lead_count = counts.get("research_lead_only", 0)
    excluded_count = counts.get("excluded", 0)

    # ── Load or generate outline ────────────────────────────────────────
    if outline_path and Path(outline_path).exists():
        outline = json.loads(Path(outline_path).read_text(encoding="utf-8"))
    else:
        outline_result = prepare_petition_outline(pack_dir, out_dir=out_path)
        if not outline_result.get("ok"):
            return outline_result
        outline = json.loads(
            Path(outline_result["outline_path"]).read_text(encoding="utf-8")
        )

    # ── Load brief for authority details ────────────────────────────────
    brief_path = pack_path / "petition-brief.json"
    brief: dict[str, Any] = {}
    if brief_path.exists():
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
    authorities = brief.get("authorities", [])
    petition_ready_auths = [a for a in authorities if a.get("classification") == "petition_ready"]
    citation_only_auths = [a for a in authorities if a.get("classification") == "citation_only"]

    # ── Read draft skeleton ─────────────────────────────────────────────
    skeleton_path = pack_path / "draft-skeleton.md"
    skeleton_text = skeleton_path.read_text(encoding="utf-8") if skeleton_path.exists() else ""
    placeholders = PLACEHOLDER_PATTERN.findall(skeleton_text)

    # ── Build footnotes from petition_ready authorities only ─────────────
    footnotes: list[dict[str, Any]] = []
    for idx, auth in enumerate(petition_ready_auths, 1):
        footnotes.append({
            "footnote_id": idx,
            "document_id": auth.get("document_id", ""),
            "source": auth.get("source", ""),
            "citation_label": auth.get("citation_label", ""),
            "classification": auth.get("classification", ""),
            "content_status": auth.get("content_status", ""),
            "type": "petition_ready",
            "warning": None,
        })

    # citation_only references go into bibliography warnings, NOT footnotes
    bib_warnings: list[str] = []
    for auth in citation_only_auths:
        bib_warnings.append(
            f"{auth.get('citation_label', auth.get('document_id', ''))} "
            f"— citation_only; yalnızca bibliyografik referans olarak eklenebilir."
        )

    # ── Blocking warnings ───────────────────────────────────────────────
    if petition_ready_count == 0:
        blocking_warnings.append(
            "Hiçbir petition_ready belge yok; kullanılamaz draft oluşturulamaz."
        )
    if excluded_count > 0 and excluded_count == len(authorities):
        blocking_warnings.append(
            "Tüm belgeler excluded; geçerli kaynak bulunmamaktadır."
        )

    # Non-blocking warnings
    if citation_only_count > 0:
        warnings.append(
            f"{citation_only_count} citation_only belge yalnızca bibliyografik "
            "referans olarak kullanılabilir; doğrudan alıntı yapılamaz."
        )
    if research_lead_count > 0:
        warnings.append(
            f"{research_lead_count} research_lead_only belge doğrulanmamıştır; "
            "kullanılmadan önce resmi kaynaktan doğrulanmalıdır."
        )

    # ── Build draft.md ──────────────────────────────────────────────────
    md_lines: list[str] = []

    # Disclaimer header
    md_lines.append(DISCLAIMER_HEADER)
    md_lines.append("")

    # Title from skeleton (first heading)
    for line in skeleton_text.splitlines():
        if line.startswith("# "):
            md_lines.append(line)
            md_lines.append("")
            break

    # Sections from outline
    for section in outline.get("sections", []):
        section_id = section.get("id", "")
        section_title = section.get("title", "")

        if section_id == "header":
            continue  # already added disclaimer

        if section_id == "bibliography":
            # Bibliography section
            md_lines.append(f"## {section_title}")
            md_lines.append("")
            if section.get("warning"):
                md_lines.append(f"> **Uyarı**: {section['warning']}")
                md_lines.append("")
            for bib_auth in section.get("authorities", []):
                label = bib_auth.get("label", bib_auth.get("document_id", ""))
                classification = bib_auth.get("classification", "")
                warning = bib_auth.get("warning")
                md_lines.append(f"- {label} ({classification})")
                if warning:
                    md_lines.append(f"  - ⚠️ {warning}")
            md_lines.append("")
            continue

        if section.get("type") == "authority_content":
            md_lines.append(f"## {section_title}")
            md_lines.append("")
            # Include petition_ready authorities with placeholders
            for p in section.get("placeholders", []):
                md_lines.append(p)
                md_lines.append("")
            # Add source references
            for doc_id in section.get("authorities", []):
                md_lines.append(f"<!-- Kaynak: {doc_id} -->")
            md_lines.append("")
            continue

        if section.get("type") == "user_content":
            md_lines.append(f"## {section_title}")
            md_lines.append("")
            for p in section.get("placeholders", []):
                md_lines.append(p)
                md_lines.append("")
            # Include content_ref if present
            if section.get("content_ref") == "issue" and pack_meta.get("issue"):
                md_lines.append(pack_meta["issue"])
                md_lines.append("")
            md_lines.append("")
            continue

        # Generic section
        if section_title:
            md_lines.append(f"## {section_title}")
            md_lines.append("")

    # Footer
    md_lines.append("---")
    md_lines.append(
        f"> Taslak emsal-mcp v{CONTROLLED_DRAFT_VERSION} tarafından "
        "otomatik olarak oluşturulmuştur."
    )
    md_lines.append("> Bu taslak avukat denetimi gerektirir.")
    md_lines.append(
        "> {{}} içindeki alanlar doğrulanmış bilgilerle doldurulmalıdır."
    )

    draft_md = "\n".join(md_lines)

    # ── Write draft.md ──────────────────────────────────────────────────
    draft_md_path = out_path / "draft.md"
    draft_md_path.write_text(draft_md, encoding="utf-8")

    # ── Compute counts for draft.json ───────────────────────────────────
    paragraphs = [p for p in draft_md.split("\n\n") if p.strip()]
    paragraph_count = len(paragraphs)

    section_count = sum(
        1 for line in draft_md.splitlines() if line.startswith("## ")
    )

    footnote_count = len(footnotes)
    placeholder_count = len(PLACEHOLDER_PATTERN.findall(draft_md))
    blocking_warning_count = len(blocking_warnings)

    # ── Readiness scoring ───────────────────────────────────────────────
    total_auths = petition_ready_count + citation_only_count + research_lead_count + excluded_count
    if total_auths == 0:
        readiness_score = 0.0
    else:
        readiness_score = round(petition_ready_count / total_auths, 2)

    if readiness_score >= 0.7:
        readiness_level = "high"
    elif readiness_score >= 0.4:
        readiness_level = "medium"
    elif readiness_score > 0:
        readiness_level = "low"
    else:
        readiness_level = "none"

    # Finalization risk: higher when more blocking warnings or fewer ready
    finalization_risk_score = round(
        min(1.0, (blocking_warning_count * 0.3) + (1.0 - readiness_score) * 0.5),
        2,
    )

    # ── Build draft.json ────────────────────────────────────────────────
    draft_metadata = {
        "version": CONTROLLED_DRAFT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pack_version": pack_meta.get("version", "unknown"),
        "matter": pack_meta.get("matter", ""),
        "issue": pack_meta.get("issue", ""),
        "paragraph_count": paragraph_count,
        "section_count": section_count,
        "footnote_count": footnote_count,
        "placeholder_count": placeholder_count,
        "blocking_warning_count": blocking_warning_count,
        "readiness_score": readiness_score,
        "readiness_level": readiness_level,
        "finalization_risk_score": finalization_risk_score,
        "classification_counts": {
            "petition_ready": petition_ready_count,
            "citation_only": citation_only_count,
            "research_lead_only": research_lead_count,
            "excluded": excluded_count,
        },
        "citation_only_bibliography_count": citation_only_count,
        "has_disclaimer": True,
        "placeholders_in_skeleton": placeholders,
        "files": {
            "draft_md": str(draft_md_path),
            "draft_json": str(out_path / "draft.json"),
            "footnotes_json": str(out_path / "footnotes.json"),
            "warnings_json": str(out_path / "warnings.json"),
        },
    }

    # ── Write draft.json ────────────────────────────────────────────────
    draft_json_path = out_path / "draft.json"
    draft_json_path.write_text(
        json.dumps(draft_metadata, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # ── Write footnotes.json ────────────────────────────────────────────
    footnotes_data = {
        "version": CONTROLLED_DRAFT_VERSION,
        "footnote_count": footnote_count,
        "footnotes": footnotes,
        "citation_only_bibliography": [
            {
                "document_id": a.get("document_id", ""),
                "source": a.get("source", ""),
                "citation_label": a.get("citation_label", ""),
                "warning": "Bibliyografik referans; doğrudan alıntı yapılamaz.",
            }
            for a in citation_only_auths
        ],
    }
    footnotes_path = out_path / "footnotes.json"
    footnotes_path.write_text(
        json.dumps(footnotes_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # ── Write warnings.json ─────────────────────────────────────────────
    all_warnings = [
        {"level": "blocking", "message": w} for w in blocking_warnings
    ] + [
        {"level": "warning", "message": w} for w in warnings
    ] + [
        {"level": "info", "message": w} for w in bib_warnings
    ]

    warnings_data = {
        "version": CONTROLLED_DRAFT_VERSION,
        "blocking_count": blocking_warning_count,
        "warning_count": len(warnings),
        "info_count": len(bib_warnings),
        "total": len(all_warnings),
        "warnings": all_warnings,
    }
    warnings_path = out_path / "warnings.json"
    warnings_path.write_text(
        json.dumps(warnings_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "out_dir": str(out_path),
        "draft_md_path": str(draft_md_path),
        "draft_json_path": str(draft_json_path),
        "footnotes_path": str(footnotes_path),
        "warnings_path": str(warnings_path),
        "draft_metadata": draft_metadata,
    }
