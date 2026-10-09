"""Tests for config module."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

from pathlib import Path

import pytest

from dayanak.config import DayanakConfig, config, setup_logging


@pytest.fixture
def fresh_config():
    """Return a fresh config instance (not the global singleton)."""
    return DayanakConfig()


class TestConfigDefaults:
    """Default values without env overrides."""

    def test_cache_path_default(self, fresh_config, monkeypatch, tmp_path):
        # The session-wide isolation fixture sets DAYANAK_CACHE_PATH; clear it to
        # assert the true built-in default.  Home is faked so a real legacy
        # ~/.emsal_mcp on the test machine does not trigger the fallback.
        monkeypatch.delenv("DAYANAK_CACHE_PATH", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert fresh_config.cache_path == tmp_path / ".dayanak" / "cache.sqlite3"

    def test_user_agent_default(self, fresh_config):
        ua = fresh_config.user_agent
        assert "Dayanak/" in ua
        assert "github.com" in ua

    def test_http_timeout_default(self, fresh_config):
        assert fresh_config.http_timeout == 30.0

    def test_log_level_default(self, fresh_config):
        assert fresh_config.log_level == "WARNING"

    def test_udf_toolkit_dir_default(self, fresh_config):
        assert fresh_config.udf_toolkit_dir is None


class TestConfigEnvOverrides:
    """Environment variable overrides."""

    def test_cache_path_env(self, fresh_config, monkeypatch, tmp_path):
        monkeypatch.setenv("DAYANAK_CACHE_PATH", str(tmp_path / "custom.sqlite3"))
        c = DayanakConfig()
        assert c.cache_path == tmp_path / "custom.sqlite3"

    def test_user_agent_env(self, fresh_config, monkeypatch):
        monkeypatch.setenv("DAYANAK_USER_AGENT", "TestAgent/1.0")
        c = DayanakConfig()
        assert c.user_agent == "TestAgent/1.0"

    def test_http_timeout_env(self, fresh_config, monkeypatch):
        monkeypatch.setenv("DAYANAK_HTTP_TIMEOUT", "60.5")
        c = DayanakConfig()
        assert c.http_timeout == 60.5

    def test_log_level_env_valid(self, fresh_config, monkeypatch):
        monkeypatch.setenv("DAYANAK_LOG_LEVEL", "DEBUG")
        c = DayanakConfig()
        assert c.log_level == "DEBUG"

    def test_log_level_env_invalid_falls_back(self, fresh_config, monkeypatch):
        monkeypatch.setenv("DAYANAK_LOG_LEVEL", "VERBOSE")
        c = DayanakConfig()
        assert c.log_level == "WARNING"

    def test_udf_toolkit_dir_env(self, fresh_config, monkeypatch, tmp_path):
        tk = tmp_path / "udf-tk"
        tk.mkdir()
        monkeypatch.setenv("DAYANAK_UDF_TOOLKIT_DIR", str(tk))
        c = DayanakConfig()
        assert c.udf_toolkit_dir == tk

    def test_udf_toolkit_dir_fallback_env(self, fresh_config, monkeypatch, tmp_path):
        tk = tmp_path / "udf-tk-fb"
        tk.mkdir()
        monkeypatch.setenv("UDF_TOOLKIT_DIR", str(tk))
        c = DayanakConfig()
        assert c.udf_toolkit_dir == tk

    def test_udf_toolkit_dir_dayanak_priority(self, fresh_config, monkeypatch, tmp_path):
        primary = tmp_path / "primary"
        fallback = tmp_path / "fallback"
        primary.mkdir()
        fallback.mkdir()
        monkeypatch.setenv("DAYANAK_UDF_TOOLKIT_DIR", str(primary))
        monkeypatch.setenv("UDF_TOOLKIT_DIR", str(fallback))
        c = DayanakConfig()
        assert c.udf_toolkit_dir == primary


class TestConfigSetters:
    """Setter methods."""

    def test_set_cache_path(self, fresh_config, tmp_path):
        fresh_config.cache_path = tmp_path / "set.sqlite3"
        assert fresh_config.cache_path == tmp_path / "set.sqlite3"

    def test_set_empty_cache_path_clears(self, fresh_config, tmp_path):
        fresh_config.cache_path = tmp_path / "custom.sqlite3"
        fresh_config.udf_toolkit_dir = tmp_path / "udf"
        assert fresh_config.udf_toolkit_dir == tmp_path / "udf"


class TestConfigDoctor:
    """Doctor diagnostic report."""

    def test_doctor_runs(self):
        result = config.doctor()
        assert result["ok"] is True
        assert "version" in result
        assert "python" in result
        assert "config" in result
        assert "udf_toolkit" in result
        assert "sources" in result

    def test_doctor_config_keys(self):
        result = config.doctor()
        assert result["config"]["cache_accessible"] in (True, False)
        assert "cache_error" in result["config"]
        assert "http_timeout" in result["config"]
        assert "log_level" in result["config"]

    def test_doctor_with_custom_cache_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DAYANAK_CACHE_PATH", str(tmp_path / "test.sqlite3"))
        c = DayanakConfig()
        result = c.doctor()
        assert tmp_path.name in result["config"]["cache_path"]


class TestLogging:
    """Structured logging setup."""

    def test_setup_logging_returns_logger(self):
        logger = setup_logging()
        assert logger.name == "dayanak"
        assert logger.level > 0

    def test_setup_logging_respects_env(self, monkeypatch):
        monkeypatch.setenv("DAYANAK_LOG_LEVEL", "ERROR")
        from dayanak.config import DayanakConfig
        c = DayanakConfig()
        assert c.log_level == "ERROR"


class TestGlobalSingleton:
    """Global config singleton."""

    def test_global_config_is_dayanak_config(self):
        from dayanak.config import config
        assert isinstance(config, DayanakConfig)

    def test_global_config_caches_on_access(self):
        from dayanak.config import config
        path1 = config.cache_path
        path2 = config.cache_path
        assert path1 == path2


