"""Central configuration for emsal-mcp.

Reads from environment variables with sensible defaults.
All settings validated on access — no silent misconfiguration.

Usage:
    from emsal_mcp.config import config
    print(config.cache_path)
    print(config.user_agent)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any


class EmsalConfig:
    """Centralized, env-based configuration with defaults and validation."""

    def __init__(self) -> None:
        self._cache_path: Path | None = None
        self._user_agent: str | None = None
        self._udf_toolkit_dir: Path | None = None
        self._log_level: str | None = None
        self._http_timeout: float | None = None

    # ── Cache path ────────────────────────────────────────────────────────

    @property
    def cache_path(self) -> Path:
        """Path to the SQLite cache database.

        Env: EMSAL_CACHE_PATH (default: ~/.emsal_mcp/cache.sqlite3)
        """
        if self._cache_path is None:
            env_val = os.environ.get("EMSAL_CACHE_PATH", "").strip()
            if env_val:
                self._cache_path = Path(env_val)
            else:
                self._cache_path = Path.home() / ".emsal_mcp" / "cache.sqlite3"
        return self._cache_path

    @cache_path.setter
    def cache_path(self, value: str | Path) -> None:
        self._cache_path = Path(value)

    # ── User agent ────────────────────────────────────────────────────────

    @property
    def user_agent(self) -> str:
        """HTTP User-Agent header for source adapter requests.

        Env: EMSAL_USER_AGENT (default: EmsalMcp/{version} + GitHub URL)
        """
        if self._user_agent is None:
            env_val = os.environ.get("EMSAL_USER_AGENT", "").strip()
            if env_val:
                self._user_agent = env_val
            else:
                from . import __version__
                self._user_agent = (
                    f"EmsalMcp/{__version__} "
                    f"(https://github.com/fatihsozer/emsal-mcp)"
                )
        return self._user_agent

    # ── HTTP timeout ──────────────────────────────────────────────────────

    @property
    def http_timeout(self) -> float:
        """HTTP request timeout in seconds.

        Env: EMSAL_HTTP_TIMEOUT (default: 30.0)
        """
        if self._http_timeout is None:
            env_val = os.environ.get("EMSAL_HTTP_TIMEOUT", "").strip()
            self._http_timeout = float(env_val) if env_val else 30.0
        return self._http_timeout

    # ── UDF toolkit directory ─────────────────────────────────────────────

    @property
    def udf_toolkit_dir(self) -> Path | None:
        """UDF toolkit directory for LibreOffice/unoconv.

        Env: EMSAL_UDF_TOOLKIT_DIR or UDF_TOOLKIT_DIR (default: None)
        """
        if self._udf_toolkit_dir is None:
            for env_var in ("EMSAL_UDF_TOOLKIT_DIR", "UDF_TOOLKIT_DIR"):
                val = os.environ.get(env_var, "").strip()
                if val:
                    p = Path(val)
                    if p.exists():
                        self._udf_toolkit_dir = p
                        break
            # Leave as None if not found
            if self._udf_toolkit_dir is None:
                return None
        return self._udf_toolkit_dir

    @udf_toolkit_dir.setter
    def udf_toolkit_dir(self, value: str | Path | None) -> None:
        self._udf_toolkit_dir = Path(value) if value else None

    # ── Log level ─────────────────────────────────────────────────────────

    @property
    def log_level(self) -> str:
        """Logging level for emsal-mcp.

        Env: EMSAL_LOG_LEVEL (default: WARNING)
        Valid values: DEBUG, INFO, WARNING, ERROR, CRITICAL
        """
        if self._log_level is None:
            env_val = os.environ.get("EMSAL_LOG_LEVEL", "").strip().upper()
            valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
            self._log_level = env_val if env_val in valid else "WARNING"
        return self._log_level

    # ── KIK / EKAP API token ───────────────────────────────────────────

    @property
    def kik_api_token(self) -> str | None:
        """Optional API token for KİK/EKAP v2 access.

        Env: KIK_API_TOKEN (primary), EKAP_API_TOKEN (fallback).
        When set, the KİK source becomes EXPERIMENTAL instead of UNAVAILABLE.
        """
        return os.environ.get("KIK_API_TOKEN") or os.environ.get("EKAP_API_TOKEN")

    # ── Doctor / diagnostic ───────────────────────────────────────────────

    def doctor(self) -> dict[str, Any]:
        """Produce a diagnostic report of the emsal-mcp environment.

        Returns a dict suitable for JSON serialization (CLI --json).
        """
        import sys
        from . import __version__

        # Check cache accessibility
        cache_ok = False
        cache_error = None
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            if self.cache_path.exists():
                cache_ok = self.cache_path.is_file()
            else:
                # Try creating and removing a test file
                test_file = self.cache_path.parent / ".emsal_doctor_test"
                test_file.touch()
                test_file.unlink()
                cache_ok = True
        except Exception as exc:
            cache_error = str(exc)

        # Check UDF toolkit
        udf_ok = False
        udf_warnings: list[str] = []
        try:
            from .udf import get_udf_toolkit_status
            udf_status = get_udf_toolkit_status()
            udf_ok = udf_status.get("ok", False)
            udf_warnings = udf_status.get("warnings", [])
        except Exception as exc:
            udf_warnings = [str(exc)]

        # Source smoke summary
        source_smoke_ok = False
        source_count = 0
        try:
            from .sources.registry import smoke_all_sync
            results = smoke_all_sync(online=False)
            source_count = len(results)
            source_smoke_ok = all(r.get("offline_ok", False) for r in results)
        except Exception:
            pass

        return {
            "ok": True,
            "version": __version__,
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "python": {
                "version": sys.version,
                "executable": sys.executable,
            },
            "config": {
                "cache_path": str(self.cache_path),
                "cache_accessible": cache_ok,
                "cache_error": cache_error,
                "http_timeout": self.http_timeout,
                "log_level": self.log_level,
                "udf_toolkit_dir": str(self.udf_toolkit_dir) if self.udf_toolkit_dir else None,
            },
            "udf_toolkit": {
                "available": udf_ok,
                "warnings": udf_warnings,
            },
            "sources": {
                "smoke_ok": source_smoke_ok,
                "count": source_count,
            },
        }


# Global singleton — import and use throughout the codebase
config = EmsalConfig()


def setup_logging() -> logging.Logger:
    """Configure stdlib logging for emsal-mcp.

    Log level is controlled by EMSAL_LOG_LEVEL (default: WARNING).
    Output goes to stderr only — never pollutes stdout JSON contracts.

    Returns the configured logger.
    """
    logger = logging.getLogger("emsal_mcp")
    level = getattr(logging, config.log_level, logging.WARNING)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        logger.addHandler(handler)

    return logger
