"""M-110: every retired tool must still be reachable through its facade.

33 MCP tools were deleted because a core facade already covered them.  That is
only true if the facade's ``mode`` / ``action`` / ``format`` / ``part`` / ``step``
/ ``detail`` argument really dispatches to the same implementation.  These tests
assert exactly that, against the tools ``server.main()`` actually registers.

Replaces ``tests/test_facades.py``, which tested ``emsal_mcp.facades`` — a
parallel module the server never imported.

Hermetic: every implementation is monkeypatched, so no network and no cache.
"""
from __future__ import annotations

import pytest

from tests.conftest import capture_registered_tools

pytestmark = [pytest.mark.integration]


def tools() -> dict:
    """Capture the registered tools (full profile).

    Call AFTER any ``_spy`` patch — see ``conftest.capture_registered_tools``.
    """
    return capture_registered_tools("full")


def _spy(monkeypatch, module_name: str, func_name: str, label: str):
    """Replace ``module.func`` with a recorder returning a marker dict."""
    module = __import__(module_name, fromlist=[func_name])
    monkeypatch.setattr(
        module,
        func_name,
        lambda *a, **kw: {"ok": True, "called": label, "args": a, "kwargs": kw},
    )


# ── search_local_corpus(mode=...) ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("mode", "func_name"),
    [
        ("hybrid", "hybrid_search"),
        ("rrf", "hybrid_search_rrf"),
    ],
)
def test_search_local_corpus_dispatches_semantic_modes(
    monkeypatch, mode, func_name
) -> None:
    _spy(monkeypatch, "emsal_mcp.semantic", func_name, func_name)
    result = tools()["search_local_corpus"](query="kıdem", mode=mode)
    assert result["called"] == func_name


def test_semantic_mode_prefers_dense_vectors_over_tfidf(monkeypatch) -> None:
    """M-112: with embeddings present, mode="semantic" must use them.

    It used to fall through to TF-IDF whenever ``provider`` was omitted, which
    left the corpus's 1.3M dense vectors unreachable from the default call.
    """
    _spy(monkeypatch, "emsal_mcp.semantic", "embedding_search", "dense")
    monkeypatch.setattr(
        "emsal_mcp.semantic.best_dense_provider", lambda *a, **kw: "somemodel",
    )
    result = tools()["search_local_corpus"](query="kıdem", mode="semantic")
    assert result["called"] == "dense"


def test_semantic_mode_falls_back_to_tfidf_without_vectors(monkeypatch) -> None:
    _spy(monkeypatch, "emsal_mcp.semantic", "semantic_search", "tfidf")
    monkeypatch.setattr(
        "emsal_mcp.semantic.best_dense_provider", lambda *a, **kw: None,
    )
    result = tools()["search_local_corpus"](query="kıdem", mode="semantic")
    assert result["called"] == "tfidf"


def test_search_local_corpus_unknown_mode_is_structured_error() -> None:
    # Used to fall through to rrf — the slowest path — so a typo looked
    # like a hang instead of an error.
    result = tools()["search_local_corpus"](query="kıdem", mode="lexcial")
    assert result["ok"] is False
    assert result["errorCode"] == "INVALID_INPUT"
    assert "lexical" in str(result.get("valid_modes"))


def test_search_local_corpus_flat_filters_reach_the_cache(monkeypatch) -> None:
    seen: dict = {}

    def fake_search_local(self, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr("emsal_mcp.cache.Cache.search_local", fake_search_local)
    tools()["search_local_corpus"](query="kıdem", court="Yargıtay", esas_no="2023/1")
    assert seen["court"] == "Yargıtay"
    assert seen["esas_no"] == "2023/1"


# ── search_legislation / get_legislation ───────────────────────────────────


def test_search_legislation_article_scope(monkeypatch) -> None:
    _spy(monkeypatch, "emsal_mcp.legislation", "search_legislation_articles", "articles")
    result = tools()["search_legislation"](query="madde", scope="article", document_id="1.5.6698")
    assert result["called"] == "articles"


def test_search_legislation_article_scope_requires_document_id() -> None:
    result = tools()["search_legislation"](query="madde", scope="article")
    assert result["ok"] is False
    assert result["errorCode"] == "INVALID_INPUT"


@pytest.mark.parametrize(
    ("part", "func_name"),
    [
        ("document", "get_legislation_document"),
        ("article_tree", "get_legislation_article_tree"),
        ("gerekce", "get_legislation_gerekce"),
    ],
)
def test_get_legislation_dispatches_parts(monkeypatch, part, func_name) -> None:
    _spy(monkeypatch, "emsal_mcp.legislation", func_name, func_name)
    result = tools()["get_legislation"](document_id="1.5.6698", part=part)
    assert result["called"] == func_name


# ── citation_check(action=...) ─────────────────────────────────────────────


def test_citation_check_verify(monkeypatch) -> None:
    _spy(monkeypatch, "emsal_mcp.citation", "verify_legal_citation", "verify")
    assert tools()["citation_check"](action="verify", text="x")["called"] == "verify"


def test_citation_check_format(monkeypatch) -> None:
    _spy(monkeypatch, "emsal_mcp.citation", "format_legal_citation", "format")
    result = tools()["citation_check"](action="format", source={"document_id": "d1"})
    assert result["called"] == "format"


def test_citation_check_format_legislation() -> None:
    # The retired format_legislation_citation tool had NO replacement action
    # until M-110 added one; a plain smoke call guards the regression.
    result = tools()["citation_check"](
        action="format_legislation",
        document={
            "title": "Test Kanun",
            "legislation_no": "7456",
            "gazette_date": "2023-07-15",
        },
        style="full",
    )
    assert "formatted_citation" in result


def test_citation_check_format_legislation_without_document() -> None:
    result = tools()["citation_check"](action="format_legislation")
    assert result["ok"] is False


def test_citation_check_safety() -> None:
    result = tools()["citation_check"](
        action="safety",
        document={
            "source": "bedesten",
            "document_id": "d1",
            "title": "K",
            "content_status": "metadata_only",
        },
    )
    assert "quoteUsable" in result


def test_citation_check_safety_without_document() -> None:
    result = tools()["citation_check"](action="safety")
    assert result["ok"] is False


# ── prepare_petition(step=...) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("step", "func_name"),
    [
        ("input_pack", "prepare_drafting_input_pack"),
        ("outline", "prepare_petition_outline"),
        ("controlled_draft", "prepare_controlled_petition_draft"),
    ],
)
def test_prepare_petition_dispatches_steps(monkeypatch, step, func_name) -> None:
    _spy(monkeypatch, "emsal_mcp.petition", func_name, func_name)
    result = tools()["prepare_petition"](
        matter="m", issue="i", step=step, pack_dir="p",
    )
    assert result["called"] == func_name


# ── export_document(format=...) ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fmt", "module_name", "func_name", "kwargs"),
    [
        ("capabilities", "emsal_mcp.exporter", "get_export_capabilities", {}),
        ("docx", "emsal_mcp.exporter", "prepare_docx_export", {"draft_path": "d.md"}),
        ("plain", "emsal_mcp.exporter", "export_plain_text", {"draft_path": "d.md"}),
        ("pdf", "emsal_mcp.exporter", "export_to_format", {"draft_path": "d.md"}),
        ("pdf", "emsal_mcp.udf", "convert_udf_to_pdf", {"udf_path": "a.udf"}),
        ("docx", "emsal_mcp.udf", "convert_udf_to_docx", {"udf_path": "a.udf"}),
        (
            "bundle",
            "emsal_mcp.exporter",
            "prepare_export_package_bundle",
            {"pack_dir": "p"},
        ),
    ],
)
def test_export_document_dispatches_formats(
    monkeypatch, fmt, module_name, func_name, kwargs
) -> None:
    _spy(monkeypatch, module_name, func_name, func_name)
    result = tools()["export_document"](format=fmt, **kwargs)
    assert result["called"] == func_name


def test_export_document_udf_from_text(monkeypatch, tmp_path) -> None:
    """format="udf" + text replaces the retired write_udf tool."""
    out = tmp_path / "o.udf"
    monkeypatch.setattr("emsal_mcp.udf.write_udf", lambda **kw: out)
    result = tools()["export_document"](format="udf", text="x", out_path=str(out))
    assert result["ok"] is True
    assert result["format"] == "udf"
    assert result["path"] == str(out)


def test_export_document_udf_from_docx(monkeypatch, tmp_path) -> None:
    """format="udf" + docx_path replaces the retired convert_docx_to_udf tool."""
    out = tmp_path / "o.udf"
    monkeypatch.setattr(
        "emsal_mcp.udf.docx_to_udf_native",
        lambda *a, **kw: {"ok": True, "out_path": str(out)},
    )
    result = tools()["export_document"](format="udf", docx_path="a.docx")
    assert result["ok"] is True
    assert result["path"] == str(out)


def test_export_document_pdf_without_input_is_structured_error() -> None:
    # This branch used to hand ``docx_path`` to a UDF converter, so md→pdf
    # was unreachable and docx→pdf silently produced garbage.
    result = tools()["export_document"](format="pdf")
    assert result["ok"] is False
    assert result["errorCode"] == "INVALID_INPUT"


# ── read_legal_file ────────────────────────────────────────────────────────


def test_read_legal_file_udf(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("emsal_mcp.udf.read_udf", lambda p: "UDF metni")
    monkeypatch.setattr("emsal_mcp.udf.probe_udf", lambda p: {"ok": True})
    result = tools()["read_legal_file"](file_path=str(tmp_path / "a.udf"))
    assert result["ok"] is True
    assert result["text"] == "UDF metni"
    assert result["format"] == "udf"


def test_read_legal_file_pdf(monkeypatch, tmp_path) -> None:
    _spy(monkeypatch, "emsal_mcp.pdf_extractor", "extract_pdf_text_from_file", "pdf")
    result = tools()["read_legal_file"](file_path=str(tmp_path / "a.pdf"))
    assert result["called"] == "pdf"


def test_read_legal_file_unknown_extension() -> None:
    result = tools()["read_legal_file"](file_path="a.txt")
    assert result["ok"] is False


# ── list_sources(detail=...) ───────────────────────────────────────────────


def test_list_sources_default() -> None:
    result = tools()["list_sources"]()
    assert result["ok"] is True
    assert len(result["sources"]) > 0


def test_list_sources_birim_codes() -> None:
    result = tools()["list_sources"](detail="birim_codes")
    assert result["ok"] is True
    assert len(result["codes"]) > 0


def test_list_sources_birim_codes_court_filter() -> None:
    all_codes = tools()["list_sources"](detail="birim_codes")["codes"]
    filtered = tools()["list_sources"](detail="birim_codes", court="Danistay")["codes"]
    assert 0 < len(filtered) < len(all_codes)


def test_list_sources_legislation_types() -> None:
    result = tools()["list_sources"](detail="legislation_types")
    assert result["ok"] is True
    assert len(result["types"]) > 0
