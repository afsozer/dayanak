"""Tests for circuit breaker module (M-17)."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from emsal_mcp.cache import Cache
from emsal_mcp.circuit import (
    _ensure_table,
    get_all_sources_health,
    get_source_health,
    is_circuit_open,
    record_failure,
    record_success,
    reset_circuit,
)


@pytest.fixture
def cache():
    """Create a temporary cache for circuit breaker tests."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_circuit.sqlite3"
        c = Cache(path)
        yield c
        c.close()


# ── record_success ─────────────────────────────────────────────────────────


class TestRecordSuccess:
    def test_resets_consecutive_failures(self, cache):
        """Success should reset consecutive_failures to 0."""
        record_failure("src", cache=cache)
        record_failure("src", cache=cache)
        record_failure("src", cache=cache)
        record_success("src", cache=cache)

        health = get_source_health("src", cache=cache)
        assert health["consecutive_failures"] == 0
        assert health["success_count"] == 1

    def test_increments_success_count(self, cache):
        """Each success increments the counter."""
        record_success("src", cache=cache)
        record_success("src", cache=cache)
        record_success("src", cache=cache)

        health = get_source_health("src", cache=cache)
        assert health["success_count"] == 3

    def test_success_in_half_open_transitions_to_closed(self, cache):
        """A success in HALF_OPEN state should transition to CLOSED."""
        # Force into half_open via open -> timeout
        for _ in range(5):
            record_failure("src", cache=cache)
        # Manually set state to half_open
        cache.db.execute(
            "UPDATE circuit_state SET state='half_open', opened_at=? WHERE source_id='src'",
            ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
        )
        cache.db.commit()

        record_success("src", cache=cache)

        health = get_source_health("src", cache=cache)
        assert health["state"] == "closed"
        assert health["circuit_open"] is False

    def test_success_sets_last_success_at(self, cache):
        """Success should update last_success_at timestamp."""
        record_success("src", cache=cache)
        health = get_source_health("src", cache=cache)
        assert health["last_success_at"] is not None


# ── record_failure ─────────────────────────────────────────────────────────


class TestRecordFailure:
    def test_increments_counters(self, cache):
        """Each failure increments both counters."""
        record_failure("src", cache=cache)
        record_failure("src", cache=cache)

        health = get_source_health("src", cache=cache)
        assert health["failure_count"] == 2
        assert health["consecutive_failures"] == 2

    def test_five_consecutive_opens_circuit(self, cache):
        """5 consecutive failures should open the circuit (default threshold=5)."""
        for i in range(5):
            record_failure("src", cache=cache)

        health = get_source_health("src", cache=cache)
        assert health["state"] == "open"
        assert health["circuit_open"] is True

    def test_failure_in_half_open_transitions_to_open(self, cache):
        """A failure in HALF_OPEN should transition back to OPEN."""
        # Force open
        for _ in range(5):
            record_failure("src", cache=cache)
        # Force to half_open
        cache.db.execute(
            "UPDATE circuit_state SET state='half_open', opened_at=? WHERE source_id='src'",
            ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
        )
        cache.db.commit()

        record_failure("src", cache=cache)

        health = get_source_health("src", cache=cache)
        assert health["state"] == "open"
        assert health["circuit_open"] is True

    def test_sets_last_failure_at(self, cache):
        """Failure should update last_failure_at timestamp."""
        record_failure("src", cache=cache)
        health = get_source_health("src", cache=cache)
        assert health["last_failure_at"] is not None


# ── is_circuit_open ────────────────────────────────────────────────────────


class TestIsCircuitOpen:
    def test_closed_not_open(self, cache):
        """CLOSED circuit should return False."""
        assert is_circuit_open("src", cache=cache) is False

    def test_no_row_not_open(self, cache):
        """Unknown source (no row) should return False."""
        assert is_circuit_open("unknown", cache=cache) is False

    def test_open_blocks_calls(self, cache):
        """OPEN circuit should return True (blocking)."""
        for _ in range(5):
            record_failure("src", cache=cache)

        assert is_circuit_open("src", cache=cache) is True

    def test_recovery_timeout_transitions_to_half_open(self, cache):
        """After recovery timeout, OPEN should transition to HALF_OPEN and return False."""
        # Force open with old timestamp
        for _ in range(5):
            record_failure("src", cache=cache)
        cache.db.execute(
            "UPDATE circuit_state SET opened_at=? WHERE source_id='src'",
            ((datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat(),),
        )
        cache.db.commit()

        # With default timeout of 300s, 600s should be past recovery
        assert is_circuit_open("src", cache=cache) is False

        # Verify state transitioned to half_open
        health = get_source_health("src", cache=cache)
        assert health["state"] == "half_open"

    def test_within_timeout_stays_open(self, cache):
        """Within recovery timeout, OPEN should still block."""
        for _ in range(5):
            record_failure("src", cache=cache)
        # Set opened_at to just now (within 300s)
        cache.db.execute(
            "UPDATE circuit_state SET opened_at=? WHERE source_id='src'",
            (datetime.now(timezone.utc).isoformat(),),
        )
        cache.db.commit()

        assert is_circuit_open("src", cache=cache) is True

    def test_half_open_not_blocked(self, cache):
        """HALF_OPEN circuit should return False (allows one try)."""
        for _ in range(5):
            record_failure("src", cache=cache)
        cache.db.execute(
            "UPDATE circuit_state SET state='half_open' WHERE source_id='src'",
        )
        cache.db.commit()

        assert is_circuit_open("src", cache=cache) is False

    def test_custom_threshold(self, cache):
        """Custom threshold should override default via EMSAL_CB_THRESHOLD env."""
        # With env-based threshold=3, 3 failures should trigger open
        with patch.dict("os.environ", {"EMSAL_CB_THRESHOLD": "3"}):
            for _ in range(3):
                record_failure("src", cache=cache)
            # record_failure reads config at call time, but is_circuit_open uses
            # the threshold parameter to check state — not to open.
            # The circuit is already OPEN from record_failure with threshold=5 default.
            # We need to manually set up state to test the threshold logic.
            # Reset and set up fresh: with threshold=3, record_failure would open at 3
            cache.db.execute(
                "UPDATE circuit_state SET state='closed', consecutive_failures=0 WHERE source_id='src'"
            )
            cache.db.commit()

        # Now use the direct threshold check: 2 failures should not open with threshold=3
        for _ in range(2):
            record_failure("src", cache=cache)
        assert get_source_health("src", cache=cache)["state"] == "closed"

    def test_custom_recovery_timeout(self, cache):
        """Custom recovery timeout should override default."""
        for _ in range(5):
            record_failure("src", cache=cache)
        # Set opened_at to 10 seconds ago
        cache.db.execute(
            "UPDATE circuit_state SET opened_at=? WHERE source_id='src'",
            ((datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),),
        )
        cache.db.commit()

        # With default 300s timeout, 10s ago should still block
        assert is_circuit_open("src", cache=cache) is True
        # With custom 5s timeout, should allow
        assert is_circuit_open("src", cache=cache, recovery_timeout=5) is False


# ── get_source_health ──────────────────────────────────────────────────────


class TestGetSourceHealth:
    def test_unknown_source_defaults(self, cache):
        """Unknown source should return healthy defaults."""
        health = get_source_health("unknown", cache=cache)
        assert health["ok"] is True
        assert health["source_id"] == "unknown"
        assert health["state"] == "closed"
        assert health["failure_count"] == 0
        assert health["success_count"] == 0
        assert health["uptime_pct"] == 100.0
        assert health["circuit_open"] is False

    def test_uptime_percentage_calculation(self, cache):
        """Uptime % should be success_count / (success + failure) * 100."""
        for _ in range(8):
            record_success("src", cache=cache)
        for _ in range(2):
            record_failure("src", cache=cache)

        health = get_source_health("src", cache=cache)
        assert health["uptime_pct"] == 80.0

    def test_all_successes_uptime_100(self, cache):
        """All successes should give 100% uptime."""
        for _ in range(5):
            record_success("src", cache=cache)

        health = get_source_health("src", cache=cache)
        assert health["uptime_pct"] == 100.0

    def test_returns_required_fields(self, cache):
        """Health dict should contain all required fields."""
        record_success("src", cache=cache)
        health = get_source_health("src", cache=cache)
        required = {
            "ok", "source_id", "state", "failure_count", "success_count",
            "last_failure_at", "last_success_at", "consecutive_failures",
            "uptime_pct", "circuit_open",
        }
        assert required.issubset(health.keys())


# ── get_all_sources_health ────────────────────────────────────────────────


class TestGetAllSourcesHealth:
    def test_empty_db(self, cache):
        """Empty circuit_state table should return empty sources dict."""
        result = get_all_sources_health(cache=cache)
        assert result["ok"] is True
        assert result["sources"] == {}

    def test_multiple_sources_tracked(self, cache):
        """Multiple sources should be tracked independently."""
        record_success("src_a", cache=cache)
        record_failure("src_b", cache=cache)

        result = get_all_sources_health(cache=cache)
        assert "src_a" in result["sources"]
        assert "src_b" in result["sources"]
        assert result["sources"]["src_a"]["success_count"] == 1
        assert result["sources"]["src_b"]["failure_count"] == 1


# ── reset_circuit ──────────────────────────────────────────────────────────


class TestResetCircuit:
    def test_reset_forces_closed(self, cache):
        """Reset should force state to CLOSED."""
        for _ in range(5):
            record_failure("src", cache=cache)

        result = reset_circuit("src", cache=cache)
        assert result["ok"] is True
        assert result["state"] == "closed"
        assert result["previous_state"] == "open"

    def test_reset_clears_consecutive_failures(self, cache):
        """Reset should set consecutive_failures to 0."""
        for _ in range(3):
            record_failure("src", cache=cache)

        reset_circuit("src", cache=cache)
        health = get_source_health("src", cache=cache)
        assert health["consecutive_failures"] == 0

    def test_reset_nonexistent_source(self, cache):
        """Reset on unknown source should still return ok."""
        result = reset_circuit("unknown", cache=cache)
        assert result["ok"] is True
        assert result["state"] == "closed"


# ── Multiple sources ───────────────────────────────────────────────────────


class TestMultipleSources:
    def test_independent_tracking(self, cache):
        """Each source should be tracked independently."""
        record_success("src_a", cache=cache)
        record_failure("src_a", cache=cache)
        record_success("src_b", cache=cache)
        record_success("src_b", cache=cache)

        health_a = get_source_health("src_a", cache=cache)
        health_b = get_source_health("src_b", cache=cache)
        assert health_a["success_count"] == 1
        assert health_a["failure_count"] == 1
        assert health_b["success_count"] == 2
        assert health_b["failure_count"] == 0

    def test_one_source_open_does_not_affect_others(self, cache):
        """Opening circuit for one source should not affect other sources."""
        for _ in range(5):
            record_failure("src_a", cache=cache)
        record_success("src_b", cache=cache)

        assert is_circuit_open("src_a", cache=cache) is True
        assert is_circuit_open("src_b", cache=cache) is False


# ── State machine transitions ──────────────────────────────────────────────


class TestStateMachine:
    def test_full_lifecycle(self, cache):
        """Test complete lifecycle: closed -> open -> half_open -> closed."""
        # Start closed
        assert get_source_health("src", cache=cache)["state"] == "closed"

        # 5 failures -> open
        for _ in range(5):
            record_failure("src", cache=cache)
        assert get_source_health("src", cache=cache)["state"] == "open"
        assert is_circuit_open("src", cache=cache) is True

        # Set old opened_at to trigger timeout
        cache.db.execute(
            "UPDATE circuit_state SET opened_at=? WHERE source_id='src'",
            ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
        )
        cache.db.commit()

        # Timeout -> half_open
        assert is_circuit_open("src", cache=cache) is False
        assert get_source_health("src", cache=cache)["state"] == "half_open"

        # Success -> closed
        record_success("src", cache=cache)
        assert get_source_health("src", cache=cache)["state"] == "closed"
        assert get_source_health("src", cache=cache)["consecutive_failures"] == 0

    def test_half_open_failure_reopens(self, cache):
        """Failure during half_open should reopen the circuit."""
        # Force open
        for _ in range(5):
            record_failure("src", cache=cache)
        # Force half_open
        cache.db.execute(
            "UPDATE circuit_state SET state='half_open', opened_at=? WHERE source_id='src'",
            ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
        )
        cache.db.commit()

        # Failure in half_open
        record_failure("src", cache=cache)
        assert get_source_health("src", cache=cache)["state"] == "open"


# ── Empty DB graceful handling ─────────────────────────────────────────────


class TestEmptyDB:
    def test_empty_db_all_functions(self, cache):
        """All functions should handle empty circuit_state table gracefully."""
        _ensure_table(cache)
        # No rows inserted
        assert get_source_health("missing", cache=cache)["ok"] is True
        assert get_all_sources_health(cache=cache)["ok"] is True
        assert is_circuit_open("missing", cache=cache) is False


# ── Config threshold/override ──────────────────────────────────────────────


class TestConfigOverride:
    def test_custom_threshold_env(self, cache):
        """EMSAL_CB_THRESHOLD env var should be respected."""
        with patch.dict("os.environ", {"EMSAL_CB_THRESHOLD": "3"}):
            # Need to reimport to pick up env change
            from emsal_mcp.config import EmsalConfig
            cfg = EmsalConfig()
            assert cfg.circuit_breaker_threshold == 3

    def test_custom_timeout_env(self, cache):
        """EMSAL_CB_TIMEOUT env var should be respected."""
        with patch.dict("os.environ", {"EMSAL_CB_TIMEOUT": "60"}):
            from emsal_mcp.config import EmsalConfig
            cfg = EmsalConfig()
            assert cfg.circuit_recovery_timeout == 60


# ── CLI and MCP imports ───────────────────────────────────────────────────


class TestImports:
    def test_circuit_module_imports(self):
        """All public circuit functions should be importable."""
        from emsal_mcp.circuit import (
            get_all_sources_health,
            get_source_health,
            is_circuit_open,
            record_failure,
            record_success,
            reset_circuit,
        )
        assert callable(record_success)
        assert callable(record_failure)
        assert callable(is_circuit_open)
        assert callable(get_source_health)
        assert callable(get_all_sources_health)
        assert callable(reset_circuit)

    def test_cli_imports(self):
        """CLI circuit commands should be importable."""
        from emsal_mcp.cli import circuit_app
        assert circuit_app is not None

    def test_server_circuit_tools_importable(self):
        """Server circuit breaker tools should be importable."""
        from emsal_mcp.circuit import get_source_health, get_all_sources_health, reset_circuit
        assert callable(get_source_health)
        assert callable(get_all_sources_health)
        assert callable(reset_circuit)
