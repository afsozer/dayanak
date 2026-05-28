"""Tests for UDF module."""
from __future__ import annotations

import pytest

from emsal_mcp.udf import (
    UdfError,
    probe_udf,
    read_udf,
    udf_to_markdown,
    write_udf,
)


class TestUDF:
    def test_write_and_read(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Test content here\nSecond line", path)
        assert path.exists()

        text = read_udf(path)
        assert "Test content here" in text
        assert "Second line" in text

    def test_read_nonexistent(self, tmp_path):
        with pytest.raises(UdfError, match="bulunamadı"):
            read_udf(tmp_path / "missing.udf")

    def test_read_invalid_zip(self, tmp_path):
        path = tmp_path / "bad.udf"
        path.write_text("not a zip file", encoding="utf-8")
        with pytest.raises(UdfError, match="ZIP imzası yok"):
            read_udf(path)

    def test_udf_to_markdown(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Title\n\nParagraph one.\nParagraph two.", path)
        md = udf_to_markdown(path)
        assert "Title" in md
        assert "Paragraph one." in md

    def test_probe_udf(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Probe test", path)
        info = probe_udf(path)
        assert info["exists"] is True
        assert info["zip"] is True
        assert info["has_content_xml"] is True
        assert info["text_length"] > 0

    def test_probe_missing(self, tmp_path):
        info = probe_udf(tmp_path / "missing.udf")
        assert info["exists"] is False

    def test_write_title_centered(self, tmp_path):
        path = tmp_path / "centered.udf"
        write_udf("Centered Title\nBody", path, title_centered=True)
        text = read_udf(path)
        assert "Centered Title" in text
