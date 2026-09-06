"""emsal_mcp.chunking — paragraph-aware text chunking for dense embedding indexing.

Why this exists
---------------
``multilingual-e5-small`` (see ``embeddings.FastEmbedMultilingualProvider``)
truncates its input at 512 tokens. Empirically, against the model's own
tokenizer, Turkish legal prose runs roughly 3.9-4.4 chars/token, so 512
tokens is on the order of 1,600-1,800 characters — call it ~1,800 chars of
safety margin once the "query: "/"passage: " prefix and special tokens are
accounted for.

Documents in this corpus range from a few hundred characters to ~224,000.
Embedding a long decision as a single vector means the model only ever sees
the first ~1,800 characters — typically the boilerplate ("Taraflar arasında
görülen dava...") that is nearly identical across thousands of decisions.
The actual reasoning, the part a semantic search needs to match on, lives
further down and would be silently discarded.

This module splits a document's text into overlapping chunks aligned to
paragraph boundaries where possible, so each chunk is a coherent unit that
fits inside the model's window, with enough overlap that a concept
straddling a chunk boundary is still captured whole in at least one chunk.
"""
from __future__ import annotations

import re

# ~1,600 chars ≈ 400 tokens against the e5-small tokenizer for typical
# Turkish legal prose (measured empirically) — leaves ~100 tokens of
# headroom under the 512-token truncation limit for the prefix, special
# tokens, and denser passages (citations, numbered lists) that tokenize
# less efficiently than prose.
DEFAULT_CHUNK_SIZE = 1600

# ~12% of chunk_size — enough that a sentence or clause split across a
# chunk boundary is still whole in the following chunk, without bloating
# the chunk count (and therefore storage/throughput) too much.
DEFAULT_OVERLAP = 200

_BLANK_LINE_RE = re.compile(r"\n\s*\n+")


def _split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty paragraphs.

    Tries blank-line-separated paragraphs first (the common case for
    markdown/html-derived decision text). Falls back to single newlines,
    then to the whole text as one paragraph if there are no line breaks
    at all.
    """
    paras = [p.strip() for p in _BLANK_LINE_RE.split(text) if p.strip()]
    if len(paras) > 1:
        return paras

    paras = [p.strip() for p in text.split("\n") if p.strip()]
    if len(paras) > 1:
        return paras

    return [text] if text else []


def _hard_split_v1(unit: str, chunk_size: int, overlap: int) -> list[str]:
    """v1 (hatalı, dondurulmuş): örtüşmeli kayan pencere.

    Split a single paragraph too large to fit in one chunk.

    Used when a paragraph itself exceeds ``chunk_size`` (e.g. a document
    with no paragraph breaks at all, or one enormous block of text).
    Falls back to a plain character sliding window since there is no
    structural boundary left to align to.
    """
    step = max(chunk_size - overlap, 1)
    pieces: list[str] = []
    i = 0
    n = len(unit)
    while i < n:
        pieces.append(unit[i : i + chunk_size])
        if i + chunk_size >= n:
            break
        i += step
    return pieces


def _chunk_text_v1(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split ``text`` into overlapping, paragraph-aligned chunks.

    Args:
        text: Full document text (full_text or markdown).
        chunk_size: Max chars per chunk. Default sized for e5-small's
            512-token window against Turkish legal prose (see module
            docstring).
        overlap: Chars of trailing context carried from one chunk into
            the start of the next, so content near a chunk boundary
            isn't split without any surrounding context in either chunk.

    Returns:
        List of chunk strings, in document order. Empty/whitespace-only
        input returns ``[]``. Input no longer than ``chunk_size`` returns
        a single-element list (the stripped text, unchanged) — no
        overlap logic applies when there's nothing to split.

    Raises:
        ValueError: if ``overlap >= chunk_size`` or either is non-positive.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    if not text or not text.strip():
        return []

    stripped = text.strip()
    if len(stripped) <= chunk_size:
        return [stripped]

    paragraphs = _split_paragraphs(stripped)

    # Expand any paragraph too big to fit a single chunk on its own.
    units: list[str] = []
    for p in paragraphs:
        if len(p) <= chunk_size:
            units.append(p)
        else:
            units.extend(_hard_split_v1(p, chunk_size, overlap))

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        # Current chunk is full — flush it and start the next one with
        # an overlapping tail of the chunk we just closed.
        if current:
            chunks.append(current)
            tail = current[-overlap:] if overlap > 0 else ""
        else:
            tail = ""

        with_tail = f"{tail}\n\n{unit}" if tail else unit
        if len(with_tail) <= chunk_size:
            current = with_tail
        else:
            # unit is already <= chunk_size (guaranteed by the expansion
            # step above); the tail is what pushed it over. Drop the tail
            # rather than violate the chunk_size contract.
            current = unit

    if current:
        chunks.append(current)

    return chunks


# ---------------------------------------------------------------------------
# v2 — örtüşme yalnız BİR kez uygulanır
# ---------------------------------------------------------------------------
#
# v1'in hatası: ``_hard_split_v1`` paragraf sınırı olmayan metni ZATEN
# ``overlap`` kadar örtüşen parçalara böler; ardından birleştirme döngüsü
# kapanan parçanın son ``overlap`` karakterini bir sonrakinin başına yeniden
# ekler.  Aynı örtüşme iki kez uygulanır: parça, aynı metni önce kuyruk
# olarak sonra parçanın kendi başlangıcı olarak içerir (ölçüm: 1.600/200 ile
# tek bloklu metinde son parça 200 karakteri birebir tekrar ediyor,
# ``... devam eder.\n\n... devam eder.``), sınırlar da ``overlap`` kadar
# kayar.  Tekrarlanan metin gömme vektörünü kendi kuyruğuna doğru çeker ve
# ``_best_chunk_text`` alıntısında görünür bir tekrara yol açar
# (bulk_index.py'deki temizleme kesmesi bu yüzden yazılmıştı).
#
# v2: sert bölme ÖRTÜŞMESİZ parçalar üretir (``chunk_size - overlap``
# boyunda), örtüşmeyi yalnız birleştirme döngüsü ekler.  Kuyruk parçaya
# sığmıyorsa tümden atılmaz, sığacak kadarı alınır; kuyruk kelime ortasından
# başlamasın diye ilk boşluğa kadar kırpılır.

#: Parçalama sürümü.  Sidecar/indeks meta'sına yazılır; bir indeks hangi
#: sürümle gömüldüyse ``chunk_index`` değerleri o sürüme göre anlamlıdır.
#: Eski (v1) indeksle üretilmiş meta'da alan yoktur → 1 varsayılır.
CHUNKING_VERSION = 2


def _hard_split_v2(unit: str, chunk_size: int, overlap: int) -> list[str]:
    """Tek bir paragrafı örtüşmesiz parçalara böl.

    Parça boyu ``chunk_size - overlap``: birleştirme döngüsü başa önceki
    parçanın kuyruğunu eklediğinde sonuç tam ``chunk_size``a oturur ve
    hiçbir metin iki kez yazılmaz.
    """
    step = max(chunk_size - overlap, 1)
    return [unit[i : i + step] for i in range(0, len(unit), step)]


def _chunk_text_v2(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    stripped = text.strip()
    if len(stripped) <= chunk_size:
        return [stripped]

    # (birim, yapıştırıcı): yapıştırıcı "" ise birim bir öncekinin metinde
    # DOĞRUDAN devamıdır (sert bölmenin parçaları) — araya "\n\n" konursa
    # sınıra denk gelen kelime ikiye bölünür ve hiçbir parçada bütün
    # görünmez.  Paragraflar arasında ise "\n\n" korunur.
    units: list[tuple[str, str]] = []
    for p in _split_paragraphs(stripped):
        if len(p) <= chunk_size:
            units.append((p, "\n\n"))
        else:
            for i, piece in enumerate(_hard_split_v2(p, chunk_size, overlap)):
                units.append((piece, "\n\n" if i == 0 else ""))

    chunks: list[str] = []
    current = ""
    for unit, glue in units:
        candidate = f"{current}{glue}{unit}" if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        tail = ""
        if current:
            chunks.append(current)
            room = chunk_size - len(unit) - len(glue)
            if overlap > 0 and room > 0:
                tail = current[-min(overlap, room):]
                if glue:
                    # Ayrı paragraf: kuyruk kelime ortasından başlamasın.
                    sp = tail.find(" ")
                    if 0 <= sp < len(tail) - 1:
                        tail = tail[sp + 1:]
        current = f"{tail}{glue}{unit}" if tail else unit

    if current:
        chunks.append(current)
    return chunks


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    *,
    version: int = CHUNKING_VERSION,
) -> list[str]:
    """Metni örtüşmeli, paragraf hizalı parçalara böl.

    Args:
        text: Belge metni (full_text ya da markdown).
        chunk_size: Parça başına en çok karakter.
        overlap: Bir parçanın sonundan bir sonrakinin başına taşınan
            karakter sayısı.
        version: 1 = eski (hatalı) parçalayıcı, YALNIZ v1 ile gömülmüş bir
            indeksin ``chunk_index`` değerlerini yeniden çözmek için;
            2 = güncel.  Yeni gömmeler her zaman ``CHUNKING_VERSION``.

    Returns:
        Belge sırasında parça listesi.  Boş/boşluk girdi ``[]`` döner.

    Raises:
        ValueError: ``overlap >= chunk_size``, ya da geçersiz sürüm.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    if not text or not text.strip():
        return []
    if version == 1:
        return _chunk_text_v1(text, chunk_size, overlap)
    if version != CHUNKING_VERSION:
        raise ValueError(f"bilinmeyen chunking sürümü: {version}")
    return _chunk_text_v2(text, chunk_size, overlap)
