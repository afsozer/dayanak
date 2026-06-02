"""Retrieval evaluation metrics — M-71 eval harness.

Provides recall@k, nDCG@k, and an evaluation runner that scores
a search function against a golden query set.  All metrics are
deterministic and hermetik — no live network, no model download.

Usage:
    from emsal_mcp.eval_metrics import evaluate_search, recall_at_k, ndcg_at_k

    results = evaluate_search(search_fn, golden_queries, k=5)
    print(results["recall_at_5"])
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

EVAL_VERSION = "1.0.0"

# ── Core metrics ─────────────────────────────────────────────────────────────


def recall_at_k(predicted_ids: list[str], expected_ids: list[str], k: int = 5) -> float:
    """Recall@k: fraction of expected docs found in top-k predictions.

    Args:
        predicted_ids: Ordered list of document_ids returned by search.
        expected_ids: Set of relevant document_ids.
        k: Cutoff rank (default 5).

    Returns:
        Float in [0.0, 1.0].  1.0 = all expected docs in top-k.
    """
    if not expected_ids:
        return 1.0
    predicted_set = set(predicted_ids[:k])
    expected_set = set(expected_ids)
    return len(predicted_set & expected_set) / len(expected_set)


def ndcg_at_k(predicted_ids: list[str], expected_ids: list[str], k: int = 5) -> float:
    """Normalized Discounted Cumulative Gain at rank k.

    Uses binary relevance (1 if in expected, 0 otherwise).

    Args:
        predicted_ids: Ordered list of document_ids.
        expected_ids: Set of relevant document_ids.
        k: Cutoff rank.

    Returns:
        Float in [0.0, 1.0].  1.0 = ideal ranking.
    """
    if not expected_ids or not predicted_ids:
        return 0.0
    expected_set = set(expected_ids)

    # DCG: relevance[i] / log2(i+2)  (i is 0-based position)
    dcg = 0.0
    idcg = 0.0
    for i in range(min(k, len(predicted_ids))):
        rel = 1.0 if predicted_ids[i] in expected_set else 0.0
        dcg += rel / math.log2(i + 2)

    # IDCG: ideal ranking (all relevant docs at top)
    ideal_count = min(k, len(expected_set))
    for i in range(ideal_count):
        idcg += 1.0 / math.log2(i + 2)

    return dcg / idcg if idcg > 0 else 0.0


# ── Evaluation runner ────────────────────────────────────────────────────────

SearchFn = Callable[..., dict[str, Any]]
"""A search function with the signature: fn(query, limit=N, cache=...) -> dict."""


def _load_golden_queries(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load golden query set from JSON file.

    Each entry:
        {
            "query": "search text",
            "expected_document_ids": ["doc-1", "doc-2", ...],
            "description": "what this query tests",
            "k": 5  # optional, defaults to 5
        }
    """
    if path is None:
        # eval_metrics.py is at src/emsal_mcp/ — go up 3 levels to project root
        path = Path(__file__).resolve().parent.parent.parent / "eval" / "golden_queries.json"
    else:
        path = Path(path)
    if not path.exists():
        return []
    data: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def evaluate_search(
    search_fn: SearchFn,
    golden_path: str | Path | None = None,
    k_default: int = 5,
    cache: Any | None = None,
) -> dict[str, Any]:
    """Evaluate a search function against the golden query set.

    Args:
        search_fn: Callable with signature ``fn(query, limit=N, cache=c) -> dict``.
                   The dict must have a ``"results"`` key containing a list of
                   dicts with a ``"document_id"`` field.
        golden_path: Path to golden_queries.json (defaults to eval/golden_queries.json).
        k_default: Default cutoff rank for queries that don't specify one.
        cache: Optional Cache instance passed to search_fn.

    Returns:
        Dict with ok, query_count, metrics (aggregate), per_query (per-query detail).
    """
    from .models import build_error

    queries = _load_golden_queries(golden_path)
    if not queries:
        return build_error(
            "NO_GOLDEN_QUERIES",
            "No golden queries found. Create eval/golden_queries.json.",
            recommended_next_steps=["Create eval/golden_queries.json with query definitions."],
        )

    per_query: list[dict[str, Any]] = []
    recall_sum = 0.0
    ndcg_sum = 0.0
    passed = 0

    for q in queries:
        query_text = q["query"]
        expected = q["expected_document_ids"]
        k = q.get("k", k_default)

        try:
            result = search_fn(query=query_text, limit=k * 2, cache=cache)  # fetch more for eval
        except Exception as exc:
            per_query.append({
                "query": query_text,
                "error": str(exc),
                "recall_at_k": 0.0,
                "ndcg_at_k": 0.0,
                "k": k,
            })
            continue

        preds = result.get("results", []) if isinstance(result, dict) else result
        if not isinstance(preds, list):
            per_query.append({
                "query": query_text,
                "error": "search_fn returned unexpected format",
                "recall_at_k": 0.0,
                "ndcg_at_k": 0.0,
                "k": k,
            })
            continue

        pred_ids = [p.get("document_id", "") for p in preds]

        rec = recall_at_k(pred_ids, expected, k)
        ndcg = ndcg_at_k(pred_ids, expected, k)
        recall_sum += rec
        ndcg_sum += ndcg
        if rec >= 0.5:
            passed += 1

        per_query.append({
            "query": query_text,
            "description": q.get("description", ""),
            "expected_ids": expected,
            "predicted_ids": pred_ids[:k],
            "recall_at_k": round(rec, 4),
            "ndcg_at_k": round(ndcg, 4),
            "k": k,
        })

    total = len(queries)
    recall_avg = round(recall_sum / total, 4) if total > 0 else 0.0
    ndcg_avg = round(ndcg_sum / total, 4) if total > 0 else 0.0
    pass_rate = round(passed / total, 4) if total > 0 else 0.0

    return {
        "ok": recall_avg >= 0.3,  # gate: at least 30% average recall
        "query_count": total,
        "passed": passed,
        "failed": total - passed,
        "metrics": {
            "recall_at_k": recall_avg,
            "ndcg_at_k": ndcg_avg,
            "pass_rate": pass_rate,
            "k_default": k_default,
        },
        "per_query": per_query,
        "version": EVAL_VERSION,
    }


def evaluate_search_simple(
    search_fn: SearchFn,
    k: int = 5,
    cache: Any | None = None,
) -> dict[str, Any]:
    """Convenience wrapper — same as evaluate_search with defaults."""
    return evaluate_search(search_fn=search_fn, k_default=k, cache=cache)
