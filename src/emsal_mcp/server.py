from __future__ import annotations

import json
from typing import Any

# M-52: All domain imports moved inside main() for faster cold-start.
# Only stdlib (json) is imported at module level.


def main() -> None:
    """Launch the MCP server with all registered tools.

    Imports FastMCP from the mcp package and registers all tool functions.
    Exits with an error message if the MCP extra is not installed.

    This is a stdio JSON-RPC MCP server, not a CLI. When started by an MCP
    client (stdin is a pipe), it enters the protocol loop. When a human runs
    it interactively (stdin is a TTY) or passes --help/--version, it prints a
    short usage note and exits instead of emitting confusing JSON parse errors.
    """
    import os
    import sys

    from . import __version__

    argv = sys.argv[1:]
    if argv and argv[0] in {"--version", "-V", "version"}:
        print(f"emsal-mcp-server {__version__}")
        return
    if (argv and argv[0] in {"--help", "-h", "help"}) or sys.stdin.isatty():
        print(
            f"emsal-mcp-server {__version__} - stdio MCP (JSON-RPC) sunucusu\n"
            "\n"
            "Bu bir CLI degil; bir MCP istemcisi (orn. Claude Desktop) tarafindan\n"
            "stdio uzerinden baslatilmak uzere tasarlanmistir. Elle/interaktif\n"
            "calistirip Enter'a basmak JSON-RPC parse hatasi uretir (beklenen).\n"
            "\n"
            "Komut satiri arac/komutlari icin:  emsal-mcp --help\n"
            "MCP istemci yapilandirmasi icin komut:  emsal-mcp-server\n",
            file=sys.stderr,
        )
        return

    from .cache import Cache
    from .server_utils import (
        # M-105: get_active_requests, get_error_codes removed (tools removed from MCP)
        validate_is_dict_with_keys,
        validate_non_empty,
        validate_positive_int,
        validate_range,
        validate_tool_input,
    )
    from .citation import format_legal_citation as format_legal_citation_impl, verify_legal_citation as verify_legal_citation_impl
    from .document import controlled_draft, export_bundle as export_bundle_impl
    from .legislation import (
        format_legislation_citation as format_legislation_citation_impl,
        get_legislation_article_tree as get_legislation_article_tree_impl,
        get_legislation_document as get_legislation_document_impl,
        get_legislation_gerekce as get_legislation_gerekce_impl,
        get_legislation_source_status as get_legislation_source_status_impl,
        get_legislation_types as get_legislation_types_impl,
        search_legislation as search_legislation_impl,
        search_legislation_articles as search_legislation_articles_impl,
    )
    from .chamber import (
        chamber_timeline as chamber_timeline_impl,
        find_similar_chambers as find_similar_chambers_impl,
        get_chamber_overview as get_chamber_overview_impl,
        profile_chamber as profile_chamber_impl,
    )
    from .citation_graph import (
        build_citation_graph as build_citation_graph_impl,
        export_graph as export_graph_impl,
        find_cited_documents as find_cited_documents_impl,
        find_citing_documents as find_citing_documents_impl,
        get_citation_graph as get_citation_graph_impl,
        get_citation_graph_stats as get_citation_graph_stats_impl,
    )
    from .privacy import (
        scan_pii as scan_pii_impl,
        redact_pii as redact_pii_impl,
        audit_privacy as audit_privacy_impl,
    )
    from .pdf_extractor import (
        extract_pdf_text_from_file as extract_pdf_text_impl,
        get_pdf_toolkit_status as get_pdf_toolkit_status_impl,
        promote_pdf_to_full_text as promote_pdf_to_full_text_impl,
    )
    from .semantic import (
        get_index_status as get_index_status_impl,
        hybrid_search as hybrid_search_impl,
        semantic_search as semantic_search_impl,
    )
    from .models import Document, build_error
    from .birim_enum import validate_birim_adi as _validate_birim_adi, list_birim_codes as _list_birim_codes
    from .petition import (
        build_multi_issue_pack as build_multi_issue_pack_impl,
        inspect_multi_issue_pack as inspect_multi_issue_pack_impl,
        inspect_petition_pack as inspect_petition_pack_impl,
        prepare_controlled_petition_draft as prepare_controlled_petition_draft_impl,
        prepare_drafting_input_pack as prepare_drafting_input_pack_impl,
        prepare_petition_outline as prepare_petition_outline_impl,
    )
    from .templates import (
        get_template as get_template_impl,
        list_templates as list_templates_impl,
    )
    # M-105: draft_diff imports removed (save_draft_version, get_fill_report,
    #        track_placeholders, diff_drafts removed from MCP; CLI-only)
    from .argument import (
        build_argument_chain as build_argument_chain_impl,
        score_argument as score_argument_impl,
        get_argument_strength_report as get_argument_strength_report_impl,
    )
    from .exporter import (
        export_plain_text as export_plain_text_impl,
        export_to_format as export_to_format_impl,
        get_export_capabilities as get_export_capabilities_impl,
        prepare_docx_export as prepare_docx_export_impl,
        prepare_export_package_bundle as prepare_export_package_bundle_impl,
    )
    from .research import research_topic as research_topic_impl
    from .safety import build_input_pack as build_input_pack_impl, citation_check as citation_check_impl
    from .sources.registry import capabilities, get_source, smoke_all_sync
    from .udf import (
        convert_docx_to_udf_experimental,
        convert_udf_to_docx,
        convert_udf_to_pdf,
        get_udf_authoring_instructions,
        get_udf_toolkit_status,
        # M-105: install_udf_toolkit removed (install_udf_toolkit_tool MCP removed)
        probe_udf,
        read_udf as read_udf_impl,
        write_udf as write_udf_impl,
    )
    # M-103: release.py trimmed to final_v1_readiness + version.
    # final_v1_readiness is no longer registered as an MCP tool (used by
    # CLI validation gate only).
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise SystemExit("MCP extra kurulu değil. Kurulum: pip install -e .[mcp]") from exc

    mcp = FastMCP("emsal-mcp")

    # ── M-97: Tool surface profile infrastructure ──────────────────────────
    _effective_profile = os.environ.get("EMSAL_TOOL_PROFILE", "core")
    if _effective_profile not in ("core", "full"):
        _effective_profile = "core"

    # _TOOL_PROFILES[name] = "core" | "extended"
    _TOOL_PROFILES: dict[str, str] = {
        # ── Core (14 tools) ─────────────────────────────────────────────
        "search_decisions":           "core",
        "get_document":               "core",
        "research_topic":             "core",  # M-98: renamed from research_topic_tool
        # ── Core facades (M-98) ─────────────────────────────────────────
        "search_local_corpus":        "core",
        "search_legislation":         "core",
        "get_legislation":            "core",
        "citation_check":             "core",
        "prepare_petition":           "core",
        "export_document":            "core",
        "read_legal_file":            "core",
        "list_sources":               "core",
        "legal_research_guide":       "core",
        "load_extended_tools":        "core",
        "health_check":               "core",
        # ── Extended: cache_admin ───────────────────────────────────────
        "search_local_cache":         "extended",
        # M-105: cache_admin tools removed from MCP (CLI-only)
        # M-103: release tools removed from MCP surface
        # M-105: routing tools removed from MCP (search_decisions handles routing)
        # ── Extended: health_admin ──────────────────────────────────────
        "circuit_breaker_status":     "extended",
        "source_health":              "extended",
        # M-105: reset_circuit, error_catalog, active_requests_count removed
        "source_smoke":               "extended",
        # ── Extended: citation_graph ────────────────────────────────────
        "build_citation_graph":       "extended",
        "get_citation_graph":         "extended",
        "find_citing_documents":      "extended",
        "find_cited_documents":       "extended",
        "citation_graph_stats":       "extended",
        "export_citation_graph":      "extended",
        # ── Extended: dedup ─────────────────────────────────────────────
        # M-105: dedup tools removed from MCP (corpus_builder handles dedup)
        # ── Extended: watch ─────────────────────────────────────────────
        "watch_add":                  "extended",
        "watch_list":                 "extended",
        "watch_run":                  "extended",
        "watch_remove":               "extended",
        # ── Extended: privacy ───────────────────────────────────────────
        "privacy_scan":               "extended",
        "privacy_redact":             "extended",
        "privacy_audit":              "extended",
        # ── Extended: chambers ──────────────────────────────────────────
        "chamber_overview":           "extended",
        "profile_chamber":            "extended",
        "chamber_timeline":           "extended",
        "find_similar_chambers":      "extended",
        # ── Extended: indexing ──────────────────────────────────────────
        # M-105: indexing tools removed from MCP except index_status
        "index_status":               "extended",
        "semantic_search":            "extended",
        "hybrid_search":              "extended",
        "hybrid_search_rrf":          "extended",
        "embedding_search":           "extended",
        # ── Extended: drafting_advanced ─────────────────────────────────
        "build_input_pack":           "extended",
        "draft_document":             "extended",
        "export_bundle":              "extended",
        "prepare_drafting_input_pack":"extended",
        "inspect_petition_pack":      "extended",
        "prepare_petition_outline":   "extended",
        "prepare_controlled_petition_draft": "extended",
        "build_multi_issue_pack":     "extended",
        "inspect_multi_issue_pack":   "extended",
        "list_petition_templates":    "extended",
        "get_petition_template":      "extended",
        # M-105: render_template_skeleton, diff_drafts, track_placeholders,
        #        get_fill_report, save_draft_version removed from MCP
        "build_argument_chain":       "extended",
        "score_argument":             "extended",
        "get_argument_strength_report":"extended",
        # ── Extended: legislation ──────────────────────────────────────
        "get_legislation_document":   "extended",
        "search_legislation_articles":"extended",
        "get_legislation_article_tree":"extended",
        "get_legislation_gerekce":    "extended",
        "legislation_source_status":  "extended",
        "format_legislation_citation":"extended",
        "get_legislation_types":      "extended",
        # ── Extended: citation ──────────────────────────────────────────
        "citation_safety":            "extended",
        "format_legal_citation":      "extended",
        "verify_legal_citation":      "extended",
        # ── Extended: udf_admin ─────────────────────────────────────────
        "read_udf":                   "extended",
        "write_udf":                  "extended",
        "udf_toolkit_status":         "extended",
        # M-105: install_udf_toolkit_tool removed from MCP (CLI-only)
        "udf_authoring_instructions":  "extended",
        "convert_udf_to_docx_tool":   "extended",
        "convert_udf_to_pdf_tool":    "extended",
        "convert_docx_to_udf_experimental_tool": "extended",
        "extract_pdf_text":           "extended",
        "pdf_toolkit_status":         "extended",
        "promote_pdf_to_full_text":   "extended",
        # ── Extended: export ────────────────────────────────────────────
        "prepare_docx_export":        "extended",
        "prepare_export_package_bundle":"extended",
        "export_plain_text":          "extended",
        "export_to_format":           "extended",
        "get_export_capabilities":    "extended",
        # ── Extended: discovery ─────────────────────────────────────────
        "source_capabilities":        "extended",
        "list_birim_codes":           "extended",
        "research_topic_tool":         "extended",
    }

    _TOOL_CATEGORIES: dict[str, str] = {
        "search_decisions":             "search",
        "get_document":                 "search",
        "search_local_corpus":          "search",
        "search_legislation":           "legislation",
        "get_legislation":              "legislation",
        "research_topic":               "research",
        "research_topic_tool":          "research",
        "citation_check":               "citation",
        "prepare_petition":             "petition",
        "export_document":              "export",
        "read_legal_file":              "file_io",
        "list_sources":                 "discovery",
        "legal_research_guide":         "guide",
        "load_extended_tools":          "admin",
        "health_check":                 "admin",
        # Extended categories
        "search_local_cache":           "cache_admin",
        # M-105: cache_admin tools removed from MCP surface
        # M-103: release category removed
        # M-105: routing tools removed from MCP surface
        # M-103: release category removed
        "circuit_breaker_status":       "health_admin",
        "source_health":                "health_admin",
        # M-105: reset_circuit, error_catalog, active_requests_count removed
        "source_smoke":                 "health_admin",
        "build_citation_graph":         "citation_graph",
        "get_citation_graph":           "citation_graph",
        "find_citing_documents":        "citation_graph",
        "find_cited_documents":         "citation_graph",
        "citation_graph_stats":         "citation_graph",
        "export_citation_graph":        "citation_graph",
        # M-105: dedup tools removed from MCP surface
        "watch_add":                    "watch",
        "watch_list":                   "watch",
        "watch_run":                    "watch",
        "watch_remove":                 "watch",
        "privacy_scan":                 "privacy",
        "privacy_redact":               "privacy",
        "privacy_audit":                "privacy",
        "chamber_overview":             "chambers",
        "profile_chamber":              "chambers",
        "chamber_timeline":             "chambers",
        "find_similar_chambers":        "chambers",
        # M-105: indexing tools removed from MCP except index_status
        "semantic_search":              "indexing",
        "hybrid_search":                "indexing",
        "hybrid_search_rrf":            "indexing",
        "index_status":                 "indexing",
        "embedding_search":             "indexing",
        "build_input_pack":             "drafting_advanced",
        "draft_document":               "drafting_advanced",
        "export_bundle":               "drafting_advanced",
        "prepare_drafting_input_pack":  "drafting_advanced",
        "inspect_petition_pack":        "drafting_advanced",
        "prepare_petition_outline":     "drafting_advanced",
        "prepare_controlled_petition_draft": "drafting_advanced",
        "build_multi_issue_pack":       "drafting_advanced",
        "inspect_multi_issue_pack":     "drafting_advanced",
        "list_petition_templates":      "drafting_advanced",
        "get_petition_template":        "drafting_advanced",
        # M-105: render_template_skeleton, diff_drafts, track_placeholders,
        #        get_fill_report, save_draft_version removed from MCP
        "build_argument_chain":         "drafting_advanced",
        "score_argument":               "drafting_advanced",
        "get_argument_strength_report": "drafting_advanced",
        "get_legislation_document":     "legislation",
        "search_legislation_articles":  "legislation",
        "get_legislation_article_tree": "legislation",
        "get_legislation_gerekce":      "legislation",
        "legislation_source_status":    "legislation",
        "format_legislation_citation":  "legislation",
        "get_legislation_types":        "legislation",
        "citation_safety":              "citation",
        "format_legal_citation":        "citation",
        "verify_legal_citation":        "citation",
        "read_udf":                     "udf_admin",
        "write_udf":                    "udf_admin",
        "udf_toolkit_status":           "udf_admin",
        # M-105: install_udf_toolkit_tool removed from MCP
        "udf_authoring_instructions":   "udf_admin",
        "convert_udf_to_docx_tool":     "udf_admin",
        "convert_udf_to_pdf_tool":      "udf_admin",
        "convert_docx_to_udf_experimental_tool": "udf_admin",
        "extract_pdf_text":             "udf_admin",
        "pdf_toolkit_status":           "udf_admin",
        "promote_pdf_to_full_text":     "udf_admin",
        "prepare_docx_export":          "export",
        "prepare_export_package_bundle":"export",
        "export_plain_text":            "export",
        "export_to_format":             "export",
        "get_export_capabilities":      "export",
        "source_capabilities":          "discovery",
        "list_birim_codes":             "discovery",
    }

    # Extended tool functions collected for dynamic loading (M-99)
    _EXTENDED_TOOLS: dict[str, Any] = {}

    def _tool(fn):
        """Decorator: conditionally register an MCP tool based on EMSAL_TOOL_PROFILE.

        In 'core' profile (default), only tools with profile='core' are registered.
        In 'full' profile, all tools are registered.
        Extended tools are collected in _EXTENDED_TOOLS for dynamic loading (M-99).
        """
        name = fn.__name__
        profile = _TOOL_PROFILES.get(name, "extended")
        if _effective_profile == "full" or profile == "core":
            return mcp.tool()(fn)
        else:
            _EXTENDED_TOOLS[name] = fn
            return fn

    def _attach_corpus_hint(result: dict) -> dict:
        """Runtime safety net: steer the model back to live search_decisions.

        Local search tools only search already-fetched documents. When they
        return nothing, or when the local cache is tiny, inject an explicit
        ``hint`` (and ``cache_document_count``) telling the caller to use the
        live `search_decisions` tool instead of trusting these results or
        falling back to web search.
        """
        if not isinstance(result, dict):
            return result
        try:
            c = Cache()
            try:
                corpus = c.db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
            finally:
                c.close()
        except Exception:
            corpus = None
        total = result.get("total_matches", len(result.get("results") or []))
        hint = None
        if total == 0:
            hint = (
                "0 eşleşme. Bu araç YALNIZCA daha önce çekilmiş belgelerde arar, "
                "canlı kaynakta DEĞİL. Karar bulmak için search_decisions (canlı) "
                "aracını çağır; web aramasına başvurma."
            )
        elif corpus is not None and corpus < 200:
            hint = (
                f"Yerel cache yalnızca {corpus} belge içeriyor (crawler/tam derlem "
                "DEĞİL). Eksiksiz ve güncel sonuç için önce search_decisions (canlı) "
                "ile getir; bu sonuçlar yalnızca çekilmiş belgelerin yeniden sıralamasıdır."
            )
        if hint:
            result["hint"] = hint
            if corpus is not None:
                result["cache_document_count"] = corpus
        return result

    @_tool
    @validate_tool_input(query=validate_non_empty, limit=validate_positive_int)
    async def search_decisions(
        source: str,
        query: str,
        limit: int = 10,
        page: int = 1,
        court_types: list[str] | None = None,
        birimAdi: str | None = None,
        karar_tarihi_start: str | None = None,
        karar_tarihi_end: str | None = None,
        esas_no: str | None = None,
        karar_no: str | None = None,
    ) -> list[dict] | dict:
        """✅ PRIMARY, MANDATORY TOOL FOR ALL CASE-LAW / DECISION / MEVZUAT RESEARCH.

        For ANY question about court decisions, precedents, case law, or
        legislation you MUST call THIS tool first. It is the ONLY tool that
        retrieves real, current documents LIVE from the official source
        (online — e.g. Bedesten/Yargıtay, Mevzuat).

        HARD RULES — no exceptions, no interpretation:
        - Do NOT answer case-law questions from memory, training data, or web search.
        - Do NOT use hybrid_search / semantic_search / embedding_search /
          search_local_cache to FIND decisions — those search ONLY the small
          local cache and only RE-RANK what THIS tool has already fetched.
          They cannot discover any decision that was not fetched here first.
        - Every esas/karar number, date, and chamber you cite MUST come from a
          document returned by THIS tool and verified via get_document full text.
        - If you have not called this tool yet, you have NO case law to cite.

        Fetched results are cached so the local re-ranking tools can operate on
        them afterward within the same session.

        --- QUERY HYGIENE (CRITICAL) ---
        - Do NOT paste the user's full question into the query string. The Bedesten
          Solr engine matches tokens, not natural language. Reduce the question to
          2–5 precise legal keywords.  Good: "işçi alacağı zamanaşımı" (3 terms).
          Bad: "işçinin fazla mesai ve kıdem tazminatı konusunda zamanaşımı süresi"
          (verbatim user question, too many noise tokens).
        - Preserve Turkish diacritics exactly. The Solr index is Turkish-aware;
          stripping diacritics silently drops matches. Use "kararı" ✓ not "karari" ✗,
          "geçici iş göremezlik" ✓ not "gecici is goremezlik" ✗.

        --- BEDESTEN SOLR OPERATOR COOKBOOK ---
        The Bedesten backend runs Apache Solr with StandardQueryParser.
        You can use these operators inside the `query` string:

        +required    Prefix + forces the term to appear (MUST match).  +tazminat
        -excluded    Prefix - excludes documents containing the term.  -bölge
        "exact"      Double quotes for phrase/exact match.  "iş kazası"
        AND / OR     UPPERCASE boolean operators (lowercase and/or are treated
                     as plain terms).  tazminat AND zamanaşımı
        NOT          UPPERCASE exclusion.  tazminat NOT manevi
        (grouping)   Parentheses for sub-expressions.  (+işçi OR +memur) +tazminat
        * wildcard   Suffix wildcard (use sparingly).  tazmin*

        Worked examples (query string → what it does):
          +işçi +tazminat                    → docs with BOTH "işçi" AND "tazminat"
          "iş kazası" tazminat               → exact phrase "iş kazası" AND term "tazminat"
          (+işçi OR +memur) +tazminat -manevi → (işçi OR memur) AND tazminat, exclude "manevi"
          boşanma tazminat*                  → "boşanma" AND any word starting "tazminat"
          kıdem AND ihbar AND tazminat       → all three terms required

        Notes:
        - Solr AND is the default operator for bare terms (tazminat zamanaşımı means
          tazminat AND zamanaşımı). OR must be explicit.
        - Overly broad queries (single common term like "karar") return noise; add
          at least one specific legal-term constraint.

        Args:
            source: Source identifier (e.g. 'bedesten', 'mevzuat').
            query: Search query string (must not be empty). For best results,
                craft a short 2–5 term keyword query using the operators above.
            limit: Max results (default 10, must be positive).
            page: Page number for pagination (default 1).
            court_types: Optional list of court item types for multi-court search
                in a single call. Bedesten values: YARGITAYKARARI, DANISTAYKARARI,
                YERELKARARI, ISTINAFKARARI, KYBKARAR. Defaults to the source's
                default type when omitted.
            birimAdi: Optional chamber/unit code (e.g. "1. Daire", "HGK").
                For the validated 79-option enum, see source_capabilities tool.
            karar_tarihi_start: Optional start date filter (ISO format,
                e.g. "2023-01-01"). Inclusive.
            karar_tarihi_end: Optional end date filter (ISO format,
                e.g. "2024-12-31"). Inclusive.
            esas_no: Optional case file number in YIL/SIRA format
                (e.g. "2023/1234"). Parsed into separate year/sequence int
                fields for the upstream API.
            karar_no: Optional decision number in YIL/SIRA format
                (e.g. "2023/5678"). Parsed into separate year/sequence int
                fields for the upstream API.

        Returns:
            List of matching document dicts.
        """
        # M-93: validate birimAdi against 79-code enum
        if birimAdi:
            birim_err = _validate_birim_adi(birimAdi)
            if birim_err is not None:
                return birim_err
        filters: dict[str, Any] = {}
        if court_types:
            filters["court_types"] = court_types
        if birimAdi:
            filters["birimAdi"] = birimAdi
        if karar_tarihi_start:
            filters["karar_tarihi_start"] = karar_tarihi_start
        if karar_tarihi_end:
            filters["karar_tarihi_end"] = karar_tarihi_end
        if esas_no:
            filters["esas_no"] = esas_no
        if karar_no:
            filters["karar_no"] = karar_no
        results = [r.model_dump(mode="json") for r in await get_source(source).search(query, limit=limit, page=page, **filters)]
        # Store search results in cache for later local search
        cache = Cache()
        cache.set(f"search:{source}:{query}:{limit}:{page}", results)
        cache.close()
        return results

    @_tool
    @validate_tool_input(document_id=validate_non_empty)
    async def get_document(source: str, document_id: str) -> dict:
        """Fetch a single document by ID from the given source.

        Args:
            source: Source identifier.
            document_id: Document ID (must not be empty).

        Returns:
            Document dict with all metadata and content fields.
        """
        doc = await get_source(source).get_document(document_id)
        cache = Cache()
        # M-65: merge cached provenance so standalone get has metadata
        _cached = cache.get_document(document_id, source)
        if _cached and _cached.esas_no:
            from .models import merge_search_metadata
            merge_search_metadata(doc, _cached)
        cache.set(f"doc:{source}:{document_id}", doc.model_dump(mode="json"))
        cache.store_document(doc)
        cache.log("get", {"source": source, "document_id": document_id})
        cache.close()
        return doc.model_dump(mode="json")

    @_tool
    def source_capabilities() -> list[dict]:
        """Return capability matrix for all registered sources."""
        return capabilities()

    @_tool
    def list_birim_codes(court: str | None = None) -> list[dict]:
        """Return the 79 validated birimAdi (chamber/unit) codes.

        Use these codes as the ``birimAdi`` parameter in ``search_decisions``
        to filter results by a specific Yargitay/Danistay chamber or assembly.

        Each entry includes the code, Turkish description, English description,
        and the parent court (Yargitay, Danistay, or Askeri).

        Args:
            court: Optional filter — "Yargitay", "Danistay", or "Askeri".
                   Returns all 79 codes when omitted.

        Returns:
            List of ``{code, description_tr, description_en, court}`` dicts.
        """
        return _list_birim_codes(court=court)

    @_tool
    def source_smoke(online: bool = False) -> dict:
        """Run per-source smoke tests. Offline by default, online opt-in."""
        results = smoke_all_sync(online=online)
        return {
            "ok": all(r.get("offline_ok", False) for r in results),
            "online_requested": online,
            "source_count": len(results),
            "sources": results,
        }

    @_tool
    @validate_tool_input(document=validate_is_dict_with_keys("document_id", "source"))
    def citation_safety(document: dict) -> dict:
        """Check citation safety of a document.

        Verifies full text availability, content status, and minimum provenance
        metadata. Returns ok=True only if the document is safe for quoting.

        Args:
            document: Document dict with document_id, source, and metadata fields.

        Returns:
            Dict with ok, quoteUsable, draftUsable, reasons, safety_state.
        """
        return citation_check_impl(Document.model_validate(document)).model_dump(mode="json")

    @_tool
    @validate_tool_input(matter=validate_non_empty, issue=validate_non_empty)
    def build_input_pack(matter: str, issue: str, documents: list[dict]) -> dict:
        """Build a citation-safe input pack for petition drafting.

        Filters unsafe documents and builds an InputPack with stable pack_id.

        Args:
            matter: Legal matter description (must not be empty).
            issue: Legal issue description (must not be empty).
            documents: List of Document dicts to classify.

        Returns:
            Dict with matter, issue, documents, safe_citations, excluded, warnings.
        """
        docs = [Document.model_validate(d) for d in documents]
        return build_input_pack_impl(matter, issue, docs).model_dump(mode="json")

    @_tool
    def draft_document(title: str, body: str, documents: list[dict]) -> dict:
        docs = [Document.model_validate(d) for d in documents]
        return {"markdown": controlled_draft(title, body, docs)}

    @_tool
    def export_bundle(out_dir: str, matter: str, issue: str, documents: list[dict]) -> dict:
        return export_bundle_impl(out_dir, matter=matter, issue=issue, docs=[Document.model_validate(d) for d in documents])

    @_tool
    def read_udf(path: str) -> dict:
        return {"text": read_udf_impl(path), "probe": probe_udf(path)}

    @_tool
    def write_udf(text: str, out_path: str, title_centered: bool = False) -> dict:
        return {"out_path": str(write_udf_impl(text, out_path, title_centered=title_centered)), "warning": "UYAP Doküman Editörü ile manuel doğrulama gerekir."}

    @_tool
    def udf_toolkit_status() -> dict:
        """Check UDF toolkit (LibreOffice/unoconv) availability."""
        return get_udf_toolkit_status()

    # M-105: install_udf_toolkit_tool removed from MCP (CLI-only)

    @_tool
    def udf_authoring_instructions(format: str = "json") -> dict:
        """Return UDF authoring instructions and warnings.

        Args:
            format: 'json' for structured dict, 'markdown' for human-readable text.
        """
        return get_udf_authoring_instructions(format=format)

    @_tool
    def convert_udf_to_docx_tool(file_path: str, out_path: str | None = None) -> dict:
        """Convert UDF to DOCX using LibreOffice (requires toolkit).

        Returns structured error dict if toolkit is unavailable.
        """
        return convert_udf_to_docx(file_path, out_path)

    @_tool
    def convert_udf_to_pdf_tool(file_path: str, out_path: str | None = None) -> dict:
        """Convert UDF to PDF using LibreOffice (requires toolkit).

        Returns structured error dict if toolkit is unavailable.
        """
        return convert_udf_to_pdf(file_path, out_path)

    @_tool
    def convert_docx_to_udf_experimental_tool(
        file_path: str, out_path: str | None = None, experimental: bool = False,
    ) -> dict:
        """Convert DOCX to UDF (experimental, requires toolkit).

        Must set experimental=True. Always returns UYAP manual round-trip warning.
        """
        return convert_docx_to_udf_experimental(file_path, out_path, experimental=experimental)

    # ── Cache v2 MCP tools ────────────────────────────────────────────

    @_tool
    def search_local_cache(
        query: str = "",
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
        limit: int = 20,
    ) -> list[dict]:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        Filters/looks up documents ALREADY fetched via `search_decisions`. It
        cannot find any decision that was not fetched first; the cache is small
        by design (not a crawler, not a full corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first — it is the primary, mandatory entry point. Use
        this tool only to filter/inspect already-fetched results. Never
        web-search, never cite esas/karar numbers not from a fetched full-text
        document.

        Supports filters: source, court, chamber, date, esas_no, karar_no,
        document_id, content_status, draft_usable, quote_usable.
        Sort options: relevance, decision_date_desc, decision_date_asc,
        fetched_at_desc, fetched_at_asc.
        Returns snippets around matching text.
        """
        cache = Cache()
        try:
            return cache.search_local(
                query=query, source=source, court=court, chamber=chamber,
                date=date, esas_no=esas_no, karar_no=karar_no,
                document_id=document_id, content_status=content_status,
                draft_usable=draft_usable, quote_usable=quote_usable,
                sort=sort, limit=limit,
            )
        finally:
            cache.close()

    # M-105: cache_admin MCP tools removed (CLI-only: emsal-mcp cache ...)

    # ── Research v0.5 MCP tools ────────────────────────────────────────

    @_tool
    def research_topic_tool(
        query: str,
        sources: list[str] | None = None,
        fetch_count: int = 5,
        filters: dict | None = None,
        output_dir: str | None = None,
    ) -> dict:
        """Search sources, fetch documents, and build a research bundle.

        Returns bundle metadata with query, sources, result_count, fetched_count,
        content_status_summary, citation_safe_count, generated_files, warnings,
        and recommended_next_steps.
        """
        return research_topic_impl(
            query=query,
            sources=sources,
            fetch_count=fetch_count,
            filters=filters or {},
            output_dir=output_dir,
        )

    # ── Citation v0.6 MCP tools ──────────────────────────────────────────

    @_tool
    def format_legal_citation(
        source: dict | None = None,
        document_id: str | None = None,
        style: str = "petition",
    ) -> dict:
        """Format a legal citation from document metadata.

        Args:
            source: Document dict with metadata fields.
            document_id: Document ID to look up from cache.
            style: 'petition', 'parenthetical', or 'short'.

        Returns:
            Dict with formatted_citation, warnings, confidence, usability flags.
        """
        return format_legal_citation_impl(
            source=source,
            document_id=document_id,
            style=style,  # type: ignore[arg-type]
        )

    @_tool
    def verify_legal_citation(
        text: str | None = None,
        file_path: str | None = None,
        source: str | None = None,
        limit: int = 5,
        fetch: int = 3,
        no_live: bool = True,
        live_only: bool = False,
        min_score: float = 1.0,
    ) -> dict:
        """Verify legal citations in text or file.

        Pipeline: extract candidates → search local cache → live search →
        rank by metadata match score → return structured result.

        Args:
            text: Text content to verify.
            file_path: Path to file to read.
            source: Filter to specific source.
            limit: Max candidates to extract.
            fetch: Max docs to fetch.
            no_live: Skip live search.
            live_only: Skip local cache search.
            min_score: Minimum match score threshold.

        Returns:
            Dict with candidates, matched_documents, formatted_citations,
            verification_findings, warnings, recommended_next_steps.
        """
        return verify_legal_citation_impl(
            text=text,
            file_path=file_path,
            source=source,
            limit=limit,
            fetch=fetch,
            no_live=no_live,
            live_only=live_only,
            min_score=min_score,
        )

    # ── Petition Pack v0.7 MCP tools ────────────────────────────────────────

    @_tool
    def prepare_drafting_input_pack(
        matter: str,
        issue: str,
        documents: list[dict] | None = None,
        research_bundle_dir: str | None = None,
        out_dir: str | None = None,
        strict: bool = True,
        template_name: str | None = None,
    ) -> dict:
        """Prepare a petition drafting input pack.

        Classifies authorities as petition_ready, citation_only,
        research_lead_only, or excluded.  Generates a structured pack
        directory with petition-brief.json, citation-bank.md, argument-map.md,
        petition-instructions.md, draft-skeleton.md, petition-pack.json,
        and source-documents/*.md.

        Args:
            matter: Legal matter description.
            issue: Legal issue description.
            documents: Optional list of Document dicts to classify.
            research_bundle_dir: Optional research bundle directory path.
            out_dir: Output directory for the pack.
            strict: If True, exclude hash-mismatch docs.
            template_name: Optional template name for the draft skeleton.

        Returns:
            Dict with ok, out_dir, draft_safe, counts, classifications,
            files, warnings, hash_manifest.
        """
        docs = [Document.model_validate(d) for d in (documents or [])]
        return prepare_drafting_input_pack_impl(
            matter=matter,
            issue=issue,
            documents=docs,
            research_bundle_dir=research_bundle_dir,
            out_dir=out_dir,
            strict=strict,
            template_name=template_name,
        )

    @_tool
    def inspect_petition_pack(pack_dir: str) -> dict:
        """Inspect and validate a petition pack directory.

        Checks required files, draft_safe flag, classification counts,
        placeholder presence, no-invention rule, citation bank safety,
        and hash manifest validity.

        Args:
            pack_dir: Path to petition pack directory.

        Returns:
            Dict with ok, draft_safe, errors, warnings, counts, checks.
        """
        return inspect_petition_pack_impl(pack_dir)

    # ── Petition v0.8 MCP tools ──────────────────────────────────────────

    @_tool
    def prepare_petition_outline(
        pack_dir: str,
        out_dir: str | None = None,
    ) -> dict:
        """Generate a structured petition outline from a petition pack.

        Reads petition-pack.json and produces an outline.json with sections,
        placeholders, and authority classification for each section.
        Only petition_ready authorities may supply direct content;
        citation_only appear only in bibliography with warning.

        Args:
            pack_dir: Path to petition pack directory.
            out_dir: Output directory for outline.json.

        Returns:
            Dict with ok, outline_path, sections, placeholder_total,
            citation_only_bibliography_count, petition_ready_count.
        """
        return prepare_petition_outline_impl(pack_dir=pack_dir, out_dir=out_dir)

    @_tool
    def prepare_controlled_petition_draft(
        pack_dir: str,
        outline_path: str | None = None,
        out_dir: str | None = None,
    ) -> dict:
        """Generate a controlled petition draft from a petition pack.

        Produces draft.md, draft.json, footnotes.json, and warnings.json.
        Only petition_ready authorities supply direct quotes; citation_only
        appear in bibliography warnings only.  Placeholders are preserved.

        Args:
            pack_dir: Path to petition pack directory.
            outline_path: Optional pre-computed outline.json.
            out_dir: Output directory for draft files.

        Returns:
            Dict with ok, out_dir, draft_md_path, draft_json_path,
            footnotes_path, warnings_path, draft_metadata.
        """
        return prepare_controlled_petition_draft_impl(
            pack_dir=pack_dir, outline_path=outline_path, out_dir=out_dir,
        )

    # ── Multi-Issue Petition Pack MCP tools (M-13) ──────────────────────

    @_tool
    def build_multi_issue_pack(
        matter: str,
        issues_json: str,
        documents_json: str | None = None,
        out_dir: str | None = None,
    ) -> dict:
        """Build a multi-issue petition pack with isolated citation banks.

        Each issue gets its own citation-bank.md and argument-map.md.
        Source documents are shared and deduplicated across issues.
        Hash manifest covers all documents across all issues.

        Args:
            matter: Legal matter description.
            issues_json: JSON string of issues list. Each issue has:
                - title: Issue title (required)
                - description: Issue description (optional)
                - documents: List of Document dicts (optional)
            documents_json: Optional JSON string of shared Document list.
            out_dir: Output directory for the multi-issue pack.

        Returns:
            Dict with ok, out_dir, issue_count, issues, combined counts,
            draft_safe, files, warnings, hash_manifest.
        """
        issues = json.loads(issues_json)
        docs = [Document.model_validate(d) for d in json.loads(documents_json)] if documents_json else []
        return build_multi_issue_pack_impl(
            matter=matter,
            issues=issues,
            documents=docs,
            out_dir=out_dir,
        )

    @_tool
    def inspect_multi_issue_pack(pack_dir: str) -> dict:
        """Inspect and validate a multi-issue petition pack directory.

        Checks per-issue citation banks, cross-issue citation contamination,
        hash manifest consistency, no-invention rules, and placeholder
        preservation.

        Args:
            pack_dir: Path to multi-issue petition pack directory.

        Returns:
            Dict with ok, draft_safe, errors, warnings, checks, issue_results.
        """
        return inspect_multi_issue_pack_impl(pack_dir)

    @_tool
    def prepare_docx_export(
        draft_path: str | None = None,
        draft_json: dict | None = None,
        out_path: str | None = None,
        pack_dir: str | None = None,
    ) -> dict:
        """Create a validated DOCX export from a controlled draft.

        Accepts draft.md path or draft.json dict.  Creates DOCX with
        disclaimer, footnotes, and placeholder preservation.

        Args:
            draft_path: Path to draft.md.
            draft_json: Draft metadata dict (with files.draft_md reference).
            out_path: Output DOCX path.
            pack_dir: Pack directory for footnotes.

        Returns:
            Dict with checksum_sha256, file_size, validation dict.
        """
        return prepare_docx_export_impl(
            draft_path=draft_path,
            draft_json=draft_json,
            out_path=out_path,
            pack_dir=pack_dir,
        )

    @_tool
    def prepare_export_package_bundle(
        pack_dir: str,
        draft_dir: str | None = None,
        docx_path: str | None = None,
        out_dir: str | None = None,
    ) -> dict:
        """Create a complete export package bundle with verification.

        Bundles draft files, petition pack, source documents, manifest,
        hash-manifest, and verification.txt.  Verifies integrity after
        creation.

        Args:
            pack_dir: Path to petition pack directory.
            draft_dir: Draft output directory.
            docx_path: Path to draft.docx.
            out_dir: Output bundle directory.

        Returns:
            Dict with ok, bundle_dir, manifest, hash_manifest,
            verification, files, post_verification.
        """
        return prepare_export_package_bundle_impl(
            pack_dir=pack_dir, draft_dir=draft_dir,
            docx_path=docx_path, out_dir=out_dir,
        )

    # ── Export Format Expansion MCP tools (M-15) ─────────────────────────

    @_tool
    def export_plain_text(draft_path: str, out_path: str | None = None) -> dict:
        """Export a draft.md to plain-text format.

        Strips markdown formatting (headers → uppercase, bold/italic → plain,
        links → text).  Preserves disclaimer header and {{PLACEHOLDER}} tokens.
        Always available — no toolkit required.

        Args:
            draft_path: Path to the draft.md file.
            out_path: Optional output .txt file path.

        Returns:
            Dict with ok, out_path, text_length, disclaimer_present,
            placeholders_preserved.
        """
        return export_plain_text_impl(draft_path=draft_path, out_path=out_path)

    @_tool
    def export_to_format(
        draft_path: str,
        format: str = "docx",
        out_path: str | None = None,
        pack_dir: str | None = None,
        experimental: bool = False,
    ) -> dict:
        """Unified export dispatcher supporting multiple formats.

        Formats:
            - docx: validated DOCX export (always available)
            - txt: plain-text export (always available)
            - pdf: PDF via LibreOffice (requires toolkit)
            - udf: UYAP UDF (requires toolkit + experimental=True)

        Returns structured error dict if toolkit is unavailable or format
        is invalid.

        Args:
            draft_path: Path to the draft.md file.
            format: Export format (docx, txt, pdf, udf).
            out_path: Optional output file path.
            pack_dir: Optional pack directory for footnotes.
            experimental: Required True for UDF format.

        Returns:
            Format-specific result dict or structured error.
        """
        return export_to_format_impl(
            draft_path=draft_path,
            format=format,
            out_path=out_path,
            pack_dir=pack_dir,
            experimental=experimental,
        )

    @_tool
    def get_export_capabilities() -> dict:
        """Report which export formats are currently available.

        Shows availability of docx, txt, pdf, udf formats based on
        toolkit presence (LibreOffice).

        Returns:
            Dict with ok, formats list, toolkit_available, toolkit_status.
        """
        return get_export_capabilities_impl()

    # ── Petition Template Library MCP tools (M-11) ─────────────────────────

    @_tool
    def list_petition_templates() -> list[dict]:
        """List all available petition templates.

        Returns a list of template summaries with name, type, title,
        section_count, and placeholder_count.
        """
        return list_templates_impl()

    @_tool
    def get_petition_template(name: str) -> dict:
        """Get a specific petition template by name.

        Returns the full template dict with name, type, title, and sections.
        Returns error dict if template not found.

        Args:
            name: Template identifier (e.g. 'dava_dilekcesi').
        """
        return get_template_impl(name)

    # M-105: render_template_skeleton, diff_drafts, track_placeholders,
    #        get_fill_report, save_draft_version removed from MCP

    # ── Argument Builder v0.12 MCP tools ──────────────────────────────────

    @_tool
    def build_argument_chain(pack_dir: str) -> dict:
        """Build structured argument chains from a petition pack.

        Reads argument-map.md and petition-pack.json, produces claim ->
        supporting authority -> counter-argument chains.  Only petition_ready
        authorities appear in supporting_authorities (citation-safe).

        Safety invariants enforced:
        - No metadata_only leak into supporting_authorities
        - No fabrication: missing support produces warning
        - All cited documents pass citation_check

        Args:
            pack_dir: Path to petition pack directory.

        Returns:
            Dict with ok, pack_dir, arguments, overall_strength, warnings.
        """
        return build_argument_chain_impl(pack_dir=pack_dir)

    @_tool
    def score_argument(
        claim_text: str,
        document_json: dict | None = None,
    ) -> dict:
        """Score how well an argument is supported by authorities.

        Computes a 0.0-1.0 score based on: count of supporting documents,
        content availability, citation safety.

        Args:
            claim_text: The legal claim/argument text.
            document_json: Optional authority dict with document_id, source,
                title, content_status fields.

        Returns:
            Dict with ok, score, factors, supporting_count, warnings.
        """
        authorities = []
        if document_json:
            authorities = [document_json]
        return score_argument_impl(
            claim_text=claim_text,
            authorities=authorities,
        )

    @_tool
    def get_argument_strength_report(pack_dir: str) -> dict:
        """Generate overall argument strength report for a petition pack.

        Aggregates individual argument scores into a comprehensive report
        with strength distribution and recommendations.

        Args:
            pack_dir: Path to petition pack directory.

        Returns:
            Dict with ok, overall_strength, argument_count,
            classification_distribution, strength_distribution,
            recommendations, warnings.
        """
        return get_argument_strength_report_impl(pack_dir=pack_dir)

    # ── Legislation v0.10 MCP tools ──────────────────────────────────────

    @_tool
    def search_legislation(
        query: str,
        sources: list[str] | None = None,
        legislation_type: str | None = None,
        limit: int = 10,
        scope: str = "law",
        document_id: str | None = None,
    ) -> dict:
        """Search legislation via the Mevzuat source.

        Args:
            query: Search phrase.
            sources: Source IDs (default: ["mevzuat"]).
            legislation_type: Filter by type (e.g. "Kanun", "YÃ¶netmelik").
            limit: Max results.
            scope: 'law' (default) searches legislation documents;
                   'article' searches individual articles within documents
                   (delegates to search_legislation_articles).
            document_id: Required when scope='article'. The mevzuat
                document ID to search articles within.

        Returns:
            Dict with ok, query, results, total_results, warnings, etc.
        """
        if scope == "article":
            return search_legislation_articles_impl(
                document_id=document_id or "",
                article_query=query,
                source=sources[0] if sources else None,
            )
        return search_legislation_impl(
            query=query,
            sources=sources,
            legislation_type=legislation_type,
            limit=limit,
        )

    @_tool
    def get_legislation_document(
        document_id: str,
        source: str | None = None,
    ) -> dict:
        """Get a full legislation document from the Mevzuat source.

        Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").

        Returns:
            Dict with ok, title, citation_check, article_count, etc.
        """
        return get_legislation_document_impl(
            document_id=document_id,
            source=source,
        )

    @_tool
    def search_legislation_articles(
        document_id: str,
        article_number: str | None = None,
        article_query: str | None = None,
        source: str | None = None,
    ) -> dict:
        """Search articles within a legislation document.

        Args:
            document_id: Mevzuat document ID.
            article_number: Optional specific article number.
            article_query: Optional keyword search in article text.
            source: Source ID (default: "mevzuat").

        Returns:
            Dict with ok, matching_articles, total_articles_found, etc.
        """
        return search_legislation_articles_impl(
            document_id=document_id,
            article_number=article_number,
            article_query=article_query,
            source=source,
        )

    @_tool
    def get_legislation_article_tree(
        document_id: str,
        source: str | None = None,
    ) -> dict:
        """Build part/section/article hierarchy from legislation document.

        Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").

        Returns:
            Dict with ok, article_count, part_count, section_count, tree, etc.
        """
        return get_legislation_article_tree_impl(
            document_id=document_id,
            source=source,
        )

    @_tool
    def get_legislation_gerekce(
        document_id: str,
        source: str | None = None,
    ) -> dict:
        """Extract GENEL GEREKCE and MADDE GEREKCELERI from legislation.

        Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").

        Returns:
            Dict with ok, found, genel_gerekce, madde_gerekceleri, etc.
        """
        return get_legislation_gerekce_impl(
            document_id=document_id,
            source=source,
        )

    @_tool
    def legislation_source_status() -> dict:
        """Check Mevzuat source health via smoke tests.

        Returns:
            Dict with ok, overall_ok, healthy_sources, degraded_sources, etc.
        """
        return get_legislation_source_status_impl()

    @_tool
    def format_legislation_citation(
        document: dict | None = None,
        style: str = "full",
    ) -> dict:
        """Format a legislation citation from document metadata.

        Args:
            document: Document dict with title, legislation_no, gazette_date.
            style: 'full', 'short', or 'article'.

        Returns:
            Dict with formatted_citation, style, warnings, etc.
        """
        return format_legislation_citation_impl(
            document=document or {},
            style=style,  # type: ignore[arg-type]
        )

    @_tool
    def get_legislation_types() -> list[dict]:
        """Return known Turkish legislation types.

        Returns:
            List of {type_id, display_name} dicts.
        """
        return get_legislation_types_impl()

    # ── Semantic v0.11 MCP tools ──────────────────────────────────────────

    # M-105: build_semantic_index removed from MCP (CLI-only)

    @_tool
    def semantic_search(
        query: str,
        limit: int = 10,
        filters: dict | None = None,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        This ONLY re-ranks documents ALREADY fetched via `search_decisions`.
        It cannot find any decision that was not fetched first; the local cache
        is small by design (not a crawler, not a full corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first — it is the primary, mandatory entry point. Use
        this tool only to re-rank already-fetched results. Never web-search,
        never cite esas/karar numbers not from a fetched full-text document.

        Pure term-frequency (TF-IDF cosine) search over the cache.
        Works best with documents that share vocabulary.
        Uses Turkish suffix stripping for query expansion — stemmed
        variants of query terms are generated automatically.

        Snippets include **highlighted** matching terms.

        Args:
            query: Search query string.
            limit: Max results (default 10).
            filters: Optional dict with source, court, chamber, content_status,
                     quote_usable, draft_usable.

        Returns:
            Dict with ok, query, results (score + snippet), total_matches, method,
            expanded_query_terms, snippet_highlighted.
        """
        return _attach_corpus_hint(semantic_search_impl(
            query=query, limit=limit, filters=filters,
        ))

    @_tool
    @validate_tool_input(limit=validate_positive_int, hybrid_weight=validate_range(0.0, 1.0))
    def hybrid_search(
        query: str,
        limit: int = 10,
        filters: dict | None = None,
        hybrid_weight: float = 0.6,
        rerank: bool = False,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        This ONLY re-ranks documents ALREADY fetched via `search_decisions`.
        It is a re-ranker over an existing local result set, NOT a way to find
        case law. It CANNOT discover any decision that was not fetched first,
        and the local cache is small by design (this is NOT a crawler and NOT a
        corpus of all decisions — it holds only what you fetched this session).

        HARD RULES — no exceptions, no interpretation:
        - To find decisions on ANY topic you MUST call `search_decisions`
          (live, online). That is THE primary, mandatory entry point.
        - Use this tool ONLY to refine/re-rank results AFTER `search_decisions`
          has fetched documents in the same session.
        - "Empty/limited results here" means "you have not fetched yet" — go
          call `search_decisions`. It does NOT mean no case law exists.
        - NEVER substitute web search for `search_decisions`. NEVER cite an
          esas/karar number, date, or chamber not coming from a fetched
          full-text document.

        Balances exact keyword matching (FTS5 BM25) with semantic similarity
        (TF-IDF cosine).  hybrid_weight controls the balance: higher = more
        keyword-oriented, lower = more semantic.

        Uses Turkish suffix stripping for query expansion — stemmed
        variants of query terms are generated automatically for FTS5.
        Snippets include **highlighted** matching terms.

        hybrid_weight must be between 0.0 and 1.0.

        Args:
            query: Search query string.
            limit: Max results (default 10).
            filters: Optional dict with source, court, chamber, content_status,
                     quote_usable, draft_usable.
            hybrid_weight: Balance 0.0-1.0 (0.0 = pure semantic, 1.0 = pure BM25).
            rerank: Cross-encoder reranking of top results (optional, requires fastembed).

        Returns:
            Dict with ok, query, results (bm25/cosine/hybrid scores + snippet),
            total_matches, method, hybrid_weight, reranked, expanded_query_terms,
            snippet_highlighted.
        """
        return _attach_corpus_hint(hybrid_search_impl(
            query=query, limit=limit, filters=filters,
            hybrid_weight=hybrid_weight,
            rerank=rerank,
        ))

    @_tool
    def index_status() -> dict:
        """Check FTS5 + TF-IDF index health and statistics.

        Returns:
            Dict with ok, fts5_exists, fts5_document_count, vectors_count,
            total_cached_documents, unindexed_documents, warnings.
        """
        return get_index_status_impl()

    # M-105: rebuild_search_index removed from MCP (CLI-only)

    # ── Dense Embedding v2.1 MCP tools (M-24) ──────────────────────────

    # M-105: build_embedding_index removed from MCP (CLI-only)

    @_tool
    def embedding_search(
        query: str,
        limit: int = 10,
        provider: str | None = None,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        Dense-embedding re-ranking over documents ALREADY fetched via
        `search_decisions`. Cannot find decisions that were not fetched first;
        the local index is small by design (not a crawler, not a full corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first — it is the primary, mandatory entry point. Use
        this tool only to re-rank already-fetched results. Never web-search,
        never cite esas/karar numbers not from a fetched full-text document.

        Uses brute-force cosine similarity over indexed embeddings.
        No approximate nearest-neighbor (ANN) — exact but slower for large
        corpora.

        Args:
            query: Search query string.
            limit: Max results (default 10).
            provider: Optional provider ID.

        Returns:
            Dict with ok, results (scored), total_matches, method, provider.
        """
        from .semantic import embedding_search as _emb_search

        return _attach_corpus_hint(_emb_search(query=query, limit=limit, provider=provider))

    # M-105: embedding_index_status, list_embedding_providers, update_indexes,
    #        index_sync_status removed from MCP (CLI-only)

    # ── Chamber Profiling v0.12 MCP tools ──────────────────────────────────

    @_tool
    def chamber_overview(
        court: str | None = None,
    ) -> dict:
        """Overview of all chambers with document counts and date ranges.

        Reads from cached documents.  GROUP BY court + chamber.

        Args:
            court: Optional court name filter (e.g. 'Yargitay').

        Returns:
            Dict with ok, total_chambers, total_documents, chambers list
            (each with document_count, content_available_count, date range).
        """
        return get_chamber_overview_impl(court=court)

    @_tool
    def profile_chamber(
        chamber: str,
        court: str | None = None,
    ) -> dict:
        """Detailed profile of a specific court chamber.

        Computes document counts, content status distribution, top keywords,
        usability flags, and recent documents.

        Args:
            chamber: Chamber name (e.g. '3. Hukuk Dairesi').
            court: Optional court name filter.

        Returns:
            Dict with ok, metrics, top_keywords, recent_documents.
        """
        return profile_chamber_impl(chamber=chamber, court=court)

    @_tool
    def chamber_timeline(
        chamber: str | None = None,
        court: str | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict:
        """Decision timeline grouped by year for a chamber.

        Args:
            chamber: Optional chamber name filter.
            court: Optional court name filter.
            start_year: Optional start year (inclusive).
            end_year: Optional end year (inclusive).

        Returns:
            Dict with ok, timeline (list of {year, count}), year_range.
        """
        return chamber_timeline_impl(
            chamber=chamber, court=court,
            start_year=start_year, end_year=end_year,
        )

    @_tool
    def find_similar_chambers(
        chamber: str,
        court: str | None = None,
        limit: int = 5,
    ) -> dict:
        """Find chambers with similar topic profiles via keyword overlap.

        Uses Jaccard similarity on top keywords extracted from decision titles.

        Args:
            chamber: Target chamber name.
            court: Optional court filter.
            limit: Max results (default 5).

        Returns:
            Dict with ok, similar_chambers (each with similarity_score,
            shared_keywords, document_count).
        """
        return find_similar_chambers_impl(
            chamber=chamber, court=court, limit=limit,
        )

    # ── Citation Graph v0.14 MCP tools ────────────────────────────────────

    @_tool
    def build_citation_graph(limit_docs: int = 100) -> dict:
        """Build citation graph from cached documents.

        Extracts court decision references, matches against cached documents,
        and stores verified edges.  Never fabricates — only detectable,
        verifiable references are graphed.

        Args:
            limit_docs: Maximum documents to process.

        Returns:
            Dict with ok, edges_created, docs_processed, citations_found,
            matches_found, confidence_distribution, warnings.
        """
        return build_citation_graph_impl(limit_docs=limit_docs)

    @_tool
    def get_citation_graph(
        document_id: str,
        source: str,
        direction: str = "both",
        max_depth: int = 1,
    ) -> dict:
        """Get citation relationships for a document.

        Args:
            document_id: The document ID.
            source: The source identifier.
            direction: 'citing' (docs that cite this), 'cited' (docs this cites),
                       or 'both'.
            max_depth: Traversal depth (1 = direct only).

        Returns:
            Dict with ok, document, citing, cited_by, total_edges.
        """
        return get_citation_graph_impl(
            document_id=document_id,
            source=source,
            direction=direction,
            max_depth=max_depth,
        )

    @_tool
    def find_citing_documents(
        document_id: str,
        source: str,
        limit: int = 20,
    ) -> dict:
        """Find documents that cite the given document.

        Args:
            document_id: The cited document ID.
            source: The cited document source.
            limit: Maximum results.

        Returns:
            Dict with ok, document, citing_documents list.
        """
        return find_citing_documents_impl(
            document_id=document_id,
            source=source,
            limit=limit,
        )

    @_tool
    def find_cited_documents(
        document_id: str,
        source: str,
        limit: int = 20,
    ) -> dict:
        """Find documents that the given document cites.

        Args:
            document_id: The citing document ID.
            source: The citing document source.
            limit: Maximum results.

        Returns:
            Dict with ok, document, cited_documents list.
        """
        return find_cited_documents_impl(
            document_id=document_id,
            source=source,
            limit=limit,
        )

    @_tool
    def citation_graph_stats() -> dict:
        """Get citation graph statistics.

        Returns:
            Dict with ok, total_edges, total_docs_with_citations,
            most_cited_docs, avg_citations_per_doc, confidence_distribution.
        """
        return get_citation_graph_stats_impl()

    @_tool
    def export_citation_graph(
        format: str = "json",
        document_id: str | None = None,
        source: str | None = None,
        max_depth: int = 2,
    ) -> dict:
        """Export citation graph in various formats.

        Args:
            format: Export format — 'json' (node-link), 'dot' (Graphviz),
                    or 'mermaid' (Mermaid diagram).
            document_id: Optional document_id to export sub-graph centered on this doc.
            source: Optional source filter for sub-graph.
            max_depth: For sub-graph, max traversal hops (default 2).

        Returns:
            Dict with ok, format, export_text, node_count, edge_count.
        """
        return export_graph_impl(
            format=format,
            document_id=document_id,
            source=source,
            max_depth=max_depth,
        )

    # M-105: dedup tools removed from MCP (corpus_builder handles dedup)

    # M-105: routing tools removed from MCP (search_decisions handles routing)

    # ── Circuit Breaker MCP tools (M-17) ──────────────────────────────

    @_tool
    def circuit_breaker_status(source: str | None = None) -> dict:
        """Check circuit breaker status for one or all sources.

        Args:
            source: Optional source_id filter.

        Returns:
            Dict with ok, state, failure_count, consecutive_failures,
            circuit_open, uptime_pct (per source).
        """
        from .circuit import get_source_health as get_source_health_impl, get_all_sources_health as get_all_sources_health_impl

        if source:
            return get_source_health_impl(source)
        return get_all_sources_health_impl()

    @_tool
    def source_health(source: str | None = None) -> dict:
        """Get source health metrics (uptime, failure counts, circuit state).

        Args:
            source: Optional source_id filter.

        Returns:
            Dict with ok, source_id, state, success_count, failure_count,
            uptime_pct, circuit_open.
        """
        from .circuit import get_source_health as get_source_health_impl, get_all_sources_health as get_all_sources_health_impl

        if source:
            return get_source_health_impl(source)
        return get_all_sources_health_impl()

    # M-105: reset_circuit, error_catalog, active_requests_count removed from MCP

    # ── PDF Extraction MCP tools (M-27) ──────────────────────────────────

    @_tool
    def extract_pdf_text(file_path: str, ocr_enabled: bool = False) -> dict:
        """Extract text layer from a PDF file.

        Uses pypdf for text-layer extraction. OCR is opt-in only.
        Never modifies the original file.

        Args:
            file_path: Path to the PDF file.
            ocr_enabled: Enable OCR extraction (opt-in, produces low confidence warning).

        Returns:
            Dict with ok, text, text_length, method, warnings.
        """
        return extract_pdf_text_impl(file_path, ocr_enabled=ocr_enabled)

    @_tool
    def pdf_toolkit_status() -> dict:
        """Check PDF extraction toolkit availability.

        Reports which PDF tools (pypdf, pytesseract, pdf2image, pillow)
        are installed and available.

        Returns:
            Dict with ok, available_tools, unavailable_tools.
        """
        return get_pdf_toolkit_status_impl()

    @_tool
    def promote_pdf_to_full_text(
        document: dict,
        ocr_enabled: bool = False,
    ) -> dict:
        """Try to promote a pdf_only Document to full_text.

        For local files, use extract_pdf_text directly. This tool
        handles the promotion workflow for documents with source_url.

        Args:
            document: Document dict with content_status, source_url, etc.
            ocr_enabled: Enable OCR extraction (opt-in).

        Returns:
            Dict with ok, promoted, method, warnings, document.
        """
        return promote_pdf_to_full_text_impl(document, ocr_enabled=ocr_enabled)

    # ── Research Watchlist v2.4 MCP tools (M-36) ─────────────────────

    @_tool
    def watch_add(
        name: str,
        query: str,
        sources: list[str] | None = None,
        fetch_count: int = 5,
        interval_hours: int = 24,
    ) -> dict:
        """Register a watch for periodic research.

        Args:
            name: Unique watch name (used as key).
            query: Research query string.
            sources: Optional list of source_ids to search.
            fetch_count: Max documents per search (default 5).
            interval_hours: Suggested interval in hours (default 24).

        Returns:
            Dict with ok, name, config.
        """
        from .research_watch import add_watch as add_watch_impl
        return add_watch_impl(
            name=name, query=query, sources=sources,
            fetch_count=fetch_count, interval_hours=interval_hours,
        )

    @_tool
    def watch_list() -> dict:
        """List all registered watches.

        Returns:
            Dict with ok, watches list, total.
        """
        from .research_watch import list_watches as list_watches_impl
        return list_watches_impl()

    @_tool
    def watch_run(name: str) -> dict:
        """Execute a watch: re-search, detect new/changed docs, produce diff report.

        Args:
            name: Watch name to execute.

        Returns:
            Dict with ok, name, result, diff_report.
        """
        from .research_watch import run_watch as run_watch_impl
        return run_watch_impl(name)

    @_tool
    def watch_remove(name: str) -> dict:
        """Remove a watch.

        Args:
            name: Watch name to remove.

        Returns:
            Dict with ok, name, removed.
        """
        from .research_watch import remove_watch as remove_watch_impl
        return remove_watch_impl(name)

    # ── Privacy / PII MCP tools (M-37) ────────────────────────────────

    @_tool
    def privacy_scan(text: str) -> dict:
        """Scan text for potential PII (TCKN, phone, email).

        Detects Turkish national ID numbers (TCKN), phone numbers, and
        email addresses. Returns findings with confidence levels.

        Args:
            text: Input text to scan for PII.

        Returns:
            Dict with ok, findings_count, findings list, risk_level.
        """
        return scan_pii_impl(text)

    @_tool
    def privacy_redact(text: str) -> dict:
        """Redact PII from text. Returns a copy — original is unchanged.

        Replaces detected TCKN, phone, and email patterns with
        [TCKN_REDACTED], [PHONE_REDACTED], [EMAIL_REDACTED] tokens.

        Args:
            text: Input text to redact PII from.

        Returns:
            Dict with ok, redacted_text, original_length, redactions_applied.
        """
        return redact_pii_impl(text)

    @_tool
    def privacy_audit(path: str) -> dict:
        """Audit a file or directory for PII presence.

        Scans .md, .txt, .json, .docx files for potential PII.
        Returns per-file findings and overall risk assessment.

        Args:
            path: File or directory path to audit.

        Returns:
            Dict with ok, files_scanned, files_with_pii, findings, warning.
        """
        return audit_privacy_impl(path)

    # ── RRF M-69 tool ────────────────────────────────────────────────────

    @_tool
    def hybrid_search_rrf(
        query: str,
        limit: int = 10,
        filters: dict | None = None,
        include_dense: bool = False,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        Re-ranks documents ALREADY fetched via `search_decisions` using
        Reciprocal Rank Fusion. Cannot find decisions that were not fetched
        first; the local cache is small by design (not a crawler, not a full
        corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first — it is the primary, mandatory entry point. Use
        this tool only to re-rank already-fetched results. Never web-search,
        never cite esas/karar numbers not from a fetched full-text document.

        RRF merges BM25, TF-IDF, and optionally dense embedding results
        by rank position only — no score normalization required.

        Args:
            query: Search query.
            limit: Max results (default 10).
            filters: Optional dict with source, court, chamber, content_status.
            include_dense: Whether to include dense embeddings (needs built index).

        Returns:
            Dict with ok, results (with rrf_score), method="rrf".
        """
        from .semantic import hybrid_search_rrf as _hybrid_search_rrf
        return _attach_corpus_hint(_hybrid_search_rrf(
            query=query, limit=limit, filters=filters, include_dense=include_dense,
        ))

    # ── M-98: Core profile facade tools ──────────────────────────────────

    @_tool
    def research_topic(
        query: str,
        sources: list[str] | None = None,
        fetch_count: int = 5,
        filters: dict | None = None,
        output_dir: str | None = None,
    ) -> dict:
        """Search sources, fetch documents, and build a research bundle.

        Returns bundle metadata with query, sources, result_count, fetched_count,
        content_status_summary, citation_safe_count, generated_files, warnings,
        and recommended_next_steps.
        """
        return research_topic_impl(
            query=query,
            sources=sources,
            fetch_count=fetch_count,
            filters=filters or {},
            output_dir=output_dir,
        )

    @_tool
    @validate_tool_input(query=validate_non_empty)
    def search_local_corpus(
        query: str,
        mode: str = "rrf",
        limit: int = 20,
        filters: dict | None = None,
        provider: str | None = None,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        Searches documents ALREADY fetched via `search_decisions`. It cannot
        find any decision that was not fetched first; the local cache is small
        by design (not a crawler, not a full corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first. Use this tool only to filter/re-rank already-fetched
        results. Never web-search, never cite numbers from uncached documents.

        Args:
            query: Search query string.
            mode: Search method — 'rrf' (default, hybrid+RRF fusion),
                  'lexical' (FTS5 full-text), 'semantic' (embedding vector),
                  'hybrid' (weighted lexical+semantic).
            limit: Max results.
            filters: Optional dict with source, court, chamber, content_status.
            provider: Embedding provider name for semantic modes (ignored for lexical).
        """
        if mode == "lexical":
            cache = Cache()
            try:
                results = cache.search_local(query=query, limit=limit, **(filters or {}))
            finally:
                cache.close()
            return _attach_corpus_hint({"results": results, "total_matches": len(results)})
        elif mode == "semantic":
            if provider:
                from .semantic import embedding_search as _emb
                result = _emb(query=query, limit=limit, provider=provider, filters=filters)
            else:
                result = semantic_search_impl(query=query, limit=limit, filters=filters)
            return _attach_corpus_hint(result)
        elif mode == "hybrid":
            result = hybrid_search_impl(query=query, limit=limit, filters=filters)
            return _attach_corpus_hint(result)
        else:  # rrf (default)
            from .semantic import hybrid_search_rrf as _rrf
            result = _rrf(query=query, limit=limit, filters=filters)
            return _attach_corpus_hint(result)

    @_tool
    def get_legislation(
        document_id: str,
        source: str | None = None,
        part: str = "document",
    ) -> dict:
        """Get legislation content from the Mevzuat source.

        Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").
            part: 'document' (default) returns full document,
                  'article_tree' returns the article tree structure,
                  'gerekce' returns the legislative rationale/preambles.

        Returns:
            Dict appropriate for the requested part.
        """
        if part == "article_tree":
            return get_legislation_article_tree_impl(
                document_id=document_id, source=source,
            )
        elif part == "gerekce":
            return get_legislation_gerekce_impl(
                document_id=document_id, source=source,
            )
        else:
            return get_legislation_document_impl(
                document_id=document_id, source=source,
            )

    @_tool
    @validate_tool_input(document=validate_is_dict_with_keys("document_id", "source"))
    def citation_check(
        action: str = "verify",
        source: dict | None = None,
        document: dict | None = None,
        document_id: str | None = None,
        text: str | None = None,
        file_path: str | None = None,
        style: str = "petition",
        limit: int = 5,
        fetch: int = 3,
        no_live: bool = True,
        live_only: bool = False,
        min_score: float = 1.0,
    ) -> dict:
        """Unified citation tool: verify, format, or safety-check legal citations.

        Args:
            action: 'verify' (default) — verify citations in text/file.
                    'format' — format a legal citation from metadata.
                    'safety' — check if a document is safe for quoting/drafting.
            document: Document dict (required for 'safety' action).
            source: Document dict with metadata (for 'format').
            document_id: Document ID to look up from cache (for 'format').
            text: Citation text to verify (for 'verify', optional).
            file_path: Path to file to verify citations in (for 'verify', optional).
            style: Citation style ('petition', 'parenthetical', 'short').
            limit: Max results for verify.
            fetch: Documents to fetch for verify.
            no_live: Skip live source checks for verify.
            live_only: Only live source checks for verify.
            min_score: Minimum confidence score for verify.
        """
        if action == "safety":
            if not document:
                return build_error("INVALID_INPUT", "document required for safety check")
            return citation_check_impl(Document.model_validate(document)).model_dump(mode="json")
        elif action == "format":
            return format_legal_citation_impl(
                source=source,
                document_id=document_id,
                style=style,  # type: ignore[arg-type]
            )
        else:  # verify
            return verify_legal_citation_impl(
                text=text,
                file_path=file_path,
                source=source.get("source_id") if source else None,
                limit=limit,
                fetch=fetch,
                no_live=no_live,
                live_only=live_only,
                min_score=min_score,
            )

    @_tool
    def prepare_petition(
        matter: str,
        issue: str,
        step: str = "input_pack",
        documents: list[dict] | None = None,
        pack_dir: str | None = None,
        research_bundle_dir: str | None = None,
        out_dir: str | None = None,
        strict: bool = True,
        template_name: str | None = None,
    ) -> dict:
        """Prepare petition drafting materials step by step.

        The three steps must be used in order: input_pack → outline → controlled_draft.
        Each step consumes output from the previous step.

        Args:
            matter: Legal matter description.
            issue: Legal issue description.
            step: 'input_pack' (default) — classify authorities, build pack.
                  'outline' — generate structured petition outline from pack.
                  'controlled_draft' — produce a controlled draft with placeholders.
            documents: List of Document dicts (for 'input_pack' step).
            pack_dir: Path to petition pack directory (for 'outline'/'controlled_draft').
            research_bundle_dir: Optional research bundle directory.
            out_dir: Output directory.
            strict: If True, exclude hash-mismatch docs.
            template_name: Optional template name for draft skeleton.
        """
        if step == "outline":
            return prepare_petition_outline_impl(
                pack_dir=pack_dir or "",
                out_dir=out_dir,
            )
        elif step == "controlled_draft":
            return prepare_controlled_petition_draft_impl(
                pack_dir=pack_dir or "",
                out_dir=out_dir,
            )
        else:  # input_pack
            docs = [Document.model_validate(d) for d in (documents or [])]
            return prepare_drafting_input_pack_impl(
                matter=matter,
                issue=issue,
                documents=docs,
                research_bundle_dir=research_bundle_dir,
                out_dir=out_dir,
                strict=strict,
                template_name=template_name,
            )

    @_tool
    def export_document(
        format: str = "docx",
        draft_path: str | None = None,
        draft_json: dict | None = None,
        text: str | None = None,
        out_path: str | None = None,
        out_dir: str | None = None,
        pack_dir: str | None = None,
        draft_dir: str | None = None,
        docx_path: str | None = None,
        title_centered: bool = False,
        title: str | None = None,
        body: str | None = None,
        documents: list[dict] | None = None,
    ) -> dict:
        """Unified document export: DOCX, UDF, PDF, plain text, or bundle.

        Args:
            format: 'docx' (default), 'udf', 'pdf', 'plain', 'bundle',
                    or 'capabilities' (returns supported formats).
            draft_path: Path to draft.md (for docx/plain).
            draft_json: Draft metadata dict (for docx).
            text: Text to write (for udf).
            out_path: Output file path (for docx/udf/plain).
            out_dir: Output directory (for bundle).
            pack_dir: Pack directory (for bundle).
            draft_dir: Draft output directory (for bundle).
            docx_path: Path to draft.docx (for pdf/bundle).
            title_centered: Center the title in UDF output.
            title: Document title (for legacy export_bundle).
            body: Document body (for legacy export_bundle).
            documents: List of document dicts (for legacy export_bundle).
        """
        if format == "capabilities":
            return get_export_capabilities_impl()
        elif format == "udf":
            udf_path = write_udf_impl(
                text=text or "",
                out_path=out_path or "",
                title_centered=title_centered,
            )
            return {"ok": True, "path": str(udf_path), "format": "udf"}
        elif format == "pdf":
            return convert_udf_to_pdf(docx_path or "", out_path=out_path)
        elif format == "plain":
            return export_plain_text_impl(
                draft_path=draft_path or "",
                out_path=out_path,
            )
        elif format == "bundle":
            kwargs: dict[str, Any] = {}
            if pack_dir:
                kwargs["pack_dir"] = pack_dir
            if draft_dir:
                kwargs["draft_dir"] = draft_dir
            if docx_path:
                kwargs["docx_path"] = docx_path
            if out_dir:
                kwargs["out_dir"] = out_dir
            if kwargs:
                return prepare_export_package_bundle_impl(**kwargs)
            # Legacy export_bundle path
            if title and body and out_dir:
                docs_models = [Document.model_validate(d) for d in (documents or [])]
                return export_bundle_impl(
                    out_dir=out_dir, matter=title, issue=body, docs=docs_models,
                )
            return build_error("INVALID_INPUT", "bundle requires pack_dir or (out_dir+title+body)")
        else:  # docx
            return prepare_docx_export_impl(
                draft_path=draft_path,
                draft_json=draft_json,
                out_path=out_path,
                pack_dir=pack_dir,
            )

    @_tool
    def read_legal_file(
        file_path: str,
        ocr_enabled: bool = False,
    ) -> dict:
        """Read and extract text from a legal file by extension.

        Supported extensions:
        - .udf → reads the UDF markup file
        - .pdf → extracts text layer from PDF

        Args:
            file_path: Path to the legal file.
            ocr_enabled: Enable OCR for PDF extraction (opt-in).
        """
        if file_path.lower().endswith(".udf"):
            return {"text": read_udf_impl(file_path), "probe": probe_udf(file_path)}
        elif file_path.lower().endswith(".pdf"):
            return extract_pdf_text_impl(file_path, ocr_enabled=ocr_enabled)
        else:
            return build_error(
                "INVALID_INPUT",
                f"Unsupported file type: {file_path}. Supported: .udf, .pdf",
                supported_formats=[".udf", ".pdf"],
            )

    @_tool
    def list_sources(
        detail: str | None = None,
    ) -> dict | list[dict]:
        """List registered sources with capabilities and optional detail views.

        Args:
            detail: None (default) returns full source capabilites list.
                    'birim_codes' returns validated chamber/unit codes.
                    'legislation_types' returns legislation type taxonomy.

        Returns:
            Source capabilities list, or detail-specific output.
        """
        if detail == "birim_codes":
            return _list_birim_codes()
        elif detail == "legislation_types":
            return get_legislation_types_impl()
        else:
            return capabilities()

    @_tool
    def legal_research_guide(
        topic: str | None = None,
    ) -> dict:
        """📖 COMPREHENSIVE GUIDE: how to use emsal-mcp tools for legal research.

        Read this tool FIRST when beginning ANY legal research task. It explains:
        - Which tool to use when (live search vs local corpus vs legislation vs
          research).
        - Bedesten Solr query operators and query hygiene rules.
        - Chamber code reference (birimAdi).
        - Citation safety rules: what quoteUsable/draftUsable mean.
        - Available extended tool categories (load with load_extended_tools).

        Args:
            topic: Optional topic filter. Leave empty for the full guide.
                   Valid topics: 'search', 'solr', 'chambers', 'citation_safety',
                   'extended_tools'.
        """
        sections: dict[str, str] = {
            "search": (
                "=== HANGİ ARAMA ARACI NE ZAMAN ===\n\n"
                "1. search_decisions (CANLI, ONLINE) — İLK ÇAĞRILMASI GEREKEN ARAÇ.\n"
                "   Her türlü içtihat/mevzuat araştırması için zorunlu giriş noktası.\n"
                "   Resmî kaynağa canlı sorgu yapar, sonuçları yerel cache'e yazar.\n"
                "   Bu araç çağrılmadan hiçbir içtihada atıf yapılamaz.\n\n"
                "2. search_local_corpus (YEREL, ÇEVRİMDIŞI) — YALNIZCA ÖNB ELLEK.\n"
                "   Daha önce search_decisions ile çekilmiş belgelerde arama/filtreleme\n"
                "   yapar. Yeni belge BULAMAZ. Modları: lexical, semantic, hybrid, rrf.\n\n"
                "3. search_legislation (CANLI, Mevzuat) — Mevzuat taraması.\n"
                "   scope='law' ile kanun/Yönetmelik düzeyinde, scope='article' ile\n"
                "   madde düzeyinde arama yapar.\n\n"
                "4. get_legislation (CANLI, Mevzuat) — Tek bir mevzuat belgesini getirir.\n"
                "   part='document' (tam metin), 'article_tree' (madde ağacı),\n"
                "   'gerekce' (gerekçe).\n\n"
                "5. research_topic — Kaynaklarda arama yapıp araştırma paketi oluşturur.\n"
                "   Belgeleri çeker, citation-safety kontrolü yapar, bundle üretir.\n\n"
                "KARAR AĞACI:\n"
                "- Yeni bir konuda içtihat mı arıyorsun? → search_decisions\n"
                "- Çekilmiş belgeleri yeniden sıralamak mı? → search_local_corpus\n"
                "- Mevzuat mı arıyorsun? → search_legislation veya get_legislation\n"
                "- Kapsamlı araştırma paketi mi? → research_topic\n"
            ),
            "solr": (
                "=== BEDESTEN SOLR OPERATÖR KILAVUZU ===\n\n"
                "search_decisions aracı Bedesten Solr motorunu kullanır.\n\n"
                "Operatörler:\n"
                "  +terim     — Terimin kesin bulunmasını zorunlu kılar.\n"
                "  -terim     — Terimi içeren belgeleri hariç tutar.\n"
                '  "tam ifade" — Tam eşleşme (phrase search).\n'
                "  AND / OR   — Boolean operatörler (BÜYÜK HARFLE).\n"
                "  NOT        — Hariç tutma (BÜYÜK HARFLE).\n"
                "  (grup)     — Alt ifade gruplama.\n"
                "  *          — Sonek joker (örn: tazmin*)\n\n"
                "Sorgu hijyeni:\n"
                "  - Kullanıcının sorusunu AYNEN yapıştırma.\n"
                "  - 2-5 anahtar hukuk terimine indirge.\n"
                "  - Türkçe aksanları KORU (kararı ✓, karari ✗).\n"
                "  - Çok geniş tek terimler gürültü getirir.\n\n"
                "Çalışan örnekler:\n"
                '  +işçi +tazminat → her iki terimi de içeren belgeler\n'
                '  "iş kazası" tazminat → tam ifade VE tazminat\n'
                "  (+işçi OR +memur) +tazminat -manevi → işçi VEYA memur, VE tazminat, manevi hariç\n"
            ),
            "chambers": (
                "=== DAİRE KODLARI (birimAdi) ===\n\n"
                "search_decisions aracında birimAdi parametresiyle daire filtresi "
                "yapabilirsiniz. Tam liste için: list_sources(detail='birim_codes')\n\n"
                "Yaygın kodlar:\n"
                "  Yargıtay: 1. Hukuk Dairesi, 2. Hukuk Dairesi, ... 23. Hukuk Dairesi\n"
                "            HGK (Hukuk Genel Kurulu), İBK (İçtihadı Birleştirme)\n"
                "  Danıştay: 1. Daire, 2. Daire, ... 17. Daire\n"
                "            İDDK (İdari Dava Daireleri Kurulu)\n"
            ),
            "citation_safety": (
                "=== ATIF GÜVENLİĞİ KURALLARI ===\n\n"
                "Her belge için iki güvenlik bayrağı kontrol edilir:\n\n"
                "  quoteUsable (alıntılanabilir):\n"
                "    - True: Tam metin mevcut, en az 50 karakter.\n"
                "    - False: Yalnızca metadata veya kısa özet — ATIF YAPILAMAZ.\n\n"
                "  draftUsable (dilekçede kullanılabilir):\n"
                "    - True: Tam metin + tüm gerekli metadata (esas no, karar no, tarih).\n"
                "    - False: Eksik bilgi — dilekçede dayanak olarak KULLANILAMAZ.\n\n"
                "KURAL: Sadece quoteUsable=True VE draftUsable=True belgelere atıf yap.\n"
                "Metadata-only belgeler araştırma ipucudur, atıf kaynağı DEĞİLDİR.\n"
            ),
            "extended_tools": (
                "=== GENİŞLETİLMİŞ ARAÇ KATEGORİLERİ ===\n\n"
                "Core profilde 14 araç bulunur. Aşağıdaki kategoriler load_extended_tools\n"
                "ile dinamik olarak yüklenebilir:\n\n"
                "  health_admin   — Circuit breaker, kaynak sağlığı\n"
                "  citation_graph — Atıf grafı oluşturma ve sorgulama\n"
                "  watch          — Araştırma izleme (watch) listeleri\n"
                "  privacy        — PII tarama, maskeleme, denetim\n"
                "  chambers       — Daire profili, timeline, benzer daire bulma\n"
                "  indexing       — Semantik indeks durumu (index_status)\n"
                "  drafting_advanced — Gelişmiş dilekçe hazırlama araçları\n"
                "  udf_admin      — UDF dönüştürme, PDF araçları\n"
                "  research_admin — Araştırma kalite dashboard, evaluasyon\n"
                "  query_tools    — Sorgu normalizasyonu, genişletme, filtre çıkarma\n\n"
                "Kullanım: load_extended_tools(categories=['health_admin', 'citation_graph'])\n"
            ),
        }
        if topic and topic in sections:
            return {"ok": True, "topic": topic, "guide": sections[topic]}
        guide = "\n\n".join(sections.values())
        return {
            "ok": True,
            "guide": (
                "# emsal-mcp Hukuk Araştırma Rehberi\n\n"
                + guide
                + "\n\n---\n"
                "Belirli bir konuda yardım için: legal_research_guide(topic='arama')\n"
                "Geçerli topic değerleri: " + ", ".join(sections.keys())
            ),
            "available_topics": list(sections.keys()),
        }

    @_tool
    def load_extended_tools(categories: list[str]) -> dict:
        """Dynamically load extended tool categories into the running MCP server.

        In core profile (default), only 14 core tools are registered. This tool
        loads additional tools by category, making them available to the LLM agent
        without restarting the server.

        Valid categories:
          cache_admin, analytics, routing, health_admin, citation_graph,
          dedup, watch, privacy, chambers, indexing, drafting_advanced,
          udf_admin, research_admin, query_tools

        Args:
            categories: List of category names to load.

        Returns:
            Dict with ok, loaded tools, already_loaded, invalid_categories,
            and a note if the MCP client may need to refresh its tool list.
        """
        valid_categories = {
            # M-105: cache_admin, analytics, routing, dedup removed from MCP
            "health_admin",
            "citation_graph", "watch", "privacy", "chambers", "indexing",
            "drafting_advanced", "udf_admin", "research_admin", "query_tools",
        }
        invalid = [c for c in categories if c not in valid_categories]
        if invalid:
            return build_error(
                "INVALID_INPUT",
                f"Invalid categories: {invalid}. Valid: {sorted(valid_categories)}",
                valid_categories=sorted(valid_categories),
            )

        loaded: list[str] = []
        already: list[str] = []
        errors: list[dict[str, str]] = []
        for cat in categories:
            for name, fn in _EXTENDED_TOOLS.items():
                if _TOOL_CATEGORIES.get(name) == cat:
                    # Check if already registered (idempotent)
                    if hasattr(mcp, "_tool_manager"):
                        existing = getattr(mcp._tool_manager, "_tools", {})
                        if name in existing:
                            already.append(name)
                            continue
                    try:
                        mcp.tool()(fn)
                        loaded.append(name)
                    except Exception as exc:
                        errors.append({"tool": name, "error": str(exc)})

        return {
            "ok": len(errors) == 0,
            "loaded_tools": loaded,
            "already_loaded": already,
            "errors": errors,
            "categories_requested": categories,
            "note": (
                "Araçlar yüklendi. MCP istemcisi araç listesini otomatik "
                "yenilemezse, yeni araçlar görünmeyebilir. Bu durumda "
                "istemciyi yeniden başlatın veya EMSAL_TOOL_PROFILE=full "
                "ile başlatın."
            ),
        }

    @_tool
    def health_check() -> dict:
        """Run a consolidated health check across sources, circuit breakers, and indexes.

        Returns a single dict with overall health status, source smoke summary,
        circuit breaker states, and search index status.
        """
        smoke = smoke_all_sync(online=False)
        from .circuit import get_all_sources_health as _get_all_health
        cb_status = _get_all_health()
        idx = get_index_status_impl()
        return {
            "ok": True,
            "source_smoke": {
                "all_ok": all(r.get("offline_ok", False) for r in smoke),
                "source_count": len(smoke),
            },
            "circuit_breakers": cb_status,
            "search_index": idx,
        }

    mcp.run()


if __name__ == "__main__":
    main()
