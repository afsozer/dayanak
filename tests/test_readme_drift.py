"""README drift detection — verifies documented counts match actual code state."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_readme_headline_matches_code() -> None:
    """README headline counts (MCP/CLI/test/module) must match live code."""
    readme = ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")

    m = re.search(r"v(\d+\.\d+\.\d+)", content.split("\n")[2])
    assert m, "README line 3 must contain a version number like v3.1.0"

    # Run the generator in check mode
    result = subprocess.run(
        ["python", str(ROOT / "scripts" / "gen_readme_counts.py"), "--check"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"README drift detected:\n{result.stdout}\n{result.stderr}\n"
        "Run: python scripts/gen_readme_counts.py > /dev/null && "
        "update README.md headline manually."
    )


@pytest.mark.unit
def test_readme_has_required_sections() -> None:
    """README must contain key sections."""
    readme = ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    for section in ("## Kırmızı çizgiler", "## Kurulum", "## Özellikler"):
        assert section in content, f"Missing section: {section}"
