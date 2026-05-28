from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from docx import Document as DocxDocument
from docx.shared import RGBColor

from .models import Draft, InputPack


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
            results = {"valid": True, "hashes": {}}
            for fname in ["draft.json", "pack.json"]:
                content = zf.read(fname)
                computed = hashlib.sha256(content).hexdigest()
                expected = manifest.get(f"{fname.split('.')[0]}_hash")
                match = computed == expected
                results["hashes"][fname] = {"computed": computed, "expected": expected, "match": match}
                if not match:
                    results["valid"] = False

            # Verify DOCX if present
            if "draft.docx" in zf.namelist():
                content = zf.read("draft.docx")
                computed = hashlib.sha256(content).hexdigest()
                expected = manifest.get("docx_hash")
                match = computed == expected if expected else False
                results["hashes"]["draft.docx"] = {"computed": computed, "expected": expected, "match": match}
                if not match:
                    results["valid"] = False

            return results
    except Exception as e:
        return {"valid": False, "error": str(e)}
