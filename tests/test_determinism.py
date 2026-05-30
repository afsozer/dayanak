"""M-49: Determinism & Flaky Test Audit.

Verifies that key functions produce deterministic output when given the
same inputs.  Seeds randomness sources where applicable and asserts
equality across two separate calls.
"""
from __future__ import annotations

import hashlib
import random
import tempfile
from pathlib import Path

import pytest

from emsal_mcp.cache import Cache
from emsal_mcp.dedup import find_duplicates
from emsal_mcp.embeddings import LocalHashProvider
from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.safety import citation_check
from emsal_mcp.semantic import build_semantic_index, hybrid_search


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seeded_hash_provider() -> LocalHashProvider:
    """Create a LocalHashProvider (deterministic by design)."""
    return LocalHashProvider()


def _make_doc(
    source: str = "test",
    doc_id: str = "doc1",
    court: str = "Yargitay",
    esas_no: str = "2023/123",
    karar_no: str = "2024/456",
    full_text: str = "Bu bir test belgesidir. İçerik burada.",
    content_status: ContentStatus = ContentStatus.FULL_TEXT,
) -> Document:
    return Document(
        source=source,
        document_id=doc_id,
        title="Test Decision",
        court=court,
        esas_no=esas_no,
        karar_no=karar_no,
        content_status=content_status,
        full_text=full_text,
    )


def _make_cache_with_docs(tmp_path: Path) -> Cache:
    """Create a cache with deterministic test documents."""
    cache = Cache(path=tmp_path / "test.sqlite3")
    docs = [
        _make_doc(source="src_a", doc_id="d1", full_text="Yargitay karar metni burada."),
        _make_doc(source="src_b", doc_id="d2", full_text="Danistay karar metni burada."),
        _make_doc(source="src_a", doc_id="d3", court="Danistay", full_text="Diger bir karar."),
    ]
    for doc in docs:
        cache.store_document(doc)
    return cache


# ---------------------------------------------------------------------------
# Test: LocalHashProvider.embed_text determinism
# ---------------------------------------------------------------------------

class TestEmbeddingDeterminism:
    """LocalHashProvider must produce identical vectors for identical input."""

    def test_embed_text_same_twice(self) -> None:
        provider = _seeded_hash_provider()
        vec1 = provider.embed_text("test")
        vec2 = provider.embed_text("test")
        assert vec1 == vec2
        assert len(vec1) == 128

    def test_embed_text_different_inputs(self) -> None:
        provider = _seeded_hash_provider()
        vec1 = provider.embed_text("hello")
        vec2 = provider.embed_text("world")
        assert vec1 != vec2

    def test_embed_batch_deterministic(self) -> None:
        provider = _seeded_hash_provider()
        texts = ["legal", "document", "analysis"]
        batch1 = provider.embed_batch(texts)
        batch2 = provider.embed_batch(texts)
        assert batch1 == batch2
        assert len(batch1) == 3

    def test_embed_text_normalization_stable(self) -> None:
        """Embedding should be stable across different capitalizations (via lowercasing)."""
        provider = _seeded_hash_provider()
        vec1 = provider.embed_text("Test")
        vec2 = provider.embed_text("test")
        # LocalHashProvider lowercases, so these should be equal
        assert vec1 == vec2

    def test_embed_text_hashlib_independence(self) -> None:
        """Verify that hashlib sha256 (used internally) produces stable results."""
        h1 = hashlib.sha256(b"test-token").digest()
        h2 = hashlib.sha256(b"test-token").digest()
        assert h1 == h2
        idx1 = int.from_bytes(h1[:4], "big") % 128
        idx2 = int.from_bytes(h2[:4], "big") % 128
        assert idx1 == idx2


# ---------------------------------------------------------------------------
# Test: citation_check determinism
# ---------------------------------------------------------------------------

class TestCitationCheckDeterminism:
    """citation_check must return identical results for identical documents."""

    def test_citation_check_same_result(self) -> None:
        doc = _make_doc()
        r1 = citation_check(doc)
        r2 = citation_check(doc)
        assert r1.ok == r2.ok
        assert r1.quoteUsable == r2.quoteUsable
        assert r1.draftUsable == r2.draftUsable
        assert r1.reasons == r2.reasons
        assert r1.safety_state == r2.safety_state

    def test_citation_check_unsafe_deterministic(self) -> None:
        doc = _make_doc(content_status=ContentStatus.METADATA_ONLY, full_text="")
        r1 = citation_check(doc)
        r2 = citation_check(doc)
        assert r1.ok == r2.ok is False
        assert set(r1.reasons) == set(r2.reasons)


# ---------------------------------------------------------------------------
# Test: find_duplicates determinism
# ---------------------------------------------------------------------------

class TestFindDuplicatesDeterminism:
    """find_duplicates must produce identical clusters for the same data."""

    def test_find_duplicates_same_result(self, tmp_path: Path) -> None:
        cache1 = _make_cache_with_docs(tmp_path / "c1")
        cache2 = _make_cache_with_docs(tmp_path / "c2")

        # Add duplicate docs to both caches
        dup_doc = _make_doc(source="src_c", doc_id="d4", full_text="Ayni karar.")
        cache1.store_document(dup_doc)
        cache2.store_document(dup_doc)

        r1 = find_duplicates(cache=cache1, dry_run=True)
        r2 = find_duplicates(cache=cache2, dry_run=True)

        # Clusters should have same structure (order-independent for members)
        assert r1["ok"] == r2["ok"]
        assert r1["clusters_found"] == r2["clusters_found"]
        assert r1["total_duplicates"] == r2["total_duplicates"]

    def test_find_duplicates_idempotent(self, tmp_path: Path) -> None:
        """Running twice on same cache should not create different results."""
        cache = _make_cache_with_docs(tmp_path)
        r1 = find_duplicates(cache=cache, dry_run=True)
        r2 = find_duplicates(cache=cache, dry_run=True)
        # Dry run doesn't mutate, so results should be identical
        assert r1["clusters_found"] == r2["clusters_found"]
        assert r1["total_duplicates"] == r2["total_duplicates"]


# ---------------------------------------------------------------------------
# Test: build_semantic_index determinism
# ---------------------------------------------------------------------------

class TestSemanticIndexDeterminism:
    """build_semantic_index must produce same vector counts and structure."""

    def test_index_same_twice(self, tmp_path: Path) -> None:
        cache1 = _make_cache_with_docs(tmp_path / "c1")
        cache2 = _make_cache_with_docs(tmp_path / "c2")

        r1 = build_semantic_index(cache=cache1, force_rebuild=True)
        r2 = build_semantic_index(cache=cache2, force_rebuild=True)

        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r1["vectors_count"] == r2["vectors_count"]
        assert r1["fts5_row_count"] == r2["fts5_row_count"]
        assert r1["documents_total"] == r2["documents_total"]


# ---------------------------------------------------------------------------
# Test: hybrid_search determinism
# ---------------------------------------------------------------------------

class TestHybridSearchDeterminism:
    """hybrid_search must return same results for same query and cache state."""

    def test_hybrid_search_same_query(self, tmp_path: Path) -> None:
        cache1 = _make_cache_with_docs(tmp_path / "c1")
        cache2 = _make_cache_with_docs(tmp_path / "c2")

        # Build index on both
        build_semantic_index(cache=cache1, force_rebuild=True)
        build_semantic_index(cache=cache2, force_rebuild=True)

        r1 = hybrid_search("test", cache=cache1, dense_weight=0.0)
        r2 = hybrid_search("test", cache=cache2, dense_weight=0.0)

        # Same query, same data → same result count and scores
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert len(r1["results"]) == len(r2["results"])

        # Compare scores (rounded)
        for res1, res2 in zip(r1["results"], r2["results"]):
            assert res1["hybrid_score"] == res2["hybrid_score"]
            assert res1["document_id"] == res2["document_id"]

    def test_hybrid_search_empty_query_deterministic(self, tmp_path: Path) -> None:
        cache = _make_cache_with_docs(tmp_path)
        build_semantic_index(cache=cache, force_rebuild=True)

        r1 = hybrid_search("karar", cache=cache, dense_weight=0.0)
        r2 = hybrid_search("karar", cache=cache, dense_weight=0.0)
        assert len(r1["results"]) == len(r2["results"])


# ---------------------------------------------------------------------------
# Test: random.Random seeding
# ---------------------------------------------------------------------------

class TestRandomSeeding:
    """Verify that seeding random.Random produces deterministic sequences."""

    def test_seeded_random_same_sequence(self) -> None:
        rng1 = random.Random(42)
        seq1 = [rng1.random() for _ in range(10)]
        rng2 = random.Random(42)
        seq2 = [rng2.random() for _ in range(10)]
        assert seq1 == seq2

    def test_seeded_random_different_seeds(self) -> None:
        rng1 = random.Random(42)
        rng2 = random.Random(99)
        seq1 = [rng1.random() for _ in range(10)]
        seq2 = [rng2.random() for _ in range(10)]
        assert seq1 != seq2

    def test_hashlib_sha256_deterministic(self) -> None:
        """hashlib.sha256 must produce identical digests for same input."""
        data = b"deterministic-test-input"
        d1 = hashlib.sha256(data).hexdigest()
        d2 = hashlib.sha256(data).hexdigest()
        assert d1 == d2

    def test_struct_pack_deterministic(self) -> None:
        """struct.pack/unpack must be deterministic (used in embeddings)."""
        import struct
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        blob1 = struct.pack(f"{len(vec)}f", *vec)
        blob2 = struct.pack(f"{len(vec)}f", *vec)
        assert blob1 == blob2  # byte-identical
        unpacked = list(struct.unpack(f"{len(vec)}f", blob1))
        assert len(unpacked) == len(vec)
        for a, b in zip(unpacked, vec):
            assert a == pytest.approx(b, abs=1e-6)
