"""M-71: Eval harness tests — recall@k, nDCG@k, evaluation runner."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

from emsal_mcp.eval_metrics import (
    evaluate_search,
    ndcg_at_k,
    recall_at_k,
)


# ── recall_at_k ──────────────────────────────────────────────────────────────

class TestRecallAtK:
    def test_all_found(self) -> None:
        assert recall_at_k(["a", "b", "c"], ["a", "b"], k=3) == 1.0

    def test_some_found(self) -> None:
        assert recall_at_k(["a", "x", "y"], ["a", "b"], k=3) == 0.5

    def test_none_found(self) -> None:
        assert recall_at_k(["x", "y"], ["a", "b"], k=3) == 0.0

    def test_k_cutoff(self) -> None:
        """Only top-k are considered."""
        assert recall_at_k(["x", "a"], ["a"], k=1) == 0.0

    def test_empty_expected(self) -> None:
        assert recall_at_k(["a", "b"], [], k=3) == 1.0

    def test_empty_predicted(self) -> None:
        assert recall_at_k([], ["a"], k=3) == 0.0


# ── ndcg_at_k ────────────────────────────────────────────────────────────────

class TestNdcgAtK:
    def test_perfect(self) -> None:
        assert ndcg_at_k(["a", "b"], ["a", "b"], k=2) == 1.0

    def test_reversed(self) -> None:
        """With binary relevance, order of equally-relevant items doesn't change nDCG."""
        perfect = ndcg_at_k(["a", "b"], ["a", "b"], k=2)
        reversed_order = ndcg_at_k(["b", "a"], ["a", "b"], k=2)
        # Both are 1.0 because both items are equally relevant (binary)
        assert perfect == 1.0
        assert reversed_order == perfect

    def test_no_match(self) -> None:
        assert ndcg_at_k(["x", "y"], ["a", "b"], k=2) == 0.0

    def test_empty_expected(self) -> None:
        assert ndcg_at_k(["a"], [], k=5) == 0.0

    def test_empty_predicted(self) -> None:
        assert ndcg_at_k([], ["a"], k=5) == 0.0


# ── evaluate_search ──────────────────────────────────────────────────────────

class TestEvaluateSearch:
    def _make_golden_file(self, queries: list[dict]) -> Path:
        tmp = tempfile.mktemp(suffix=".json")
        Path(tmp).write_text(json.dumps(queries), encoding="utf-8")
        return Path(tmp)

    def _fake_search(self, query: str, limit: int = 10, cache=None) -> dict:
        """Fake search that returns a known set filtered by query keyword."""
        all_docs = {
            "a": {"document_id": "doc-a", "title": "Doc A"},
            "b": {"document_id": "doc-b", "title": "Doc B"},
            "c": {"document_id": "doc-c", "title": "Doc C"},
        }
        results = [v for k, v in all_docs.items() if k in query]
        return {"ok": True, "results": results[:limit]}

    def test_basic_evaluation(self) -> None:
        queries = [
            {"query": "a b", "expected_document_ids": ["doc-a", "doc-b"]},
            {"query": "b", "expected_document_ids": ["doc-b"]},
        ]
        golden = self._make_golden_file(queries)
        result = evaluate_search(self._fake_search, golden_path=golden, k_default=3)
        assert result["ok"] is True
        assert result["query_count"] == 2
        assert result["passed"] == 2
        assert result["metrics"]["recall_at_k"] == 1.0

    def test_random_search_fails(self) -> None:
        queries = [
            {"query": "x y z", "expected_document_ids": ["doc-a", "doc-b"]},
        ]
        golden = self._make_golden_file(queries)
        result = evaluate_search(self._fake_search, golden_path=golden, k_default=3)
        assert result["ok"] is False  # below 0.3 recall threshold

    def test_no_golden_file(self) -> None:
        result = evaluate_search(self._fake_search, golden_path="/nonexistent/path.json")
        assert result["ok"] is False

    def test_empty_golden_file(self) -> None:
        golden = self._make_golden_file([])
        result = evaluate_search(self._fake_search, golden_path=golden)
        assert result["ok"] is False

    def test_passed_failed_counts(self) -> None:
        queries = [
            {"query": "a", "expected_document_ids": ["doc-a"]},  # will pass (recall 1.0)
            {"query": "x", "expected_document_ids": ["doc-a"]},  # will fail (recall 0.0)
        ]
        golden = self._make_golden_file(queries)
        result = evaluate_search(self._fake_search, golden_path=golden)
        assert result["passed"] == 1
        assert result["failed"] == 1

    def test_per_query_detail(self) -> None:
        queries = [
            {"query": "a", "expected_document_ids": ["doc-a"], "description": "test A"},
        ]
        golden = self._make_golden_file(queries)
        result = evaluate_search(self._fake_search, golden_path=golden)
        assert len(result["per_query"]) == 1
        assert result["per_query"][0]["description"] == "test A"

    def test_custom_k(self) -> None:
        queries = [
            {"query": "a", "expected_document_ids": ["doc-a"], "k": 1},
        ]
        golden = self._make_golden_file(queries)
        result = evaluate_search(self._fake_search, golden_path=golden, k_default=10)
        assert result["per_query"][0]["k"] == 1


# ── Imports ──────────────────────────────────────────────────────────────────

class TestEvalImports:
    def test_cli_import(self) -> None:
        from emsal_mcp.cli import app  # noqa: F401

    def test_server_import(self) -> None:
        from emsal_mcp.server import main  # noqa: F401

    def test_eval_module_import(self) -> None:
        from emsal_mcp.eval_metrics import EVAL_VERSION
        assert EVAL_VERSION == "1.0.0"
