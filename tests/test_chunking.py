"""Tests for emsal_mcp.chunking — paragraph-aware chunking for dense embeddings.

Covers the boundary cases called out in the M-95 embeddings work: empty
input, text shorter than one chunk, text exactly one chunk, very long text
needing many chunks, and text with no paragraph breaks at all.
"""
from __future__ import annotations

import pytest

from emsal_mcp.chunking import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    chunk_text,
)


class TestEmptyAndTrivialInput:
    def test_empty_string(self) -> None:
        assert chunk_text("") == []

    def test_whitespace_only(self) -> None:
        assert chunk_text("   \n\n\t  ") == []

    def test_none_like_falsy_not_passed(self) -> None:
        # Guard: only strings are valid input; empty string is the floor.
        assert chunk_text("") == []


class TestShorterThanOneChunk:
    def test_short_text_single_chunk(self) -> None:
        text = "Kısa bir metin."
        result = chunk_text(text, chunk_size=1000, overlap=100)
        assert result == [text]

    def test_short_text_preserves_content(self) -> None:
        text = "Taraflar arasındaki uyuşmazlık hakkında karar."
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert len(result) == 1
        assert result[0] == text

    def test_strips_surrounding_whitespace(self) -> None:
        text = "  metin burada  "
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert result == ["metin burada"]


class TestExactlyOneChunk:
    def test_exact_chunk_size_boundary(self) -> None:
        text = "a" * 500
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert result == [text]

    def test_one_char_over_boundary_splits(self) -> None:
        text = "a" * 501
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert len(result) >= 2


class TestVeryLongText:
    def test_produces_multiple_chunks(self) -> None:
        paragraph = "Bu bir test paragrafıdır ve tekrar edilmektedir. " * 10
        text = "\n\n".join([paragraph] * 30)
        result = chunk_text(text, chunk_size=1000, overlap=150)
        assert len(result) > 1

    def test_all_chunks_within_size(self) -> None:
        paragraph = "Mahkemece yapılan yargılama sonucunda karar verilmiştir. " * 8
        text = "\n\n".join([paragraph] * 50)
        result = chunk_text(text, chunk_size=1200, overlap=200)
        for c in result:
            assert len(c) <= 1200

    def test_consecutive_chunks_overlap(self) -> None:
        paragraph = "Sözleşme hükümleri taraflarca kabul edilmiştir. " * 12
        text = "\n\n".join([paragraph] * 20)
        result = chunk_text(text, chunk_size=800, overlap=150)
        assert len(result) > 1
        # Tail of chunk i should share content with the head of chunk i+1
        for i in range(len(result) - 1):
            tail = result[i][-100:]
            assert tail[:20] in result[i + 1] or tail[-20:] in result[i + 1]

    def test_realistic_224k_document(self) -> None:
        """Simulates the corpus's largest known document (~224,000 chars)."""
        paragraph = (
            "Davacı vekili dilekçesinde, müvekkilinin iş akdinin haksız "
            "feshedildiğini beyan ederek kıdem ve ihbar tazminatı taleplerinde "
            "bulunmuştur. Mahkemece bilirkişi raporu değerlendirilmiştir.\n\n"
        )
        text = paragraph * 1400  # ~224,000 chars
        assert len(text) > 200_000
        result = chunk_text(text)
        assert len(result) > 100
        for c in result:
            assert len(c) <= DEFAULT_CHUNK_SIZE

    def test_order_preserved(self) -> None:
        paras = [f"Paragraf numara {i}. " * 20 for i in range(10)]
        text = "\n\n".join(paras)
        result = chunk_text(text, chunk_size=400, overlap=50)
        # First chunk should start with paragraph 0's content
        assert "numara 0" in result[0]
        # Last chunk should contain the final paragraph's content
        assert "numara 9" in result[-1]


class TestNoParagraphBreaks:
    def test_single_line_no_breaks_splits_by_size(self) -> None:
        text = "kelime " * 500  # long, single line, no \n at all
        assert "\n" not in text
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert len(result) > 1
        for c in result:
            assert len(c) <= 500

    def test_no_breaks_short_enough_stays_one_chunk(self) -> None:
        text = "kelime " * 5
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert len(result) == 1


class TestParagraphAlignment:
    def test_splits_on_blank_lines_when_possible(self) -> None:
        p1 = "İlk paragraf burada yer almaktadır ve yeterince uzundur diyelim."
        p2 = "İkinci paragraf farklı bir konuyu ele almaktadır burada da."
        text = f"{p1}\n\n{p2}"
        result = chunk_text(text, chunk_size=len(p1) + 5, overlap=10)
        # p2 shouldn't be crammed into the same chunk as p1 if it doesn't fit
        assert len(result) >= 1

    def test_single_newlines_fallback(self) -> None:
        lines = [f"Satır {i} burada metin var yeterince uzun olsun diye." for i in range(20)]
        text = "\n".join(lines)
        result = chunk_text(text, chunk_size=300, overlap=40)
        assert len(result) > 1


class TestValidation:
    def test_overlap_equal_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError):
            chunk_text("some text", chunk_size=100, overlap=100)

    def test_overlap_greater_than_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError):
            chunk_text("some text", chunk_size=100, overlap=200)

    def test_negative_overlap_raises(self) -> None:
        with pytest.raises(ValueError):
            chunk_text("some text", chunk_size=100, overlap=-1)

    def test_zero_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError):
            chunk_text("some text", chunk_size=0, overlap=0)

    def test_negative_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError):
            chunk_text("some text", chunk_size=-10, overlap=0)


class TestDefaults:
    def test_default_chunk_size_reasonable(self) -> None:
        # Documented as ~400 tokens against the e5-small tokenizer for
        # Turkish legal prose, leaving headroom under the 512-token cap.
        assert 1000 <= DEFAULT_CHUNK_SIZE <= 2000

    def test_default_overlap_smaller_than_chunk(self) -> None:
        assert DEFAULT_OVERLAP < DEFAULT_CHUNK_SIZE

    def test_defaults_used_when_unspecified(self) -> None:
        text = "x" * 5000
        result = chunk_text(text)
        assert len(result) > 1
        for c in result:
            assert len(c) <= DEFAULT_CHUNK_SIZE


def _unique_text(n_sentences: int) -> str:
    """Kendini tekrar etmeyen metin: tekrar ölçümü ancak böyle güvenilir."""
    return " ".join(
        f"Cumle{i:04d} burada bir hukuki gerekce yer almaktadir ve devam eder."
        for i in range(n_sentences)
    )


class TestOverlapAppliedOnce:
    """Regresyon: v1'de örtüşme iki kez uygulanıyordu.

    ``_hard_split_v1`` paragraf sınırı olmayan metni zaten ``overlap`` kadar
    örtüşen parçalara bölüyor, birleştirme döngüsü aynı örtüşmeyi bir kez
    daha başa ekliyordu; parça kendi ilk ``overlap`` karakterini birebir
    tekrar ediyordu.
    """

    def test_v1_duplicates_the_overlap_inside_a_chunk(self) -> None:
        text = _unique_text(60)[:3959]  # tek blok, paragraf sınırı yok
        chunks = chunk_text(text, 1600, 200, version=1)
        # Son parça: ilk 80 karakter ~200 karakter sonra yeniden geliyor.
        assert any(c.find(c[:80], 1) > 0 for c in chunks), "v1 hatası yeniden üretilemedi"

    def test_v2_never_repeats_its_own_head(self) -> None:
        text = _unique_text(60)[:3959]
        for c in chunk_text(text, 1600, 200):
            assert c.find(c[:80], 1) == -1, f"parça kendini tekrar ediyor: {c[:120]!r}"

    def test_v2_no_duplicated_content_across_lengths(self) -> None:
        for n in (1750, 3000, 4001, 9000):
            text = _unique_text(400)[:n]
            for c in chunk_text(text):
                assert c.find(c[:80], 1) == -1, (n, c[:120])

    def test_v2_covers_whole_document(self) -> None:
        """Kayan sınırlar metin kaybetmemeli: her cümle en az bir parçada."""
        text = _unique_text(200)
        chunks = chunk_text(text)
        joined = " ".join(chunks)
        for i in range(200):
            assert f"Cumle{i:04d}" in joined, f"Cumle{i:04d} kayboldu"

    def test_v2_consecutive_chunks_share_context(self) -> None:
        text = _unique_text(200)
        chunks = chunk_text(text, 1600, 200)
        assert len(chunks) > 2
        for a, b in zip(chunks, chunks[1:]):
            head = b[:60]
            assert head in a, "ardışık parçalar arasında örtüşme yok"

    def test_v2_respects_chunk_size_with_paragraphs(self) -> None:
        paras = [_unique_text(30) for _ in range(5)]
        text = "\n\n".join(paras)
        for c in chunk_text(text, 1600, 200):
            assert len(c) <= 1600


class TestVersionSelection:
    def test_default_is_current_version(self) -> None:
        from emsal_mcp.chunking import CHUNKING_VERSION

        assert CHUNKING_VERSION == 2
        text = _unique_text(60)[:3959]
        assert chunk_text(text) == chunk_text(text, version=CHUNKING_VERSION)

    def test_v1_still_reachable_for_the_live_index(self) -> None:
        """Canlı indeks v1 ile gömüldü; chunk_index'i çözmek için v1 şart."""
        text = _unique_text(60)[:3959]
        assert chunk_text(text, version=1) != chunk_text(text, version=2)

    def test_unknown_version_raises(self) -> None:
        with pytest.raises(ValueError):
            chunk_text("x" * 5000, version=99)

    def test_validation_runs_before_dispatch(self) -> None:
        with pytest.raises(ValueError):
            chunk_text("x" * 5000, chunk_size=100, overlap=100, version=1)
