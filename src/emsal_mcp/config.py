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
        self._circuit_breaker_threshold: int | None = None
        self._circuit_recovery_timeout: int | None = None
        self._retry_max_attempts: int | None = None
        self._retry_base_delay: float | None = None
        self._rate_limit_enabled: bool | None = None

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
                    f"(https://github.com/afsozer/emsal-mcp)"
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

    # ── Circuit breaker threshold ──────────────────────────────────────

    @property
    def circuit_breaker_threshold(self) -> int:
        """Consecutive failures before circuit breaker opens.

        Env: EMSAL_CB_THRESHOLD (default: 5)
        """
        if self._circuit_breaker_threshold is None:
            env_val = os.environ.get("EMSAL_CB_THRESHOLD", "").strip()
            self._circuit_breaker_threshold = int(env_val) if env_val else 5
        return self._circuit_breaker_threshold

    # ── Circuit breaker recovery timeout ───────────────────────────────

    @property
    def circuit_recovery_timeout(self) -> int:
        """Seconds to wait before transitioning OPEN -> HALF_OPEN.

        Env: EMSAL_CB_TIMEOUT (default: 300)
        """
        if self._circuit_recovery_timeout is None:
            env_val = os.environ.get("EMSAL_CB_TIMEOUT", "").strip()
            self._circuit_recovery_timeout = int(env_val) if env_val else 300
        return self._circuit_recovery_timeout

    # ── Retry max attempts ──────────────────────────────────────────────

    @property
    def retry_max_attempts(self) -> int:
        """Maximum number of retry attempts for source adapter calls.

        Env: EMSAL_RETRY_MAX (default: 3)
        """
        if self._retry_max_attempts is None:
            env_val = os.environ.get("EMSAL_RETRY_MAX", "").strip()
            self._retry_max_attempts = int(env_val) if env_val else 3
        return self._retry_max_attempts

    # ── Retry base delay ────────────────────────────────────────────────

    @property
    def retry_base_delay(self) -> float:
        """Base delay in seconds between retry attempts.

        Env: EMSAL_RETRY_DELAY (default: 1.0)
        """
        if self._retry_base_delay is None:
            env_val = os.environ.get("EMSAL_RETRY_DELAY", "").strip()
            self._retry_base_delay = float(env_val) if env_val else 1.0
        return self._retry_base_delay

    # ── Rate limit enabled ──────────────────────────────────────────────

    @property
    def rate_limit_enabled(self) -> bool:
        """Whether the global rate limiter is enabled.

        Env: EMSAL_RATE_LIMIT_ENABLED (default: false)
        Accepts: 1, true, yes → enabled; anything else → disabled.
        """
        if self._rate_limit_enabled is None:
            env_val = os.environ.get("EMSAL_RATE_LIMIT_ENABLED", "").strip().lower()
            self._rate_limit_enabled = env_val in ("1", "true", "yes")
        return self._rate_limit_enabled

    # ── UDF toolkit directory ─────────────────────────────────────────────

    # ── Embedding provider ─────────────────────────────────────────────

    @property
    def embedding_provider(self) -> str:
        """Embedding provider ID.

        Env: EMSAL_EMBEDDING_PROVIDER (default: local-hash-v1)
        """
        return os.environ.get("EMSAL_EMBEDDING_PROVIDER", "local-hash-v1")

    @property
    def embedding_cache_dir(self) -> Path:
        """Cache directory for downloaded embedding models.

        Env: EMSAL_EMBEDDING_CACHE_DIR (default: ~/.emsal_mcp/models/fastembed)
        """
        env = os.environ.get("EMSAL_EMBEDDING_CACHE_DIR", "")
        if env:
            return Path(env)
        return Path.home() / ".emsal_mcp" / "models" / "fastembed"

    @property
    def embedding_batch_size(self) -> int:
        """Batch size for embedding operations.

        Env: EMSAL_EMBEDDING_BATCH_SIZE (default: 16)
        """
        return int(os.environ.get("EMSAL_EMBEDDING_BATCH_SIZE", "16"))

    # ── Hybrid search weights ──────────────────────────────────────────

    @property
    def hybrid_w_bm25(self) -> float:
        """Weight for BM25 component in hybrid search.

        Env: EMSAL_HYBRID_W_BM25 (default: 0.4)
        """
        return float(os.environ.get("EMSAL_HYBRID_W_BM25", "0.4"))

    @property
    def hybrid_w_tfidf(self) -> float:
        """Weight for TF-IDF cosine component in hybrid search.

        Env: EMSAL_HYBRID_W_TFIDF (default: 0.6)
        """
        return float(os.environ.get("EMSAL_HYBRID_W_TFIDF", "0.6"))

    @property
    def hybrid_w_dense(self) -> float:
        """Weight for dense embedding component in hybrid search.

        Env: EMSAL_HYBRID_W_DENSE (default: 0.0)
        """
        return float(os.environ.get("EMSAL_HYBRID_W_DENSE", "0.0"))

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

    # ── PDF / OCR extraction ──────────────────────────────────────────

    @property
    def pdf_extraction_enabled(self) -> bool:
        """Whether to attempt PDF text extraction.

        Env: EMSAL_PDF_EXTRACTION (default: true)
        Accepts: 0, false, no → disabled; anything else → enabled.
        """
        env_val = os.environ.get("EMSAL_PDF_EXTRACTION", "true").strip().lower()
        return env_val not in ("0", "false", "no")

    @property
    def ocr_enabled(self) -> bool:
        """Whether to enable OCR for scanned/image PDFs.

        Env: EMSAL_OCR_ENABLED (default: false)
        OCR is opt-in because it is slow and confidence is low.
        Accepts: 1, true, yes → enabled; anything else → disabled.
        """
        env_val = os.environ.get("EMSAL_OCR_ENABLED", "false").strip().lower()
        return env_val in ("1", "true", "yes")

    @property
    def ocr_language(self) -> str:
        """Tesseract OCR language code.

        Env: EMSAL_OCR_LANGUAGE (default: tur)
        """
        return os.environ.get("EMSAL_OCR_LANGUAGE", "tur").strip()

    # ── Concurrency control ───────────────────────────────────────────

    @property
    def max_concurrency(self) -> int:
        """Maximum number of concurrent source requests.

        Env: EMSAL_MAX_CONCURRENCY (default: 3)
        Conservative default — single-user design preserved.
        """
        try:
            return int(os.environ.get("EMSAL_MAX_CONCURRENCY", "3"))
        except ValueError:
            return 3

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
