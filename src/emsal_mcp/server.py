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
    import functools
    import inspect
    import logging
    import os
    import sys
    import threading
    import time

    from . import __version__

    # Transport: varsayilan stdio (MCP istemcisi surecmizi baslatir).  Ag
    # uzerinden yayin icin EMSAL_MCP_TRANSPORT=streamable-http ver; host/port
    # EMSAL_MCP_HOST / EMSAL_MCP_PORT ile ayarlanir (varsayilan 127.0.0.1:8790).
    _transport = os.environ.get("EMSAL_MCP_TRANSPORT", "stdio").strip() or "stdio"
    if _transport not in ("stdio", "streamable-http", "sse"):
        _transport = "stdio"

    argv = sys.argv[1:]
    if argv and argv[0] in {"--version", "-V", "version"}:
        print(f"emsal-mcp-server {__version__}")
        return
    if (argv and argv[0] in {"--help", "-h", "help"}) or (
        _transport == "stdio" and sys.stdin.isatty()
    ):
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
        validate_non_empty,
        validate_positive_int,
        validate_tool_input,
    )
    from .citation import format_legal_citation as format_legal_citation_impl, verify_legal_citation as verify_legal_citation_impl
    from .document import controlled_draft, export_bundle as export_bundle_impl
    from .legislation import (
        get_legislation_article_tree as get_legislation_article_tree_impl,
        get_legislation_document as get_legislation_document_impl,
        get_legislation_gerekce as get_legislation_gerekce_impl,
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
    from .safety import citation_check as citation_check_impl
    from .sources.registry import capabilities, get_source, smoke_all_sync
    from .udf import (
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

    _fastmcp_kwargs: dict[str, Any] = {}
    if _transport != "stdio":
        _fastmcp_kwargs["host"] = os.environ.get("EMSAL_MCP_HOST", "127.0.0.1")
        _fastmcp_kwargs["port"] = int(os.environ.get("EMSAL_MCP_PORT", "8790"))

    mcp = FastMCP("emsal-mcp", **_fastmcp_kwargs)

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
        "mevzuat_korpus_ara":         "core",
        "mevzuat_madde_getir":        "core",
        "citation_check":             "core",
        "prepare_petition":           "core",
        "export_document":            "core",
        "read_legal_file":            "core",
        "list_sources":               "core",
        "legal_research_guide":       "core",
        "load_extended_tools":        "core",
        "health_check":               "core",
        # ── Extended: mevzuat güncelleme (Faz 2b) ───────────────────────
        "mevzuat_degisiklik_raporu":  "extended",
        # ── Extended: cache_admin ───────────────────────────────────────
        # M-105: cache_admin tools removed from MCP (CLI-only)
        # M-103: release tools removed from MCP surface
        # M-105: routing tools removed from MCP (search_decisions handles routing)
        # ── Extended: health_admin ──────────────────────────────────────
        "circuit_breaker_status":     "extended",
        "source_health":              "extended",
        # M-105: reset_circuit, error_catalog, active_requests_count removed
        "source_smoke":               "extended",
        "check_government_servers_health": "extended",
        # ── Extended: citation_graph ────────────────────────────────────
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
        # ── Extended: drafting_advanced ─────────────────────────────────
        "draft_document":             "extended",
        "export_bundle":              "extended",
        "inspect_petition_pack":      "extended",
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
        # ── Extended: citation ──────────────────────────────────────────
        # ── Extended: udf_admin ─────────────────────────────────────────
        "udf_toolkit_status":         "extended",
        # M-105: install_udf_toolkit_tool removed from MCP (CLI-only)
        "udf_authoring_instructions":  "extended",
        "pdf_toolkit_status":         "extended",
        "promote_pdf_to_full_text":   "extended",
        # ── Extended: export ────────────────────────────────────────────
        # ── Extended: discovery ─────────────────────────────────────────
    }

    _TOOL_CATEGORIES: dict[str, str] = {
        "search_decisions":             "search",
        "get_document":                 "search",
        "search_local_corpus":          "search",
        "search_legislation":           "legislation",
        "get_legislation":              "legislation",
        "mevzuat_korpus_ara":           "legislation",
        "mevzuat_madde_getir":          "legislation",
        "mevzuat_degisiklik_raporu":    "legislation",
        "research_topic":               "research",
        "citation_check":               "citation",
        "prepare_petition":             "petition",
        "export_document":              "export",
        "read_legal_file":              "file_io",
        "list_sources":                 "discovery",
        "legal_research_guide":         "guide",
        "load_extended_tools":          "admin",
        "health_check":                 "admin",
        # Extended categories
        # M-105: cache_admin tools removed from MCP surface
        # M-103: release category removed
        # M-105: routing tools removed from MCP surface
        # M-103: release category removed
        "circuit_breaker_status":       "health_admin",
        "source_health":                "health_admin",
        # M-105: reset_circuit, error_catalog, active_requests_count removed
        "source_smoke":                 "health_admin",
        "check_government_servers_health": "health_admin",
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
        "index_status":                 "indexing",
        "draft_document":               "drafting_advanced",
        "export_bundle":               "drafting_advanced",
        "inspect_petition_pack":        "drafting_advanced",
        "build_multi_issue_pack":       "drafting_advanced",
        "inspect_multi_issue_pack":     "drafting_advanced",
        "list_petition_templates":      "drafting_advanced",
        "get_petition_template":        "drafting_advanced",
        # M-105: render_template_skeleton, diff_drafts, track_placeholders,
        #        get_fill_report, save_draft_version removed from MCP
        "build_argument_chain":         "drafting_advanced",
        "score_argument":               "drafting_advanced",
        "get_argument_strength_report": "drafting_advanced",
        "udf_toolkit_status":           "udf_admin",
        # M-105: install_udf_toolkit_tool removed from MCP
        "udf_authoring_instructions":   "udf_admin",
        "pdf_toolkit_status":           "udf_admin",
        "promote_pdf_to_full_text":     "udf_admin",
    }

    # Extended tool functions collected for dynamic loading (M-99)
    _EXTENDED_TOOLS: dict[str, Any] = {}

    # ── M-118: sync araclari olay dongusunu bloklamasin ────────────────────
    #
    # FastMCP 1.27 (mcp/server/fastmcp/utilities/func_metadata.py:96) sync bir
    # araci DOGRUDAN olay dongusu thread'inde cagirir:
    #
    #     if fn_is_async: return await fn(...)
    #     else:           return fn(...)
    #
    # Bu yuzden uzun suren tek bir sync arac (orn. FTS taramasi, dense
    # vektor aramasi) TUM istemcileri kilitler; sunucu yeni baglanti kabul
    # eder ama hicbir istege cevap veremez.  Cozum: sync araci bir worker
    # thread'inde calistiran async bir sarmalayiciyla kaydetmek.
    #
    # Guvenlik notu (olculdu): paylasilan mutable durum yok.  ``Cache()`` her
    # cagrida yeni bir ``sqlite3.connect`` acar (cache.py:85) ve arac
    # govdesinde yaratildigi icin baglanti hep kendi thread'inde dogar
    # (``check_same_thread`` sorunu cikmaz); ``semantic._get_db`` ve
    # ``circuit`` de ayni deseni kullanir.  Modul seviyesindeki tek onbellek
    # ``semantic._MATRIX_VERIFIED`` bir dict'tir; en kotu ihtimalle dogrulama
    # tekrar edilir.  Model/oturum singleton'i yoktur.
    #
    # EMSAL_TOOL_THREADS=0 sarmalayiciyi kapatir (eski, bloklayan davranis).
    _tool_thread_limit = 6
    try:
        _tool_thread_limit = int(os.environ.get("EMSAL_TOOL_THREADS", "6") or "6")
    except ValueError:
        _tool_thread_limit = 6

    _limiter_holder: dict[str, Any] = {}

    def _get_tool_limiter():
        """CapacityLimiter'i tembel yarat: anyio calisan bir dongu ister."""
        lim = _limiter_holder.get("limiter")
        if lim is None:
            import anyio
            lim = anyio.CapacityLimiter(_tool_thread_limit)
            _limiter_holder["limiter"] = lim
        return lim

    # -- M-119: arac basina zaman siniri --------------------------------
    #
    # EMSAL_TOOL_TIMEOUT (saniye, varsayilan 120; 0 = sinirsiz) her arac
    # cagrisina bir tavan koyar.  Arac bazli tavan gerekirse ``_TOOL_TIMEOUTS``
    # sozlugune ``fn.__name__ -> saniye`` yaz.
    #
    # KRITIK KISIT: thread'de kosan sync bir fonksiyon IPTAL EDILEMEZ.
    # ``anyio.fail_after`` yalnizca bekleyen coroutine'i birakir; worker thread
    # ``fn`` bitene kadar calisir ve limiter jetonunu tutar.  Bu yuzden zaman
    # asan sync cagrilari "runaway" (kacak) olarak sayiyoruz: health_check
    # ``tool_runtime`` blogunda raporlaniyor ve sayac limiter kapasitesine
    # yaklasinca WARNING log'u dusuyor.  Async araclarda boyle bir sorun yok,
    # coroutine gercekten iptal edilir.
    _tool_timeout_default = 120.0
    try:
        _tool_timeout_default = float(
            os.environ.get("EMSAL_TOOL_TIMEOUT", "120") or "120"
        )
    except ValueError:
        _tool_timeout_default = 120.0
    if _tool_timeout_default < 0:
        _tool_timeout_default = 0.0

    # Arac bazli tavanlar (saniye); 0 / negatif = o arac icin sinirsiz.
    _TOOL_TIMEOUTS: dict[str, float] = {}

    _tool_runtime_stats: dict[str, int] = {
        "in_flight": 0,
        "timed_out_total": 0,
        "runaway": 0,
    }
    _tool_runtime_lock = threading.Lock()
    _tool_log = logging.getLogger("emsal_mcp.server")

    # anyio 4.1+ ``abandon_on_cancel``, oncesi ``cancellable`` diyor.  Bayrak
    # SART: varsayilan (False) iptalde thread'in bitmesini BEKLER, yani
    # fail_after hicbir ise yaramaz.
    _abandon_kw: dict[str, bool] = {"abandon_on_cancel": True}
    try:  # pragma: no cover - surum tespiti
        import anyio.to_thread as _anyio_to_thread

        if "abandon_on_cancel" not in inspect.signature(
            _anyio_to_thread.run_sync
        ).parameters:
            _abandon_kw = {"cancellable": True}
    except Exception:  # pragma: no cover
        pass

    def _tool_timeout_for(name: str) -> "float | None":
        raw = _TOOL_TIMEOUTS.get(name, _tool_timeout_default)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        return val if val > 0 else None

    def _tool_runtime_snapshot() -> dict[str, Any]:
        """health_check icin canli calisma-zamani sayaclari.

        ``borrowed_tokens`` limiter'in o an dagittigi jeton sayisidir; bu
        aracin kendisi de bir jeton tuttugu icin en az 1 gorunur.
        """
        borrowed: Any = None
        lim = _limiter_holder.get("limiter")
        if lim is not None:
            try:
                borrowed = lim.statistics().borrowed_tokens
            except Exception:  # pragma: no cover
                borrowed = None
        with _tool_runtime_lock:
            snap = dict(_tool_runtime_stats)
        return {
            "threads_limit": _tool_thread_limit,
            "timeout_seconds": _tool_timeout_default,
            "in_flight": snap["in_flight"],
            "timed_out_total": snap["timed_out_total"],
            "runaway": snap["runaway"],
            "borrowed_tokens": borrowed,
        }

    def _tool_enter_call() -> None:
        with _tool_runtime_lock:
            _tool_runtime_stats["in_flight"] += 1

    def _tool_exit_call() -> None:
        with _tool_runtime_lock:
            _tool_runtime_stats["in_flight"] -= 1

    def _tool_note_timeout(state: "dict | None") -> bool:
        """Zaman asimi sayaclarini guncelle; kacak varsa True dondur."""
        escaped = False
        with _tool_runtime_lock:
            _tool_runtime_stats["timed_out_total"] += 1
            if state is not None and not state["finished"]:
                state["runaway"] = True
                _tool_runtime_stats["runaway"] += 1
                escaped = True
            runaway_now = _tool_runtime_stats["runaway"]
        if (
            escaped
            and _tool_thread_limit > 0
            and runaway_now >= max(1, _tool_thread_limit - 1)
        ):
            _tool_log.warning(
                "emsal-mcp: iptal edilemeyen %d arac cagrisi hala worker "
                "thread'inde kosuyor (limiter kapasitesi %d); yeni cagrilar "
                "kuyrukta bekleyebilir.",
                runaway_now,
                _tool_thread_limit,
            )
        return escaped

    def _tool_timeout_error(
        name: str, limit: float, elapsed: float, *, escaped: bool
    ) -> dict[str, Any]:
        warnings = []
        if escaped:
            warnings.append(
                "Cagri iptal edilemedi: islem arka planda surmeye devam ediyor "
                "olabilir ve bitene kadar bir worker thread'ini mesgul tutar."
            )
        else:
            warnings.append(
                "Cagri iptal edildi; islem arka planda surmeye devam ediyor "
                "olabilir."
            )
        return build_error(
            "TOOL_TIMEOUT",
            f"'{name}' araci {limit:g} saniyelik zaman sinirini asti; "
            f"{elapsed:.1f} saniye sonra beklemekten vazgecildi.",
            source="emsal-mcp",
            retryable=True,
            warnings=warnings,
            recommended_next_steps=[
                "Sorguyu daralt: daha az sonuc iste, tarih/mahkeme filtresini "
                "sikilastir.",
                "Uzun suren isler icin EMSAL_TOOL_TIMEOUT degerini yukselt "
                "(0 = sinirsiz).",
                "health_check araciyla tool_runtime blogunu oku; runaway > 0 "
                "ise sunucu gecici olarak yavaslamis demektir.",
            ],
            tool=name,
            timeout_seconds=limit,
            elapsed_seconds=round(elapsed, 3),
            cancelled=not escaped,
        )

    def _threaded(fn):
        """Araci zaman sinirli async bir sarmalayiciyla dondur.

        ``functools.wraps`` ``__wrapped__``/``__annotations__``/``__doc__``
        kopyalar; FastMCP arac semasini ``inspect.signature`` ile uretir ve o
        da ``__wrapped__``'i takip eder, boylece tools/list ciktisi degismez.

        - sync arac: worker thread + ``fail_after`` (M-118 + M-119).  Isaret:
          ``__emsal_threaded__`` ve ``__emsal_timeout__``.
        - async arac: thread yok, sadece ``fail_after`` (gercekten iptal
          edilir).  Isaret: yalnizca ``__emsal_timeout__``.
        - ``EMSAL_TOOL_THREADS=0``: sync araclar hic sarmalanmaz (eski
          bloklayan davranis); bloklayan bir cagriya zaman siniri zaten
          uygulanamaz.
        """
        name = fn.__name__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def _async_runner(**kwargs):
                import anyio

                limit = _tool_timeout_for(name)
                started = time.monotonic()
                _tool_enter_call()
                try:
                    if limit is None:
                        return await fn(**kwargs)
                    try:
                        with anyio.fail_after(limit):
                            return await fn(**kwargs)
                    except TimeoutError:
                        _tool_note_timeout(None)
                        return _tool_timeout_error(
                            name, limit, time.monotonic() - started, escaped=False
                        )
                finally:
                    _tool_exit_call()

            _async_runner.__emsal_timeout__ = True  # type: ignore[attr-defined]
            return _async_runner

        if _tool_thread_limit <= 0:
            return fn

        @functools.wraps(fn)
        async def _runner(**kwargs):
            import anyio
            import anyio.to_thread

            limit = _tool_timeout_for(name)
            state = {"finished": False, "runaway": False}

            def _body():
                try:
                    return fn(**kwargs)
                finally:
                    # Kacak sayacini, govde GERCEKTEN bitince dusur.
                    with _tool_runtime_lock:
                        state["finished"] = True
                        if state["runaway"]:
                            state["runaway"] = False
                            _tool_runtime_stats["runaway"] -= 1

            started = time.monotonic()
            _tool_enter_call()
            try:
                if limit is None:
                    return await anyio.to_thread.run_sync(
                        _body, limiter=_get_tool_limiter()
                    )
                try:
                    with anyio.fail_after(limit):
                        return await anyio.to_thread.run_sync(
                            _body, limiter=_get_tool_limiter(), **_abandon_kw
                        )
                except TimeoutError:
                    escaped = _tool_note_timeout(state)
                    return _tool_timeout_error(
                        name, limit, time.monotonic() - started, escaped=escaped
                    )
            finally:
                _tool_exit_call()

        # Sarmalayiciyi tanimak icin acik isaret: ``__wrapped__`` tek basina
        # yetmez, bazi araclar zaten baska dekoratorlerle sarmalanmis durumda.
        _runner.__emsal_threaded__ = True  # type: ignore[attr-defined]
        _runner.__emsal_timeout__ = True  # type: ignore[attr-defined]
        return _runner

    def _tool(fn):
        """Decorator: conditionally register an MCP tool based on EMSAL_TOOL_PROFILE.

        In 'core' profile (default), only tools with profile='core' are registered.
        In 'full' profile, all tools are registered.
        Extended tools are collected in _EXTENDED_TOOLS for dynamic loading (M-99).

        M-118: MCP'ye kaydedilen sey ``_threaded(fn)`` sarmalayicisidir; modul
        icindeki dogrudan cagrilar bozulmasin diye dekorator orijinal ``fn``i
        dondurur (mcp.tool() de zaten fn'i degistirmeden donduruyordu).
        """
        name = fn.__name__
        profile = _TOOL_PROFILES.get(name, "extended")
        if _effective_profile == "full" or profile == "core":
            mcp.tool()(_threaded(fn))
            return fn
        else:
            # M-99 dinamik yukleme yolu da ayni sarmalayicidan gecsin.
            _EXTENDED_TOOLS[name] = _threaded(fn)
            return fn

    def _attach_corpus_hint(result: dict, query: str = "") -> dict:
        """Runtime safety net: steer the model back to live search_decisions.

        Local search tools only search already-fetched documents. When they
        return nothing, or when the local cache is tiny, inject an explicit
        ``hint`` (and ``cache_document_count``) telling the caller to use the
        live `search_decisions` tool instead of trusting these results or
        falling back to web search.

        Also attaches ``related_quotes`` per result and ``corpus_coverage``.
        M-110: the docstring of ``search_local_corpus`` had promised both for
        two releases while only a dead parallel module implemented them.
        """
        if not isinstance(result, dict):
            return result
        corpus = None
        coverage = None
        try:
            # 11 M kararlik korpusta COUNT(*) + MIN/MAX(decision_date) tam tablo
            # taramasi = her arac cagrisinda ~100 s (5 Eyl 2026, py-spy ile
            # olculdu). Sayim FTS golge tablosundan (ms); kapsam yalniz kucuk
            # korpusta (decision_date dd.mm.yyyy dizesinde MIN/MAX zaten
            # kronolojik degil).
            from .semantic import _BIG_CORPUS_DOCS, _docs_total
            c = Cache()
            try:
                corpus = _docs_total(c.db)
                if corpus and corpus <= _BIG_CORPUS_DOCS:
                    row = c.db.execute(
                        "SELECT MIN(decision_date), MAX(decision_date) "
                        "FROM documents_v2 WHERE decision_date IS NOT NULL"
                    ).fetchone()
                    if row and row[0] and row[1]:
                        coverage = f"{row[0]} — {row[1]}"
            finally:
                c.close()
        except Exception:
            corpus = None

        if query:
            from .snippet import extract_query_terms, make_snippet

            terms = extract_query_terms(query)
            # Dedup by document_id: collect every matched passage per decision
            # instead of returning the same decision once per hit.
            by_doc: dict[str, dict] = {}
            ordered: list[str] = []
            for r in result.get("results") or []:
                if not isinstance(r, dict):
                    continue
                did = r.get("document_id") or r.get("documentId") or ""
                text = r.get("snippet") or r.get("text") or ""
                quote = make_snippet(text, terms, max_length=280) if text else ""
                if did in by_doc:
                    if quote:
                        by_doc[did].setdefault("related_quotes", []).append(quote)
                else:
                    r.setdefault("related_quotes", [])
                    if quote:
                        r["related_quotes"].append(quote)
                    by_doc[did] = r
                    ordered.append(did)
            if by_doc:
                result["results"] = [by_doc[d] for d in ordered]
        if coverage:
            result["corpus_coverage"] = coverage

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
    @validate_tool_input(limit=validate_positive_int)
    async def search_decisions(
        source: str | None = None,
        query: str | None = None,
        limit: int = 10,
        page: int = 1,
        court_types: list[str] | None = None,
        birimAdi: str | None = None,
        karar_tarihi_start: str | None = None,
        karar_tarihi_end: str | None = None,
        esas_no: str | None = None,
        karar_no: str | None = None,
        sort_by: str | None = None,
        include_snippets: bool = False,
        include_raw: bool = False,
    ) -> list[dict] | dict:
        """✅ PRIMARY, MANDATORY TOOL FOR ALL CASE-LAW / DECISION / MEVZUAT RESEARCH.

        For ANY question about court decisions, precedents, case law, or
        legislation you MUST call THIS tool first. It is the ONLY tool that
        retrieves real, current documents LIVE from the official source
        (online — e.g. Bedesten/Yargıtay, Mevzuat).

        HARD RULES — no exceptions, no interpretation:
        - Do NOT answer case-law questions from memory, training data, or web search.
        - Do NOT use search_local_corpus to FIND decisions — it searches ONLY
          the local corpus and cannot discover anything not fetched here first.
        - Every esas/karar number, date, and chamber you cite MUST come from a
          document returned by THIS tool and verified via get_document full text.
        - If you have not called this tool yet, you have NO case law to cite.

        --- QUERY HYGIENE (CRITICAL) ---
        - Do NOT paste the user's question in. Solr matches tokens, not natural
          language. Reduce it to 2–5 legal keywords: "işçi alacağı zamanaşımı" ✓,
          not "işçinin fazla mesai ve kıdem tazminatı konusunda zamanaşımı süresi".
        - Preserve Turkish diacritics exactly; stripping them silently drops
          matches. "kararı" ✓ not "karari" ✗.

        --- BEDESTEN SOLR OPERATOR COOKBOOK ---
        ⚠️ THE DEFAULT OPERATOR IS OR — whitespace between bare terms means
        UNION.  `tahliye taahhüdü geçerlilik` matches ANY of the three words.
        To require all, prefix each with `+` or join with UPPERCASE `AND`.

        +required  must appear (+tazminat)   -excluded  must not (-bölge)
        "exact"    phrase ("iş kazası")      AND/OR/NOT UPPERCASE only
        (grouping) sub-expressions           *          suffix wildcard

        ⚠️ THE INDEX IS NOT STEMMED — each inflected form is its own token:
        `+taahhüdü` ≈ 16 700 hits vs `+taahhüt` ≈ 43 800.  Prefer noun stems or
        quoted phrases, and keep the diacritics (`+taahhut` ≈ 10 hits).

        TWO-PASS BEHAVIOUR: A plain multi-word query with NO operators is first
        tried with every term required (`+t1 +t2 ...`).  If that pass cannot
        fill `limit` — normal for 3+ inflected terms on an unstemmed index — the
        ORIGINAL query re-runs as OR.  Nothing is lost (OR is a superset, and
        Solr ranks multi-term matches higher).  Reported in `warnings` and as
        `fallback_to_or`, so a starved AND pass never looks like "no precedent".

        Worked examples (query string → what it does):
          +işçi +tazminat                    → BOTH "işçi" AND "tazminat"
          +"iş kazası" +tazminat             → phrase "iş kazası" AND "tazminat"
          (+işçi OR +memur) +tazminat -manevi → (işçi OR memur) AND tazminat, not "manevi"

        ⚠️ Quote each concept rather than listing bare inflected words:
        `+"tahliye taahhüdü" +"adli tatil"` ✓.  A `+`-joined query returning 0
        is a real finding about the phrasing — retry broader or with the stem,
        not with more terms.

        Notes:
        - A single common term ("karar") returns noise; add a specific constraint.
        - At least ONE criterion is required (query, esas_no, karar_no, birimAdi,
          or a date range). court_types alone is rejected — it is a filter.

        Args:
            source: Optional source identifier. Available sources:
                - ``'bedesten'`` (default) — combined Yargıtay + Danıştay sweep
                - ``'resmigazete'`` — Resmî Gazete, one issue per call.
                  ``karar_tarihi_start='YYYY-MM-DD'`` picks the day (default
                  today); ``query`` filters that issue locally (diacritic-
                  insensitive), omit to list it all. Ids: ``20260731-1``.
                - ``'aihm'`` — AİHM/ECHR via HUDOC (EXPERIMENTAL; search API
                  currently unavailable — returns empty; get_document works)
                - ``'btk'`` — BTK Kurul Kararları (PARTIAL; HTML card scraping
                  with PDF download for full text)
            query: Search query string (optional when filtering by docket no /
                chamber / date). For best results, craft a short 2–5 term
                keyword query using the operators above.
            limit: Max results (default 10, must be positive).
            page: Page number for pagination (default 1).
            court_types: Optional list of court item types for multi-court search
                in a single call. Bedesten values (exact spelling — verified
                live): YARGITAYKARARI (Yargıtay), DANISTAYKARAR (Danıştay, no
                trailing I), YERELHUKUK (yerel hukuk mahkemeleri), ISTINAFHUKUK
                (bölge adliye hukuk daireleri), KYB (kanun yararına bozma).
                Defaults to ["YARGITAYKARARI", "DANISTAYKARAR"] when
                source=bedesten and omitted. An unrecognised value is rejected
                with INVALID_COURT_TYPE — Bedesten answers a bogus itemType
                with a silent total=0 that is indistinguishable from "no such
                precedent", so we never forward one.
            birimAdi: Optional chamber code. Yargıtay H1–H23 / C1–C23 (hukuk /
                ceza daireleri), HGK, CGK, BGK; Danıştay D1–D17, IDDK, VDDK;
                AYIM. Full list: list_sources(detail="birim_codes").
            karar_tarihi_start: Optional ISO start date, inclusive
                (e.g. "2023-01-01").
            karar_tarihi_end: Optional ISO end date, inclusive
                (e.g. "2024-12-31").
            esas_no: Optional case file number, YIL/SIRA ("2023/1234").
            karar_no: Optional decision number, YIL/SIRA ("2023/5678").
            sort_by: Result ordering — "relevance" (Solr score, default when a
                query/phrase is present) or "date" (newest first, default when
                only filters like esas_no/karar_no/date range are given). When
                omitted, the source infers: non-empty query → relevance,
                filter-only lookup → date.
            include_snippets: When true, fetch the full text of the first 5
                results and attach a ``snippet`` (~360-char passage centred on
                the query terms) to each.  Lets you triage relevance without
                calling get_document per result.  Results already in the local
                corpus get a snippet for free even when this is false.
            include_raw: When true, keep the raw upstream ``metadata`` block.
                Default false: fields duplicated by the flat keys
                (``esas_no``, ``karar_no``, ``decision_date``, ``chamber``, ...)
                are dropped to save context.  Nothing unique is lost.

        Returns:
            Dict with results, pagination metadata, and optional warnings.
            The ``results`` key holds the list of matching document dicts.
            ``total_results`` (int or null) is the total count across pages,
            ``page`` (int) the current page, and ``total_pages`` (int or null)
            the total number of pages.  When the source cannot provide a total
            (e.g. Mevzuat search), ``total_results`` and ``total_pages`` are
            ``null`` and a warning is appended.  Example::

                {
                  "results": [ /* SearchResult dicts */ ],
                  "total_results": 543,
                  "page": 1,
                  "total_pages": 55
                }
        """
        # ── "At least one criterion required" guard (Yargı-MCP parity Görev 6).
        # A court_types-only call is too broad; require a query, docket number,
        # chamber, or date range so we never run a meaningless full-corpus scan.
        has_criterion = any([
            query and query.strip(),
            esas_no, karar_no, birimAdi,
            karar_tarihi_start, karar_tarihi_end,
        ])
        if not has_criterion:
            return build_error(
                "MISSING_CRITERION",
                "En az bir arama kriteri zorunludur: query, esas_no, karar_no, "
                "birimAdi veya tarih aralığından birini verin. Yalnızca court_types "
                "yeterli değildir.",
                recommended_next_steps=[
                    "Anahtar kelime sorgusu (query) verin, örn. '+\"kıdem tazminatı\" +zamanaşımı'.",
                    "Belirli bir kararı arıyorsanız esas_no/karar_no verin.",
                ],
            )
        # ── Default source = bedesten (multi-court search, no source forcing).
        effective_source = source or "bedesten"
        # Default court_types when none given and the source is bedesten: a
        # combined Yargıtay + Danıştay sweep (mirrors yargı-mcp ictihat_ara).
        if effective_source == "bedesten":
            from .sources.bedesten import (
                DEFAULT_COURT_TYPES,
                VALID_ITEM_TYPES,
                normalize_item_types,
            )
            if not court_types:
                court_types = list(DEFAULT_COURT_TYPES)
            else:
                # Reject unknown itemTypes up front: Bedesten does not error on
                # one, it silently returns total=0 — which an agent reads as
                # "no precedent exists".  Known-bad spellings are repaired.
                court_types, unknown_types = normalize_item_types(court_types)
                if unknown_types:
                    return build_error(
                        "INVALID_COURT_TYPE",
                        f"Geçersiz court_types değeri: {', '.join(unknown_types)}. "
                        f"Geçerli değerler: {', '.join(sorted(VALID_ITEM_TYPES))}.",
                        recommended_next_steps=[
                            "Danıştay için 'DANISTAYKARAR' (sonda I yok), istinaf için "
                            "'ISTINAFHUKUK', yerel mahkeme için 'YERELHUKUK' kullanın.",
                        ],
                    )
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
        if sort_by:
            filters["sort_by"] = sort_by
        try:
            src_client = get_source(effective_source)
            sp = await src_client.search_page(query or "", limit=limit, page=page, **filters)
            results = [r.model_dump(mode="json") for r in sp.results]
        except Exception as exc:
            # Bedesten upstream fault (ADALET_RUNTIME_EXCEPTION etc.) — surface
            # as a structured error, NOT an empty list.  An empty list would be
            # misread as "no precedent exists", which is false: the source is
            # temporarily faulty.  See Yargı-MCP parity Görev 3.
            from .sources.base import BedestenUpstreamError
            if isinstance(exc, BedestenUpstreamError):
                return build_error(
                    "SOURCE_UPSTREAM_ERROR",
                    f"Kaynak ({effective_source}) geçici hata döndürdü ({exc.fmc}); bu 'sonuç yok' "
                    "anlamına gelmez, sorguyu daha sonra tekrarlayın.",
                    source=effective_source,
                    retryable=True,
                    recommended_next_steps=["Sorguyu birkaç saniye/dakika sonra tekrarlayın."],
                    upstream_error_code=exc.fmc,
                    upstream_error_message=exc.fmte,
                )
            if isinstance(exc, ValueError):
                # Raised by the source client when no usable court_types remain.
                return build_error("INVALID_COURT_TYPE", str(exc))
            raise
        # Store search results in cache for later local search
        cache = Cache()
        cache.set(f"search:{effective_source}:{query}:{limit}:{page}", results)

        # ── Snippet enrichment (Yargı-MCP parity Görev 4) ──────────────
        # Attach a query-term snippet to each result.  Free for documents
        # already in the local corpus (no network); for the rest, optionally
        # fetch the first 5 full texts concurrently when include_snippets=true.
        from .snippet import extract_query_terms, make_snippet
        terms = extract_query_terms(query or "")
        # 1) Free corpus snippets — try the cache first for every result.
        for r in results:
            if r.get("snippet"):
                continue
            cached_doc = cache.get_document(r.get("document_id", ""), effective_source)
            if cached_doc is not None:
                txt = cached_doc.full_text or cached_doc.markdown or ""
                if txt:
                    snip = make_snippet(txt, terms)
                    if snip:
                        r["snippet"] = snip

        # 2) Opt-in live snippet fetch for the first N results still lacking one.
        if include_snippets:
            snippet_top_n = 5
            need: list[dict] = []
            for r in results:
                if r.get("snippet"):
                    continue
                if len(need) >= snippet_top_n:
                    break
                need.append(r)
            if need:
                src_client = get_source(effective_source)
                from .concurrency import run_concurrently
                fetch_coros = [src_client.get_document(r["document_id"]) for r in need]
                fetched = await run_concurrently(fetch_coros)
                skipped_pdf = 0
                for r, doc in zip(need, fetched):
                    if isinstance(doc, Exception) or doc is None:
                        continue
                    # Skip PDF-only docs (snippet would require extraction).
                    if doc.content_status.value == "pdf_link_only":
                        skipped_pdf += 1
                        continue
                    txt = doc.full_text or doc.markdown or ""
                    if txt:
                        snip = make_snippet(txt, terms)
                        if snip:
                            r["snippet"] = snip
                    # Persist the fetched full text so a follow-up get_document
                    # call is cache-served (no second network round-trip).
                    cache.store_document(doc)
                if skipped_pdf:
                    # Surface the skip count on the first result's metadata.
                    need[0].setdefault("metadata", {})
                    need[0]["metadata"]["snippet_note"] = (
                        f"{skipped_pdf} PDF-only sonuç snippet için atlandı."
                    )
        cache.close()

        # ── Compact the payload for LLM context ─────────────────────────
        # Sonuç başına tekrarlanan sabit metinleri ve düz alanların metadata
        # içindeki kopyalarını düşür; yönlendirmeyi yanıt seviyesinde bir kez
        # ver.  Bilgi kaybı yok, ~%40 daha az bağlam.  include_raw=True ile
        # ham hâli alınır.
        from .models import collect_next_steps, compact_results
        next_steps = collect_next_steps(results)
        results = compact_results(results, include_raw=include_raw)

        # ── Build response with pagination metadata ─────────────────────
        response: dict[str, Any] = {
            "results": results,
            "total_results": sp.total,
            "page": sp.page,
            "total_pages": sp.total_pages,
        }
        if next_steps:
            response["recommended_next_steps"] = next_steps
        # Source-level notices (AND→OR fallback, dropped court_types, ...) —
        # the caller must see how the search was actually executed.
        if sp.warnings:
            response["warnings"] = list(sp.warnings)
        if sp.total is None:
            response.setdefault("warnings", [])
            response["warnings"].append(
                f"Kaynak '{effective_source}' toplam sonuç sayısı sağlamıyor; "
                "yalnızca mevcut sayfa döndürüldü."
            )
        return response

    @_tool
    @validate_tool_input(document_id=validate_non_empty)
    async def get_document(
        source: str,
        document_id: str,
        include_raw: bool = False,
        page_number: int = 1,
    ) -> dict:
        """Fetch a single document by ID from the given source.

        Args:
            source: Source identifier.
            document_id: Document ID (must not be empty).
            include_raw: If True, include the raw upstream response in the
                         output (debugging).  Default: False (deduplicated
                         output with single markdown text field).
            page_number: 1-indexed page number for long documents (>= 40 000
                         chars).  Default 1 returns the first page.  Long
                         documents are split at paragraph boundaries so no
                         page starts or ends mid-paragraph.

        Returns:
            Document dict with deduplicated metadata and content fields.
            Text is served as a single ``markdown`` field; ``full_text``,
            ``raw``, and ``metadata.content`` are omitted by default.

            For long documents (>= 40 000 chars), the response includes
            ``current_page``, ``total_pages``, and ``total_chars`` so the
            agent can request subsequent pages via ``page_number``.
        """
        try:
            doc = await get_source(source).get_document(document_id)
        except Exception as exc:
            from .sources.base import BedestenUpstreamError
            if isinstance(exc, BedestenUpstreamError):
                return build_error(
                    "SOURCE_UPSTREAM_ERROR",
                    f"Kaynak ({source}) geçici hata döndürdü ({exc.fmc}); belge metni "
                    "şu an alınamıyor, daha sonra tekrar deneyin.",
                    source=source,
                    retryable=True,
                    recommended_next_steps=["Belgeyi birkaç saniye/dakika sonra tekrar isteyin."],
                    upstream_error_code=exc.fmc,
                    upstream_error_message=exc.fmte,
                )
            raise
        cache = Cache()
        # M-65: merge cached provenance so standalone get has metadata
        _cached = cache.get_document(document_id, source)
        if _cached and _cached.esas_no:
            from .models import merge_search_metadata
            merge_search_metadata(doc, _cached)
        # Cache stores the FULL Document (json dump) — trimming is output-only
        cache.set(f"doc:{source}:{document_id}", doc.model_dump(mode="json"))
        cache.store_document(doc)
        cache.log("get", {"source": source, "document_id": document_id})
        cache.close()

        # Build deduplicated payload
        payload = doc.to_tool_payload(include_raw=include_raw)

        # ── Long-document pagination (Yargı-MCP parity Görev 4) ──────────
        from .server_utils import split_markdown_for_pagination
        text = payload.get("markdown") or ""
        page_info = split_markdown_for_pagination(text, page_number=page_number)
        payload["markdown"] = page_info["markdown"]
        payload["current_page"] = page_info["current_page"]
        payload["total_pages"] = page_info["total_pages"]
        payload["total_chars"] = page_info["total_chars"]

        return payload



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
    def draft_document(title: str, body: str, documents: list[dict]) -> dict:
        docs = [Document.model_validate(d) for d in documents]
        return {"markdown": controlled_draft(title, body, docs)}

    @_tool
    def export_bundle(out_dir: str, matter: str, issue: str, documents: list[dict]) -> dict:
        return export_bundle_impl(out_dir, matter=matter, issue=issue, docs=[Document.model_validate(d) for d in documents])



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




    # ── Cache v2 MCP tools ────────────────────────────────────────────


    # M-105: cache_admin MCP tools removed (CLI-only: emsal-mcp cache ...)

    # ── Research v0.5 MCP tools ────────────────────────────────────────


    # ── Citation v0.6 MCP tools ──────────────────────────────────────────



    # ── Petition Pack v0.7 MCP tools ────────────────────────────────────────


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



    # ── Export Format Expansion MCP tools (M-15) ─────────────────────────




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
        sort_by: str | None = None,
        mevzuat_adi: str | None = None,
        mevzuat_no: str | None = None,
        mevzuat_tur_list: list[str] | None = None,
    ) -> dict:
        """Search legislation via the Mevzuat source.

        Use ``mevzuat_adi`` to search ONLY in titles (e.g. "kişisel veri" →
        KVKK surfaces). Use ``mevzuat_no`` for direct lookup by official number
        (e.g. "6698" → KVKK, "5237" → TCK) — never guess the number; if unsure
        use ``mevzuat_adi`` first. ``query`` does a body-text/concept search.
        Common abbreviations (TCK, HMK, KVKK, ...) in ``query`` are auto-routed
        to ``mevzuat_no``.

        Args:
            query: Search phrase (body-text). Auto-routes TCK/HMK/etc → number.
            sources: Source IDs (default: ["mevzuat"]).
            legislation_type: Filter by type (e.g. "Kanun", "Yönetmelik").
            limit: Max results.
            scope: 'law' (default) or 'article'.
            document_id: Required when scope='article'.
            sort_by: "relevance" (default) | "date" | "kayit_tarihi".
            mevzuat_adi: Title-only search.
            mevzuat_no: Official legislation number (NEVER guess).
            mevzuat_tur_list: Multi-type filter (KANUN, KHK, YONETMELIK, ...).

        Returns:
            Dict with ok, query, results, total_results, warnings, etc.
        """
        if scope == "article":
            if not document_id:
                return build_error(
                    "INVALID_INPUT",
                    "scope='article' requires document_id. Find it first with "
                    "scope='law' (or mevzuat_no / mevzuat_adi).",
                )
            return search_legislation_articles_impl(
                document_id=document_id,
                article_query=query,
                source=sources[0] if sources else None,
            )
        return search_legislation_impl(
            query=query,
            sources=sources,
            legislation_type=legislation_type,
            limit=limit,
            sort_by=sort_by,
            mevzuat_adi=mevzuat_adi,
            mevzuat_no=mevzuat_no,
            mevzuat_tur_list=mevzuat_tur_list,
        )

    # ── Yerel mevzuat korpusu (Faz 1) ────────────────────────────────────

    @_tool
    def mevzuat_korpus_ara(
        query: str,
        mevzuat_no: str | None = None,
        limit: int = 20,
        mode: str = "hybrid",
    ) -> dict:
        """YEREL korpusta MADDE bazında arama (çevrimdışı, madde metinlerinde).

        mode: "hybrid" (varsayılan; BM25+anlam RRF), "lexical" (FTS5, kelime
        AND), "semantic" (ifade metinde geçmese de bulur). 0 sonuç "hüküm yok"
        DEMEK DEĞİL: korpus yalnız çekilmişi içerir, search_legislation çağır.
        mevzuat_no tek mevzuatla sınırlar (ör. "6098"). Sonuç: mevzuat_adi,
        madde_no, baslik, snippet, kaynak_url.
        """
        from . import legislation_semantic as _sem
        from .legislation_corpus import corpus_stats, search_madde

        istenen = (mode or "hybrid").strip().lower()
        if istenen not in ("lexical", "semantic", "hybrid"):
            istenen = "hybrid"
        if not (query or "").strip():
            istenen = "lexical"  # bos sorgu: search_madde duzgun hata dondursun
        aday = max(int(limit), 20)
        c = Cache()
        try:
            uyari = None
            sem = None
            if istenen in ("semantic", "hybrid"):
                qv = _sem.embed_query(query)
                sem = None if qv is None else _sem.search(
                    c.db, c.path, qv, limit=aday, mevzuat_no=mevzuat_no)
                if sem is None:
                    uyari = ("Semantik indeks ya da gomme saglayicisi yok; "
                             "sozluksel (BM25) aramaya dusuldu.")
                    istenen = "lexical"
            if istenen == "semantic":
                out = {"ok": True, "query": query, "results": sem[:limit],
                       "total_matches": len(sem[:limit])}
            else:
                lex = search_madde(c.db, query, mevzuat_no=mevzuat_no, limit=aday)
                if istenen == "lexical" or not lex.get("ok"):
                    lex["results"] = lex.get("results", [])[:limit]
                    lex["total_matches"] = len(lex["results"])
                    out = lex
                    istenen = "lexical"
                else:
                    birlesik = _sem.rrf_merge(lex.get("results", []), sem, limit=limit)
                    out = {"ok": True, "query": query,
                           "fts_query": lex.get("fts_query"),
                           "results": birlesik, "total_matches": len(birlesik)}
            out["mode"] = istenen
            if uyari:
                out["uyari"] = uyari
            stats = corpus_stats(c.db)
        finally:
            c.close()
        out["korpus_ozeti"] = stats
        if out.get("ok") and not out.get("total_matches"):
            out["hint"] = (
                "0 eşleşme. Bu araç YALNIZCA yerel korpusta arar; korpusta "
                f"{stats['belge_sayisi']} mevzuat var. Hüküm gerçekten yok "
                "sonucuna VARMA — canlı search_legislation ile doğrula."
            )
        return out

    @_tool
    def mevzuat_degisiklik_raporu(gun_sayisi: int = 7) -> dict:
        """Son N günde Resmî Gazete'de YAYIMLANAN mevzuat değişiklikleri.

        "Bu hafta ne değişti" sorusunun cevabı: RG fihristindeki mevzuat
        kalemleri (kanun, yönetmelik, tebliğ, CB kararı), başlıktan çıkarılan
        HEDEF mevzuat ve bu hedefin yerel korpustaki karşılığı. Ayrıca son
        haftalık güncelleme koşusunun özeti.

        UYARI: eşleşme başlık benzerliğiyle kurulur; ``eslesme.yontem`` "no"
        ise bağ ZAYIFTIR (aynı numara farklı türlerde tekrar ediyor). Eşleşme
        yoksa mevzuat korpusta yok demektir — "değişiklik yok" DEMEK DEĞİLDİR.
        gun_sayisi büyüdükçe maliyet doğrusal artar (ölçüm ~2,4 s/gün).
        """
        import asyncio as _asyncio

        from .legislation_update import degisiklik_raporu

        gun = max(1, min(int(gun_sayisi), 60))
        c = Cache()
        try:
            return _asyncio.run(degisiklik_raporu(c.db, gun))
        finally:
            c.close()

    @_tool
    def mevzuat_madde_getir(mevzuat_no: str, madde_no: str) -> dict:
        """Yerel korpustan tek maddenin TAM metni (çevrimdışı).

        madde_no "390", "12/A", "Geçici 1" kabul eder. Korpusta yoksa
        NOT_FOUND döner — uydurma, canlı get_legislation çağır.
        """
        from .legislation_corpus import get_madde

        c = Cache()
        try:
            return get_madde(c.db, mevzuat_no, madde_no)
        finally:
            c.close()








    # ── Semantic v0.11 MCP tools ──────────────────────────────────────────

    # M-105: build_semantic_index removed from MCP (CLI-only)



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
        mode: str = "lexical",
        limit: int = 20,
        filters: dict | None = None,
        provider: str | None = None,
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
    ) -> dict:
        """Concept DISCOVERY over the local corpus.

        Searches the local corpus (decisions already fetched this session or
        via the corpus crawl) for a legal CONCEPT when the exact wording is
        unknown.  Each result carries ``related_quotes`` — matched passages —
        so you can spot relevant precedent without fetching every full text.

        Roles are complementary: THIS tool = DISCOVERY over the local corpus;
        ``search_decisions`` = live CURRENT search + citation verification.
        The corpus may lag; always confirm any decision you cite with
        ``search_decisions`` + ``get_document`` first.

        QUERY FORM: 2–6 legal keywords, NOT a sentence.  All terms are
        required (AND) and match anywhere in the text, so narrative filler
        only shrinks the result set.  Quote words to require them adjacent:
        ``kıdem tazminatı zamanaşımı`` · ``"tahliye taahhüdü" geçerlilik``.
        Unlike Bedesten this index folds diacritics (kamulastirma =
        kamulaştırma).

        Args:
            query: 2–6 legal keywords; `"quoted spans"` match as phrases.
            mode: 'lexical' (default; FTS5/BM25, sub-second), 'rrf'
                  (BM25+TF-IDF fusion; SLOW — minutes on a large corpus),
                  'semantic' (dense embeddings), 'hybrid'.
            limit: Max results.
            filters: Optional dict with source, court, chamber, content_status.
            provider: Embedding provider name for semantic modes (ignored for lexical).
            source/court/chamber/date/esas_no/karar_no/document_id: Flat
                  filters — equivalent to putting them in ``filters``.
            content_status/draft_usable/quote_usable: Content filters.
            sort: 'relevance' (default) or 'date' — lexical mode only.
        """
        # Flat kwargs are merged into `filters` so a caller never has to know
        # which of the two spellings a given mode expects.
        merged = dict(filters or {})
        for _key, _val in (
            ("source", source), ("court", court), ("chamber", chamber),
            ("date", date), ("esas_no", esas_no), ("karar_no", karar_no),
            ("document_id", document_id), ("content_status", content_status),
            ("draft_usable", draft_usable), ("quote_usable", quote_usable),
        ):
            if _val is not None:
                merged[_key] = _val

        if mode == "lexical":
            cache = Cache()
            try:
                results = cache.search_local(
                    query=query, limit=limit, sort=sort, **merged,
                )
            finally:
                cache.close()
            return _attach_corpus_hint({
                "ok": True,
                "results": results,
                "total_matches": len(results),
                "method": "bm25_fts5",
            }, query)
        elif mode == "semantic":
            # M-112: without an explicit provider this used to fall through to
            # TF-IDF, so the corpus's 1.3M dense embeddings were unreachable
            # unless the caller happened to know the provider string.  Prefer
            # whichever provider actually has vectors here.
            from .semantic import best_dense_provider as _best
            use = provider or _best()
            if use:
                from .semantic import embedding_search as _emb
                result = _emb(query=query, limit=limit, provider=use, filters=merged)
            else:
                result = semantic_search_impl(query=query, limit=limit, filters=merged)
            return _attach_corpus_hint(result, query)
        elif mode == "hybrid":
            result = hybrid_search_impl(query=query, limit=limit, filters=merged)
            return _attach_corpus_hint(result, query)
        elif mode == "rrf":
            from .semantic import hybrid_search_rrf as _rrf
            result = _rrf(query=query, limit=limit, filters=merged)
            return _attach_corpus_hint(result, query)
        # M-110: an unrecognised mode used to fall through to rrf — the
        # SLOWEST path — so a typo cost minutes and looked like a hang.
        return build_error(
            "INVALID_INPUT",
            f"Unknown mode: {mode!r}. Valid: lexical, semantic, hybrid, rrf.",
            valid_modes=["lexical", "semantic", "hybrid", "rrf"],
        )

    @_tool
    def get_legislation(
        document_id: str,
        source: str | None = None,
        part: str = "document",
        page_number: int = 1,
    ) -> dict:
        """Get legislation content from the Mevzuat source.

        Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").
            part: 'document' (default, full text), 'article_tree' the
                  part/section/article tree, 'gerekce' the rationale.
            page_number: page of part='document' (40 000 chars/page).

        Returns:
            Dict for the requested part; 'document' also carries
            current_page/total_pages/total_chars.
        """
        if part == "article_tree":
            return get_legislation_article_tree_impl(
                document_id=document_id, source=source,
            )
        elif part == "gerekce":
            return get_legislation_gerekce_impl(
                document_id=document_id, source=source,
            )
        result = get_legislation_document_impl(
            document_id=document_id, source=source,
        )
        if result.get("markdown"):
            from .server_utils import split_markdown_for_pagination
            page = split_markdown_for_pagination(
                result["markdown"], page_number=page_number
            )
            result["markdown"] = page["markdown"]
            result["current_page"] = page["current_page"]
            result["total_pages"] = page["total_pages"]
            result["total_chars"] = page["total_chars"]
        return result

    @_tool
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
                    'format' — format a court-decision citation from metadata.
                    'format_legislation' — format a legislation citation.
                    'safety' — check if a document is safe for quoting/drafting.
            document: Document dict (required for 'safety' and
                    'format_legislation').
            source: Document dict with metadata (for 'format').
            document_id: Document ID to look up from cache (for 'format').
            text: Citation text to verify (for 'verify', optional).
            file_path: Path to file to verify citations in (for 'verify', optional).
            style: Citation style ('petition', 'parenthetical', 'short';
                    'article' for legislation).
            limit: Max results for verify.
            fetch: Documents to fetch for verify.
            no_live: Skip live source checks for verify.
            live_only: Only live source checks for verify.
            min_score: Minimum confidence score for verify.
        """
        if action == "safety":
            # M-110: this used to be a @validate_tool_input decorator requiring
            # document_id+source on EVERY action, which made the legislation
            # formatter (whose input has neither) permanently unreachable.
            if not document:
                return build_error("INVALID_INPUT", "document required for safety check")
            missing = [k for k in ("document_id", "source") if not document.get(k)]
            if missing:
                return build_error(
                    "INVALID_INPUT",
                    f"document: missing required fields: {', '.join(missing)}",
                )
            return citation_check_impl(Document.model_validate(document)).model_dump(mode="json")
        elif action == "format":
            return format_legal_citation_impl(
                source=source,
                document_id=document_id,
                style=style,  # type: ignore[arg-type]
            )
        elif action == "format_legislation":
            # M-110: replaces the retired format_legislation_citation tool.
            from .legislation import format_legislation_citation as _fmt_leg

            doc = document or source
            if not doc:
                return build_error(
                    "INVALID_INPUT",
                    "document required for format_legislation",
                )
            return _fmt_leg(document=doc, style=style)  # type: ignore[arg-type]
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
        outline_path: str | None = None,
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
            outline_path: Optional pre-computed outline.json (controlled_draft).
        """
        if step == "outline":
            return prepare_petition_outline_impl(
                pack_dir=pack_dir or "",
                out_dir=out_dir,
            )
        elif step == "controlled_draft":
            return prepare_controlled_petition_draft_impl(
                pack_dir=pack_dir or "",
                outline_path=outline_path,
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
        udf_path: str | None = None,
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
            text: Text to write (for udf; plain text — petition formatting
                  such as bold title/labels/headings is applied automatically).
            out_path: Output file path (for docx/udf/plain).
            out_dir: Output directory (for bundle).
            pack_dir: Pack directory (for bundle).
            draft_dir: Draft output directory (for bundle).
            docx_path: Path to a .docx (for bundle; for udf this is the
                  PREFERRED input — converts DOCX directly to UDF preserving
                  bold, alignment, indent and line spacing).
            udf_path: Path to a .udf — converts it to docx or pdf via
                  LibreOffice (replaces convert_udf_to_docx/pdf).
            title_centered: Center the title in UDF output.
            title: Document title (for legacy export_bundle).
            body: Document body (for legacy export_bundle).
            documents: List of document dicts (for legacy export_bundle).
        """
        if format == "capabilities":
            return get_export_capabilities_impl()
        elif format == "udf":
            if docx_path:
                # Preferred: convert DOCX directly, preserving bold/alignment/
                # indent formatting (native converter, no external toolkit).
                from .udf import docx_to_udf_native

                result = docx_to_udf_native(docx_path, out_path=out_path)
                if result.get("ok"):
                    return {**result, "path": result["out_path"], "format": "udf"}
                return result
            written = write_udf_impl(
                text=text or "",
                out_path=out_path or "",
                title_centered=title_centered,
            )
            return {"ok": True, "path": str(written), "format": "udf"}
        elif format == "docx" and udf_path:
            # M-110: replaces the retired convert_udf_to_docx_tool.
            from .udf import convert_udf_to_docx as _udf_to_docx

            return _udf_to_docx(udf_path, out_path)
        elif format == "pdf":
            # M-110: this branch used to hand ``docx_path`` to a UDF converter,
            # so md→pdf was unreachable and docx→pdf was silently wrong.
            if udf_path:
                return convert_udf_to_pdf(udf_path, out_path=out_path)
            if draft_path:
                return export_to_format_impl(
                    draft_path=draft_path, format="pdf",
                    out_path=out_path, pack_dir=pack_dir,
                )
            return build_error(
                "INVALID_INPUT",
                "pdf export requires draft_path (markdown) or udf_path (UDF).",
                supported_inputs=["draft_path", "udf_path"],
            )
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
            try:
                return {
                    "ok": True,
                    "text": read_udf_impl(file_path),
                    "probe": probe_udf(file_path),
                    "path": file_path,
                    "format": "udf",
                }
            except Exception as exc:
                # M-110: a corrupt UDF used to raise out of the tool, which the
                # MCP layer renders as a bare traceback rather than an error dict.
                return build_error(
                    "FILE_READ_ERROR",
                    f"UDF dosyası okunamadı: {exc}",
                    path=file_path,
                    format="udf",
                )
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
        court: str | None = None,
    ) -> dict:
        """List registered sources with capabilities and optional detail views.

        Args:
            detail: None (default) returns the full source capability matrix.
                    'birim_codes' returns validated chamber/unit codes.
                    'legislation_types' returns the legislation type taxonomy.
            court: Filter for birim_codes ('Yargitay', 'Danistay', 'Askeri').

        Returns:
            Dict with ok plus 'sources', 'codes' or 'types' depending on detail.
        """
        # M-110: always a dict.  This used to return a bare list for the
        # default view and a list for birim_codes, so a caller could not tell
        # an empty result from a failure.
        if detail == "birim_codes":
            return {
                "ok": True,
                "detail": "birim_codes",
                "codes": _list_birim_codes(court=court),
            }
        elif detail == "legislation_types":
            return {
                "ok": True,
                "detail": "legislation_types",
                "types": get_legislation_types_impl(),
            }
        return {"ok": True, "sources": capabilities()}

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
          chambers, citation_graph, drafting_advanced, health_admin,
          indexing, privacy, udf_admin, watch

        Args:
            categories: List of category names to load.

        Returns:
            Dict with ok, loaded tools, already_loaded, invalid_categories,
            and a note if the MCP client may need to refresh its tool list.
        """
        # Derived from the category table so the two can never drift apart.
        valid_categories = {
            cat for name, cat in _TOOL_CATEGORIES.items()
            if _TOOL_PROFILES.get(name, "extended") != "core"
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
            # M-119: zaman siniri / thread havuzu durumu.
            "tool_runtime": _tool_runtime_snapshot(),
        }

    @_tool
    async def check_government_servers_health() -> dict:
        """Check the operational status of Turkish government legal search servers.

        Tests connection to official portals (UYAP emsal, Mevzuat, Danıştay, AYM)
        and returns their status and response times.
        """
        import httpx
        import time
        from datetime import datetime, timezone
        import urllib3

        # Disable SSL warnings for the InsecureRequestWarning when verifying=False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        targets = {
            "bedesten": "https://bedesten.adalet.gov.tr",
            "mevzuat": "https://www.mevzuat.gov.tr",
            "danistay": "https://danistay.gov.tr",
            "aym": "https://www.anayasa.gov.tr"
        }
        
        results = {}
        healthy_count = 0
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # Use verify=False to bypass local SSL certificate store issues (common on gov sites)
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, verify=False) as client:
            for name, url in targets.items():
                start = time.monotonic()
                try:
                    r = await client.get(url, headers=headers)
                    elapsed = (time.monotonic() - start) * 1000
                    
                    # 4xx still means the server is online and responding (e.g. Bedesten API gateway returns 404 on root).
                    # 5xx represents a server-side crash/unavailability.
                    if r.status_code < 500:
                        results[name] = {"status": "healthy", "response_time_ms": round(elapsed, 2)}
                        healthy_count += 1
                    else:
                        results[name] = {
                            "status": "degraded", 
                            "response_time_ms": round(elapsed, 2),
                            "error": f"HTTP {r.status_code}"
                        }
                except Exception as exc:
                    elapsed = (time.monotonic() - start) * 1000
                    results[name] = {
                        "status": "unavailable", 
                        "response_time_ms": round(elapsed, 2),
                        "error": str(exc)
                    }

        return {
            "overall_status": "healthy" if healthy_count == len(targets) else "degraded" if healthy_count > 0 else "unhealthy",
            "healthy_servers": healthy_count,
            "total_servers": len(targets),
            "servers": results,
            "check_timestamp": datetime.now(timezone.utc).isoformat()
        }

    if _transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=_transport)


if __name__ == "__main__":
    main()
