#!/usr/bin/env python3
"""Scan source files for user-facing strings and output a JSON inventory.

Finds:
- Strings passed to 'warnings' lists
- Strings passed to 'recommended_next_steps'
- Error messages from build_error() calls
- User-facing log/echo strings

Output: JSON report grouped by module, saved to docs/message_inventory.json.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "emsal_mcp"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "message_inventory.json"


def extract_string_literals(filepath: Path) -> list[dict]:
    """Extract user-facing string literals from a Python source file.

    Returns list of dicts with keys: line, context, message, category.
    """
    content = filepath.read_text(encoding="utf-8")
    results: list[dict] = []

    # Pattern 1: recommended_next_steps=[...] or "recommended_next_steps": [...]
    rec_steps = re.finditer(
        r'recommended_next_steps\s*[=:]\s*\[(.*?)\]',
        content,
        re.DOTALL,
    )
    for m in rec_steps:
        block = m.group(1)
        line_no = content[:m.start()].count("\n") + 1
        # Extract string literals from the block
        for sm in re.finditer(r'"([^"]+)"', block):
            results.append({
                "line": line_no,
                "context": "recommended_next_steps",
                "message": sm.group(1),
                "category": "recommended_next_step",
            })
        for sm in re.finditer(r"'([^']+)'", block):
            if '"' not in sm.group(1):  # skip if already captured with double quotes
                results.append({
                    "line": line_no,
                    "context": "recommended_next_steps",
                    "message": sm.group(1),
                    "category": "recommended_next_step",
                })

    # Pattern 2: warnings.append("...") or warnings = ["..."]
    warn_append = re.finditer(
        r'warnings\.append\(\s*["\'](.+?)["\']\s*\)',
        content,
    )
    for m in warn_append:
        line_no = content[:m.start()].count("\n") + 1
        results.append({
            "line": line_no,
            "context": "warnings.append",
            "message": m.group(1),
            "category": "warning",
        })

    # Pattern 3: build_error(...) with message= kwarg
    build_err = re.finditer(
        r'build_error\([^)]*message\s*=\s*["\'](.+?)["\']',
        content,
        re.DOTALL,
    )
    for m in build_err:
        line_no = content[:m.start()].count("\n") + 1
        results.append({
            "line": line_no,
            "context": "build_error",
            "message": m.group(1),
            "category": "error_message",
        })

    # Pattern 4: "warnings": [...] in dict literals (multi-line safe)
    warn_dict = re.finditer(
        r'"warnings"\s*:\s*\[(.*?)\]',
        content,
        re.DOTALL,
    )
    for m in warn_dict:
        block = m.group(1)
        line_no = content[:m.start()].count("\n") + 1
        for sm in re.finditer(r'"([^"]{5,})"', block):
            results.append({
                "line": line_no,
                "context": "warnings dict",
                "message": sm.group(1),
                "category": "warning",
            })

    # Pattern 5: f-string messages with common prefixes
    fmsg = re.finditer(
        r'f["\']((?:İçerik|Bu |Kaynak|Belge|Dikkat|Uyarı|Hata|Dosya|PDF|OCR|Toolkit|UDF|Cache|Index|Graf|Chamber|Circuit)[^"\']{10,}?)["\']',
        content,
    )
    for m in fmsg:
        line_no = content[:m.start()].count("\n") + 1
        msg = m.group(1)
        # De-f-string: remove {expr} patterns for readability
        msg_clean = re.sub(r'\{[^}]+\}', '{...}', msg)
        results.append({
            "line": line_no,
            "context": "f-string message",
            "message": msg_clean,
            "category": "user_message",
        })

    # Pattern 6: typer.echo or typer.echo(..., err=True)
    typer_echo = re.finditer(
        r'typer\.echo\(\s*["\'](.+?)["\']',
        content,
    )
    for m in typer_echo:
        line_no = content[:m.start()].count("\n") + 1
        results.append({
            "line": line_no,
            "context": "typer.echo",
            "message": m.group(1),
            "category": "cli_output",
        })

    # Pattern 7: standalone Turkish string literals that look like messages
    # (only in context of "next_step", "error", "warning" nearby)
    turkish_msg = re.finditer(
        r'(?:next_step|error|warning|message)\s*=\s*["\']([^"\']{15,}?)["\']',
        content,
    )
    for m in turkish_msg:
        line_no = content[:m.start()].count("\n") + 1
        msg = m.group(1)
        if any(c in msg for c in 'çğıöşüÇĞİÖŞÜ') or 'kayıt' in msg.lower():
            results.append({
                "line": line_no,
                "context": "assigned message",
                "message": msg,
                "category": "user_message",
            })

    # Pattern 8: return dict with "message" key
    msg_dict = re.finditer(
        r'"message"\s*:\s*["\'](.+?)["\']',
        content,
    )
    for m in msg_dict:
        line_no = content[:m.start()].count("\n") + 1
        results.append({
            "line": line_no,
            "context": "message dict key",
            "message": m.group(1),
            "category": "error_message",
        })

    return results


def dedup_messages(messages: list[dict]) -> list[dict]:
    """Remove exact duplicate messages, keeping first occurrence."""
    seen: set[str] = set()
    result: list[dict] = []
    for msg in messages:
        key = (msg["message"], msg["category"])
        if key not in seen:
            seen.add(key)
            result.append(msg)
    return result


def main() -> None:
    """Generate message inventory from source files and save to JSON."""
    if not SRC_DIR.exists():
        print(f"ERROR: Source directory not found: {SRC_DIR}", file=sys.stderr)
        sys.exit(1)

    inventory: dict[str, list[dict]] = defaultdict(list)

    py_files = sorted(SRC_DIR.glob("*.py"))
    for filepath in py_files:
        module_name = filepath.stem
        messages = extract_string_literals(filepath)
        if messages:
            inventory[module_name] = dedup_messages(messages)

    # Summary stats
    total_messages = sum(len(msgs) for msgs in inventory.values())
    by_category: dict[str, int] = defaultdict(int)
    for msgs in inventory.values():
        for msg in msgs:
            by_category[msg["category"]] += 1

    output = {
        "generated_by": "scripts/inventory_messages.py",
        "source_dir": str(SRC_DIR),
        "module_count": len(inventory),
        "total_unique_messages": total_messages,
        "category_counts": dict(by_category),
        "modules": dict(inventory),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Message inventory saved to {OUTPUT}")
    print(f"  Modules: {len(inventory)}")
    print(f"  Total unique messages: {total_messages}")
    print(f"  By category: {dict(by_category)}")


if __name__ == "__main__":
    main()
