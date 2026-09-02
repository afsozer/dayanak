"""M-119: arac cagrilarina zaman siniri + kacak (runaway) sayaclari.

M-118 sync araclari worker thread'e tasidi ama bir arac sonsuza kadar
kosabiliyordu.  ``server.main()`` artik her arac cagrisini
``anyio.fail_after`` ile sariyor:

* varsayilan tavan ``EMSAL_TOOL_TIMEOUT`` (saniye, varsayilan 120; ``0`` =
  sinirsiz), arac bazli tavan ``_TOOL_TIMEOUTS``;
* zaman asiminda istemciye ``build_error("TOOL_TIMEOUT", ...)`` govdesi
  doner (arac adi, gecen sure, "arka planda surebilir" uyarisi,
  ``recommended_next_steps``);
* async araclar gercekten iptal edilir; sync araclar EDILEMEZ - thread
  ``fn`` bitene kadar kosar.  Bu yuzden zaman asan sync cagrilar "runaway"
  olarak sayiliyor ve ``health_check`` ``tool_runtime`` blogunda
  raporlaniyor.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.integration]


def _capture_registered(profile: str = "full") -> dict:
    """``mcp.tool()`` cagrisina VERILEN nesneyi dondur (soyulmamis)."""
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


SYNC_TOOL = "list_sources"
ASYNC_TOOL = "check_government_servers_health"


def _make_sync_tool_slow(monkeypatch, seconds: float) -> None:
    """``list_sources(detail="birim_codes")`` govdesini yavaslatir."""
    import emsal_mcp.birim_enum as birim_enum

    original = birim_enum.list_birim_codes

    def slow(*a, **kw):
        time.sleep(seconds)
        return original(*a, **kw)

    monkeypatch.setattr(birim_enum, "list_birim_codes", slow)


def _make_health_check_cheap(monkeypatch) -> None:
    """health_check'in agir I/O bagimliliklarini ucuzlatir.

    ``main()`` bu isimleri cagri aninda ``from ... import`` ile aldigi icin
    modul uzerinde yamalamak yeterli (yamayi ``main()``den ONCE koy).
    """
    import importlib

    import emsal_mcp.semantic as semantic

    # ``emsal_mcp.sources`` paketinde ayni adli bir fonksiyon oldugu icin
    # ``import ... as registry`` alt modulu DEGIL fonksiyonu getirir.
    registry = importlib.import_module("emsal_mcp.sources.registry")

    monkeypatch.setattr(registry, "smoke_all_sync", lambda **kw: [])
    monkeypatch.setattr(semantic, "get_index_status", lambda *a, **kw: {"stub": True})


# ── 1. Sync arac: zaman asimi hata govdesi ────────────────────────────────

def test_sync_tool_timeout_returns_error_body(monkeypatch) -> None:
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "0.2")
    _make_sync_tool_slow(monkeypatch, 1.0)

    tool = _capture_registered("full")[SYNC_TOOL]

    started = time.monotonic()
    result = asyncio.run(tool(detail="birim_codes"))
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert result["errorCode"] == "TOOL_TIMEOUT"
    assert result["retryable"] is True
    assert result["tool"] == SYNC_TOOL
    assert result["timeout_seconds"] == pytest.approx(0.2)
    assert result["elapsed_seconds"] >= 0.2
    # sync arac iptal edilemez: kacak olarak isaretlenmeli
    assert result["cancelled"] is False
    assert any("arka planda" in w for w in result["warnings"]), result["warnings"]
    assert result["recommended_next_steps"], "yol gosterici adim yok"
    # Cagri gercekten erken donmus olmali (1.0 sn'lik govdeyi beklememeli).
    assert elapsed < 0.9, f"zaman siniri islemedi: {elapsed:.2f} sn"

    # Kacak thread'in test bitmeden kapanmasini bekle.
    time.sleep(1.0)


def test_sync_tool_under_the_limit_is_untouched(monkeypatch) -> None:
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "5")
    tool = _capture_registered("full")[SYNC_TOOL]
    result = asyncio.run(tool(detail="birim_codes"))
    assert result["ok"] is True
    assert "errorCode" not in result


# ── 2. EMSAL_TOOL_TIMEOUT=0 → sinirsiz ────────────────────────────────────

def test_timeout_zero_means_unlimited(monkeypatch) -> None:
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "0")
    _make_sync_tool_slow(monkeypatch, 0.4)

    tool = _capture_registered("full")[SYNC_TOOL]
    started = time.monotonic()
    result = asyncio.run(tool(detail="birim_codes"))
    elapsed = time.monotonic() - started

    assert result["ok"] is True, result
    assert elapsed >= 0.4, "sinirsiz modda govde tam kosmaliydi"
    assert getattr(tool, "__emsal_threaded__", False) is True


def test_invalid_timeout_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "abc")
    _make_health_check_cheap(monkeypatch)
    tools = _capture_registered("full")
    hc = asyncio.run(tools["health_check"]())
    assert hc["tool_runtime"]["timeout_seconds"] == 120.0


# ── 3. Async arac: gercek iptal ───────────────────────────────────────────

class _SlowAsyncClient:
    """``check_government_servers_health`` icin yavas httpx sahtesi."""

    finished = False

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        await asyncio.sleep(5.0)
        type(self).finished = True
        raise AssertionError("buraya gelinmemeliydi")


def test_async_tool_is_really_cancelled(monkeypatch) -> None:
    import httpx

    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "0.2")
    _SlowAsyncClient.finished = False
    monkeypatch.setattr(httpx, "AsyncClient", _SlowAsyncClient)

    tool = _capture_registered("full")[ASYNC_TOOL]
    # async arac thread'e tasinmaz, sadece zaman siniri sarmalayicisi alir
    assert getattr(tool, "__emsal_timeout__", False) is True
    assert getattr(tool, "__emsal_threaded__", False) is False

    started = time.monotonic()
    result = asyncio.run(tool())
    elapsed = time.monotonic() - started

    assert result["errorCode"] == "TOOL_TIMEOUT"
    assert result["tool"] == ASYNC_TOOL
    # Coroutine gercekten iptal edildi: kacak yok.
    assert result["cancelled"] is True
    assert elapsed < 1.0, f"async iptal calismadi: {elapsed:.2f} sn"
    assert _SlowAsyncClient.finished is False


# ── 4. Sayaclar / health_check tool_runtime ───────────────────────────────

def test_health_check_reports_tool_runtime(monkeypatch) -> None:
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "5")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "30")
    _make_health_check_cheap(monkeypatch)

    tools = _capture_registered("full")
    hc = asyncio.run(tools["health_check"]())
    tr = hc["tool_runtime"]

    assert set(tr) == {
        "threads_limit", "timeout_seconds", "in_flight",
        "timed_out_total", "runaway", "borrowed_tokens",
    }
    assert tr["threads_limit"] == 5
    assert tr["timeout_seconds"] == 30.0
    assert tr["timed_out_total"] == 0
    assert tr["runaway"] == 0
    # health_check'in kendisi de bir thread jetonu tutar
    assert tr["in_flight"] == 1
    assert tr["borrowed_tokens"] == 1


def test_runaway_counter_rises_then_falls(monkeypatch) -> None:
    """Zaman asan sync cagri kacak sayilir; govde bitince sayac duser."""
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "0.2")
    _make_sync_tool_slow(monkeypatch, 1.5)
    _make_health_check_cheap(monkeypatch)

    tools = _capture_registered("full")

    async def drive():
        first = await tools[SYNC_TOOL](detail="birim_codes")
        assert first["errorCode"] == "TOOL_TIMEOUT"
        # Govde hala kosuyor.
        hot = (await tools["health_check"]())["tool_runtime"]
        # Govde bitene kadar bekle.
        await asyncio.sleep(2.0)
        cold = (await tools["health_check"]())["tool_runtime"]
        return hot, cold

    hot, cold = asyncio.run(drive())

    assert hot["timed_out_total"] == 1
    assert hot["runaway"] == 1, hot
    assert cold["timed_out_total"] == 1, "toplam sayac geri sarmamali"
    assert cold["runaway"] == 0, cold


def test_timed_out_total_accumulates(monkeypatch) -> None:
    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "0.2")
    _make_sync_tool_slow(monkeypatch, 0.6)
    _make_health_check_cheap(monkeypatch)

    tools = _capture_registered("full")

    async def drive():
        for _ in range(3):
            r = await tools[SYNC_TOOL](detail="birim_codes")
            assert r["errorCode"] == "TOOL_TIMEOUT"
        return (await tools["health_check"]())["tool_runtime"]

    tr = asyncio.run(drive())
    assert tr["timed_out_total"] == 3, tr
    time.sleep(0.8)


# ── 5. Sarmalayici isaretleri / sema korunuyor ────────────────────────────

def test_timeout_wrapper_keeps_markers_and_signature(monkeypatch) -> None:
    import inspect

    monkeypatch.setenv("EMSAL_TOOL_THREADS", "4")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "120")
    tools = _capture_registered("full")

    sync_tool = tools["search_local_corpus"]
    assert getattr(sync_tool, "__emsal_threaded__", False) is True
    assert getattr(sync_tool, "__emsal_timeout__", False) is True
    assert inspect.signature(sync_tool) == inspect.signature(sync_tool.__wrapped__)

    async_tool = tools[ASYNC_TOOL]
    assert inspect.signature(async_tool) == inspect.signature(async_tool.__wrapped__)


def test_threads_zero_disables_timeout_for_sync_tools(monkeypatch) -> None:
    """Thread yoksa bloklayan cagriya zaman siniri UYGULANAMAZ; sarmalanmaz."""
    import inspect

    monkeypatch.setenv("EMSAL_TOOL_THREADS", "0")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "0.2")
    tools = _capture_registered("full")

    assert not inspect.iscoroutinefunction(tools[SYNC_TOOL])
    assert not getattr(tools[SYNC_TOOL], "__emsal_timeout__", False)
    # Async araclar yine de zaman sinirli kalir.
    assert getattr(tools[ASYNC_TOOL], "__emsal_timeout__", False) is True


def test_runaway_triggers_warning_log(monkeypatch, caplog) -> None:
    """Kacak sayisi limiter kapasitesine yaklasinca WARNING dusmeli.

    Esik ``max(1, EMSAL_TOOL_THREADS - 1)``; 2 thread ile tek bir kacak
    yeter.
    """
    import logging

    monkeypatch.setenv("EMSAL_TOOL_THREADS", "2")
    monkeypatch.setenv("EMSAL_TOOL_TIMEOUT", "0.2")
    _make_sync_tool_slow(monkeypatch, 1.0)

    tool = _capture_registered("full")[SYNC_TOOL]

    with caplog.at_level(logging.WARNING, logger="emsal_mcp.server"):
        result = asyncio.run(tool(detail="birim_codes"))

    assert result["errorCode"] == "TOOL_TIMEOUT"
    hits = [
        r for r in caplog.records
        if r.name == "emsal_mcp.server" and "iptal edilemeyen" in r.getMessage()
    ]
    assert hits, [r.getMessage() for r in caplog.records]
    assert "kuyrukta bekleyebilir" in hits[0].getMessage()

    time.sleep(1.0)
