"""M-71 Eval Harness Tests — retrieval metrics and evaluation runner.

Unit tests for recall_at_k / ndcg_at_k.  Integration tests with the
5-sample golden corpus seeded into cache and evaluated against
golden_queries.json.  All tests are hermetik — no live network.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.cache import Cache
from emsal_mcp.eval_metrics import (
    evaluate_search,
    evaluate_search_simple,
    ndcg_at_k,
    recall_at_k,
)
from emsal_mcp.models import ContentStatus, Document

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_QUERIES_PATH = Path(__file__).resolve().parent.parent / "eval" / "golden_queries.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_samples() -> list[dict]:
    return json.loads((FIXTURES / "sample_decisions.json").read_text(encoding="utf-8"))


def _sample_to_doc(s: dict) -> Document:
    return Document(
        source=s["source"],
        document_id=s["document_id"],
        title=s["title"],
        court=s["court"],
        chamber=s["chamber"],
        decision_date=s["decision_date"],
        esas_no=s["esas_no"],
        karar_no=s["karar_no"],
        content_status=ContentStatus.FULL_TEXT,
        full_text=s["full_text"],
        source_url=f"https://synthetic-golden.test/{s['document_id']}",
    )


def _search_local_fn(query: str, limit: int, cache):
    """Adapter: wrap cache.search_local() to match eval SearchFn signature."""
    return cache.search_local(query, limit=limit)


# ---------------------------------------------------------------------------
# Unit: recall_at_k
# ---------------------------------------------------------------------------


class TestRecallAtK:
    def test_perfect(self):
        assert recall_at_k(["a", "b", "c", "d", "e"], ["a", "b", "c"], k=5) == 1.0

    def test_partial(self):
        r = recall_at_k(["a", "b", "c", "d", "e"], ["a", "x", "y"], k=3)
        assert r == pytest.approx(1.0 / 3, abs=0.01)

    def test_zero(self):
        assert recall_at_k(["a", "b", "c"], ["x", "y", "z"], k=5) == 0.0

    def test_empty_expected(self):
        assert recall_at_k(["a", "b"], [], k=5) == 1.0

    def test_empty_predicted(self):
        assert recall_at_k([], ["a", "b"], k=5) == 0.0

    def test_k_smaller_than_list(self):
        """k=2 should only consider first 2 predicted."""
        assert recall_at_k(["a", "x", "y", "z"], ["a", "y"], k=2) == 0.5

    def test_k_larger_than_list(self):
        """k larger than predicted list uses all predictions."""
        assert recall_at_k(["a", "b"], ["a", "b", "c"], k=10) == pytest.approx(2.0 / 3, abs=0.01)


# ---------------------------------------------------------------------------
# Unit: ndcg_at_k
# ---------------------------------------------------------------------------


class TestNDCGAtK:
    def test_perfect(self):
        assert ndcg_at_k(["a", "b", "c"], ["a", "b", "c"], k=5) == 1.0

    def test_partial_order_matters(self):
        """NDCG penalizes non-ideal ordering."""
        ndcg_best = ndcg_at_k(["a", "b", "c", "x"], ["a", "b", "c"], k=3)
        ndcg_worst = ndcg_at_k(["x", "y", "z"], ["a", "b", "c"], k=3)
        assert ndcg_best == 1.0
        assert ndcg_worst == 0.0

    def test_relevant_late(self):
        """Relevant doc at position 2 vs 0 should have lower NDCG."""
        ndcg_early = ndcg_at_k(["a", "x", "y"], ["a"], k=3)
        ndcg_late = ndcg_at_k(["x", "a", "y"], ["a"], k=3)
        assert ndcg_early > ndcg_late

    def test_empty_expected(self):
        assert ndcg_at_k(["a", "b"], [], k=5) == 0.0

    def test_empty_predicted(self):
        assert ndcg_at_k([], ["a", "b"], k=5) == 0.0

    def test_ndcg_decreasing_with_rank(self):
        """Single relevant doc — NDCG should decrease as position moves down."""
        ndcg_pos0 = ndcg_at_k(["a", "x", "y", "z"], ["a"], k=4)
        ndcg_pos2 = ndcg_at_k(["x", "y", "a", "z"], ["a"], k=4)
        ndcg_pos3 = ndcg_at_k(["x", "y", "z", "a"], ["a"], k=4)
        assert ndcg_pos0 > ndcg_pos2 > ndcg_pos3


# ---------------------------------------------------------------------------
# Integration: evaluate_search with golden corpus
# ---------------------------------------------------------------------------


class TestEvaluateSearch:
    def test_evaluate_with_golden_queries_and_samples(self):
        """Seed samples, run eval, verify per-query metrics and aggregate."""
        samples = _load_samples()
        queries = json.loads(GOLDEN_QUERIES_PATH.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "eval_test.sqlite3"
            cache = Cache(path=cache_path)
            try:
                # Seed all 5 sample decisions
                for s in samples:
                    doc = _sample_to_doc(s)
                    cache.store_document(doc)

                # Run evaluation against golden queries
                result = evaluate_search(
                    search_fn=_search_local_fn,
                    golden_path=GOLDEN_QUERIES_PATH,
                    k_default=5,
                    cache=cache,
                )

                # Top-level structure
                assert "ok" in result
                assert "query_count" in result
                assert result["query_count"] == len(queries)
                assert "metrics" in result
                assert "per_query" in result
                assert len(result["per_query"]) == len(queries)

                # Metrics keys
                metrics = result["metrics"]
                assert "recall_at_k" in metrics
                assert "ndcg_at_k" in metrics
                assert "pass_rate" in metrics
                assert "k_default" in metrics
                assert metrics["k_default"] == 5

                # recall_at_k should be between 0 and 1
                assert 0.0 <= metrics["recall_at_k"] <= 1.0
                assert 0.0 <= metrics["ndcg_at_k"] <= 1.0

                # Each per_query entry has required keys
                for pq in result["per_query"]:
                    assert "query" in pq
                    assert "expected_ids" in pq
                    assert "predicted_ids" in pq
                    assert "recall_at_k" in pq
                    assert "ndcg_at_k" in pq
                    assert "k" in pq

                # Passed + failed = total
                assert result["passed"] + result["failed"] == result["query_count"]

            finally:
                cache.close()

    def test_evaluate_search_simple_wrapper(self):
        """evaluate_search_simple forwards to evaluate_search."""
        samples = _load_samples()
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "simple_test.sqlite3"
            cache = Cache(path=cache_path)
            try:
                for s in samples:
                    cache.store_document(_sample_to_doc(s))

                result = evaluate_search_simple(
                    search_fn=_search_local_fn, k=5, cache=cache
                )
                assert "ok" in result
                assert result["metrics"]["k_default"] == 5
            finally:
                cache.close()

    def test_no_golden_file_returns_error(self):
        """When no golden file exists, evaluate_search returns error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "no_golden.sqlite3"
            cache = Cache(path=cache_path)
            try:
                result = evaluate_search(
                    search_fn=_search_local_fn,
                    golden_path=Path(tmpdir) / "nonexistent.json",
                    cache=cache,
                )
                assert result["ok"] is False
                assert "errorCode" in result
                assert result["errorCode"] == "NO_GOLDEN_QUERIES"
                assert "recommended_next_steps" in result
            finally:
                cache.close()

    def test_search_fn_error_is_handled_per_query(self):
        """If one query raises, it's recorded as error but eval continues."""
        samples = _load_samples()

        def _flaky_search(query: str, limit: int, cache):
            if "fail" in query:
                raise RuntimeError("simulated failure")
            return cache.search_local(query, limit=limit)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "flaky.sqlite3"
            cache = Cache(path=cache_path)
            try:
                for s in samples:
                    cache.store_document(_sample_to_doc(s))

                # Write a small golden query set with a failing query
                flaky_queries = [
                    {
                        "query": "fail sözleşme",
                        "expected_document_ids": ["SYNTH-YT-2025-001"],
                        "description": "this will fail",
                    },
                    {
                        "query": "idari para cezası",
                        "expected_document_ids": ["SYNTH-DT-2025-002"],
                        "description": "this passes",
                    },
                ]
                flaky_path = Path(tmpdir) / "flaky_queries.json"
                flaky_path.write_text(
                    json.dumps(flaky_queries, ensure_ascii=False),
                    encoding="utf-8",
                )

                result = evaluate_search(
                    search_fn=_flaky_search,
                    golden_path=flaky_path,
                    cache=cache,
                )
                assert result["query_count"] == 2
                assert len(result["per_query"]) == 2

                # First query should have error
                err_entry = result["per_query"][0]
                assert "error" in err_entry
                assert err_entry["recall_at_k"] == 0.0
                assert err_entry["ndcg_at_k"] == 0.0

                # Second query should be normal (recall may be partial)
                ok_entry = result["per_query"][1]
                assert "error" not in ok_entry
                assert "recall_at_k" in ok_entry

            finally:
                cache.close()

    def test_eval_with_empty_cache(self):
        """Eval on empty cache should produce 0-recall results gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "empty.sqlite3"
            cache = Cache(path=cache_path)
            try:
                result = evaluate_search(
                    search_fn=_search_local_fn,
                    golden_path=GOLDEN_QUERIES_PATH,
                    cache=cache,
                )
                assert "ok" in result
                assert "per_query" in result
                # All queries should return 0 recall with empty cache
                for pq in result["per_query"]:
                    assert pq["recall_at_k"] == 0.0
            finally:
                cache.close()

    def test_eval_result_version_present(self):
        """Result dict includes version key."""
        samples = _load_samples()
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "version.sqlite3"
            cache = Cache(path=cache_path)
            try:
                for s in samples:
                    cache.store_document(_sample_to_doc(s))

                result = evaluate_search(
                    search_fn=_search_local_fn,
                    golden_path=GOLDEN_QUERIES_PATH,
                    cache=cache,
                )
                assert "version" in result
                assert result["version"] == "1.0.0"
            finally:
                cache.close()

    def test_recall_at_k_is_deterministic(self):
        """Same inputs produce identical recall values."""
        samples = _load_samples()
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "det.sqlite3"
            cache = Cache(path=cache_path)
            try:
                for s in samples:
                    cache.store_document(_sample_to_doc(s))

                r1 = evaluate_search(
                    search_fn=_search_local_fn,
                    golden_path=GOLDEN_QUERIES_PATH,
                    cache=cache,
                )
                r2 = evaluate_search(
                    search_fn=_search_local_fn,
                    golden_path=GOLDEN_QUERIES_PATH,
                    cache=cache,
                )
                assert r1["metrics"]["recall_at_k"] == r2["metrics"]["recall_at_k"]
                assert r1["metrics"]["ndcg_at_k"] == r2["metrics"]["ndcg_at_k"]
                assert r1["passed"] == r2["passed"]
            finally:
                cache.close()

    def test_eval_preserves_predicted_ids_ordering(self):
        """predicted_ids in per_query retains the order from search results."""
        samples = _load_samples()

        def _ordered_search(query: str, limit: int, cache):
            # Return a fixed, ordered set of results regardless of query
            ordered = [
                {"document_id": "SYNTH-YH-2025-005"},
                {"document_id": "SYNTH-AYM-2025-003"},
                {"document_id": "SYNTH-DT-2025-002"},
                {"document_id": "SYNTH-YT-2025-001"},
                {"document_id": "SYNTH-AH-2025-004"},
            ][:limit]
            return ordered

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "order.sqlite3"
            cache = Cache(path=cache_path)
            try:
                for s in samples:
                    cache.store_document(_sample_to_doc(s))

                result = evaluate_search(
                    search_fn=_ordered_search,
                    golden_path=GOLDEN_QUERIES_PATH,
                    cache=cache,
                )
                # First golden query has k=3, so predicted_ids is truncated to 3
                pq = result["per_query"][0]
                assert pq["k"] == 3
                assert pq["predicted_ids"] == [
                    "SYNTH-YH-2025-005",
                    "SYNTH-AYM-2025-003",
                    "SYNTH-DT-2025-002",
                ]
            finally:
                cache.close()

    def test_golden_queries_file_is_valid(self):
        """Golden queries file loads as valid JSON with required keys."""
        queries = json.loads(GOLDEN_QUERIES_PATH.read_text(encoding="utf-8"))
        assert isinstance(queries, list)
        assert len(queries) > 0
        for q in queries:
            assert "query" in q
            assert "expected_document_ids" in q
            assert isinstance(q["expected_document_ids"], list)
            assert len(q["expected_document_ids"]) > 0
            assert "description" in q

    def test_all_expected_ids_exist_in_samples(self):
        """Every expected_document_id in golden queries exists in sample corpus."""
        samples = _load_samples()
        all_sample_ids = {s["document_id"] for s in samples}
        queries = json.loads(GOLDEN_QUERIES_PATH.read_text(encoding="utf-8"))
        for q in queries:
            for eid in q["expected_document_ids"]:
                assert eid in all_sample_ids, (
                    f"Expected id '{eid}' in query '{q['query']}' "
                    f"not found in sample corpus: {all_sample_ids}"
                )
