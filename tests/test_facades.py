"""M-101 facade equivalence and dispatch tests."""

from __future__ import annotations

from pathlib import Path
import importlib
from types import SimpleNamespace

import pytest

from emsal_mcp import facades


def _result(name: str, **kwargs):
    return {"ok": True, "called": name, **kwargs}


@pytest.mark.parametrize(
    ("mode", "module_name", "func_name", "expected"),
    [
        ("semantic", "emsal_mcp.semantic", "semantic_search", "semantic_search"),
        ("hybrid", "emsal_mcp.semantic", "hybrid_search", "hybrid_search"),
        ("rrf", "emsal_mcp.semantic", "hybrid_search_rrf", "hybrid_search_rrf"),
    ],
)
def test_search_local_corpus_dispatches_semantic_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    module_name: str,
    func_name: str,
    expected: str,
) -> None:
    module = __import__(module_name, fromlist=[func_name])
    monkeypatch.setattr(
        module,
        func_name,
        lambda **kwargs: _result(expected, kwargs=kwargs),
    )
    monkeypatch.setattr(
        facades,
        "Cache",
        lambda: SimpleNamespace(
            db=SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: [500])),
            close=lambda: None,
        ),
        raising=False,
    )

    assert facades.search_local_corpus("x", mode=mode, limit=3)["called"] == expected


def test_search_local_corpus_dispatches_embedding_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import emsal_mcp.semantic as semantic

    monkeypatch.setattr(
        semantic,
        "embedding_search",
        lambda **kwargs: _result("embedding_search", kwargs=kwargs),
    )
    monkeypatch.setattr(
        facades,
        "Cache",
        lambda: SimpleNamespace(
            db=SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: [500])),
            close=lambda: None,
        ),
        raising=False,
    )

    result = facades.search_local_corpus("x", mode="semantic", provider="p")

    assert result["called"] == "embedding_search"
    assert result["kwargs"]["provider"] == "p"


def test_search_local_corpus_dispatches_lexical(monkeypatch: pytest.MonkeyPatch) -> None:
    import emsal_mcp.cache as cache

    class FakeCache:
        def search_local(self, **kwargs):
            self.kwargs = kwargs
            return [{"id": 1}]

        def close(self):
            pass

    monkeypatch.setattr(cache, "Cache", FakeCache)

    result = facades.search_local_corpus("x", mode="lexical", limit=4)

    assert result["ok"] is True
    assert result["total_matches"] == 1
    assert result["results"][0]["id"] == 1
    # Enrichment (Görev 7) may add related_quotes; assert it exists.
    assert "related_quotes" in result["results"][0]


@pytest.mark.parametrize(
    ("scope", "expected"),
    [("law", "search_legislation"), ("article", "search_legislation_articles")],
)
def test_search_legislation_dispatches_scope(
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    expected: str,
) -> None:
    import emsal_mcp.legislation as legislation

    monkeypatch.setattr(
        legislation,
        "search_legislation",
        lambda **kwargs: _result("search_legislation", kwargs=kwargs),
    )
    monkeypatch.setattr(
        legislation,
        "search_legislation_articles",
        lambda **kwargs: _result("search_legislation_articles", kwargs=kwargs),
    )

    assert facades.search_legislation("borc", scope=scope)["called"] == expected


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ("document", "get_legislation_document"),
        ("article_tree", "get_legislation_article_tree"),
        ("gerekce", "get_legislation_gerekce"),
    ],
)
def test_get_legislation_dispatches_part(
    monkeypatch: pytest.MonkeyPatch,
    part: str,
    expected: str,
) -> None:
    import emsal_mcp.legislation as legislation

    monkeypatch.setattr(
        legislation,
        "get_legislation_document",
        lambda **kwargs: _result("get_legislation_document", kwargs=kwargs),
    )
    monkeypatch.setattr(
        legislation,
        "get_legislation_article_tree",
        lambda **kwargs: _result("get_legislation_article_tree", kwargs=kwargs),
    )
    monkeypatch.setattr(
        legislation,
        "get_legislation_gerekce",
        lambda **kwargs: _result("get_legislation_gerekce", kwargs=kwargs),
    )

    assert facades.get_legislation("doc-1", part=part)["called"] == expected


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("verify", "verify_legal_citation"),
        ("format", "format_legal_citation"),
        ("format_legislation", "format_legislation_citation"),
    ],
)
def test_citation_check_dispatches_actions(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    expected: str,
) -> None:
    import emsal_mcp.citation as citation
    import emsal_mcp.legislation as legislation

    monkeypatch.setattr(
        citation,
        "verify_legal_citation",
        lambda **kwargs: _result("verify_legal_citation", kwargs=kwargs),
    )
    monkeypatch.setattr(
        citation,
        "format_legal_citation",
        lambda **kwargs: _result("format_legal_citation", kwargs=kwargs),
    )
    monkeypatch.setattr(
        legislation,
        "format_legislation_citation",
        lambda **kwargs: _result("format_legislation_citation", kwargs=kwargs),
    )

    assert facades.citation_check(action=action, document={})["called"] == expected


def test_citation_check_dispatches_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    import emsal_mcp.safety as safety

    monkeypatch.setattr(
        safety,
        "citation_check",
        lambda doc: SimpleNamespace(model_dump=lambda mode: _result("citation_safety")),
    )

    result = facades.citation_check(
        action="safety",
        document_dict={"source": "s", "document_id": "d", "title": "t"},
    )

    assert result["called"] == "citation_safety"


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ("input_pack", "prepare_drafting_input_pack"),
        ("outline", "prepare_petition_outline"),
        ("controlled_draft", "prepare_controlled_petition_draft"),
    ],
)
def test_prepare_petition_dispatches_steps(
    monkeypatch: pytest.MonkeyPatch,
    step: str,
    expected: str,
) -> None:
    import emsal_mcp.petition as petition

    monkeypatch.setattr(
        petition,
        "prepare_drafting_input_pack",
        lambda **kwargs: _result("prepare_drafting_input_pack", kwargs=kwargs),
    )
    monkeypatch.setattr(
        petition,
        "prepare_petition_outline",
        lambda **kwargs: _result("prepare_petition_outline", kwargs=kwargs),
    )
    monkeypatch.setattr(
        petition,
        "prepare_controlled_petition_draft",
        lambda **kwargs: _result("prepare_controlled_petition_draft", kwargs=kwargs),
    )

    result = facades.prepare_petition(
        step=step,
        matter="m",
        issue="i",
        documents=[{"source": "s", "document_id": "d", "title": "t"}],
        pack_dir="pack",
    )

    assert result["called"] == expected


@pytest.mark.parametrize(
    ("fmt", "module_name", "func_name", "expected"),
    [
        ("capabilities", "emsal_mcp.exporter", "get_export_capabilities", "get_export_capabilities"),
        ("docx", "emsal_mcp.exporter", "prepare_docx_export", "prepare_docx_export"),
        ("plain", "emsal_mcp.exporter", "export_plain_text", "export_plain_text"),
        ("bundle", "emsal_mcp.exporter", "prepare_export_package_bundle", "prepare_export_package_bundle"),
    ],
)
def test_export_document_dispatches_exporter_formats(
    monkeypatch: pytest.MonkeyPatch,
    fmt: str,
    module_name: str,
    func_name: str,
    expected: str,
) -> None:
    module = __import__(module_name, fromlist=[func_name])
    monkeypatch.setattr(module, func_name, lambda **kwargs: _result(expected, kwargs=kwargs))

    assert facades.export_document(format=fmt, draft_path="d.md", pack_dir="p")["called"] == expected


def test_export_document_dispatches_udf(monkeypatch: pytest.MonkeyPatch) -> None:
    import emsal_mcp.udf as udf

    monkeypatch.setattr(udf, "write_udf", lambda *args, **kwargs: Path("out.udf"))

    assert facades.export_document(format="udf", text="x", experimental=True)["path"] == "out.udf"


def test_export_document_pdf_structured_error() -> None:
    result = facades.export_document(format="pdf", draft_path="")

    assert result["ok"] is False


def test_read_legal_file_dispatches_udf(monkeypatch: pytest.MonkeyPatch) -> None:
    import emsal_mcp.udf as udf

    monkeypatch.setattr(udf, "read_udf", lambda path: "udf text")
    monkeypatch.setattr(udf, "probe_udf", lambda path: {"ok": True})

    result = facades.read_legal_file("file.udf")

    assert result["ok"] is True
    assert result["text"] == "udf text"
    assert result["format"] == "udf"


def test_read_legal_file_dispatches_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    import emsal_mcp.pdf_extractor as pdf_extractor

    monkeypatch.setattr(
        pdf_extractor,
        "extract_pdf_text_from_file",
        lambda path, ocr_enabled=False: _result("extract_pdf_text", path=path),
    )

    assert facades.read_legal_file("file.pdf")["called"] == "extract_pdf_text"


def test_read_legal_file_unknown_extension_is_structured_error() -> None:
    result = facades.read_legal_file("file.txt")

    assert result["ok"] is False
    assert result["errorCode"] == "UNSUPPORTED_FORMAT"


@pytest.mark.parametrize(
    ("detail", "expected_key"),
    [(None, "sources"), ("birim_codes", "codes"), ("legislation_types", "types")],
)
def test_list_sources_dispatches_details(
    monkeypatch: pytest.MonkeyPatch,
    detail: str | None,
    expected_key: str,
) -> None:
    import emsal_mcp.birim_enum as birim_enum
    import emsal_mcp.legislation as legislation
    registry = importlib.import_module("emsal_mcp.sources.registry")

    monkeypatch.setattr(registry, "capabilities", lambda: [{"source": "s"}])
    monkeypatch.setattr(birim_enum, "list_birim_codes", lambda court=None: ["H1"])
    monkeypatch.setattr(legislation, "get_legislation_types", lambda: ["KANUN"])

    result = facades.list_sources(detail=detail)

    assert result["ok"] is True
    assert expected_key in result


def test_health_check_contains_expected_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    import emsal_mcp.circuit as circuit
    import emsal_mcp.semantic as semantic
    registry = importlib.import_module("emsal_mcp.sources.registry")

    monkeypatch.setattr(registry, "smoke_all_sync", lambda online=False: [{"offline_ok": True}])
    monkeypatch.setattr(circuit, "get_all_sources_health", lambda: {"s": {"circuit_open": False}})
    monkeypatch.setattr(semantic, "get_index_status", lambda: {"ready": True})

    result = facades.health_check()

    assert result["ok"] is True
    assert {"source_results", "circuit_status", "index_status"} <= set(result)


def test_legal_research_guide_topic_contains_expected_keys() -> None:
    result = facades.legal_research_guide(topic="overview")

    assert result["ok"] is True
    assert result["topic"] == "overview"
    assert "content" in result
