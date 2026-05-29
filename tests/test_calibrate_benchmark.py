"""Tests for calibrate (M-30) and benchmark (M-31) modules."""
from __future__ import annotations

import json


class TestCalibrate:
    """Tests for calibrate.py."""

    def test_import(self) -> None:
        from emsal_mcp.calibrate import calibrate_source, calibrate_all
        assert callable(calibrate_source)
        assert callable(calibrate_all)

    def test_calibrate_unknown_source(self) -> None:
        from emsal_mcp.calibrate import calibrate_source
        result = calibrate_source("nonexistent_source")
        assert result["ok"] is False
        assert "SOURCE_NOT_FOUND" in result.get("errorCode", "")

    def test_calibrate_offline(self) -> None:
        """Offline calibration does smoke check without HTTP calls."""
        from emsal_mcp.calibrate import calibrate_source
        result = calibrate_source("bedesten", online=False)
        assert result["ok"] is True
        assert result["source_id"] == "bedesten"
        assert result["online_tested"] is False

    def test_calibrate_all(self) -> None:
        from emsal_mcp.calibrate import calibrate_all
        result = calibrate_all(online=False)
        assert result["ok"] is True
        assert "results" in result
        assert "summary" in result


class TestBenchmark:
    """Tests for benchmark.py."""

    def test_import(self) -> None:
        from emsal_mcp.benchmark import run_benchmarks
        assert callable(run_benchmarks)

    def test_run_small_benchmark(self) -> None:
        """Run benchmark with tiny corpus — should complete without error."""
        from emsal_mcp.benchmark import run_benchmarks
        result = run_benchmarks(corpus_size=5)
        assert result["ok"] is True
        assert "benchmarks" in result
        assert "corpus_creation" in result["benchmarks"]
        assert "build_semantic_index" in result["benchmarks"]
        assert "build_embedding_index" in result["benchmarks"]

    def test_benchmark_json_serializable(self) -> None:
        """Benchmark result is JSON-serializable."""
        from emsal_mcp.benchmark import run_benchmarks
        result = run_benchmarks(corpus_size=3)
        json.dumps(result)


class TestCLIImports:
    """CLI imports for new commands."""

    def test_calibrate_app(self) -> None:
        from emsal_mcp.cli import calibrate_app
        assert calibrate_app is not None
