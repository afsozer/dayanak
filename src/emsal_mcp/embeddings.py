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
    Model: sentence-transformers/all-MiniLM-L6-v2
    """

    id = "fastembed-minilm-l6-v2"
    dimensions = 384

    _MAX_TEXT_CHARS = 8000
    _BATCH_SIZE = 16

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = cache_dir
        self._model: object | None = None

    def _get_model(self) -> object:
        if self._model is None:
            try:
                from fastembed import TextEmbedding  # type: ignore[import-untyped]

                kwargs: dict = {}
                if self._cache_dir:
                    kwargs["cache_dir"] = self._cache_dir
                self._model = TextEmbedding(
                    model_name="sentence-transformers/all-MiniLM-L6-v2",
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
            for emb in model.embed(batch):
                embeddings.append(emb.tolist())
        return embeddings


# ---------------------------------------------------------------------------
# Provider Factory
# ---------------------------------------------------------------------------

def get_embedding_provider(provider: str | None = None) -> EmbeddingProvider | None:
    """Factory: provider arg > EMSAL_EMBEDDING_PROVIDER env > default local-hash-v1.

    Returns EmbeddingProvider instance.
    Returns None if provider is invalid or unavailable (caller handles graceful).
    """
    resolved = provider or os.environ.get("EMSAL_EMBEDDING_PROVIDER", "local-hash-v1")

    if resolved == "local-hash-v1":
        return LocalHashProvider()
    elif resolved in ("fastembed-minilm-l6-v2", "fastembed"):
        try:
            from .config import config

            cache_dir = str(config.embedding_cache_dir) if config.embedding_cache_dir else None
            return FastEmbedProvider(cache_dir=cache_dir)
        except RuntimeError:
            return None  # fastembed not installed
    else:
        return None  # unknown provider


def list_embedding_providers() -> list[dict]:
    """Return metadata for all known providers."""
    providers: list[dict] = [
        {
            "id": "local-hash-v1",
            "dimensions": 128,
            "label": "Local Hash Provider",
            "status": "available",
            "is_default": True,
            "needs_download": False,
        },
    ]

    fastembed_available = False
    try:
        import fastembed  # noqa: F401  # type: ignore[import-untyped]

        fastembed_available = True
    except ImportError:
        pass

    providers.append(
        {
            "id": "fastembed-minilm-l6-v2",
            "dimensions": 384,
            "label": "FastEmbed MiniLM L6 v2",
            "status": "available" if fastembed_available else "unavailable",
            "is_default": False,
            "needs_download": True,
            "model": "sentence-transformers/all-MiniLM-L6-v2",
        }
    )

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
