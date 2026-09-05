from __future__ import annotations

import hashlib
import json
import re
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor

from .models import Draft, InputPack, build_error

# Karar/belge disa aktarimi icin kisa uyari. Placeholder cumlesi dilekce
# taslaklarina ozgudur ve petition.DISCLAIMER_HEADER'da durur; kararda
# placeholder olmaz (kullanici istegi, 5 Eyl 2026).
DISCLAIMER_TEXT = (
    "DİKKAT: Bu belge emsal-mcp tarafından otomatik olarak oluşturulmuştur."
)

PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}")


def export_draft_to_docx(draft: Draft, output_path: str | Path, pack: InputPack | None = None) -> Path:
    """Export a draft to DOCX format."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = DocxDocument()

    # Title
    title = doc.add_heading(draft.kind, level=1)
    title.runs[0].font.color.rgb = RGBColor(0, 0, 0)

    # Body
    for paragraph in draft.body_markdown.split("\n"):
        if paragraph.strip():
            doc.add_paragraph(paragraph)

    # Citations section
    if draft.citations:
        doc.add_heading("Kaynakça", level=2)
        for citation in draft.citations:
            doc.add_paragraph(citation, style="List Number")

    # Warnings
    if draft.warnings:
        doc.add_heading("Uyarılar", level=2)
        for warning in draft.warnings:
            doc.add_paragraph(warning, style="List Bullet")

    if pack is not None:
        doc.add_heading("Input Pack Doğrulama", level=2)
        doc.add_paragraph(f"Pack ID: {pack.id}")
        doc.add_paragraph(f"Pack Hash: {pack.compute_hash()}")
        doc.add_paragraph(f"Citation-safe belge sayısı: {len(pack.documents)}")
        for warning in pack.warnings:
            doc.add_paragraph(warning, style="List Bullet")

    doc.save(str(path))
    return path


def create_bundle(
    draft: Draft,
    pack: InputPack,
    output_dir: str | Path,
    docx_content: bytes | None = None,
) -> Path:
    """Create a ZIP bundle with manifest hashes and verification.txt."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle_path = out_dir / f"draft_{draft.id[:8]}.zip"
    manifest: dict[str, Any] = {
        "draft_id": draft.id,
        "pack_id": pack.id,
        "pack_hash": pack.compute_hash(),
        "created_at": draft.created_at,
        "citations": draft.citations,
        "warnings": draft.warnings,
    }

    with ZipFile(bundle_path, "w") as zf:
        # Add draft JSON
        draft_json = draft.model_dump_json()
        zf.writestr("draft.json", draft_json)
        manifest["draft_hash"] = hashlib.sha256(draft_json.encode()).hexdigest()

        # Add pack JSON
        pack_json = pack.model_dump_json()
        zf.writestr("pack.json", pack_json)
        manifest["pack_hash"] = hashlib.sha256(pack_json.encode()).hexdigest()

        # Add DOCX if provided
        if docx_content:
            zf.writestr("draft.docx", docx_content)
            manifest["docx_hash"] = hashlib.sha256(docx_content).hexdigest()

        # Add manifest
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
        zf.writestr("manifest.json", manifest_json)

        # Create verification.txt
        verification_lines = [
            "=" * 60,
            "DOĞRULAMA DOSYASI",
            "=" * 60,
            "",
            f"Draft ID: {draft.id}",
            f"Pack ID: {pack.id}",
            f"Pack Hash: {pack.compute_hash()}",
            "",
            "İÇERİK ÖZETLERİ:",
            f"  draft.json: {manifest['draft_hash']}",
            f"  pack.json: {manifest['pack_hash']}",
        ]
        if docx_content:
            verification_lines.append(f"  draft.docx: {manifest.get('docx_hash', 'N/A')}")
        verification_lines.extend([
            "",
            "DOĞRULAMA YÖNTEMİ:",
            "  sha256sum ile dosya hash'lerini kontrol edin.",
            "",
            "=" * 60,
        ])
        zf.writestr("verification.txt", "\n".join(verification_lines))

    return bundle_path


def verify_bundle(bundle_path: str | Path) -> dict[str, Any]:
    """Verify integrity of a ZIP bundle."""
    path = Path(bundle_path)
    if not path.exists():
        return {"valid": False, "error": "Bundle not found"}

    try:
        with ZipFile(path, "r") as zf:
            # Check required files
            required = ["draft.json", "pack.json", "manifest.json"]
            missing = [f for f in required if f not in zf.namelist()]
            if missing:
                return {"valid": False, "error": f"Missing files: {missing}"}

            # Load manifest
            manifest = json.loads(zf.read("manifest.json"))

            # Verify hashes
            hashes: dict[str, dict[str, Any]] = {}
            results: dict[str, Any] = {"valid": True, "hashes": hashes}
            for fname in ["draft.json", "pack.json"]:
                content = zf.read(fname)
                computed = hashlib.sha256(content).hexdigest()
                expected = manifest.get(f"{fname.split('.')[0]}_hash")
                match = computed == expected
                hashes[fname] = {"computed": computed, "expected": expected, "match": match}
                if not match:
                    results["valid"] = False

            # Verify DOCX if present
            if "draft.docx" in zf.namelist():
                content = zf.read("draft.docx")
                computed = hashlib.sha256(content).hexdigest()
                expected = manifest.get("docx_hash")
                match = computed == expected if expected else False
                hashes["draft.docx"] = {"computed": computed, "expected": expected, "match": match}
                if not match:
                    results["valid"] = False

            return results
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ===========================================================================
# v0.8: DOCX Export Validation + Export Package Bundle v2
# ===========================================================================


def prepare_docx_export(
    draft_path: str | Path | None = None,
    draft_json: dict[str, Any] | None = None,
    out_path: str | Path | None = None,
    pack_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Create a validated DOCX export from a controlled draft.

    Accepts either a ``draft.md`` path or a ``draft.json`` dict.  When
    *pack_dir* is provided, footnotes are appended from the pack's
    ``petition-brief.json``.

    The DOCX includes:
    - A disclaimer header paragraph
    - Draft body content
    - Footnotes / citation references
    - Placeholder preservation (``{{…}}``)

    Returns a dict with:
    - ``checksum_sha256``: SHA-256 of the DOCX file
    - ``file_size``: file size in bytes
    - ``validation``: dict with zip_valid, disclaimer_present,
      footnotes_consistent, placeholders_preserved,
      validation_warnings, export_readiness
    """
    validation_warnings: list[str] = []

    # ── Determine markdown content ──────────────────────────────────────
    markdown_content = ""
    draft_md_path: Path | None = None

    if draft_path is not None:
        draft_md_path = Path(draft_path)
        if draft_md_path.exists():
            markdown_content = draft_md_path.read_text(encoding="utf-8")
        else:
            return build_error("FILE_NOT_FOUND", f"Draft file not found: {draft_path}", error=f"Draft file not found: {draft_path}")
    elif draft_json is not None:
        # draft.json may reference a draft_md file
        ref_md = draft_json.get("files", {}).get("draft_md")
        if ref_md and Path(ref_md).exists():
            draft_md_path = Path(ref_md)
            markdown_content = draft_md_path.read_text(encoding="utf-8")
        else:
            # Build minimal markdown from draft_json metadata
            markdown_content = f"# {draft_json.get('matter', 'Dilekçe')}\n\n"
            markdown_content += f"{draft_json.get('issue', '')}\n\n"
            markdown_content += DISCLAIMER_TEXT + "\n"
    else:
        return build_error("INVALID_INPUT", "Either draft_path or draft_json must be provided", error="Either draft_path or draft_json must be provided")

    # ── Determine out_path ──────────────────────────────────────────────
    if out_path is None:
        if draft_md_path:
            out_path = draft_md_path.with_suffix(".docx")
        else:
            out_path = Path("draft_output/draft.docx")
    else:
        out_path = Path(out_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Build DOCX ──────────────────────────────────────────────────────
    doc = DocxDocument()

    # Disclaimer header
    disclaimer_para = doc.add_paragraph(DISCLAIMER_TEXT)
    for run in disclaimer_para.runs:
        run.font.size = Pt(8)

    doc.add_paragraph("")  # spacer

    # Body content
    placeholders_found: list[str] = []
    for line in markdown_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith("- "):
            doc.add_paragraph(stripped[2:], style="List Bullet")
        elif stripped.startswith("> "):
            doc.add_paragraph(stripped[2:])
        elif stripped.startswith("<!--"):
            continue  # skip HTML comments
        elif stripped:
            doc.add_paragraph(stripped)
        else:
            doc.add_paragraph("")

        # Track placeholders
        phs = PLACEHOLDER_RE.findall(stripped)
        placeholders_found.extend(phs)

    # ── Add footnotes section from pack ─────────────────────────────────
    footnote_refs: list[dict[str, Any]] = []
    if pack_dir:
        pack_path = Path(pack_dir)
        brief_path = pack_path / "petition-brief.json"
        if brief_path.exists():
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            for auth in brief.get("authorities", []):
                if auth.get("classification") == "petition_ready":
                    footnote_refs.append({
                        "document_id": auth.get("document_id", ""),
                        "source": auth.get("source", ""),
                        "citation_label": auth.get("citation_label", ""),
                        "classification": auth.get("classification", ""),
                    })

    if footnote_refs:
        doc.add_heading("Kaynakça ve Dipnotlar", level=2)
        for ref in footnote_refs:
            label = ref.get("citation_label", ref.get("document_id", ""))
            doc.add_paragraph(f"{label} ({ref.get('source', '')})", style="List Number")

    # ── Save DOCX ───────────────────────────────────────────────────────
    doc.save(str(out_path))

    # ── Compute checksum and size ───────────────────────────────────────
    docx_bytes = out_path.read_bytes()
    checksum = hashlib.sha256(docx_bytes).hexdigest()
    file_size = len(docx_bytes)

    # ── Validation ──────────────────────────────────────────────────────
    zip_valid = False
    disclaimer_present = False
    placeholders_preserved = False

    try:
        with ZipFile(out_path, "r") as zf:
            zip_valid = True
            # DOCX is a ZIP; check it opens correctly
            namelist = zf.namelist()
            if "word/document.xml" not in namelist:
                validation_warnings.append("word/document.xml missing from DOCX ZIP")
    except Exception as e:
        validation_warnings.append(f"DOCX ZIP validation failed: {e}")

    # Check disclaimer is present in the DOCX body text
    try:
        verify_doc = DocxDocument(str(out_path))
        full_text = "\n".join(p.text for p in verify_doc.paragraphs)
        disclaimer_short = "emsal-mcp tarafından otomatik"
        disclaimer_present = disclaimer_short.lower() in full_text.lower()
    except Exception:
        # Fallback: try reading word/document.xml from the ZIP
        try:
            with ZipFile(out_path, "r") as zf:
                if "word/document.xml" in zf.namelist():
                    xml_content = zf.read("word/document.xml").decode("utf-8", errors="ignore")
                    disclaimer_short = "emsal-mcp"
                    disclaimer_present = disclaimer_short.lower() in xml_content.lower()
        except Exception:
            validation_warnings.append("Could not verify disclaimer presence in DOCX")

    # Check placeholders preserved
    if draft_md_path and draft_md_path.exists():
        original_text = draft_md_path.read_text(encoding="utf-8")
        original_placeholders = set(PLACEHOLDER_RE.findall(original_text))
        if original_placeholders:
            # Read DOCX body text for comparison
            try:
                verify_doc = DocxDocument(str(out_path))
                docx_text = "\n".join(p.text for p in verify_doc.paragraphs)
            except Exception:
                try:
                    with ZipFile(out_path, "r") as zf:
                        if "word/document.xml" in zf.namelist():
                            docx_text = zf.read("word/document.xml").decode("utf-8", errors="ignore")
                        else:
                            docx_text = ""
                except Exception:
                    docx_text = ""
            placeholders_preserved = all(
                ph in docx_text for ph in original_placeholders
            )
            if not placeholders_preserved:
                missing = original_placeholders - set(PLACEHOLDER_RE.findall(docx_text))
                validation_warnings.append(
                    f"Placeholders not fully preserved in DOCX: {missing}"
                )
        else:
            placeholders_preserved = True
    else:
        placeholders_preserved = len(placeholders_found) > 0 or True

    # Footnotes consistency
    footnotes_consistent = True
    if pack_dir:
        pack_path = Path(pack_dir)
        brief_path = pack_path / "petition-brief.json"
        if brief_path.exists():
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            pr_count = sum(
                1 for a in brief.get("authorities", [])
                if a.get("classification") == "petition_ready"
            )
            if pr_count != len(footnote_refs):
                footnotes_consistent = False
                validation_warnings.append(
                    f"Footnote count ({len(footnote_refs)}) does not match "
                    f"petition_ready count ({pr_count})"
                )

    export_readiness = (
        zip_valid
        and disclaimer_present
        and footnotes_consistent
        and placeholders_preserved
    )

    validation = {
        "zip_valid": zip_valid,
        "disclaimer_present": disclaimer_present,
        "footnotes_consistent": footnotes_consistent,
        "placeholders_preserved": placeholders_preserved,
        "validation_warnings": validation_warnings,
        "export_readiness": export_readiness,
    }

    return {
        "ok": True,
        "out_path": str(out_path),
        "checksum_sha256": checksum,
        "file_size": file_size,
        "validation": validation,
    }


def prepare_export_package_bundle(
    pack_dir: str | Path,
    draft_dir: str | Path | None = None,
    docx_path: str | Path | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Create a complete export package bundle (v2) with verification.

    Bundles together:
    - draft.md, draft.json, footnotes.json, warnings.json (from draft_dir)
    - petition-pack.json, citation-bank.md, source-documents/ (from pack_dir)
    - manifest.json, hash-manifest.json, verification.txt, warnings.json

    After creation the bundle is verified; any integrity failures are
    reported in the return dict.

    Returns:
        Dict with ok, bundle_dir, manifest, hash_manifest, verification,
        files, post_verification.
    """
    pack_path = Path(pack_dir)
    bundle_path = Path(out_dir) if out_dir else pack_path / "export_bundle"
    try:
        bundle_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return build_error("OUTPUT_DIR_ERROR", f"Cannot create output dir '{bundle_path}': {exc}")

    warnings: list[str] = []
    files_written: list[str] = []

    # ── Validate pack_dir ───────────────────────────────────────────────
    if not (pack_path / "petition-pack.json").exists():
        return build_error("PACK_NOT_FOUND", "petition-pack.json not found in pack_dir")

    # ── Copy/include petition pack files ────────────────────────────────
    pack_files = [
        "petition-pack.json",
        "petition-brief.json",
        "citation-bank.md",
        "argument-map.md",
        "petition-instructions.md",
        "draft-skeleton.md",
    ]
    for fname in pack_files:
        src = pack_path / fname
        if src.exists():
            (bundle_path / fname).write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8"
            )
            files_written.append(fname)
        else:
            warnings.append(f"Pack file missing: {fname}")

    # Source documents
    src_dir = pack_path / "source-documents"
    if src_dir.exists():
        (bundle_path / "source-documents").mkdir(exist_ok=True)
        for f in sorted(src_dir.glob("*.md")):
            (bundle_path / "source-documents" / f.name).write_text(
                f.read_text(encoding="utf-8"), encoding="utf-8"
            )
            files_written.append(f"source-documents/{f.name}")

    # Hash manifest from pack
    pack_hash_manifest = pack_path / "hash-manifest.json"
    if pack_hash_manifest.exists():
        (bundle_path / "pack-hash-manifest.json").write_text(
            pack_hash_manifest.read_text(encoding="utf-8"), encoding="utf-8"
        )
        files_written.append("pack-hash-manifest.json")

    # ── Copy/include draft files ────────────────────────────────────────
    draft_src = Path(draft_dir) if draft_dir else pack_path / "draft_output"
    if draft_src.exists():
        for fname in ["draft.md", "draft.json", "footnotes.json", "warnings.json"]:
            src = draft_src / fname
            if src.exists():
                (bundle_path / fname).write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8"
                )
                files_written.append(fname)

    # ── Include DOCX if provided ────────────────────────────────────────
    if docx_path and Path(docx_path).exists():
        src = Path(docx_path)
        (bundle_path / "draft.docx").write_bytes(src.read_bytes())
        files_written.append("draft.docx")

    # ── Build manifest.json ─────────────────────────────────────────────
    manifest_entries: dict[str, Any] = {}
    for fname in files_written:
        fpath = bundle_path / fname
        if fpath.exists():
            content = fpath.read_bytes()
            manifest_entries[fname] = {
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }

    manifest = {
        "version": "0.8.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pack_dir": str(pack_path),
        "draft_dir": str(draft_src) if draft_src.exists() else None,
        "file_count": len(files_written),
        "files": manifest_entries,
    }

    manifest_path = bundle_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    files_written.append("manifest.json")

    # ── Build hash-manifest.json (flat SHA-256 map) ─────────────────────
    hash_manifest: dict[str, str] = {}
    for fname in files_written:
        fpath = bundle_path / fname
        if fpath.exists() and fname != "hash-manifest.json":
            hash_manifest[fname] = hashlib.sha256(fpath.read_bytes()).hexdigest()

    hash_manifest_path = bundle_path / "hash-manifest.json"
    hash_manifest_path.write_text(
        json.dumps(hash_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files_written.append("hash-manifest.json")

    # ── Build verification.txt ──────────────────────────────────────────
    verification_lines = [
        "=" * 60,
        "DOĞRULAMA DOSYASI — EMSAL-MCP v0.8.0",
        "=" * 60,
        "",
        f"Oluşturulma Tarihi: {manifest['created_at']}",
        f"Paket Dizini: {manifest['pack_dir']}",
        f"Dosya Sayısı: {manifest['file_count']}",
        "",
        "İÇERİK ÖZETLERİ (SHA-256):",
    ]
    for fname, info in manifest_entries.items():
        verification_lines.append(f"  {fname}: {info['sha256']}")

    verification_lines.extend([
        "",
        "DOĞRULAMA YÖNTEMİ:",
        "  sha256sum ile dosya hash'lerini kontrol edin.",
        "",
        "UYARILAR:",
    ])
    for w in warnings:
        verification_lines.append(f"  - {w}")
    if not warnings:
        verification_lines.append("  (Uyarı yok)")

    verification_lines.extend(["", "=" * 60])

    verification_path = bundle_path / "verification.txt"
    verification_path.write_text("\n".join(verification_lines), encoding="utf-8")
    files_written.append("verification.txt")

    # ── Post-creation verification ──────────────────────────────────────
    post_verification = _verify_export_bundle(bundle_path, hash_manifest, manifest)

    return {
        "ok": True,
        "bundle_dir": str(bundle_path),
        "manifest": manifest,
        "hash_manifest": hash_manifest,
        "verification": verification_lines,
        "files": files_written,
        "warnings": warnings,
        "post_verification": post_verification,
    }


def _verify_export_bundle(
    bundle_path: Path,
    expected_hashes: dict[str, str],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Verify the integrity of an export package bundle after creation."""
    errors: list[str] = []
    checks: dict[str, Any] = {}

    # Check all files in hash-manifest exist and hashes match
    hash_ok = True
    hash_mismatches: list[str] = []
    for fname, expected_hash in expected_hashes.items():
        fpath = bundle_path / fname
        if not fpath.exists():
            hash_mismatches.append(f"{fname}: file missing")
            hash_ok = False
        else:
            actual = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if actual != expected_hash:
                hash_mismatches.append(f"{fname}: hash mismatch")
                hash_ok = False

    checks["hash_manifest_valid"] = {
        "ok": hash_ok,
        "mismatches": hash_mismatches,
        "file_count": len(expected_hashes),
    }

    # Check required files
    required = [
        "petition-pack.json",
        "manifest.json",
        "hash-manifest.json",
        "verification.txt",
    ]
    missing = [f for f in required if not (bundle_path / f).exists()]
    checks["required_files_present"] = {
        "ok": len(missing) == 0,
        "missing": missing,
    }

    # Check manifest.json is valid
    manifest_path = bundle_path / "manifest.json"
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            checks["manifest_valid_json"] = {
                "ok": True,
                "file_count": loaded.get("file_count", 0),
            }
        except json.JSONDecodeError as e:
            checks["manifest_valid_json"] = build_error("CHECK_FAILED", str(e))
            errors.append("manifest.json is not valid JSON")

    # Check DOCX ZIP if present
    docx_path = bundle_path / "draft.docx"
    if docx_path.exists():
        try:
            with ZipFile(docx_path, "r"):  # opening it is the validity check
                checks["docx_zip_valid"] = {"ok": True}
        except Exception as e:
            checks["docx_zip_valid"] = build_error("CHECK_FAILED", str(e))
            errors.append(f"DOCX ZIP invalid: {e}")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "checks": checks,
    }


# ===========================================================================
# v1.0: Export Format Expansion — plain text + unified dispatcher
# ===========================================================================


def _strip_markdown(text: str) -> str:
    """Convert markdown text to plain text.

    - Headers become uppercase
    - Bold/italic markers stripped
    - Links rendered as text only
    - HTML comments removed
    """
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.rstrip()
        # Remove HTML comments
        stripped = re.sub(r"<!--.*?-->", "", stripped).strip()
        if not stripped:
            lines.append("")
            continue
        # Headers → uppercase
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            lines.append(m.group(2).upper())
            continue
        # Bold/italic markers
        stripped = re.sub(r"\*\*\*([^*]+)\*\*\*", r"\1", stripped)
        stripped = re.sub(r"\*\*([^*]+)\*\*", r"\1", stripped)
        stripped = re.sub(r"\*([^*]+)\*", r"\1", stripped)
        stripped = re.sub(r"___([^_]+)___", r"\1", stripped)
        stripped = re.sub(r"__([^_]+)__", r"\1", stripped)
        stripped = re.sub(r"_([^_]+)_", r"\1", stripped)
        # Links: [text](url) → text
        stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        # Inline code
        stripped = re.sub(r"`([^`]+)`", r"\1", stripped)
        # List markers → plain
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        stripped = re.sub(r"^\d+\.\s+", "", stripped)
        # Blockquotes
        stripped = re.sub(r"^>\s?", "", stripped)
        lines.append(stripped)
    return "\n".join(lines)


def export_plain_text(
    draft_path: str | Path,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """Export a draft.md to plain text format.

    Converts markdown to plain text by stripping formatting while preserving
    the disclaimer header and ``{{PLACEHOLDER}}`` tokens.

    Returns:
        Dict with ok, out_path, text_length, disclaimer_present,
        placeholders_preserved.
    """
    src = Path(draft_path)
    if not src.exists():
        return build_error("FILE_NOT_FOUND", f"Draft file not found: {draft_path}")

    markdown_content = src.read_text(encoding="utf-8")

    # Strip markdown formatting
    plain = _strip_markdown(markdown_content)

    # Ensure disclaimer header is present
    disclaimer_short = "emsal-mcp tarafından otomatik"
    disclaimer_present = disclaimer_short.lower() in plain.lower()
    if not disclaimer_present:
        # Prepend disclaimer block
        disclaimer_block = (
            DISCLAIMER_TEXT
            + "\n"
            + "=" * 60
            + "\n\n"
        )
        plain = disclaimer_block + plain
        disclaimer_present = True

    # Track placeholders from original
    original_placeholders = set(PLACEHOLDER_RE.findall(markdown_content))
    plain_placeholders = set(PLACEHOLDER_RE.findall(plain))
    if original_placeholders:
        placeholders_preserved = original_placeholders <= plain_placeholders
    else:
        placeholders_preserved = True

    # Determine out_path
    if out_path is None:
        out_path = src.with_suffix(".txt")
    else:
        out_path = Path(out_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(plain, encoding="utf-8")

    return {
        "ok": True,
        "out_path": str(out_path),
        "text_length": len(plain),
        "disclaimer_present": disclaimer_present,
        "placeholders_preserved": placeholders_preserved,
    }


def _check_toolkit_available() -> dict[str, Any]:
    """Check if LibreOffice/UDF toolkit is available (returns status dict)."""
    libreoffice_path = (
        shutil.which("soffice")
        or shutil.which("libreoffice")
        or shutil.which("soffice.exe")
    )
    toolkit_dir = None
    for env_var in ("EMSAL_UDF_TOOLKIT_DIR", "UDF_TOOLKIT_DIR"):
        val = __import__("os").environ.get(env_var, "").strip()
        if val:
            p = Path(val)
            if p.exists():
                toolkit_dir = p
                break
    return {
        "available": libreoffice_path is not None or toolkit_dir is not None,
        "libreoffice_path": libreoffice_path,
        "toolkit_dir": str(toolkit_dir) if toolkit_dir else None,
    }


def export_to_format(
    draft_path: str | Path,
    format: str = "docx",
    out_path: str | Path | None = None,
    pack_dir: str | Path | None = None,
    experimental: bool = False,  # deprecated, ignored (kept for API compatibility)
) -> dict[str, Any]:
    """Unified export dispatcher supporting multiple formats.

    Formats:
        - ``docx``: validated DOCX export (always available via python-docx)
        - ``txt``: plain-text export (always available, stdlib only)
        - ``pdf``: PDF export via LibreOffice (requires toolkit)
        - ``udf``: UYAP UDF format (always available, preserves formatting)

    When the toolkit is absent for formats that require it, returns a
    structured error dict (``TOOLKIT_UNAVAILABLE``) — never raises.

    Returns:
        Format-specific result dict or structured error.
    """
    format = format.lower().strip()

    if format == "docx":
        return prepare_docx_export(
            draft_path=str(draft_path),
            out_path=str(out_path) if out_path else None,
            pack_dir=str(pack_dir) if pack_dir else None,
        )

    if format == "txt":
        return export_plain_text(
            draft_path=str(draft_path),
            out_path=str(out_path) if out_path else None,
        )

    if format == "pdf":
        toolkit = _check_toolkit_available()
        if not toolkit["available"]:
            return build_error(
                "TOOLKIT_UNAVAILABLE",
                "PDF export requires LibreOffice toolkit. "
                "Install LibreOffice or set EMSAL_UDF_TOOLKIT_DIR.",
                recommended_next_steps=[
                    "Install LibreOffice and ensure soffice is on PATH.",
                    "Set EMSAL_UDF_TOOLKIT_DIR environment variable.",
                ],
                toolkit_status=toolkit,
            )
        # Delegate to UDF convert pipeline: draft.md → docx → pdf
        # 5 Eyl 2026: out_path (.pdf) DOCX adimina da veriliyordu; DOCX
        # "x.pdf" adiyla yaziliyor, LibreOffice girdi=cikti adinda bekliyor ve
        # 60 s zaman asimina dusuyordu. Ara DOCX her zaman .docx uzantili.
        pdf_target = Path(out_path) if out_path else Path(str(draft_path)).with_suffix(".pdf")
        docx_result = prepare_docx_export(
            draft_path=str(draft_path),
            out_path=str(pdf_target.with_suffix(".docx")),
            pack_dir=str(pack_dir) if pack_dir else None,
        )
        if not docx_result.get("ok"):
            return docx_result
        docx_path = docx_result["out_path"]
        # LibreOffice can convert DOCX → PDF directly
        try:
            soffice = toolkit["libreoffice_path"]
            if soffice:
                import subprocess

                # Windows'ta which() PATHEXT sirasina gore soffice.COM secebilir;
                # .exe yanindaysa onu kullan. Izole kullanici profili: ilk-calisma
                # sihirbazi / baska bir LibreOffice orneginin kilidi donusumu
                # asmasin. Zaman asiminda sureci oldur (aksi halde soffice.bin
                # arkada kalir ve sonraki cagrilar da bekler).
                exe = Path(soffice)
                if exe.suffix.lower() == ".com" and exe.with_suffix(".exe").exists():
                    soffice = str(exe.with_suffix(".exe"))
                # Her donusume SIFIRDAN gecici profil: oldurulen bir onceki
                # soffice'in kilidi/crash kaydi kalirsa yeni ornek headless'ta
                # kurtarma penceresi acamayip 1 ile cikiyor (5 Eyl 2026 tanisi).
                import tempfile
                profile_dir = Path(tempfile.mkdtemp(prefix="emsal-lo-"))
                cmd = [
                    soffice, f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                    "--headless", "--norestore", "--nologo",
                    "--convert-to", "pdf", "--outdir", str(pdf_target.parent), docx_path,
                ]
                # Bu ortamda (Windows, headless) soffice PDF'i yazdiktan sonra
                # CIKMIYOR: 120 s'de zaman asimi, dosya ise 10 s'de hazir
                # (5 Eyl 2026 tanisi). Cikis kodunu beklemek yerine PDF'in olusup
                # boyutunun sabitlenmesini bekle, sonra baslattigimiz sureci kapat.
                pdf_path = pdf_target.parent / (Path(docx_path).stem + ".pdf")
                if pdf_path.exists():
                    pdf_path.unlink()
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                import time as _time
                deadline = _time.monotonic() + 120
                last_size, stable = -1, 0
                while _time.monotonic() < deadline:
                    if pdf_path.exists():
                        size = pdf_path.stat().st_size
                        if size > 0 and size == last_size:
                            stable += 1
                            if stable >= 2:
                                break
                        else:
                            stable = 0
                        last_size = size
                    if proc.poll() is not None:
                        break
                    _time.sleep(0.5)
                stderr_txt = ""
                if proc.poll() is None:
                    try:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                                capture_output=True, timeout=15,
                            )
                        proc.kill()
                    except Exception:
                        pass
                else:
                    try:
                        stderr_txt = (proc.stderr.read() if proc.stderr else "") or ""
                    except Exception:
                        stderr_txt = ""
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                except Exception:
                    pass
                if not pdf_path.exists() or pdf_path.stat().st_size == 0:
                    return build_error(
                        "CONVERSION_FAILED",
                        stderr_txt.strip() or "LibreOffice PDF uretmedi (120 s)",
                        returncode=proc.returncode,
                        expected_pdf=str(pdf_path),
                        soffice=soffice,
                    )
                if pdf_path != pdf_target:
                    pdf_path.replace(pdf_target)
                    pdf_path = pdf_target
                return {
                    "ok": True,
                    "format": "pdf",
                    "out_path": str(pdf_path),
                    "file_size": pdf_path.stat().st_size if pdf_path.exists() else 0,
                    "source_format": "docx",
                    "docx_path": docx_path,
                }
        except Exception as e:
            return build_error("CONVERSION_FAILED", str(e))

        return build_error(
            "TOOLKIT_UNAVAILABLE",
            "PDF export requires LibreOffice (soffice) on PATH.",
        )

    if format == "udf":
        # Export via DOCX → UDF pipeline (native converter, no toolkit needed)
        docx_result = prepare_docx_export(
            draft_path=str(draft_path),
            out_path=None,
            pack_dir=str(pack_dir) if pack_dir else None,
        )
        if not docx_result.get("ok"):
            return docx_result
        docx_path = docx_result["out_path"]
        try:
            from .udf import convert_docx_to_udf

            udf_out = str(out_path) if out_path else str(Path(docx_path).with_suffix(".udf"))
            return convert_docx_to_udf(docx_path, out_path=udf_out)
        except Exception as e:
            return build_error("CONVERSION_FAILED", str(e))

    return build_error(
        "INVALID_FORMAT",
        f"Unknown export format: {format!r}. "
        "Supported formats: docx, txt, pdf, udf.",
        supported_formats=["docx", "txt", "pdf", "udf"],
    )


def get_export_capabilities() -> dict[str, Any]:
    """Report which export formats are currently available.

    Returns:
        Dict with formats list, each indicating availability and requirements.
    """
    toolkit = _check_toolkit_available()
    toolkit_available = toolkit["available"]

    formats = [
        {
            "format": "docx",
            "available": True,
            "requires_toolkit": False,
            "description": "Validated DOCX export with disclaimer and footnotes.",
        },
        {
            "format": "txt",
            "available": True,
            "requires_toolkit": False,
            "description": "Plain-text export. Strips markdown formatting, preserves disclaimer and placeholders.",
        },
        {
            "format": "pdf",
            "available": toolkit_available,
            "requires_toolkit": True,
            "description": "PDF export via LibreOffice headless conversion.",
        },
        {
            "format": "udf",
            "available": True,
            "requires_toolkit": False,
            "description": "UYAP UDF format. Preserves bold/alignment/indent formatting from DOCX sources.",
        },
    ]

    return {
        "ok": True,
        "formats": formats,
        "toolkit_available": toolkit_available,
        "toolkit_status": toolkit,
    }
