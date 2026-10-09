"""emsal-mcp → Dayanak (2.0.0) geriye donuk uyumluluk."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import dayanak

pytestmark = [pytest.mark.unit]


class TestLegacyEnv:
    def test_emsal_prefix_is_copied(self, monkeypatch):
        monkeypatch.setenv("EMSAL_UYUMLULUK_DENEME", "eski")
        monkeypatch.delenv("DAYANAK_UYUMLULUK_DENEME", raising=False)
        dayanak._alias_legacy_env()
        assert os.environ["DAYANAK_UYUMLULUK_DENEME"] == "eski"
        monkeypatch.delenv("DAYANAK_UYUMLULUK_DENEME")

    def test_new_name_wins(self, monkeypatch):
        monkeypatch.setenv("EMSAL_UYUMLULUK_DENEME", "eski")
        monkeypatch.setenv("DAYANAK_UYUMLULUK_DENEME", "yeni")
        dayanak._alias_legacy_env()
        assert os.environ["DAYANAK_UYUMLULUK_DENEME"] == "yeni"


class TestDataHome:
    @pytest.fixture
    def home(self, monkeypatch, tmp_path) -> Path:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return tmp_path

    def test_fresh_install_uses_new_dir(self, home):
        assert dayanak.data_home() == home / ".dayanak"

    def test_legacy_dir_is_kept(self, home):
        (home / ".emsal_mcp").mkdir()
        assert dayanak.data_home() == home / ".emsal_mcp"

    def test_hyphenated_legacy_name(self, home):
        (home / ".emsal-mcp").mkdir()
        assert dayanak.data_home(".emsal-mcp") == home / ".emsal-mcp"
        assert dayanak.data_home() == home / ".dayanak"

    def test_new_dir_wins_over_legacy(self, home):
        (home / ".emsal_mcp").mkdir()
        (home / ".dayanak").mkdir()
        assert dayanak.data_home() == home / ".dayanak"
