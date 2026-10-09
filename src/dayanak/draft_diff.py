"""Draft Diff & Versioning (M-14).

Line-by-line diff comparison, placeholder fill tracking, and
\"what still needs filling\" reports for petition drafts.

All functions are pure-stdlib (difflib) with no external deps.
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import build_error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRAFT_DIFF_VERSION = "0.14.0"

# Same regex pattern as petition.py for {{PLACEHOLDER}} detection
PLACEHOLDER_PATTERN = re.compile(r"\{\{([^}]+)\}\}")

# Sections used for mapping placeholders (same keywords as petition.py outline)
_SECTION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("BASLIK", ["BASLIK"]),
    ("MAHKEME", ["MAHKEME"]),
    ("DAVACI", ["DAVACI"]),
    ("DAVALI", ["DAVALI", "DALI"]),
    ("ACIKLAMA", ["ACIKLAMA", "ACIKLAMALAR"]),
    ("KARAR", ["KARAR"]),
    ("SONUC", ["SONUC"]),
    ("TALEP", ["TALEP"]),
    ("EKLER", ["EKLER"]),
]


def _placeholder_section(name: str) -> str:
    """Map a placeholder name to its section label."""
    upper = name.upper()
    for section_label, keywords in _SECTION_KEYWORDS:
        if any(kw in upper for kw in keywords):
            return section_label
    return "GENEL"


def _detect_sections(text: str) -> list[str]:
    """Extract section headers (## headings) from markdown text."""
    sections: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append(line[3:].strip())
    return sections


def _is_filled(text: str, placeholder_match: str) -> bool:
    """Check if a placeholder occurrence has been filled (no longer appears as raw pattern).

    A placeholder ``{{NAME}}`` is considered *filled* in ``text`` when
    the raw ``{{NAME}}`` pattern no longer appears at that location — i.e.
    it has been replaced with actual content.
    """
    # Simple heuristic: if the raw ``{{…}}`` token is gone from the text,
    # it has been filled.
    return placeholder_match not in text


# ---------------------------------------------------------------------------
# diff_drafts
# ---------------------------------------------------------------------------

def diff_drafts(
    draft_path_a: str | Path,
    draft_path_b: str | Path,
) -> dict[str, Any]:
    """Compare two draft files (draft.md or draft.json).

    Reads both files, computes a unified line-by-line diff, and analyses
    placeholder changes (filled vs unfilled).

    Args:
        draft_path_a: Path to the first (older) draft.
        draft_path_b: Path to the second (newer) draft.

    Returns:
        Dict with ok, draft_a, draft_b, diff_lines, changes, unified_diff,
        warnings.
    """
    path_a = Path(draft_path_a)
    path_b = Path(draft_path_b)

    # ── Validate inputs ────────────────────────────────────────────────────
    if not path_a.exists():
        return build_error(
            "DRAFT_NOT_FOUND",
            f"Draft file not found: {path_a}",
            source=str(path_a),
        )
    if not path_b.exists():
        return build_error(
            "DRAFT_NOT_FOUND",
            f"Draft file not found: {path_b}",
            source=str(path_b),
        )

    try:
        text_a = path_a.read_text(encoding="utf-8")
    except Exception as exc:
        return build_error("READ_ERROR", f"Cannot read {path_a}: {exc}", source=str(path_a))

    try:
        text_b = path_b.read_text(encoding="utf-8")
    except Exception as exc:
        return build_error("READ_ERROR", f"Cannot read {path_b}: {exc}", source=str(path_b))

    # ── Unified diff ───────────────────────────────────────────────────────
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)
    diff_iter = difflib.unified_diff(
        lines_a,
        lines_b,
        fromfile=str(path_a),
        tofile=str(path_b),
        lineterm="",
    )
    diff_lines = list(diff_iter)
    unified_diff_text = "".join(diff_lines)

    # ── Section diff ───────────────────────────────────────────────────────
    sections_a = _detect_sections(text_a)
    sections_b = _detect_sections(text_b)
    sections_added = [s for s in sections_b if s not in sections_a]
    sections_removed = [s for s in sections_a if s not in sections_b]
    sections_modified_count = len(sections_added) + len(sections_removed)
    # Also count modified sections (present in both but content differs)
    common_sections = [s for s in sections_a if s in sections_b]
    for section_name in common_sections:
        # Extract content for this section from both drafts
        content_a = _extract_section_content(text_a, section_name)
        content_b = _extract_section_content(text_b, section_name)
        if content_a != content_b:
            sections_modified_count += 1

    # ── Placeholder diff ───────────────────────────────────────────────────
    placeholders_a = set(PLACEHOLDER_PATTERN.findall(text_a))
    placeholders_b = set(PLACEHOLDER_PATTERN.findall(text_b))

    # Determine fill status: a placeholder in A that no longer appears in B
    # was filled; a new placeholder in B is newly added.
    filled_in_b: set[str] = set()
    for ph in placeholders_a:
        if ph not in placeholders_b:
            filled_in_b.add(ph)

    added_placeholders = placeholders_b - placeholders_a
    removed_placeholders = placeholders_a - placeholders_b

    changes = {
        "sections_added": len(sections_added),
        "sections_removed": len(sections_removed),
        "sections_modified": sections_modified_count,
        "placeholders_filled": len(filled_in_b),
        "placeholders_added": len(added_placeholders),
        "placeholders_removed": len(removed_placeholders),
    }

    warnings: list[str] = []
    if not unified_diff_text.strip():
        warnings.append("No differences found between the two drafts.")

    return {
        "ok": True,
        "draft_a": str(path_a),
        "draft_b": str(path_b),
        "diff_lines": diff_lines,
        "changes": changes,
        "unified_diff": unified_diff_text,
        "sections_added": sections_added,
        "sections_removed": sections_removed,
        "placeholders_filled": sorted(filled_in_b),
        "placeholders_added": sorted(added_placeholders),
        "placeholders_removed": sorted(removed_placeholders),
        "warnings": warnings,
    }


def _extract_section_content(text: str, section_name: str) -> str:
    """Extract content under a ## heading until the next ## heading."""
    lines = text.splitlines()
    capture = False
    result_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if capture:
                break
            if line[3:].strip() == section_name:
                capture = True
                continue
        elif capture:
            result_lines.append(line)
    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# track_placeholders
# ---------------------------------------------------------------------------

def track_placeholders(
    draft_path: str | Path,
) -> dict[str, Any]:
    """Analyze a draft for placeholder fill status.

    Finds all ``{{PLACEHOLDER}}`` patterns and reports which are filled
    (no longer present as raw tokens in the text) vs unfilled (still present).

    Args:
        draft_path: Path to the draft file.

    Returns:
        Dict with ok, total_placeholders, filled, unfilled, fill_ratio,
        placeholders, unfilled_list, ready_for_submission, warnings.
    """
    path = Path(draft_path)

    if not path.exists():
        return build_error(
            "DRAFT_NOT_FOUND",
            f"Draft file not found: {path}",
            source=str(path),
        )

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return build_error("READ_ERROR", f"Cannot read {path}: {exc}", source=str(path))

    # ── Locate all placeholder occurrences ─────────────────────────────────
    matches = list(PLACEHOLDER_PATTERN.finditer(text))

    if not matches:
        return {
            "ok": True,
            "total_placeholders": 0,
            "filled": 0,
            "unfilled": 0,
            "fill_ratio": 1.0,
            "placeholders": [],
            "unfilled_list": [],
            "ready_for_submission": True,
            "warnings": [],
        }

    # Build a list with status for each unique placeholder name
    seen: dict[str, dict[str, Any]] = {}
    for m in matches:
        name = m.group(1)
        if name not in seen:
            # Compute preview: first 60 chars after the }} on same line
            full_token = m.group(0)
            token_start = m.start()
            rest_of_line = text[token_start + len(full_token):].split("\n")[0].strip()
            preview = rest_of_line[:60] if rest_of_line else ""

            seen[name] = {
                "name": name,
                "token": full_token,
                "section": _placeholder_section(name),
                "preview": preview,
                "found_in_text": full_token in text,
            }

    # A placeholder is "unfilled" if its raw token still appears in the text
    placeholders_list: list[dict[str, Any]] = []
    filled_count = 0
    unfilled_count = 0
    unfilled_names: list[str] = []

    for name, info in seen.items():
        status = "unfilled" if info["found_in_text"] else "filled"
        if status == "filled":
            filled_count += 1
        else:
            unfilled_count += 1
            unfilled_names.append(name)
        placeholders_list.append({
            "name": info["name"],
            "status": status,
            "section": info["section"],
            "preview": info["preview"],
        })

    total = len(seen)
    fill_ratio = round(filled_count / total, 3) if total > 0 else 1.0

    warnings: list[str] = []
    if unfilled_count > 0:
        warnings.append(f"{unfilled_count} placeholder{'s' if unfilled_count > 1 else ''} unfilled")

    ready_for_submission = unfilled_count == 0

    return {
        "ok": True,
        "total_placeholders": total,
        "filled": filled_count,
        "unfilled": unfilled_count,
        "fill_ratio": fill_ratio,
        "placeholders": placeholders_list,
        "unfilled_list": unfilled_names,
        "ready_for_submission": ready_for_submission,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# get_fill_report
# ---------------------------------------------------------------------------

def get_fill_report(
    draft_path: str | Path,
    pack_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Human-readable report of what still needs attention.

    Lists unfilled placeholders with section context, suggests sources
    from the pack (if available), and provides a readiness assessment.

    Args:
        draft_path: Path to the draft file.
        pack_dir: Optional petition pack directory for source suggestions.

    Returns:
        Dict with ok, total_placeholders, filled, unfilled, fill_ratio,
        readiness, items (per-unfilled-placeholder), suggestions, warnings.
    """
    path = Path(draft_path)

    if not path.exists():
        return build_error(
            "DRAFT_NOT_FOUND",
            f"Draft file not found: {path}",
            source=str(path),
        )

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return build_error("READ_ERROR", f"Cannot read {path}: {exc}", source=str(path))

    matches = list(PLACEHOLDER_PATTERN.finditer(text))

    # ── Build per-placeholder items ────────────────────────────────────────
    seen: dict[str, dict[str, Any]] = {}
    for m in matches:
        name = m.group(1)
        if name not in seen:
            full_token = m.group(0)
            token_start = m.start()
            # Get surrounding context (3 lines before, 3 after)
            line_start = text.rfind("\n", 0, token_start)
            if line_start == -1:
                line_start = 0
            else:
                line_start += 1
            line_end = text.find("\n", token_start + len(full_token))
            if line_end == -1:
                line_end = len(text)

            # Expand context to ~3 lines before/after
            ctx_start = text.rfind("\n", 0, line_start)
            if ctx_start == -1:
                ctx_start = 0
            else:
                ctx_start = text.rfind("\n", 0, ctx_start) + 1
                ctx_start2 = text.rfind("\n", 0, ctx_start)
                if ctx_start2 != -1:
                    ctx_start = ctx_start2 + 1

            ctx_end = line_end
            for _ in range(3):
                nxt = text.find("\n", ctx_end + 1)
                if nxt == -1:
                    ctx_end = len(text)
                    break
                ctx_end = nxt

            context_text = text[ctx_start:ctx_end].strip()

            seen[name] = {
                "name": name,
                "token": full_token,
                "section": _placeholder_section(name),
                "context": context_text,
                "found_in_text": full_token in text,
            }

    items: list[dict[str, Any]] = []
    filled_count = 0
    unfilled_count = 0
    unfilled_names: list[str] = []

    for name, info in seen.items():
        status = "unfilled" if info["found_in_text"] else "filled"
        if status == "filled":
            filled_count += 1
        else:
            unfilled_count += 1
            unfilled_names.append(name)
        items.append({
            "name": info["name"],
            "status": status,
            "section": info["section"],
            "context": info["context"],
        })

    total = len(seen)
    fill_ratio = round(filled_count / total, 3) if total > 0 else 1.0

    # ── Readiness assessment ───────────────────────────────────────────────
    if unfilled_count == 0:
        readiness = "ready"
    elif fill_ratio >= 0.75:
        readiness = "nearly_ready"
    elif fill_ratio >= 0.5:
        readiness = "in_progress"
    else:
        readiness = "early_draft"

    # ── Source suggestions from pack ───────────────────────────────────────
    suggestions: dict[str, list[str]] = {}
    if pack_dir is not None:
        pack_path = Path(pack_dir)
        citation_bank_path = pack_path / "citation-bank.md"
        if citation_bank_path.exists():
            try:
                citation_text = citation_bank_path.read_text(encoding="utf-8")
                for name in unfilled_names:
                    # Simple keyword match: check if any citation-bank
                    # reference mentions the placeholder keyword parts
                    parts = name.split("_")
                    relevant_refs: list[str] = []
                    for line in citation_text.splitlines():
                        line_lower = line.lower()
                        if any(p.lower() in line_lower for p in parts if len(p) > 2):
                            relevant_refs.append(line.strip())
                    if relevant_refs:
                        suggestions[name] = relevant_refs[:3]
            except Exception:
                pass  # non-critical

    warnings: list[str] = []
    if unfilled_count > 0:
        warnings.append(
            f"{unfilled_count} placeholder{'s' if unfilled_count > 1 else ''} still unfilled"
        )

    return {
        "ok": True,
        "draft_path": str(path),
        "total_placeholders": total,
        "filled": filled_count,
        "unfilled": unfilled_count,
        "fill_ratio": fill_ratio,
        "readiness": readiness,
        "items": items,
        "suggestions": suggestions,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# save_draft_version
# ---------------------------------------------------------------------------

def save_draft_version(
    draft_dir: str | Path,
    version_label: str | None = None,
) -> dict[str, Any]:
    """Save a snapshot of the current draft state for later diff.

    Copies draft files into a versioned subdirectory under
    ``<draft_dir>/.versions/<version_id>/`` and stores metadata.

    Args:
        draft_dir: Directory containing draft files.
        version_label: Optional human-readable label for this version.

    Returns:
        Dict with ok, version_id, version_label, version_dir, files_copied,
        metadata_path, warnings.
    """
    draft_path = Path(draft_dir)

    if not draft_path.exists():
        return build_error(
            "DRAFT_DIR_NOT_FOUND",
            f"Draft directory not found: {draft_path}",
            source=str(draft_path),
        )

    if not draft_path.is_dir():
        return build_error(
            "NOT_A_DIRECTORY",
            f"Path is not a directory: {draft_path}",
            source=str(draft_path),
        )

    # ── Generate version id ────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    if version_label:
        safe_label = re.sub(r"[^\w\-]", "_", version_label)[:40]
        version_id = f"{timestamp}_{safe_label}"
    else:
        version_id = timestamp

    versions_dir = draft_path / ".versions"
    version_dir = versions_dir / version_id

    try:
        version_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return build_error(
            "VERSION_DIR_ERROR",
            f"Cannot create version directory: {exc}",
            source=str(version_dir),
        )

    # ── Copy draft files ───────────────────────────────────────────────────
    files_copied: list[str] = []
    warnings: list[str] = []

    for item in draft_path.iterdir():
        if item.name == ".versions":
            continue
        if item.name.startswith("."):
            continue
        if item.is_file():
            try:
                dest = version_dir / item.name
                shutil.copy2(item, dest)
                files_copied.append(item.name)
            except Exception as exc:
                warnings.append(f"Failed to copy {item.name}: {exc}")
        elif item.is_dir():
            # Copy subdirectories (like source-documents/)
            dest = version_dir / item.name
            try:
                shutil.copytree(item, dest, dirs_exist_ok=True)
                files_copied.append(f"{item.name}/")
            except Exception as exc:
                warnings.append(f"Failed to copy directory {item.name}: {exc}")

    # ── Write version metadata ─────────────────────────────────────────────
    metadata = {
        "version_id": version_id,
        "version_label": version_label or "",
        "created_at": now.isoformat(),
        "source_dir": str(draft_path),
        "files_copied": files_copied,
        "file_count": len(files_copied),
    }

    metadata_path = version_dir / "version-meta.json"
    try:
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        warnings.append(f"Failed to write version metadata: {exc}")

    return {
        "ok": True,
        "version_id": version_id,
        "version_label": version_label or "",
        "version_dir": str(version_dir),
        "files_copied": files_copied,
        "file_count": len(files_copied),
        "metadata_path": str(metadata_path),
        "warnings": warnings,
    }
