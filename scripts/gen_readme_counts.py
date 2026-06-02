"""Generate drand-free README counts from actual code state.

Usage: python scripts/gen_readme_counts.py [--check]
  Without --check: prints the latest counts as a Markdown headline line.
  With --check: exits 0 if README.md is in sync, 1 if drift detected (for CI).
"""
from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _count_mcp_tools() -> int:
    server = ROOT / "src" / "emsal_mcp" / "server.py"
    text = server.read_text(encoding="utf-8")
    return len(re.findall(r"@mcp\.tool\(\)", text))


def _count_cli_commands() -> int:
    cli = ROOT / "src" / "emsal_mcp" / "cli.py"
    text = cli.read_text(encoding="utf-8")
    # Typer commands: @xxx.command("name") or @app.command(...)
    return len(re.findall(r'\.(?:command|add_typer)\b', text))


def _count_modules() -> int:
    src = ROOT / "src" / "emsal_mcp"
    return len(list(src.glob("*.py")))


def _count_test_files() -> int:
    tests = ROOT / "tests"
    return len(list(tests.glob("test_*.py")))


def _version_from_init() -> str:
    init = ROOT / "src" / "emsal_mcp" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "?.?.?"


def _headline() -> str:
    v = _version_from_init()
    mcp = _count_mcp_tools()
    cli = _count_cli_commands()
    mod = _count_modules()
    tests = _count_test_files()
    return f"> **v{v}** — {mcp} MCP tools · {cli} CLI commands · {tests} test files · {mod} source modules"


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    args = sys.argv[1:]
    headline = _headline()

    if "--check" in args:
        readme = ROOT / "README.md"
        content = readme.read_text(encoding="utf-8")
        # Find the existing headline line (starts with "> **v")
        existing = re.search(r"^> \*\*v[\d.]+.*$", content, re.MULTILINE)
        if existing and existing.group().strip() == headline:
            sys.exit(0)
        print(f"DRIFT: README headline out of sync.")
        print(f"  Expected: {headline}")
        if existing:
            print(f"  Found:    {existing.group().strip()}")
        sys.exit(1)
    else:
        print(headline)


if __name__ == "__main__":
    main()
