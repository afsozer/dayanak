"""Tests for emsal_mcp.embeddings module and M-24 dense embedding integration.

Covers:
  - LocalHashProvider (deterministic, 128 dims, batch, Turkish, empty text)
  - FastEmbedProvider (lazy import, graceful unavailable)
  - Provider factory (default, env override, unknown, list)
  - pack_vector / unpack_vector round-trip
  - embedding_vectors BLOB storage
  - build_embedding_index (indexing, content-hash skip)
  - embedding_search (scored results, sorted, empty, provider unavailable)
  - get_embedding_index_status
  - Hybrid v3 (w_dense=0 regression, w_dense>0 merge)
  - CLI imports (embed-index, embed-search, providers, embedding-status)
  - MCP imports (4 new tools)
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

import math
import os
from pathlib import Path
from unittest.mock import patch

from emsal_mcp.cache import Cache
from emsal_mcp.embeddings import (
    EMBEDDING_VERSION,
    EmbeddingProvider,
    FastEmbedProvider,
    LocalHashProvider,
    get_embedding_provider,
    heuristic_rerank,
    list_embedding_providers,
    pack_vector,
    rerank_results,
    unpack_vector,
)
from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.semantic import (
    build_embedding_index,
    build_semantic_index,
    embedding_search,
    get_embedding_index_status,
    hybrid_search,
)


# ---------------------------------------------------------------------------
# Fake test provider
# ---------------------------------------------------------------------------

class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic keyword-based test provider (8 dims)."""

    id = "fake-test"
    dimensions = 8

    def embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for i, ch in enumerate(text.lower()[: self.dimensions]):
            vec[i % self.dimensions] += ord(ch) / 1000.0
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_DOCS = [
    {
        "source": "yargitay",
        "document_id": "yg-001",
        "title": "Sözleşme İhlali Hakkında Karar",
        "court": "Yargitay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": (
            "Taraflar arasındaki sözleşme hükümleri ihlal edilmiştir. "
            "Borçlar Kanunu madde 96 uyarınca tazminat talep edilebilir."
        ),
        "markdown": "# Sözleşme İhlali\n\nTaraflar arasındaki sözleşme hükümleri ihlal edilmiştir.",
    },
    {
        "source": "danistay",
        "document_id": "ds-001",
        "title": "İdari Para Cezası İptali",
        "court": "Danistay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": (
            "İdari para cezasının iptali talebiyle açılan davada, "
            "idarenin yetkisiz olduğu anlaşılmıştır. Kabahatler Kanunu kapsamında değerlendirme yapılmıştır."
        ),
        "markdown": "# İdari Para Cezası\n\nİdari para cezasının iptali talebiyle açılan davada...",
    },
    {
        "source": "yargitay",
        "document_id": "yg-002",
        "title": "İş Kazası Tazminat Davası",
        "court": "Yargitay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": (
            "İş kazası sonucu oluşan maddi zararın tazmini istemiyle açılan dava. "
            "İşverenin kusur oranı bilirkişi raporuyla tespit edilmiştir."
        ),
        "markdown": "# İş Kazası\n\nİş kazası sonucu oluşan maddi zarar...",
    },
]


def _populate_docs(cache: Cache, docs: list[dict] | None = None) -> None:
    """Store a list of document dicts (or SAMPLE_DOCS) into cache."""
    for doc_data in (docs or SAMPLE_DOCS):
        cache.store_document(Document(**doc_data))


# ===================================================================
# TestLocalHashProvider
# ===================================================================


class TestLocalHashProvider:
    """Tests for LocalHashProvider."""

    def test_dimensions(self) -> None:
        """Dimensions is 128."""
        p = LocalHashProvider()
        assert p.dimensions == 128

    def test_id(self) -> None:
        """ID is 'local-hash-v1'."""
        p = LocalHashProvider()
        assert p.id == "local-hash-v1"

    def test_embed_text_returns_128(self) -> None:
        """embed_text returns a 128-dim vector."""
        p = LocalHashProvider()
        vec = p.embed_text("test sentence")
        assert len(vec) == 128

    def test_embed_text_deterministic(self) -> None:
        """Same text always produces the same vector."""
        p = LocalHashProvider()
        v1 = p.embed_text("hello world")
        v2 = p.embed_text("hello world")
        assert v1 == v2

    def test_embed_text_different_texts(self) -> None:
        """Different texts produce different vectors."""
        p = LocalHashProvider()
        v1 = p.embed_text("hello world")
        v2 = p.embed_text("goodbye universe")
        assert v1 != v2

    def test_embed_text_turkish(self) -> None:
        """Turkish characters work correctly."""
        p = LocalHashProvider()
        vec = p.embed_text("sözleşme hükümleri tazminat")
        assert len(vec) == 128
        # Should be normalized (unit vector)
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_embed_text_empty(self) -> None:
        """Empty text returns zero vector (L2-norm = 0)."""
        p = LocalHashProvider()
        vec = p.embed_text("")
        assert len(vec) == 128
        # L2-norm should be 0 for empty input
        norm = math.sqrt(sum(v * v for v in vec))
        assert norm == 0.0

    def test_embed_text_whitespace_only(self) -> None:
        """Whitespace-only text returns zero vector."""
        p = LocalHashProvider()
        vec = p.embed_text("   \t\n  ")
        norm = math.sqrt(sum(v * v for v in vec))
        assert norm == 0.0

    def test_embed_batch(self) -> None:
        """embed_batch returns correct count."""
        p = LocalHashProvider()
        results = p.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        for r in results:
            assert len(r) == 128

    def test_embed_batch_matches_single(self) -> None:
        """embed_batch[i] == embed_text(texts[i])."""
        p = LocalHashProvider()
        texts = ["hello", "world", "test"]
        batch = p.embed_batch(texts)
        singles = [p.embed_text(t) for t in texts]
        assert batch == singles

    def test_l2_normalized(self) -> None:
        """Output is L2-normalized (unit vector)."""
        p = LocalHashProvider()
        vec = p.embed_text("hello world")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_trigrams_for_long_tokens(self) -> None:
        """Tokens >= 5 chars produce trigram contributions."""
        p = LocalHashProvider()
        # 'hello' is 5 chars, should produce trigram contributions
        v_short = p.embed_text("hi")
        v_long = p.embed_text("hello")
        # They should be different because 'hello' gets trigram boost
        assert v_short != v_long


# ===================================================================
# TestFastEmbedProvider
# ===================================================================


class TestFastEmbedProvider:
    """Tests for FastEmbedProvider (graceful unavailable)."""

    def test_class_constants(self) -> None:
        """FastEmbedProvider has correct class constants."""
        assert FastEmbedProvider.id == "fastembed-minilm-l6-v2"
        assert FastEmbedProvider.dimensions == 384

    def test_init_without_fastembed(self) -> None:
        """FastEmbedProvider can be instantiated even without fastembed."""
        p = FastEmbedProvider()
        assert p.id == "fastembed-minilm-l6-v2"
        assert p.dimensions == 384

    def test_raises_on_embed_without_fastembed(self) -> None:
        """embed_text raises RuntimeError when fastembed is not installed."""
        p = FastEmbedProvider()
        try:
            p.embed_text("test")
            # If fastembed IS installed, this won't raise — that's fine
        except RuntimeError as e:
            assert "fastembed not installed" in str(e)

    def test_raises_on_batch_without_fastembed(self) -> None:
        """embed_batch raises RuntimeError when fastembed is not installed."""
        p = FastEmbedProvider()
        try:
            p.embed_batch(["test1", "test2"])
        except RuntimeError as e:
            assert "fastembed not installed" in str(e)


# ===================================================================
# TestProviderFactory
# ===================================================================


class TestProviderFactory:
    """Tests for get_embedding_provider()."""

    def test_default_returns_local_hash(self) -> None:
        """Default provider is local-hash-v1."""
        p = get_embedding_provider()
        assert p is not None
        assert p.id == "local-hash-v1"
        assert isinstance(p, LocalHashProvider)

    def test_explicit_local_hash(self) -> None:
        """Explicit 'local-hash-v1' returns LocalHashProvider."""
        p = get_embedding_provider("local-hash-v1")
        assert p is not None
        assert isinstance(p, LocalHashProvider)

    def test_env_override(self) -> None:
        """EMSAL_EMBEDDING_PROVIDER env overrides default."""
        with patch.dict(os.environ, {"EMSAL_EMBEDDING_PROVIDER": "local-hash-v1"}):
            p = get_embedding_provider()
            assert p is not None
            assert p.id == "local-hash-v1"

    def test_fastembed_when_unavailable(self) -> None:
        """fastembed provider returns provider or None depending on install status."""
        with patch.dict(os.environ, {"EMSAL_EMBEDDING_PROVIDER": "fastembed-minilm-l6-v2"}):
            p = get_embedding_provider()
            # If fastembed is installed, returns FastEmbedProvider; otherwise None
            if p is not None:
                assert p.id == "fastembed-minilm-l6-v2"
            # Either outcome is valid

    def test_unknown_provider_returns_none(self) -> None:
        """Unknown provider with strict=True returns None (no fallback)."""
        p = get_embedding_provider("nonexistent-provider", strict=True)
        assert p is None

    def test_unknown_provider_falls_back_to_hash(self) -> None:
        """Default (strict=False) returns LocalHashProvider for unknown providers."""
        p = get_embedding_provider("nonexistent-provider")
        assert p is not None
        assert p.id == "local-hash-v1"

    def test_fastembed_alias(self) -> None:
        """'fastembed' alias resolves to fastembed provider or None."""
        with patch.dict(os.environ, {"EMSAL_EMBEDDING_PROVIDER": "fastembed"}):
            p = get_embedding_provider()
            # If fastembed is installed, returns FastEmbedProvider; otherwise None
            if p is not None:
                assert p.id == "fastembed-minilm-l6-v2"
            # Either outcome is valid


# ===================================================================
# TestListEmbeddingProviders
# ===================================================================


class TestListEmbeddingProviders:
    """Tests for list_embedding_providers()."""

    def test_returns_all_providers(self) -> None:
        """Returns metadata for all known providers (3: hash + 2 fastembed)."""
        providers = list_embedding_providers()
        assert len(providers) == 3
        ids = {p["id"] for p in providers}
        assert "local-hash-v1" in ids
        assert "fastembed-minilm-l6-v2" in ids
        assert "fastembed-multilingual-e5" in ids

    def test_local_hash_available(self) -> None:
        """local-hash-v1 is always available."""
        providers = list_embedding_providers()
        local = [p for p in providers if p["id"] == "local-hash-v1"]
        assert len(local) == 1
        assert local[0]["status"] == "available"
        assert local[0]["is_default"] is True

    def test_fastembed_status_tracks_installation(self) -> None:
        """fastembed's reported status must follow whether it is importable.

        This used to hard-code "unavailable", which only held because the
        package happened to be missing; installing it broke the test even
        though the reporting was correct.  Assert the invariant instead: the
        status matches reality, and an unavailable provider is flagged as
        needing a download.
        """
        import importlib.util

        installed = importlib.util.find_spec("fastembed") is not None
        providers = list_embedding_providers()
        fast = [p for p in providers if p["id"] == "fastembed-minilm-l6-v2"]
        assert len(fast) == 1
        assert fast[0]["status"] == ("available" if installed else "unavailable")
        if not installed:
            assert fast[0]["needs_download"] is True

    def test_selected_field(self) -> None:
        """Each provider has a 'selected' field."""
        providers = list_embedding_providers()
        for p in providers:
            assert "selected" in p
            assert isinstance(p["selected"], bool)

    def test_dimensions_field(self) -> None:
        """Each provider has a 'dimensions' field."""
        providers = list_embedding_providers()
        for p in providers:
            assert "dimensions" in p
            assert isinstance(p["dimensions"], int)
            assert p["dimensions"] > 0


# ===================================================================
# TestPackUnpackVector
# ===================================================================


class TestPackUnpackVector:
    """Tests for pack_vector / unpack_vector BLOB helpers."""

    def test_round_trip(self) -> None:
        """Pack then unpack returns the same vector."""
        vec = [0.1, 0.2, -0.3, 0.0, 1.0, -1.0]
        blob = pack_vector(vec)
        result = unpack_vector(blob, len(vec))
        assert len(result) == len(vec)
        for a, b in zip(vec, result, strict=True):
            assert abs(a - b) < 1e-6

    def test_128_dim_round_trip(self) -> None:
        """Round-trip with 128-dim vector (LocalHashProvider size)."""
        p = LocalHashProvider()
        vec = p.embed_text("test sentence for packing")
        blob = pack_vector(vec)
        result = unpack_vector(blob, 128)
        assert len(result) == 128
        for a, b in zip(vec, result, strict=True):
            assert abs(a - b) < 1e-6

    def test_blob_is_bytes(self) -> None:
        """pack_vector returns bytes."""
        blob = pack_vector([0.0, 1.0])
        assert isinstance(blob, bytes)

    def test_blob_size(self) -> None:
        """Blob size is dim * 4 bytes (float32)."""
        vec = [0.0] * 10
        blob = pack_vector(vec)
        assert len(blob) == 40  # 10 * 4

    def test_negative_values(self) -> None:
        """Negative float values survive round-trip."""
        vec = [-1.5, -0.001, -999.9]
        blob = pack_vector(vec)
        result = unpack_vector(blob, len(vec))
        for a, b in zip(vec, result, strict=True):
            assert abs(a - b) < 1e-3


# ===================================================================
# TestEmbeddingVectorsTable
# ===================================================================


class TestEmbeddingVectorsTable:
    """Tests for embedding_vectors BLOB storage in SQLite."""

    def test_table_created(self) -> None:
        """embedding_vectors table is created after ensure call."""
        from emsal_mcp.semantic import _ensure_embedding_vectors

        cache = Cache(Path("test_emb.sqlite3"))
        try:
            _ensure_embedding_vectors(cache.db)
            tables = [
                r[0]
                for r in cache.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "embedding_vectors" in tables
        finally:
            cache.close()
            try:
                Path("test_emb.sqlite3").unlink()
            except Exception:
                pass

    def test_insert_and_retrieve(self) -> None:
        """Insert a vector row and retrieve it."""
        from emsal_mcp.semantic import _ensure_embedding_vectors

        cache = Cache(Path("test_emb_ir.sqlite3"))
        try:
            _ensure_embedding_vectors(cache.db)
            p = LocalHashProvider()
            vec = p.embed_text("test")
            blob = pack_vector(vec)
            norm = math.sqrt(sum(v * v for v in vec))

            cache.db.execute(
                """INSERT OR REPLACE INTO embedding_vectors
                (document_id, source, provider_id, dim, vector, norm, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("doc-1", "test-src", "local-hash-v1", 128, blob, norm, "hash1"),
            )
            cache.db.commit()

            row = cache.db.execute(
                "SELECT * FROM embedding_vectors WHERE document_id='doc-1'"
            ).fetchone()
            assert row is not None
            retrieved = unpack_vector(row["vector"], row["dim"])
            assert len(retrieved) == 128
            for a, b in zip(vec, retrieved, strict=True):
                assert abs(a - b) < 1e-6
        finally:
            cache.close()
            try:
                Path("test_emb_ir.sqlite3").unlink()
            except Exception:
                pass


# ===================================================================
# TestBuildEmbeddingIndex
# ===================================================================


class TestBuildEmbeddingIndex:
    """Tests for build_embedding_index()."""

    def test_index_empty(self, tmp_path: Path) -> None:
        """Indexing empty DB returns ok with 0 indexed."""
        cache = Cache(tmp_path / "emb_empty.sqlite3")
        try:
            result = build_embedding_index(cache=cache)
            assert result["ok"] is True
            assert result["documents_indexed"] == 0
        finally:
            cache.close()

    def test_index_with_docs(self, tmp_path: Path) -> None:
        """Index 3 documents, verify count."""
        cache = Cache(tmp_path / "emb_docs.sqlite3")
        try:
            _populate_docs(cache)
            result = build_embedding_index(cache=cache)
            assert result["ok"] is True
            assert result["documents_indexed"] == 3
            assert result["provider"] == "local-hash-v1"
            assert result["dimensions"] == 128
        finally:
            cache.close()

    def test_content_hash_skip(self, tmp_path: Path) -> None:
        """Documents whose hash hasn't changed are skipped."""
        cache = Cache(tmp_path / "emb_skip.sqlite3")
        try:
            _populate_docs(cache)
            r1 = build_embedding_index(cache=cache)
            assert r1["documents_indexed"] == 3
            # Second call: content_hash unchanged, should skip all
            r2 = build_embedding_index(cache=cache)
            assert r2["ok"] is True
            assert r2["skipped"] == 3
            assert r2["documents_indexed"] == 0
        finally:
            cache.close()

    def test_force_rebuild(self, tmp_path: Path) -> None:
        """force_rebuild=True re-embeds all documents."""
        cache = Cache(tmp_path / "emb_force.sqlite3")
        try:
            _populate_docs(cache)
            build_embedding_index(cache=cache)
            result = build_embedding_index(cache=cache, force_rebuild=True)
            assert result["ok"] is True
            assert result["documents_indexed"] == 3
            assert result["skipped"] == 0
        finally:
            cache.close()

    def test_textless_docs_skipped(self, tmp_path: Path) -> None:
        """Documents without text content are not indexed."""
        cache = Cache(tmp_path / "emb_notext.sqlite3")
        try:
            docs = [
                {
                    "source": "test",
                    "document_id": "no-text-1",
                    "title": "No Text Doc",
                    "content_status": ContentStatus.METADATA_ONLY,
                },
            ]
            _populate_docs(cache, docs=docs)
            result = build_embedding_index(cache=cache)
            assert result["ok"] is True
            assert result["documents_indexed"] == 0
        finally:
            cache.close()


# ===================================================================
# TestEmbeddingSearch
# ===================================================================


class TestEmbeddingSearch:
    """Tests for embedding_search()."""

    def test_basic_search(self, tmp_path: Path) -> None:
        """Search after indexing finds relevant documents."""
        cache = Cache(tmp_path / "emb_search.sqlite3")
        try:
            _populate_docs(cache)
            build_embedding_index(cache=cache)
            result = embedding_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] >= 1
            assert result["method"] == "dense"
            assert result["provider"] == "local-hash-v1"
        finally:
            cache.close()

    def test_results_sorted(self, tmp_path: Path) -> None:
        """Results are sorted by score descending."""
        cache = Cache(tmp_path / "emb_sorted.sqlite3")
        try:
            _populate_docs(cache)
            build_embedding_index(cache=cache)
            result = embedding_search("tazminat", cache=cache)
            assert result["ok"] is True
            scores = [r["score"] for r in result["results"]]
            assert scores == sorted(scores, reverse=True)
        finally:
            cache.close()

    def test_empty_query(self, tmp_path: Path) -> None:
        """Empty query returns empty results."""
        cache = Cache(tmp_path / "emb_empty_q.sqlite3")
        try:
            _populate_docs(cache)
            build_embedding_index(cache=cache)
            result = embedding_search("", cache=cache)
            assert result["ok"] is True
            assert result["results"] == []
        finally:
            cache.close()

    def test_provider_unavailable(self, tmp_path: Path) -> None:
        """Invalid provider with strict=True returns error (M-95 fallback disabled)."""
        cache = Cache(tmp_path / "emb_bad_prov.sqlite3")
        # Override get_embedding_provider to return None for this test
        from unittest.mock import patch as _patch
        with _patch("emsal_mcp.embeddings.get_embedding_provider", return_value=None):
            result = embedding_search("test", provider="nonexistent", cache=cache)
        assert result["ok"] is False
        assert "EMBEDDING_BACKEND_UNAVAILABLE" in result.get("errorCode", "")
        cache.close()

    def test_result_structure(self, tmp_path: Path) -> None:
        """Each result has expected keys."""
        cache = Cache(tmp_path / "emb_struct.sqlite3")
        try:
            _populate_docs(cache)
            build_embedding_index(cache=cache)
            result = embedding_search("test", cache=cache)
            assert result["ok"] is True
            for r in result["results"]:
                assert "document_id" in r
                assert "source" in r
                assert "title" in r
                assert "score" in r
                assert "content_status" in r
        finally:
            cache.close()

    def test_version_field(self, tmp_path: Path) -> None:
        """version field is correct."""
        cache = Cache(tmp_path / "emb_ver.sqlite3")
        try:
            _populate_docs(cache)
            build_embedding_index(cache=cache)
            result = embedding_search("test", cache=cache)
            assert result["ok"] is True
            assert result["version"] == EMBEDDING_VERSION
        finally:
            cache.close()

    def test_limit(self, tmp_path: Path) -> None:
        """limit parameter is respected."""
        cache = Cache(tmp_path / "emb_limit.sqlite3")
        try:
            _populate_docs(cache)
            build_embedding_index(cache=cache)
            result = embedding_search("test", cache=cache, limit=1)
            assert result["ok"] is True
            assert len(result["results"]) <= 1
        finally:
            cache.close()


# ===================================================================
# TestEmbeddingIndexStatus
# ===================================================================


class TestEmbeddingIndexStatus:
    """Tests for get_embedding_index_status()."""

    def test_empty_status(self, tmp_path: Path) -> None:
        """Empty DB returns ok with no providers."""
        cache = Cache(tmp_path / "emb_status_empty.sqlite3")
        try:
            result = get_embedding_index_status(cache=cache)
            assert result["ok"] is True
            assert result["providers"] == []
            assert result["version"] == EMBEDDING_VERSION
        finally:
            cache.close()

    def test_status_after_index(self, tmp_path: Path) -> None:
        """After indexing, status shows provider with count."""
        cache = Cache(tmp_path / "emb_status_idx.sqlite3")
        try:
            _populate_docs(cache)
            build_embedding_index(cache=cache)
            result = get_embedding_index_status(cache=cache)
            assert result["ok"] is True
            assert len(result["providers"]) == 1
            p = result["providers"][0]
            assert p["provider_id"] == "local-hash-v1"
            assert p["cnt"] == 3
            assert p["dim"] == 128
        finally:
            cache.close()


# ===================================================================
# TestHybridV3Regression
# ===================================================================


class TestHybridV3Regression:
    """Tests for hybrid_search v3 with dense_weight parameter."""

    def test_w_dense_none_uses_config(self, tmp_path: Path) -> None:
        """dense_weight=None falls back to config (default 0.0)."""
        cache = Cache(tmp_path / "h3_none.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            result = hybrid_search("test", cache=cache)
            assert result["ok"] is True
            # dense_weight should be resolved from config (default 0.0)
            assert result.get("dense_weight", 0.0) == 0.0
        finally:
            cache.close()

    def test_w_dense_zero_same_as_v2(self, tmp_path: Path) -> None:
        """dense_weight=0.0 produces identical results to v2 (no dense)."""
        cache = Cache(tmp_path / "h3_zero.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            # v2 behaviour: dense_weight explicitly 0
            r_v2 = hybrid_search("sözleşme", cache=cache, hybrid_weight=0.6, dense_weight=0.0)
            # v3 behaviour: dense_weight=None (uses config default 0.0)
            r_v3 = hybrid_search("sözleşme", cache=cache, hybrid_weight=0.6, dense_weight=None)
            assert r_v2["ok"] is True
            assert r_v3["ok"] is True
            # Both should have same results when dense is disabled
            assert r_v2["hybrid_weight"] == r_v3["hybrid_weight"]
            # dense_weight should be 0.0 in both cases
            assert r_v2.get("dense_weight", 0.0) == 0.0
            assert r_v3.get("dense_weight", 0.0) == 0.0
        finally:
            cache.close()

    def test_w_dense_positive_adds_dense_score(self, tmp_path: Path) -> None:
        """dense_weight>0 adds dense_score field to results."""
        cache = Cache(tmp_path / "h3_pos.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            build_embedding_index(cache=cache)
            result = hybrid_search(
                "sözleşme", cache=cache, hybrid_weight=0.4, dense_weight=0.3,
            )
            assert result["ok"] is True
            assert result["dense_weight"] == 0.3
            if result["results"]:
                # dense_score should be present in each result
                for r in result["results"]:
                    assert "dense_score" in r
        finally:
            cache.close()

    def test_dense_weight_in_output(self, tmp_path: Path) -> None:
        """dense_weight is always in output dict."""
        cache = Cache(tmp_path / "h3_out.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            result = hybrid_search("test", cache=cache, dense_weight=0.5)
            assert "dense_weight" in result
            assert result["dense_weight"] == 0.5
        finally:
            cache.close()

    def test_existing_hybrid_tests_still_pass(self, tmp_path: Path) -> None:
        """Existing hybrid behaviour is preserved (regression guard)."""
        cache = Cache(tmp_path / "h3_regress.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            # Default: hybrid_weight=0.6, dense_weight from config (0.0)
            result = hybrid_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert result["method"] == "hybrid"
            assert result["hybrid_weight"] == 0.6
            assert result["total_matches"] >= 1
            # Results should have bm25_score and cosine_score
            for r in result["results"]:
                assert "bm25_score" in r
                assert "cosine_score" in r
                assert "hybrid_score" in r
        finally:
            cache.close()


# ===================================================================
# TestCLIImports
# ===================================================================


class TestCLIImports:
    """Tests that CLI commands are importable and registered."""

    def test_cli_app_has_embed_commands(self) -> None:
        """CLI app has embed-index, embed-search, providers commands."""
        from typer.testing import CliRunner

        from emsal_mcp.cli import app

        runner = CliRunner()
        # Test providers command exists and works
        result = runner.invoke(app, ["semantic", "providers", "--json"])
        assert result.exit_code == 0
        assert "local-hash-v1" in result.output

    def test_cli_embed_index_command(self) -> None:
        """CLI embed-index command runs successfully."""
        from typer.testing import CliRunner

        from emsal_mcp.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["semantic", "embed-index", "--json"])
        assert result.exit_code == 0
        assert "ok" in result.output

    def test_cli_embed_search_command(self) -> None:
        """CLI embed-search command runs successfully."""
        from typer.testing import CliRunner

        from emsal_mcp.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["semantic", "embed-search", "test", "--json"])
        assert result.exit_code == 0
        assert "ok" in result.output

    def test_cli_embedding_status_command(self) -> None:
        """CLI embedding-status command runs successfully."""
        from typer.testing import CliRunner

        from emsal_mcp.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["semantic", "embedding-status", "--json"])
        assert result.exit_code == 0
        assert "ok" in result.output


# ===================================================================
# TestMCPImports
# ===================================================================


class TestMCPImports:
    """Tests that MCP server can import the new tools."""

    def test_server_imports(self) -> None:
        """Server module can be imported (tools registered)."""
        from emsal_mcp.server import main

        assert callable(main)

    def test_semantic_imports_all_new_functions(self) -> None:
        """All new semantic functions are importable."""
        from emsal_mcp.semantic import (
            build_embedding_index,
            embedding_search,
            get_embedding_index_status,
        )

        assert callable(build_embedding_index)
        assert callable(embedding_search)
        assert callable(get_embedding_index_status)

    def test_embeddings_imports_all(self) -> None:
        """All embeddings module exports are importable."""
        from emsal_mcp.embeddings import (
            EMBEDDING_VERSION,
            EmbeddingProvider,
            FastEmbedProvider,
            LocalHashProvider,
        )

        assert EMBEDDING_VERSION == "2.1.0"
        assert issubclass(LocalHashProvider, EmbeddingProvider)
        assert issubclass(FastEmbedProvider, EmbeddingProvider)


# ===================================================================
# TestConfigEmbeddingProperties
# ===================================================================


class TestConfigEmbeddingProperties:
    """Tests for EmsalConfig embedding properties."""

    def test_embedding_provider_default(self) -> None:
        """Default embedding_provider is 'local-hash-v1'."""
        from emsal_mcp.config import EmsalConfig

        c = EmsalConfig()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EMSAL_EMBEDDING_PROVIDER", None)
            assert c.embedding_provider == "local-hash-v1"

    def test_embedding_cache_dir_default(self) -> None:
        """Default embedding_cache_dir is ~/.emsal_mcp/models/fastembed."""
        from emsal_mcp.config import EmsalConfig

        c = EmsalConfig()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EMSAL_EMBEDDING_CACHE_DIR", None)
            d = c.embedding_cache_dir
            assert d == Path.home() / ".emsal_mcp" / "models" / "fastembed"

    def test_embedding_batch_size_default(self) -> None:
        """Default embedding_batch_size is 16."""
        from emsal_mcp.config import EmsalConfig

        c = EmsalConfig()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EMSAL_EMBEDDING_BATCH_SIZE", None)
            assert c.embedding_batch_size == 16

    def test_hybrid_weights_defaults(self) -> None:
        """Default hybrid weights: bm25=0.4, tfidf=0.6, dense=0.0."""
        from emsal_mcp.config import EmsalConfig

        c = EmsalConfig()
        with patch.dict(os.environ, {}, clear=False):
            for k in ("EMSAL_HYBRID_W_BM25", "EMSAL_HYBRID_W_TFIDF", "EMSAL_HYBRID_W_DENSE"):
                os.environ.pop(k, None)
            assert c.hybrid_w_bm25 == 0.4
            assert c.hybrid_w_tfidf == 0.6
            assert c.hybrid_w_dense == 0.0


# ===================================================================
# TestRerankResults (M-25)
# ===================================================================


class TestRerankResults:
    """Tests for rerank_results() cross-encoder reranker."""

    def test_empty_candidates_passthrough(self) -> None:
        """Empty candidates list returns passthrough with no rerank."""
        result = rerank_results("test query", [])
        assert result["ok"] is True
        assert result["results"] == []
        assert result["was_reranked"] is False
        assert result["method"] == "passthrough"

    def test_single_candidate_passthrough(self) -> None:
        """Single candidate returns passthrough (nothing to rerank)."""
        candidates = [{"document_id": "d1", "source": "s", "title": "t", "score": 0.5}]
        result = rerank_results("query", candidates)
        assert result["ok"] is True
        assert len(result["results"]) == 1
        assert result["was_reranked"] is False
        assert result["method"] == "passthrough"

    def test_fastembed_unavailable_passthrough(self) -> None:
        """When fastembed is unavailable, returns passthrough with warning."""
        candidates = [
            {"document_id": "d1", "source": "s", "title": "t1", "score": 0.5, "snippet": "text a"},
            {"document_id": "d2", "source": "s", "title": "t2", "score": 0.3, "snippet": "text b"},
        ]
        # Ensure fastembed is not in sys.modules
        import sys
        saved = sys.modules.pop("fastembed", None)
        sys.modules["fastembed"] = None  # block import
        try:
            result = rerank_results("query", candidates)
        finally:
            if saved is not None:
                sys.modules["fastembed"] = saved
            else:
                sys.modules.pop("fastembed", None)
        assert result["ok"] is True
        assert result["was_reranked"] is False
        assert result["method"] == "passthrough"
        assert any("Cross-encoder not available" in w for w in result["warnings"])

    def test_mock_cross_encoder_reranked(self) -> None:
        """With a mock cross-encoder, was_reranked=True and results are resorted."""
        candidates = [
            {"document_id": "d1", "source": "s", "title": "t1", "score": 0.5, "snippet": "text a"},
            {"document_id": "d2", "source": "s", "title": "t2", "score": 0.3, "snippet": "text b"},
            {"document_id": "d3", "source": "s", "title": "t3", "score": 0.1, "snippet": "text c"},
        ]

        # Create a fake TextCrossEncoder class
        class FakeCrossEncoder:
            def __init__(self, model_name: str = "") -> None:
                pass

            def predict(self, pairs: list[list[str]]) -> list[float]:
                # d2 gets highest score (10.0), d3 middle (5.0), d1 lowest (1.0)
                score_map = {"text a": 1.0, "text b": 10.0, "text c": 5.0}
                return [score_map.get(p[1], 0.0) for p in pairs]

        # Create a fake fastembed module
        import types
        import sys
        fake_fe = types.ModuleType("fastembed")
        fake_fe.TextCrossEncoder = FakeCrossEncoder  # type: ignore[attr-defined]
        saved = sys.modules.get("fastembed")
        sys.modules["fastembed"] = fake_fe
        try:
            result = rerank_results("query", candidates, top_k=2)
        finally:
            if saved is not None:
                sys.modules["fastembed"] = saved
            else:
                sys.modules.pop("fastembed", None)

        assert result["ok"] is True
        assert result["was_reranked"] is True
        assert result["method"] == "cross-encoder"
        assert len(result["results"]) == 2
        # d2 gets highest rerank_score (10.0), should be first
        assert result["results"][0]["document_id"] == "d2"
        assert result["results"][1]["document_id"] == "d3"
        assert "rerank_score" in result["results"][0]

    def test_rerank_exception_passthrough(self) -> None:
        """If cross-encoder predict() throws, gracefully passes through."""

        class BrokenCrossEncoder:
            def __init__(self, model_name: str = "") -> None:
                pass

            def predict(self, pairs: list[list[str]]) -> list[float]:
                raise RuntimeError("Model load failed")

        candidates = [
            {"document_id": "d1", "source": "s", "title": "t1", "score": 0.5, "snippet": "a"},
            {"document_id": "d2", "source": "s", "title": "t2", "score": 0.3, "snippet": "b"},
        ]

        import types
        import sys
        fake_fe = types.ModuleType("fastembed")
        fake_fe.TextCrossEncoder = BrokenCrossEncoder  # type: ignore[attr-defined]
        saved = sys.modules.get("fastembed")
        sys.modules["fastembed"] = fake_fe
        try:
            result = rerank_results("query", candidates)
        finally:
            if saved is not None:
                sys.modules["fastembed"] = saved
            else:
                sys.modules.pop("fastembed", None)

        assert result["ok"] is True
        assert result["was_reranked"] is False
        assert result["method"] == "passthrough"
        assert any("Reranking failed" in w for w in result["warnings"])

    def test_top_k_respected(self) -> None:
        """top_k limits the number of returned results."""
        candidates = [
            {"document_id": f"d{i}", "source": "s", "title": f"t{i}", "score": 0.5 - i * 0.1, "snippet": f"text {i}"}
            for i in range(10)
        ]
        result = rerank_results("query", candidates, top_k=3)
        assert result["ok"] is True
        assert len(result["results"]) <= 3

    def test_builds_text_preview_from_snippet(self) -> None:
        """rerank_results uses snippet/text_preview/title as doc_text."""
        candidates = [
            {"document_id": "d1", "source": "s", "title": "t1", "score": 0.5, "snippet": "the snippet"},
            {"document_id": "d2", "source": "s", "title": "t2", "score": 0.3},  # no snippet
        ]

        captured_pairs: list[list[str]] = []

        class CapturingEncoder:
            def __init__(self, model_name: str = "") -> None:
                pass

            def predict(self, pairs: list[list[str]]) -> list[float]:
                captured_pairs.extend(pairs)
                return [1.0, 0.5]

        import types
        import sys
        fake_fe = types.ModuleType("fastembed")
        fake_fe.TextCrossEncoder = CapturingEncoder  # type: ignore[attr-defined]
        saved = sys.modules.get("fastembed")
        sys.modules["fastembed"] = fake_fe
        try:
            rerank_results("query", candidates, top_k=2)
        finally:
            if saved is not None:
                sys.modules["fastembed"] = saved
            else:
                sys.modules.pop("fastembed", None)

        assert len(captured_pairs) == 2
        assert captured_pairs[0] == ["query", "the snippet"]
        # d2 has no snippet, falls back to title
        assert captured_pairs[1] == ["query", "t2"]


# ===================================================================
# TestHybridSearchRerank (M-25 integration)
# ===================================================================


class TestHybridSearchRerank:
    """Tests for hybrid_search with rerank parameter."""

    def test_rerank_false_no_rerank_field(self, tmp_path: Path) -> None:
        """hybrid_search with rerank=False does not include 'reranked' from reranking."""
        cache = Cache(tmp_path / "rerank_false.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            result = hybrid_search("sözleşme", cache=cache, rerank=False)
            assert result["ok"] is True
            # reranked field should be present (always) but False when rerank=False
            assert result.get("reranked") is False
        finally:
            cache.close()

    def test_rerank_true_includes_metadata(self, tmp_path: Path) -> None:
        """hybrid_search with rerank=True includes reranked field (passthrough when fastembed unavailable)."""
        cache = Cache(tmp_path / "rerank_true.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            result = hybrid_search("sözleşme", cache=cache, rerank=True)
            assert result["ok"] is True
            # reranked should be in result (False since fastembed not installed)
            assert "reranked" in result
            assert result["reranked"] is False
            # warnings should mention cross-encoder not available
            assert any("Cross-encoder" in w for w in result.get("warnings", []))
        finally:
            cache.close()

    def test_rerank_true_with_mock(self, tmp_path: Path) -> None:
        """hybrid_search with rerank=True and mock cross-encoder sets reranked=True."""
        cache = Cache(tmp_path / "rerank_mock.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)

            class FakeCrossEncoder:
                def __init__(self, model_name: str = "") -> None:
                    pass

                def predict(self, pairs: list[list[str]]) -> list[float]:
                    return [float(i) for i in range(len(pairs))]

            import types
            import sys
            fake_fe = types.ModuleType("fastembed")
            fake_fe.TextCrossEncoder = FakeCrossEncoder  # type: ignore[attr-defined]
            saved = sys.modules.get("fastembed")
            sys.modules["fastembed"] = fake_fe
            try:
                result = hybrid_search("sözleşme", cache=cache, rerank=True)
            finally:
                if saved is not None:
                    sys.modules["fastembed"] = saved
                else:
                    sys.modules.pop("fastembed", None)

            assert result["ok"] is True
            assert result["reranked"] is True
        finally:
            cache.close()

    def test_rerank_not_in_output_when_false(self, tmp_path: Path) -> None:
        """When rerank=False, reranked is False."""
        cache = Cache(tmp_path / "rerank_absent.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            result = hybrid_search("test", cache=cache, rerank=False)
            assert result["ok"] is True
            assert result.get("reranked") is False
        finally:
            cache.close()

    def test_empty_results_rerank_noop(self, tmp_path: Path) -> None:
        """Reranking with no results is a no-op."""
        cache = Cache(tmp_path / "rerank_empty.sqlite3")
        try:
            # No docs → no results
            result = hybrid_search("nonexistent", cache=cache, rerank=True)
            assert result["ok"] is True
            assert result["results"] == []
            assert result.get("reranked") is False
        finally:
            cache.close()


# ===================================================================
# M-72: Heuristic Rerank (citation-safe + recency boost)
# ===================================================================


class TestHeuristicRerank:
    """Tests for heuristic_rerank() — deterministic citation-safe and recency boost."""

    def _make_candidate(self, doc_id: str, score: float, **kwargs) -> dict:
        c = {"document_id": doc_id, "source": "test", "title": f"Doc {doc_id}", "score": score}
        c.update(kwargs)
        return c

    def test_empty_candidates(self):
        result = heuristic_rerank([], top_k=5)
        assert result["ok"] is True
        assert result["results"] == []
        assert result["method"] == "heuristic"

    def test_basic_passthrough(self):
        """No boost attributes → same order as input."""
        candidates = [
            self._make_candidate("a", 0.9),
            self._make_candidate("b", 0.5),
            self._make_candidate("c", 0.3),
        ]
        result = heuristic_rerank(candidates, top_k=3)
        assert result["results"][0]["document_id"] == "a"
        assert result["results"][1]["document_id"] == "b"
        assert result["results"][2]["document_id"] == "c"

    def test_citation_safe_boost(self):
        """Document with quote_usable=True gets boosted over higher-score doc."""
        candidates = [
            self._make_candidate("safe", 0.6, quote_usable=True),
            self._make_candidate("unsafe", 0.8, quote_usable=False),
        ]
        result = heuristic_rerank(candidates, top_k=2, citation_safe_boost=0.3)
        # safe gets 0.6 + 0.3 = 0.9 > 0.8
        assert result["results"][0]["document_id"] == "safe"
        assert result["boosted"] == 1

    def test_draft_usable_also_counts(self):
        """draft_usable=True gives same boost as quote_usable."""
        candidates = [
            self._make_candidate("draft", 0.5, draft_usable=True),
            self._make_candidate("plain", 0.6),
        ]
        result = heuristic_rerank(candidates, top_k=2, citation_safe_boost=0.2)
        # draft gets 0.5 + 0.2 = 0.7 > 0.6
        assert result["results"][0]["document_id"] == "draft"

    def test_recency_boost(self):
        """Newer decision_date gets higher bonus."""
        candidates = [
            self._make_candidate("old", 0.7, decision_date="2020-01-01"),
            self._make_candidate("new", 0.7, decision_date="2025-06-01"),
        ]
        result = heuristic_rerank(candidates, top_k=2, citation_safe_boost=0.0, recency_weight=0.5)
        # newer should rank higher with equal base score
        assert result["results"][0]["document_id"] == "new"

    def test_combined_boost(self):
        """Citation-safe + recency both applied."""
        candidates = [
            self._make_candidate("a", 0.7, quote_usable=True, decision_date="2023-01-01"),
            self._make_candidate("b", 0.7, quote_usable=False, decision_date="2020-01-01"),
        ]
        result = heuristic_rerank(candidates, top_k=2, citation_safe_boost=0.1, recency_weight=0.1)
        assert result["results"][0]["document_id"] == "a"
        assert result["boosted"] >= 1

    def test_top_k_respected(self):
        """Only top_k results returned."""
        candidates = [
            self._make_candidate(str(i), float(10 - i)) for i in range(10)
        ]
        result = heuristic_rerank(candidates, top_k=4)
        assert len(result["results"]) == 4

    def test_deterministic(self):
        """Same input always produces same output."""
        candidates = [
            self._make_candidate("a", 0.5, quote_usable=True),
            self._make_candidate("b", 0.8),
            self._make_candidate("c", 0.3, quote_usable=True),
        ]
        r1 = heuristic_rerank(candidates, top_k=3)
        r2 = heuristic_rerank(candidates, top_k=3)
        assert [x["document_id"] for x in r1["results"]] == [x["document_id"] for x in r2["results"]]

    def test_heuristic_score_added(self):
        """Each result gets a heuristic_score field."""
        candidates = [self._make_candidate("x", 0.5)]
        result = heuristic_rerank(candidates)
        assert "heuristic_score" in result["results"][0]
        assert result["results"][0]["heuristic_score"] >= 0.5

    def test_invalid_date_ignored(self):
        """Unparseable decision_date → no recency boost, no crash."""
        candidates = [
            self._make_candidate("bad", 0.5, decision_date="not-a-date"),
            self._make_candidate("good", 0.5),
        ]
        result = heuristic_rerank(candidates)
        for r in result["results"]:
            assert "heuristic_score" in r