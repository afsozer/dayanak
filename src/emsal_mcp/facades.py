"""FAZ M — Facade tool implementations (M-98).

Each facade wraps existing domain functions.  NO business logic is duplicated.
All facades respect the five invariants (no fabrication, citation safety,
graceful degradation, additive, no live network in tests).
"""

from __future__ import annotations

from typing import Any

from .models import build_error


# ── search_local_corpus facade ──────────────────────────────────────────

def search_local_corpus(
    query: str = "",
    mode: str = "rrf",
    limit: int = 10,
    filters: dict[str, Any] | None = None,
    provider: str | None = None,
    hybrid_weight: float = 0.6,
    rerank: bool = False,
    include_dense: bool = False,
    source: str | None = None,
    court: str | None = None,
    chamber: str | None = None,
    date: str | None = None,
    esas_no: str | None = None,
    karar_no: str | None = None,
    document_id: str | None = None,
    content_status: str | None = None,
    draft_usable: bool | None = None,
    quote_usable: bool | None = None,
    sort: str = "relevance",
) -> dict[str, Any]:
    """Unified local corpus search.

    ⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY.

    Re-ranks documents ALREADY fetched via ``search_decisions``. Cannot find
    new decisions.  The local cache is small (not a crawler).

    HARD RULE: call ``search_decisions`` (live, online) FIRST.

    Args:
        query: Search query string.
        mode: "lexical", "semantic", "hybrid", or "rrf" (default "rrf").
        limit: Max results.
        filters: Optional dict with source, court, chamber, content_status.
        provider: Optional embedding provider for semantic modes.
        hybrid_weight: Balance for hybrid mode (0.0-1.0, default 0.6).
        rerank: Cross-encoder reranking for hybrid mode.
        include_dense: Include dense embeddings in RRF.
        source/court/chamber/date/esas_no/karar_no/document_id: Filters.
        content_status/draft_usable/quote_usable: Content filters.
        sort: Sort order (lexical mode).

    Returns:
        Dict with ok, results, total_matches, method, optional hint.
    """
    from .cache import Cache
    from .semantic import (
        hybrid_search,
        hybrid_search_rrf,
        semantic_search,
    )

    filters = dict(filters or {})
    for key, val in [
        ("source", source), ("court", court), ("chamber", chamber),
        ("content_status", content_status), ("draft_usable", draft_usable),
        ("quote_usable", quote_usable),
    ]:
        if val is not None:
            filters[key] = val

    def _corpus_hint(result: dict) -> dict:
        if not isinstance(result, dict):
            return result
        try:
            c = Cache()
            try:
                corpus = c.db.execute(
                    "SELECT COUNT(*) FROM documents_v2"
                ).fetchone()[0]
            finally:
                c.close()
        except Exception:
            corpus = None
        total = result.get("total_matches", len(result.get("results") or []))
        if total == 0:
            result["hint"] = (
                "0 eslesme. Bu arac YALNIZCA daha once cekilmis belgelerde "
                "arar. Karar bulmak icin search_decisions (canli) aracini "
                "cagir; web aramasina basvurma."
            )
        elif corpus is not None and corpus < 200:
            result["hint"] = (
                f"Yerel cache yalnizca {corpus} belge iceriyor. Eksiksiz "
                "sonuc icin once search_decisions (canli) ile getir."
            )
        if result.get("hint") and corpus is not None:
            result["cache_document_count"] = corpus
        return result

    mode = mode.lower()

    if mode == "lexical":
        cache = Cache()
        try:
            results = cache.search_local(
                query=query, source=source, court=court, chamber=chamber,
                date=date, esas_no=esas_no, karar_no=karar_no,
                document_id=document_id, content_status=content_status,
                draft_usable=draft_usable, quote_usable=quote_usable,
                sort=sort, limit=limit,
            )
            return {"ok": True, "results": results, "total_matches": len(results)}
        finally:
            cache.close()

    if mode == "semantic":
        if provider:
            from .semantic import embedding_search as _emb
            return _corpus_hint(_emb(query=query, limit=limit, provider=provider))
        return _corpus_hint(semantic_search(
            query=query, limit=limit, filters=filters,
        ))

    if mode == "hybrid":
        return _corpus_hint(hybrid_search(
            query=query, limit=limit, filters=filters,
            hybrid_weight=hybrid_weight, rerank=rerank,
        ))

    if mode == "rrf":
        return _corpus_hint(hybrid_search_rrf(
            query=query, limit=limit, filters=filters,
            include_dense=include_dense,
        ))

    return build_error(
        "INVALID_ARGUMENT",
        f"Unknown mode: {mode!r}. Valid: lexical, semantic, hybrid, rrf.",
    )


# ── get_legislation facade ──────────────────────────────────────────────

def search_legislation(
    query: str,
    scope: str = "law",
    sources: list[str] | None = None,
    legislation_type: str | None = None,
    limit: int = 10,
    document_id: str | None = None,
    article_number: str | None = None,
    article_query: str | None = None,
    source: str | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search legislation at law or article scope."""
    from .legislation import (
        search_legislation as _search_law,
        search_legislation_articles as _search_articles,
    )

    scope = scope.lower()

    if scope == "law":
        return _search_law(
            query=query,
            sources=sources,
            legislation_type=legislation_type,
            limit=limit,
            sources_override=sources_override,
        )

    if scope == "article":
        return _search_articles(
            document_id=document_id or query,
            article_number=article_number,
            article_query=article_query or query,
            source=source,
            sources_override=sources_override,
        )

    return build_error(
        "INVALID_ARGUMENT",
        f"Unknown scope: {scope!r}. Valid: law, article.",
    )


def get_legislation(
    document_id: str,
    part: str = "document",
    source: str | None = None,
) -> dict[str, Any]:
    """Get legislation document, article tree, or gerekce.

    Args:
        document_id: Mevzuat document ID.
        part: "document", "article_tree", or "gerekce" (default "document").
        source: Source ID (default "mevzuat").

    Returns:
        Dict with ok, title, and part-specific fields.
    """
    from .legislation import (
        get_legislation_article_tree as _tree,
        get_legislation_document as _doc,
        get_legislation_gerekce as _gerekce,
    )

    part = part.lower()

    if part == "document":
        return _doc(document_id=document_id, source=source)

    if part == "article_tree":
        return _tree(document_id=document_id, source=source)

    if part == "gerekce":
        return _gerekce(document_id=document_id, source=source)

    return build_error(
        "INVALID_ARGUMENT",
        f"Unknown part: {part!r}. Valid: document, article_tree, gerekce.",
    )


# ── citation_check facade ───────────────────────────────────────────────

def citation_check(
    action: str = "verify",
    text: str | None = None,
    file_path: str | None = None,
    source: str | None = None,
    limit: int = 5,
    fetch: int = 3,
    no_live: bool = True,
    live_only: bool = False,
    min_score: float = 1.0,
    style: str = "petition",
    document: dict[str, Any] | None = None,
    document_id: str | None = None,
    document_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Citation verification, formatting, and safety checking.

    Args:
        action: "verify", "format", "format_legislation", or "safety"
                (default "verify").
        text/file_path: For verify action — text or file to check.
        source: Filter by source.
        limit/fetch/no_live/live_only/min_score: Verify params.
        style: "petition", "parenthetical", "short", "full", "article".
        document: Dict with metadata fields (for format actions).
        document_id: Look up from cache (for format actions).
        document_dict: For safety action — dict with document_id, source, etc.

    Returns:
        Action-specific result dict.
    """
    from .citation import (
        format_legal_citation as _fmt_legal,
        verify_legal_citation as _verify,
    )
    from .legislation import format_legislation_citation as _fmt_leg
    from .models import Document
    from .safety import citation_check as _safety

    action = action.lower()

    if action == "verify":
        return _verify(
            text=text, file_path=file_path, source=source,
            limit=limit, fetch=fetch, no_live=no_live,
            live_only=live_only, min_score=min_score,
        )

    if action == "format":
        return _fmt_legal(
            source=document or {}, document_id=document_id, style=style,  # type: ignore[arg-type]
        )

    if action == "format_legislation":
        return _fmt_leg(document=document or {}, style=style)  # type: ignore[arg-type]

    if action == "safety":
        doc = Document.model_validate(document_dict or {})
        return _safety(doc).model_dump(mode="json")

    return build_error(
        "INVALID_ARGUMENT",
        f"Unknown action: {action!r}. "
        f"Valid: verify, format, format_legislation, safety.",
    )


# ── prepare_petition facade ─────────────────────────────────────────────

def prepare_petition(
    step: str,
    matter: str = "",
    issue: str = "",
    documents: list[dict[str, Any]] | None = None,
    research_bundle_dir: str | None = None,
    out_dir: str | None = None,
    strict: bool = True,
    template_name: str | None = None,
    pack_dir: str = "",
    outline_path: str | None = None,
) -> dict[str, Any]:
    """Guided petition preparation workflow.

    Steps (use in order):
      1. ``step="input_pack"`` — classify documents and build a petition pack.
      2. ``step="outline"`` — generate structured outline from the pack.
      3. ``step="controlled_draft"`` — generate citation-safe draft.

    ALL drafts contain [DOGRULANMADI] markers. A human lawyer MUST review.

    Args:
        step: "input_pack", "outline", or "controlled_draft".
        matter/issue: For input_pack — legal matter and issue description.
        documents: Optional Document dicts to classify.
        research_bundle_dir: Optional research bundle path.
        out_dir: Output directory.
        strict: Exclude hash-mismatch docs.
        template_name: Optional template name.
        pack_dir: Path to petition pack (for outline and controlled_draft).
        outline_path: Optional pre-computed outline.json.

    Returns:
        Dict with ok, out_dir, and step-specific fields.
    """
    from .models import Document
    from .petition import (
        prepare_controlled_petition_draft as _draft,
        prepare_drafting_input_pack as _input_pack,
        prepare_petition_outline as _outline,
    )

    step = step.lower()

    if step == "input_pack":
        docs = [Document.model_validate(d) for d in (documents or [])]
        return _input_pack(
            matter=matter, issue=issue, documents=docs,
            research_bundle_dir=research_bundle_dir, out_dir=out_dir,
            strict=strict, template_name=template_name,
        )

    if step == "outline":
        return _outline(pack_dir=pack_dir, out_dir=out_dir)

    if step == "controlled_draft":
        return _draft(
            pack_dir=pack_dir, outline_path=outline_path, out_dir=out_dir,
        )

    return build_error(
        "INVALID_ARGUMENT",
        f"Unknown step: {step!r}. Valid: input_pack, outline, controlled_draft.",
    )


# ── export_document facade ──────────────────────────────────────────────

def export_document(
    format: str = "docx",
    draft_path: str = "",
    out_path: str | None = None,
    pack_dir: str | None = None,
    draft_json: dict[str, Any] | None = None,
    experimental: bool = False,
    text: str = "",
    title_centered: bool = False,
    draft_dir: str | None = None,
    docx_path: str | None = None,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """Export documents in multiple formats.

    Formats:
        ``"capabilities"`` — report available formats.
        ``"docx"`` — validated DOCX with disclaimer and footnotes.
        ``"udf"`` — UYAP UDF (requires toolkit, experimental=True).
        ``"pdf"`` — PDF via LibreOffice (requires toolkit).
        ``"plain"`` — plain-text (strips markdown).
        ``"bundle"`` — complete package with verification.

    Args:
        format: Export format (see above).
        draft_path: Path to draft.md.
        out_path: Optional output path.
        pack_dir: Pack directory for footnotes.
        draft_json: Draft metadata dict.
        experimental: Required for UDF format.
        text: Text for UDF export.
        title_centered: Center title in UDF.
        draft_dir/docx_path/out_dir: For bundle export.

    Returns:
        Format-specific result dict or error.
    """
    from .exporter import (
        export_plain_text as _plain,
        export_to_format as _export_to,
        get_export_capabilities as _caps,
        prepare_docx_export as _docx,
        prepare_export_package_bundle as _bundle,
    )
    from .udf import write_udf as _write_udf

    fmt = format.lower()

    if fmt == "capabilities":
        return _caps()

    if fmt == "docx":
        return _docx(
            draft_path=draft_path or None, draft_json=draft_json,
            out_path=out_path, pack_dir=pack_dir,
        )

    if fmt == "udf":
        if not experimental:
            return build_error(
                "EXPERIMENTAL_REQUIRED",
                "UDF export requires experimental=True. Bu deneysel bir "
                "ozelliktir; UYAP Dokuman Editoru ile manuel dogrulama gerekir.",
                warnings=["UDF ciktisi UYAP'ta manuel kontrol edilmelidir."],
            )
        path_result = _write_udf(
            text, out_path or "output.udf", title_centered=title_centered,
        )
        return {"ok": True, "path": str(path_result)}

    if fmt == "pdf":
        return _export_to(
            draft_path=draft_path, format="pdf", out_path=out_path,
            pack_dir=pack_dir, experimental=experimental,
        )

    if fmt == "plain":
        return _plain(draft_path=draft_path, out_path=out_path)

    if fmt == "bundle":
        return _bundle(
            pack_dir=pack_dir or "", draft_dir=draft_dir,
            docx_path=docx_path, out_dir=out_dir,
        )

    return build_error(
        "INVALID_ARGUMENT",
        f"Unknown format: {format!r}. "
        f"Valid: capabilities, docx, udf, pdf, plain, bundle.",
    )


# ── read_legal_file facade ──────────────────────────────────────────────

def read_legal_file(
    path: str,
    ocr_enabled: bool = False,
    title_centered: bool = False,
) -> dict[str, Any]:
    """Read a legal file (.udf or .pdf) and return text content.

    Args:
        path: File path.
        ocr_enabled: Enable OCR for PDF.
        title_centered: Center title in UDF.

    Returns:
        Dict with text and file metadata, or error.
    """
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    if ext == "udf":
        from .udf import probe_udf as _probe, read_udf as _read_udf
        try:
            return {
                "ok": True,
                "text": _read_udf(path),
                "probe": _probe(path),
                "path": path,
                "format": "udf",
            }
        except Exception as exc:
            return build_error(
                "FILE_READ_ERROR",
                f"UDF dosyasi okunamadi: {exc}",
                warnings=[str(exc)],
                path=path,
                format="udf",
            )

    if ext == "pdf":
        from .pdf_extractor import extract_pdf_text_from_file as _pdf
        return _pdf(path, ocr_enabled=ocr_enabled)

    return build_error(
        "UNSUPPORTED_FORMAT",
        f"Desteklenmeyen dosya uzantisi: .{ext!r}. "
        f"Desteklenen uzantilar: .udf, .pdf.",
        path=path,
        extension=ext,
        supported_extensions=["udf", "pdf"],
    )


# ── list_sources facade ─────────────────────────────────────────────────

def list_sources(
    detail: str | None = None,
    court: str | None = None,
) -> dict[str, Any]:
    """List available sources and their capabilities.

    Args:
        detail: "birim_codes" for chamber/unit codes, "legislation_types"
                for legislation types.  Omit for capability matrix.
        court: Filter for birim_codes ("Yargitay", "Danistay", "Askeri").

    Returns:
        Dict with sources/capability info.
    """
    from .birim_enum import list_birim_codes as _bc
    from .legislation import get_legislation_types as _lt
    from .sources.registry import capabilities as _caps

    if detail == "birim_codes":
        return {"ok": True, "detail": "birim_codes", "codes": _bc(court=court)}

    if detail == "legislation_types":
        return {"ok": True, "detail": "legislation_types", "types": _lt()}

    return {"ok": True, "sources": _caps()}


# ── legal_research_guide ────────────────────────────────────────────────

_GUIDE_OVERVIEW = """\
## Emsal-MCP Hangi Arac Ne Zaman?

### 1. Canli Arama (ZORUNLU ILK ADIM)
search_decisions: HER karar/mevzuat sorusunda ILK arac. Canli kaynaklarda
arama yapar. Hicbir karari hafizadan/web'den yanitlama.

### 2. Yerel Korpus (Yeniden Siralama)
search_local_corpus: YALNIZCA search_decisions ile cekilmis belgeleri
yeniden siralar. Yeni karar BULAMAZ. Once search_decisions calistir.

### 3. Mevzuat
search_legislation: Mevzuat metinlerinde arama. scope="article" ile madde.
get_legislation: Mevzuat dokumani/madde agaci/gerekce getir.

### 4. Toplu Arastirma
research_topic: Birden cok kaynaktan toplu arama + arastirma paketi.

### 5. Atif Kontrolu
citation_check: action="verify" dogrula, "format" bicimlendir, "safety" kontrol.

### 6. Dilekce
prepare_petition: step="input_pack" → "outline" → "controlled_draft".
[DOGRULANMADI] isaretleri icerir; avukat kontrolu sart.

### 7. Disa Aktarma
export_document: format="docx"/"udf"/"pdf"/"plain"/"bundle".

### 8. Dosya Okuma
read_legal_file: .udf veya .pdf oku.

### 9. Kaynak Listesi
list_sources: Kaynak yetenek matrisi + detail="birim_codes"/"legislation_types".

### 10. Sistem Sagligi
health_check: Kaynak, indeks, devre kesici tek cagrida.

### 11. Genisletilmis Araclar
load_extended_tools: Ek arac kategorilerini yukle.
legal_research_guide: Bu rehberi tekrar goruntule.
"""

_GUIDE_SEARCH_HYGIENE = """\
## Sorgu Hijyeni ve Bedesten Solr Operatorleri

### Temel Kurallar
- Sorguyu 2-5 hukuki anahtar kelimeye indir.
- Turkce aksanlari KORU: "karari" ✓, "karari" ✗

### ⚠️ Onemli: Varsayilan Operator OR'dur
Bedesten Solr'da CIPLAK terimler arasi BOSLUK = OR demektir (UNION).
`tahliye taahhüdü geçerlilik` → bu 3 kelimeden HERANGI birini iceren kararlar.
Birden fazla kavrami ZORUNLU kilmak icin HER terime `+` koy veya BUYUK
harfle AND kullan.

### Solr Operatorleri (search_decisions query icine)
| Operator       | Anlami                                  |
|----------------|-----------------------------------------|
| +required      | Terim MUTLAKA bulunmali: +tazminat      |
| -excluded      | Disla: -bolge                           |
| "exact"        | Tam ifade: "is kazasi"                  |
| AND / OR / NOT | BUYUK harfle boolean                    |
| (grouping)     | Gruplama: (+isci OR +memur) +tazminat   |
| * wildcard     | Sonek jokeri: tazmin*                   |

### Guvenlik Agi (Otomatik Yeniden Yazim)
Operator icermeyen (+, -, ", AND, OR, NOT, parantez YOK) duz cok-kelimeli
sorgular emsal-mcp tarafindan otomatik olarak her terimi + ile zorunlu hale
getirilecek sekilde yeniden yazilir. Bu, OR-varsayilinin gurultu dondurmesini
engeller. Yine de kesinlik icin acikca + veya AND kullan.

### Ornek Sorgular
- +isci +tazminat → HER IKI terim zorunlu
- +"is kazasi" +tazminat → tam ifade + terim
- (+isci OR +memur) +tazminat -manevi → isci/memur + tazminat, manevi haric

### Yanlis Ornekler (OR'a donusur, kacinin)
- tahliye taahhüdü geçerlilik → 3 kelimenin OR'u = cogunlukla ilgisiz
- boşanma tazminat* → OR, "boşanma AND tazminat*" DEGIL
"""

_GUIDE_SOURCES = """\
## Kaynaklar ve Daire Kodlari

Mevcut kaynak yetenekleri: list_sources
Daire kodlari (79 kod): list_sources(detail="birim_codes")
Mevzuat turleri: list_sources(detail="legislation_types")

Daire kodu kullanimi: search_decisions birimAdi="3. Hukuk Dairesi"
"""

_GUIDE_CITATION_SAFETY = """\
## Atif Guvenligi Kurallari

### Guvenlik Seviyeleri
- **quoteUsable=true**: Tam metin/HTML mevcut → alinti yapilabilir.
- **draftUsable=true**: Taslakta referans verilebilir.

### Icerik Durumlari
1. FULL_TEXT — tam metin alinmis, alintilanabilir.
2. HTML_MARKDOWN — HTML'den donusturulmus, alintilanabilir.
3. METADATA_ONLY — yalnizca baslik/tarih, ICERIK YOK, atif yapilamaz.
4. PDF_ONLY — PDF var ama metin cikarilmamis. read_legal_file ile cikar.

### Altin Kural
YALNIZCA quoteUsable=true belgelerden dogrudan alinti yap.
"""

_GUIDE_EXTENDED = """\
## Genisletilmis Arac Kategorileri

load_extended_tools ile yuklenebilir:

| Kategori        | Icerik                                      |
|-----------------|---------------------------------------------|
| cache_admin     | Cache yonetimi (istatistik, temizlik)       |
| release         | Surum yonetimi                              |
| analytics       | Arama analitigi                             |
| routing         | Kaynak yonlendirme                          |
| health_admin    | Devre kesici, hata katalogu                 |
| citation_graph  | Atif grafi olusturma/sorgulama              |
| dedup           | Tekrarsizlastirma                           |
| watch           | Arastirma takip                             |
| privacy         | PII tarama/maskeleme                        |
| chambers        | Daire profilleme                            |
| indexing        | Indeks yonetimi                             |
| drafting_advanced| Gelismis dilekce (inceleme, diff, sablon)  |
| udf_admin       | UDF/PDF toolkit yonetimi                    |
| research_admin  | Arastirma yonetimi                          |
| query_tools     | Sorgu araclari                              |
"""

_GUIDE_SECTIONS: dict[str, str] = {
    "overview": _GUIDE_OVERVIEW,
    "search_hygiene": _GUIDE_SEARCH_HYGIENE,
    "sources": _GUIDE_SOURCES,
    "citation_safety": _GUIDE_CITATION_SAFETY,
    "extended_categories": _GUIDE_EXTENDED,
}


def legal_research_guide(topic: str | None = None) -> dict[str, Any]:
    """Guide the agent on which tool to use when (pure-text reference).

    Args:
        topic: Optional section filter. Valid: "overview", "search_hygiene",
               "sources", "citation_safety", "extended_categories".

    Returns:
        Dict with ok, topic, sections list, and content.
    """
    if topic and topic.lower() in _GUIDE_SECTIONS:
        return {
            "ok": True,
            "topic": topic.lower(),
            "content": _GUIDE_SECTIONS[topic.lower()],
        }

    return {
        "ok": True,
        "topic": topic or "all",
        "sections": list(_GUIDE_SECTIONS.keys()),
        "content": "\n\n---\n\n".join(_GUIDE_SECTIONS.values()),
    }


# ── health_check facade ─────────────────────────────────────────────────

def health_check() -> dict[str, Any]:
    """Comprehensive health check: sources, circuit breakers, index status.

    Returns:
        Dict with ok, overall_healthy, source_healthy, circuit_healthy,
        source_results, circuit_status, index_status.
    """
    from .circuit import get_all_sources_health as _health
    from .semantic import get_index_status as _index
    from .sources.registry import smoke_all_sync as _smoke

    source_results = _smoke(online=False)
    source_ok = all(r.get("offline_ok", False) for r in source_results)

    circuit_status = _health()
    if isinstance(circuit_status, dict):
        circuit_healthy = not any(
            s.get("circuit_open", False)
            for s in circuit_status.values()
            if isinstance(s, dict)
        )
    else:
        circuit_healthy = True

    index_status = _index()

    return {
        "ok": True,
        "overall_healthy": source_ok and circuit_healthy,
        "source_healthy": source_ok,
        "source_results": source_results,
        "circuit_healthy": circuit_healthy,
        "circuit_status": circuit_status,
        "index_status": index_status,
    }


# ── load_extended_tools (M-99) ──────────────────────────────────────────
