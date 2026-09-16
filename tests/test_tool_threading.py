"""M-118: sync MCP araclari olay dongusunu bloklamamali.

FastMCP 1.27 sync bir araci dogrudan olay dongusu thread'inde cagirir
(``mcp/server/fastmcp/utilities/func_metadata.py:96`` —
``if fn_is_async: return await fn(...) else: return fn(...)``).  Bu yuzden
uzun suren tek bir sync arac tum istemcileri kilitliyordu: sunucu yeni
baglanti kabul ediyor ama hicbir istege cevap veremiyordu.

``server.main()`` icindeki ``_tool`` dekoratoru artik sync araclari
``anyio.to_thread.run_sync`` ile calistiran, ``__emsal_threaded__`` isaretli
bir async sarmalayiciyla kaydediyor.  Buradaki testler sarmalayicinin

1. gercekten olay dongusu disinda bir thread kullandigini,
2. FastMCP'nin sema uretimi icin gereken imza/docstring/annotation'i
   bozmadigini (tools/list ciktisi degismemeli),
3. zaten async olan araclara dokunmadigini,
4. ``EMSAL_TOOL_THREADS=0`` ile kapatilabildigini

dogrular.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.integration]


def _capture_registered(profile: str = "full") -> dict:
    """``mcp.tool()`` cagrisina VERILEN nesneyi dondur (soyulmamis).

    ``tests/conftest.capture_registered_tools`` bilerek thread sarmalayicisini
    soyar; burada tam da sarmalayicinin kendisini incelemek istiyoruz.
    """
    registered: dict = {}
    mock_mcp = MagicMock()
    mock_mcp._tool_manager = MagicMock()
    mock_mcp._tool_manager._tools = {}

    def capture_tool(name=None, **kw):
        def decorator(fn):
            registered[name or getattr(fn, "__name__", "unknown")] = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    mock_mcp.run = MagicMock()

    prev = os.environ.get("EMSAL_TOOL_PROFILE")
    os.environ["EMSAL_TOOL_PROFILE"] = profile
    try:
        with patch(
            "mcp.server.fastmcp.FastMCP", return_value=mock_mcp
        ), patch.object(sys.stdin, "isatty", return_value=False):
            import emsal_mcp.server

            emsal_mcp.server.main()
    finally:
        if prev is None:
            os.environ.pop("EMSAL_TOOL_PROFILE", None)
        else:
            os.environ["EMSAL_TOOL_PROFILE"] = prev
    return registered


# Sarmalayici gozlemlemek icin ucuz, saf bir sync arac.
SYNC_TOOL = "list_sources"
# Kaynakta ``async def`` olarak yazilmis araclar.
ASYNC_TOOLS = ("search_decisions", "get_document", "check_government_servers_health")


@pytest.fixture()
def threaded_tools(monkeypatch):
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    return _capture_registered("full")


# ── 1. Sync arac olay dongusu disinda bir thread'de kosuyor ───────────────

def test_sync_tool_is_registered_as_async_wrapper(threaded_tools) -> None:
    tool = threaded_tools[SYNC_TOOL]
    assert getattr(tool, "__emsal_threaded__", False) is True
    assert inspect.iscoroutinefunction(tool), (
        "FastMCP sadece coroutine fonksiyonlari await eder "
        "(tools/base.py::_is_async_callable)"
    )


def test_sync_tool_body_runs_on_a_worker_thread(monkeypatch) -> None:
    """Aracin GOVDESI, olay dongusunun thread'inden farkli bir thread'de kosmali."""
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")

    seen: dict[str, int] = {}

    # ``main()`` ``birim_enum.list_birim_codes``i cagri aninda import ettigi
    # icin modul uzerinden casuslamak yeterli.
    import emsal_mcp.birim_enum as birim_enum

    original = birim_enum.list_birim_codes

    def spy(*a, **kw):
        seen["body"] = threading.get_ident()
        return original(*a, **kw)

    monkeypatch.setattr(birim_enum, "list_birim_codes", spy)

    tools = _capture_registered("full")
    tool = tools[SYNC_TOOL]

    async def drive():
        seen["loop"] = threading.get_ident()
        return await tool(detail="birim_codes")

    result = asyncio.run(drive())

    assert result["ok"] is True
    assert "body" in seen, "casus cagrilmadi"
    assert seen["body"] != seen["loop"], (
        f"arac govdesi olay dongusu thread'inde kosmus: {seen}"
    )


def test_sync_tool_body_blocks_the_loop_when_disabled(monkeypatch) -> None:
    """EMSAL_TOOL_THREADS=0 ile ayni govde olay dongusu thread'inde kosar."""
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "0")

    seen: dict[str, int] = {}
    import emsal_mcp.birim_enum as birim_enum

    original = birim_enum.list_birim_codes

    def spy(*a, **kw):
        seen["body"] = threading.get_ident()
        return original(*a, **kw)

    monkeypatch.setattr(birim_enum, "list_birim_codes", spy)

    tools = _capture_registered("full")
    tool = tools[SYNC_TOOL]

    async def drive():
        seen["loop"] = threading.get_ident()
        return tool(detail="birim_codes")

    asyncio.run(drive())
    assert seen["body"] == seen["loop"]


def test_wrapper_result_matches_direct_call(threaded_tools) -> None:
    tool = threaded_tools[SYNC_TOOL]
    direct = tool.__wrapped__()
    through_wrapper = asyncio.run(tool())
    assert through_wrapper == direct


# ── 2. Imza / sema korunuyor ──────────────────────────────────────────────

def test_wrapper_preserves_signature_name_and_doc(threaded_tools) -> None:
    tool = threaded_tools["search_local_corpus"]
    original = tool.__wrapped__

    assert tool is not original
    assert tool.__name__ == original.__name__ == "search_local_corpus"
    assert tool.__doc__ == original.__doc__
    assert inspect.signature(tool) == inspect.signature(original)
    assert tool.__annotations__ == original.__annotations__


def test_fastmcp_schema_is_identical_with_and_without_wrapper(monkeypatch) -> None:
    """FastMCP'nin urettigi arac semasi sarmalayiciyla birebir ayni kalmali."""
    from mcp.server.fastmcp.tools.base import Tool

    monkeypatch.setenv("EMSAL_TOOL_THREADS", "0")
    plain = _capture_registered("full")
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    wrapped = _capture_registered("full")

    assert set(plain) == set(wrapped)
    # Arac sayisi elle sabitlenmemeli: server.py'deki ``_TOOL_PROFILES`` tek
    # dogruluk kaynagi.  Sabit 46 rakami mevzuat araclari eklenince bayatladi.
    from emsal_mcp.tool_profile import TOOL_PROFILE

    assert len(plain) == len(TOOL_PROFILE), (
        "kayitli arac sayisi _TOOL_PROFILES ile ortusmuyor"
    )

    for name in sorted(plain):
        a = Tool.from_function(plain[name], name=name)
        b = Tool.from_function(wrapped[name], name=name)
        assert a.parameters == b.parameters, f"{name}: inputSchema degisti"
        assert a.description == b.description, f"{name}: description degisti"
        assert a.output_schema == b.output_schema, f"{name}: outputSchema degisti"
        assert b.is_async is True, f"{name}: FastMCP sarmalayiciyi await etmeyecek"


# ── 3. Async araclara dokunulmuyor ────────────────────────────────────────

def test_async_tools_are_not_rewrapped(threaded_tools) -> None:
    for name in ASYNC_TOOLS:
        tool = threaded_tools[name]
        assert inspect.iscoroutinefunction(tool)
        assert not getattr(tool, "__emsal_threaded__", False), (
            f"{name} zaten async, sarmalanmamaliydi"
        )


def test_every_registered_tool_is_awaitable(threaded_tools) -> None:
    """FastMCP'nin await edebilmesi icin hepsi coroutine fonksiyon olmali."""
    for name, tool in threaded_tools.items():
        assert inspect.iscoroutinefunction(tool), f"{name} sync kalmis"


# ── 4. Kapatma anahtari ───────────────────────────────────────────────────

def test_threads_zero_disables_the_wrapper(monkeypatch) -> None:
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "0")
    tools = _capture_registered("full")
    tool = tools[SYNC_TOOL]
    assert not inspect.iscoroutinefunction(tool)
    assert not getattr(tool, "__emsal_threaded__", False)


def test_invalid_thread_count_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "abc")
    tools = _capture_registered("full")
    assert getattr(tools[SYNC_TOOL], "__emsal_threaded__", False) is True


# ── 5. M-99 dinamik yukleme yolu da sarmalayicidan geciyor ────────────────

def test_extended_tools_are_wrapped_too(monkeypatch) -> None:
    """``load_extended_tools`` ile sonradan kaydedilenler de thread'de kosmali."""
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_PROFILE", "core")

    registered: dict = {}
    mock_mcp = MagicMock()
    mock_mcp._tool_manager = MagicMock()
    mock_mcp._tool_manager._tools = {}

    def capture_tool(name=None, **kw):
        def decorator(fn):
            key = name or getattr(fn, "__name__", "unknown")
            registered[key] = fn
            mock_mcp._tool_manager._tools[key] = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    mock_mcp.run = MagicMock()

    with patch(
        "mcp.server.fastmcp.FastMCP", return_value=mock_mcp
    ), patch.object(sys.stdin, "isatty", return_value=False):
        import emsal_mcp.server

        emsal_mcp.server.main()

    loader = registered["load_extended_tools"]
    # loader'in kendisi de sarmalanmistir; implementasyonu cagir.
    impl = loader.__wrapped__ if getattr(loader, "__emsal_threaded__", False) else loader
    result = impl(["chambers"])

    assert result["ok"] is True, result
    assert "chamber_overview" in registered, "dinamik yukleme kaydetmedi"
    assert getattr(registered["chamber_overview"], "__emsal_threaded__", False) is True
