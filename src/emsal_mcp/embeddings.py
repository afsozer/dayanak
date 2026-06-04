"""Emsal-mcp Dense Embedding Providers - v2.1

Pluggable embedding provider architecture ported from local-yargi.
Core provider (LocalHashProvider) is always available; optional
FastEmbedProvider requires ``pip install emsal-mcp[embeddings]``.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import struct
from abc import ABC, abstractmethod
from typing import Any

EMBEDDING_VERSION = "2.1.0"


# ---------------------------------------------------------------------------
# Abstract Interface
# ---------------------------------------------------------------------------

class EmbeddingProvider(ABC):
    """Abstract interface for text embedding providers."""

    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...

    @abstractmethod
    def embed_text(self, text: str) -> list[float]: ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


# ---------------------------------------------------------------------------
# LocalHashProvider  (core-only, zero deps)
# ---------------------------------------------------------------------------

class LocalHashProvider(EmbeddingProvider):
    """Deterministic hash-based embedding — no model download, pure stdlib.

    Ported from local-yargi LocalEmbeddingProvider.
    ID: local-hash-v1, Dims: 128
    """

    id = "local-hash-v1"
    dimensions = 128

    def embed_text(self, text: str) -> list[float]:
        return self._hash_embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        # 1. Tokenize: lowercase, strip diacritics-ish, split on non-alpha
        text = text.lower().strip()
        tokens = re.findall(r'\b\w{2,}\b', text, re.UNICODE)
        if not tokens:
            return self._l2_normalize([0.0] * self.dimensions)

        vec = [0.0] * self.dimensions

        for token in tokens:
            # Full token: weight 1.5
            self._add_token_to_vec(vec, token, 1.5)

            # Trigrams for tokens >= 5 chars: weight 0.35 each
            if len(token) >= 5:
                for i in range(len(token) - 2):
                    self._add_token_to_vec(vec, token[i : i + 3], 0.35)

        return self._l2_normalize(vec)

    def _add_token_to_vec(self, vec: list[float], token: str, weight: float) -> None:
        h = hashlib.sha256(token.encode()).digest()
        idx = int.from_bytes(h[:4], "big") % self.dimensions
        sign = 1.0 if (h[4] % 2 == 0) else -1.0
        vec[idx] += sign * weight

    def _l2_normalize(self, vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            return [v / norm for v in vec]
        return vec


# ---------------------------------------------------------------------------
# FastEmbedProvider  (optional, lazy-import)
# ---------------------------------------------------------------------------

class FastEmbedProvider(EmbeddingProvider):
    """Optional fastembed-based embedding provider.

    Lazy-imports fastembed. If not installed, raises RuntimeError on first use.
    ID: fastembed-minilm-l6-v2, Dims: 384
    Model: sentence-transformers/all-MiniLM-L6-v2 (English-optimized)
    """

    id = "fastembed-minilm-l6-v2"
    dimensions = 384

    _MAX_TEXT_CHARS = 8000
    _BATCH_SIZE = 16
    _MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = cache_dir
        self._model: object | None = None

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from fastembed import TextEmbedding  # type: ignore[import-untyped]

                kwargs: dict = {}
                if self._cache_dir:
                    kwargs["cache_dir"] = self._cache_dir
                self._model = TextEmbedding(
                    model_name=self._MODEL_NAME,
                    **kwargs,
                )
            except ImportError:
                raise RuntimeError(
                    "fastembed not installed. Run: pip install fastembed"
                )
        return self._model

    def _normalize(self, text: str) -> str:
        text = " ".join(text.split())
        return text[: self._MAX_TEXT_CHARS] if len(text) > self._MAX_TEXT_CHARS else text

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        normalized = [self._normalize(t) or " " for t in texts]
        embeddings: list[list[float]] = []
        for i in range(0, len(normalized), self._BATCH_SIZE):
            batch = normalized[i : i + self._BATCH_SIZE]
            for emb in model.embed(batch):  # type: ignore[attr-defined]
                embeddings.append(emb.tolist())
        return embeddings


# ── M-95: Multilingual provider (Turkish-native, 100+ languages) ─────


class FastEmbedMultilingualProvider(FastEmbedProvider):
    """Fastembed multilingual provider — Turkish-native model (M-95).

    Uses ``intfloat/multilingual-e5-small`` which supports 100+ languages
    including Turkish with proper tokenization.  Same dimensions (384) as
    MiniLM, so drop-in compatible with existing indices.

    ID: fastembed-multilingual-e5, Dims: 384
    Model: intfloat/multilingual-e5-small

    Gracefully falls back to ``LocalHashProvider`` when ``fastembed`` is
    not installed (invariant #6 — core stdlib+sqlite3 preserved).
    """

    id = "fastembed-multilingual-e5"
    dimensions = 384
    _MODEL_NAME = "intfloat/multilingual-e5-small"

    # E5 prefix: prepend "query: " for queries and "passage: " for docs
    # to signal the model whether the text is a query or document.
    _QUERY_PREFIX = "query: "
    _DOC_PREFIX = "passage: "

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query with the E5 query prefix."""
        return self.embed_text(self._QUERY_PREFIX + text)

    def embed_document(self, text: str) -> list[float]:
        """Embed a document/passage with the E5 passage prefix."""
        return self.embed_text(self._DOC_PREFIX + text)

    def embed_documents_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents with the passage prefix."""
        prefixed = [self._DOC_PREFIX + self._normalize(t) for t in texts]
        return self.embed_batch(prefixed)

    def embed_queries_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of queries with the query prefix."""
        prefixed = [self._QUERY_PREFIX + self._normalize(t) for t in texts]
        return self.embed_batch(prefixed)


# ---------------------------------------------------------------------------
# Provider Factory
# ---------------------------------------------------------------------------

def get_embedding_provider(
    provider: str | None = None,
    *,
    strict: bool = False,
) -> EmbeddingProvider | None:
    """Factory: provider arg > EMSAL_EMBEDDING_PROVIDER env > default.

    Priority:
    1. Explicit ``provider`` argument
    2. ``EMSAL_EMBEDDING_PROVIDER`` environment variable
    3. ``EMSAL_EMBEDDING_PROVIDER`` config
    4. Default: ``local-hash-v1`` (always available, zero deps)

    If ``strict=True``, returns None when the requested provider is
    unavailable.  If ``strict=False`` (default), falls back to
    ``local-hash-v1`` when the requested provider is unavailable — the
    caller always gets *some* provider back (graceful degradation).

    Returns:
        EmbeddingProvider instance, or None only if strict=True and
        the requested provider is truly unavailable.
    """
    resolved = provider or os.environ.get("EMSAL_EMBEDDING_PROVIDER", "local-hash-v1")

    # ── Built-in providers ──────────────────────────────────────
    if resolved == "local-hash-v1":
        return LocalHashProvider()

    # ── fastembed-based providers ───────────────────────────────
    if resolved in ("fastembed-minilm-l6-v2", "fastembed"):
        try:
            from .config import config

            cache_dir = str(config.embedding_cache_dir) if config.embedding_cache_dir else None
            return FastEmbedProvider(cache_dir=cache_dir)
        except RuntimeError:
            if strict:
                return None
            return LocalHashProvider()

    if resolved in ("fastembed-multilingual-e5", "fastembed-multilingual", "fastembed-turkish"):
        try:
            from .config import config

            cache_dir = str(config.embedding_cache_dir) if config.embedding_cache_dir else None
            return FastEmbedMultilingualProvider(cache_dir=cache_dir)
        except RuntimeError:
            if strict:
                return None
            return LocalHashProvider()

    # ── Unknown provider ────────────────────────────────────────
    if strict:
        return None
    return LocalHashProvider()


def list_embedding_providers() -> list[dict]:
    """Return metadata for all known providers."""
    fastembed_available = False
    try:
        import fastembed  # noqa: F401  # type: ignore[import-untyped]

        fastembed_available = True
    except ImportError:
        pass

    providers: list[dict] = [
        {
            "id": "local-hash-v1",
            "dimensions": 128,
            "label": "Local Hash Provider (always available)",
            "description": "Deterministic hash-based embeddings — no model download, pure stdlib. Suitable for exact-match recall, not semantic search.",
            "status": "available",
            "is_default": True,
            "needs_download": False,
            "languages": ["any"],
        },
        {
            "id": "fastembed-minilm-l6-v2",
            "dimensions": 384,
            "label": "FastEmbed MiniLM L6 v2 (English)",
            "description": "English-optimized sentence embeddings via fastembed. Requires pip install emsal-mcp[embeddings].",
            "status": "available" if fastembed_available else "unavailable",
            "is_default": False,
            "needs_download": True,
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "languages": ["en"],
        },
        {
            "id": "fastembed-multilingual-e5",
            "dimensions": 384,
            "label": "FastEmbed Multilingual E5 Small (Turkish+100 langs, M-95)",
            "description": "Turkish-native sentence embeddings via fastembed. Supports 100+ languages including full Turkish morphology. Requires pip install emsal-mcp[embeddings]. Recommended for Turkish legal text.",
            "status": "available" if fastembed_available else "unavailable",
            "is_default": False,
            "needs_download": True,
            "model": "intfloat/multilingual-e5-small",
            "languages": ["tr", "en", "fr", "de", "es", "ar", "zh", "ja", "ko", "+90 more"],
        },
    ]

    # Mark the selected/default
    default_id = os.environ.get("EMSAL_EMBEDDING_PROVIDER", "local-hash-v1")
    for p in providers:
        p["selected"] = p["id"] == default_id

    return providers


# ---------------------------------------------------------------------------
# BLOB helpers for vector storage
# ---------------------------------------------------------------------------

def pack_vector(vec: list[float]) -> bytes:
    """Pack float32 vector into BLOB for SQLite storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vector(blob: bytes, dim: int) -> list[float]:
    """Unpack BLOB back to float32 vector."""
    return list(struct.unpack(f"{dim}f", blob[: dim * 4]))


# ---------------------------------------------------------------------------
# Cross-Encoder Reranker (M-25)
# ---------------------------------------------------------------------------


def rerank_results(
    query: str,
    candidates: list[dict],
    top_k: int = 10,
    provider: str | None = None,
) -> dict:
    """Re-rank candidates using cross-encoder if available.

    If cross-encoder is not available, returns original candidates as-is
    with a warning.  Never raises an exception.

    Args:
        query: Original search query.
        candidates: List of {document_id, source, title, score, text_preview...}.
        top_k: Number of top results to return after reranking.
        provider: Embedding provider (unused, kept for interface consistency).

    Returns:
        dict with ok, results (reranked), was_reranked: bool, method, warnings.
    """
    warnings: list[str] = []

    # Try lazy import cross-encoder
    reranker_available = False
    try:
        from fastembed import TextCrossEncoder  # type: ignore[import-untyped]

        reranker_available = True
    except ImportError:
        warnings.append("Cross-encoder not available (install fastembed for reranking)")

    if not reranker_available or len(candidates) == 0:
        return {
            "ok": True,
            "results": candidates[:top_k],
            "was_reranked": False,
            "method": "passthrough",
            "warnings": warnings,
        }

    # Build query-document pairs for cross-encoder
    pairs: list[list[str]] = []
    for c in candidates[: max(20, top_k * 2)]:
        doc_text = c.get("text_preview", "") or c.get("snippet", "") or c.get("title", "")
        pairs.append([query, doc_text])

    try:
        model = TextCrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        scores = model.predict(pairs)

        # Map scores back to candidates
        for i, (c, score) in enumerate(zip(candidates[: len(pairs)], scores)):
            c["rerank_score"] = float(score)

        # Re-sort by rerank score
        reranked = sorted(
            candidates[: len(pairs)],
            key=lambda x: x.get("rerank_score", 0),
            reverse=True,
        )

        return {
            "ok": True,
            "results": reranked[:top_k],
            "was_reranked": True,
            "method": "cross-encoder",
            "warnings": warnings,
        }
    except Exception as e:
        warnings.append(f"Reranking failed: {e}")
        return {
            "ok": True,
            "results": candidates[:top_k],
            "was_reranked": False,
            "method": "passthrough",
            "warnings": warnings,
        }


def heuristic_rerank(
    candidates: list[dict],
    top_k: int = 10,
    *,
    citation_safe_boost: float = 0.05,
    recency_weight: float = 0.02,
) -> dict:
    """Re-rank candidates with deterministic citation-safety and recency signals (M-72).

    Each candidate receives bonus points for:
    - ``quote_usable`` / ``draft_usable`` (citation safety signal)
    - More recent ``decision_date`` (recency signal, ISO YYYY-MM-DD format)

    Boost values are configurable — default adds up to 0.07 to the score.
    The boost is additive and deterministic — never replaces the base score.
    No model download required. Always available, never raises.

    Args:
        candidates: List of {document_id, source, title, score, quote_usable,
                    draft_usable, decision_date, ...}.
        top_k: Number of top results to return.
        citation_safe_boost: Score added when quote_usable or draft_usable is True.
        recency_weight: Continuous recency multiplier with 5-year half-life.

    Returns:
        Dict with ok, results (with heuristic_score), method, boosted.
    """
    import datetime as _dt

    if not candidates:
        return {"ok": True, "results": [], "method": "heuristic", "boosted": 0}

    now = _dt.date.today()
    boosted = 0

    for c in candidates:
        base = float(c.get("score", 0.0) or c.get("hybrid_score", 0.0) or 0.0)
        bonus = 0.0

        # Citation-safe boost
        if c.get("quote_usable") or c.get("draft_usable"):
            bonus += citation_safe_boost
            boosted += 1

        # Recency boost — newer decisions get higher bonus
        date_str = c.get("decision_date") or ""
        try:
            if len(date_str) >= 10:
                d = _dt.date.fromisoformat(date_str[:10])
                days_ago = max(0, (now - d).days)
                # Map days_ago to [0, 1] with 5-year (1825 day) half-life
                recency = 1.0 / (1.0 + days_ago / 1825.0)
                bonus += recency_weight * recency
        except (ValueError, TypeError):
            pass

        c["heuristic_boost"] = round(bonus, 4)
        c["heuristic_score"] = round(base + bonus, 6)

    # Sort by heuristic score descending
    reranked = sorted(candidates, key=lambda x: x.get("heuristic_score", 0), reverse=True)

    return {
        "ok": True,
        "results": reranked[:top_k],
        "method": "heuristic",
        "boosted": boosted,
    }
