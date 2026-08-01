"""Tests for FastEmbedMultilingualProvider (M-95 / E5 prefix + custom-model registration).

Split out from test_embeddings.py (owned by a concurrent semantic.py effort)
to avoid touching that file. Covers two independent concerns:

1. Prefix logic — model-independent, always runs. Verifies embed_query /
   embed_document prepend the correct E5 asymmetric prefix, using a
   monkeypatched embed_text so no model download is required.

2. Real semantic behaviour — model-dependent, skips cleanly if fastembed
   isn't installed or the model can't be loaded/downloaded (no network).
   Confirms a Turkish legal query scores its relevant passage higher than
   an irrelevant one, using the actual fastembed pipeline end to end.

Note: fastembed does not ship ``intfloat/multilingual-e5-small`` natively
(verified against fastembed 0.4.2-0.8.0 — only ``multilingual-e5-large``,
1024 dims, is built in). FastEmbedMultilingualProvider registers the
community ONNX export (``Xenova/multilingual-e5-small``, quantized) as a
custom model via ``TextEmbedding.add_custom_model`` (fastembed>=0.6).
"""
from __future__ import annotations

import pytest

from emsal_mcp.embeddings import FastEmbedMultilingualProvider


# ===================================================================
# Prefix logic — no model required
# ===================================================================


class TestE5PrefixLogic:
    """embed_query/embed_document must prepend the correct E5 prefix.

    These tests monkeypatch embed_text itself, so they exercise only the
    prefixing logic and never touch fastembed or the network.
    """

    def test_query_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str] = {}

        def fake_embed_text(self: FastEmbedMultilingualProvider, text: str) -> list[float]:
            captured["text"] = text
            return [0.0] * 384

        monkeypatch.setattr(FastEmbedMultilingualProvider, "embed_text", fake_embed_text)
        p = FastEmbedMultilingualProvider()
        p.embed_query("kıdem tazminatı hesaplanır mı")
        assert captured["text"] == "query: kıdem tazminatı hesaplanır mı"

    def test_document_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str] = {}

        def fake_embed_text(self: FastEmbedMultilingualProvider, text: str) -> list[float]:
            captured["text"] = text
            return [0.0] * 384

        monkeypatch.setattr(FastEmbedMultilingualProvider, "embed_text", fake_embed_text)
        p = FastEmbedMultilingualProvider()
        p.embed_document("tahliye taahhüdü kira sözleşmesinden sonra verilmelidir")
        assert captured["text"] == "passage: tahliye taahhüdü kira sözleşmesinden sonra verilmelidir"

    def test_query_and_document_prefixes_differ(self) -> None:
        assert FastEmbedMultilingualProvider._QUERY_PREFIX == "query: "
        assert FastEmbedMultilingualProvider._DOC_PREFIX == "passage: "
        assert FastEmbedMultilingualProvider._QUERY_PREFIX != FastEmbedMultilingualProvider._DOC_PREFIX

    def test_documents_batch_uses_doc_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[str] = []

        def fake_embed_batch(self: FastEmbedMultilingualProvider, texts: list[str]) -> list[list[float]]:
            captured.extend(texts)
            return [[0.0] * 384 for _ in texts]

        monkeypatch.setattr(FastEmbedMultilingualProvider, "embed_batch", fake_embed_batch)
        p = FastEmbedMultilingualProvider()
        p.embed_documents_batch(["metin bir", "metin iki"])
        assert captured == ["passage: metin bir", "passage: metin iki"]

    def test_queries_batch_uses_query_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[str] = []

        def fake_embed_batch(self: FastEmbedMultilingualProvider, texts: list[str]) -> list[list[float]]:
            captured.extend(texts)
            return [[0.0] * 384 for _ in texts]

        monkeypatch.setattr(FastEmbedMultilingualProvider, "embed_batch", fake_embed_batch)
        p = FastEmbedMultilingualProvider()
        p.embed_queries_batch(["soru bir", "soru iki"])
        assert captured == ["query: soru bir", "query: soru iki"]

    def test_id_and_dimensions(self) -> None:
        p = FastEmbedMultilingualProvider()
        assert p.id == "fastembed-multilingual-e5"
        assert p.dimensions == 384


# ===================================================================
# Real model behaviour — skips cleanly without fastembed/network
# ===================================================================


def _load_provider_or_skip() -> FastEmbedMultilingualProvider:
    pytest.importorskip("fastembed")
    p = FastEmbedMultilingualProvider()
    try:
        # Trigger the actual (possibly network-downloading) model load.
        p.embed_text("ısınma turu")
    except Exception as e:  # noqa: BLE001 - deliberately broad: any load failure -> skip
        pytest.skip(f"fastembed model unavailable (no network/cache?): {e}")
    return p


@pytest.mark.integration
class TestE5RealSemanticBehaviour:
    def test_relevant_passage_scores_higher_than_irrelevant(self) -> None:
        p = _load_provider_or_skip()

        query = "kıdem tazminatı hesaplanırken son ücret esas alınır mı"
        relevant = (
            "İşçinin kıdem tazminatı, işten ayrıldığı tarihteki son brüt "
            "ücreti esas alınarak hesaplanır. Otuz günlük ücret her tam "
            "yıl için ödenir."
        )
        irrelevant = (
            "Tahliye taahhüdüne dayalı icra takibinde, taahhüdün kira "
            "sözleşmesinden sonraki bir tarihte serbest iradeyle verilmiş "
            "olması gerekir."
        )

        qv = p.embed_query(query)
        rv = p.embed_document(relevant)
        iv = p.embed_document(irrelevant)

        cos_rel = sum(a * b for a, b in zip(qv, rv, strict=True))
        cos_irr = sum(a * b for a, b in zip(qv, iv, strict=True))

        assert cos_rel > cos_irr

    def test_prefix_changes_the_embedding(self) -> None:
        """Sanity check: the E5 prefix must actually alter the vector,
        not be silently ignored (which would look identical to the raw
        embed_text output and would degrade retrieval without erroring).
        """
        p = _load_provider_or_skip()
        text = "kıdem tazminatı"
        raw = p.embed_text(text)
        prefixed = p.embed_query(text)
        assert raw != prefixed

    def test_dimensions_match_declared(self) -> None:
        p = _load_provider_or_skip()
        vec = p.embed_text("test")
        assert len(vec) == p.dimensions == 384
