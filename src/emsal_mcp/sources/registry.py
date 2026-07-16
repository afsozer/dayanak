from __future__ import annotations

from typing import Any

from .base import SourceClient
from .bedesten import BedestenClient
from .mevzuat import MevzuatClient
from .simple_public import (
    AymClient,
    BtkClient,
    DanistayClient,
    GibClient,
    RekabetClient,
    SayistayClient,
    UyusmazlikClient,
)
from .resmigazete import ResmiGazeteClient
from .kvkk import KvkkClient
from .aihm import AihmClient
from emsal_mcp.models import SourceSmokeResult, SourceStatus


# ---------------------------------------------------------------------------
# Extra (plugin / test) adapters — populated by register_adapter()
# ---------------------------------------------------------------------------

_extra_adapters: dict[str, Any] = {}


def register_adapter(source_id: str, client_instance: Any) -> None:
    """Register a custom adapter (for plugins/testing).

    After registration, ``get_source(source_id)`` returns *client_instance*
    and it appears in the capability matrix.

    This does NOT persist across restarts — call it at application startup.
    """
    _extra_adapters[source_id] = client_instance


class YargitayClient(BedestenClient):
    source_id = "yargitay"
    name = "Yargıtay/Bedesten"
    _default_item_type = "YARGITAYKARARI"


# ---------------------------------------------------------------------------
# Source-specific known limitations
# ---------------------------------------------------------------------------

class _BedestenClient(BedestenClient):
    _known_limitations: list[str] = [
        "Content returned as base64-encoded HTML; PDF documents yield only a link.",
    ]
    _notes: str = "Bedesten API is internal to Adalet Bakanlığı; availability depends on upstream."


class _YargitayClient(YargitayClient):
    _known_limitations: list[str] = [
        "Content returned as base64-encoded HTML; PDF documents yield only a link.",
    ]
    _notes: str = "Shares Bedesten API infrastructure."


class _MevzuatClient(MevzuatClient):
    _capability_status = SourceStatus.EXPERIMENTAL
    _supports_article_search = True
    _supports_type_filter = True
    _known_limitations: list[str] = [
        "Mevzuat search results are metadata-only; full text requires Bedesten fetch.",
    ]
    _notes: str = "Legislation documents rather than court decisions."


class _AymClient(AymClient):
    _known_limitations: list[str] = [
        "KBB JSON API kullanılır (F5 WAF: tarayıcı UA + cookie warm-up gerekli). "
        "Karar tam metni UDF dosyasından çıkarılır; dosya listesi ucu ara sıra "
        "HTTP 500 döndürür (bir kez otomatik yeniden denenir).",
    ]


class _DanistayClient(DanistayClient):
    _known_limitations: list[str] = [
        "Search relies on the Danıştay karar-arama AJAX endpoint.",
    ]


class _GibClient(GibClient):
    _known_limitations: list[str] = [
        "Only publishes Ministerial opinions (özelge); not a court decision source.",
    ]


class _UyusmazlikClient(UyusmazlikClient):
    _capability_status = SourceStatus.PARTIAL
    _supports_full_text = False
    _supports_pdf_link = True
    _known_limitations: list[str] = [
        "Many decisions are PDF-only links; HTML scraping is ASP.NET form-based.",
    ]


class _RekabetClient(RekabetClient):
    _capability_status = SourceStatus.PARTIAL
    _supports_full_text = False
    _supports_pdf_link = True
    _known_limitations: list[str] = [
        "Rekabet Kurumu decision details are scraped from HTML table markup.",
    ]


class _SayistayClient(SayistayClient):
    _capability_status = SourceStatus.PARTIAL
    _known_limitations: list[str] = [
        "DataTables-based scraping; may require CSRF tokens.",
    ]


class _ResmiGazeteClient(ResmiGazeteClient):
    _capability_status = SourceStatus.EXPERIMENTAL
    _known_limitations: list[str] = [
        "HTML-only scraping; no structured API available.",
        "Search may require session/cookie handling.",
    ]


class _KvkkClient(KvkkClient):
    _capability_status = SourceStatus.EXPERIMENTAL
    _known_limitations: list[str] = [
        "HTML-only scraping; no structured API available.",
        "Search may require session/cookie handling.",
    ]


class _BtkClient(BtkClient):
    _capability_status = SourceStatus.PARTIAL
    _known_limitations: list[str] = [
        "HTML card-based scraping from server-rendered page.",
        "No server-side keyword search; local filter applied client-side.",
        "Decision text requires PDF download and extraction.",
    ]


class _AihmClient(AihmClient):
    _capability_status = SourceStatus.EXPERIMENTAL
    _known_limitations: list[str] = [
        "HUDOC belgeleri orijinal dilinde döner (ENG/FRE); Türkçe çeviri her "
        "kararda bulunmaz. Sorgu contentsitename:ECHR ile başlamalıdır "
        "(adaptör bunu otomatik ekler).",
    ]


# ---------------------------------------------------------------------------
# Registry and capability matrix
# ---------------------------------------------------------------------------

def registry() -> dict[str, Any]:
    """Return source_id -> client instance for all known sources."""
    return {
        "bedesten": _BedestenClient(),
        "yargitay": _YargitayClient(),
        "mevzuat": _MevzuatClient(),
        "aym": _AymClient(),
        "danistay": _DanistayClient(),
        "gib": _GibClient(),
        "uyusmazlik": _UyusmazlikClient(),
        "rekabet": _RekabetClient(),
        "sayistay": _SayistayClient(),
        "resmigazete": _ResmiGazeteClient(),
        "kvkk": _KvkkClient(),
        "aihm": _AihmClient(),
        "btk": _BtkClient(),
    }


def capabilities() -> list[dict[str, Any]]:
    """Return the full capability matrix for all sources.

    Each entry is a dict with canonical snake_case keys plus legacy camelCase
    aliases for backward compatibility.  Extra adapters registered via
    ``register_adapter()`` are included.
    """
    out: list[dict[str, Any]] = []
    for sid, src in registry().items():
        cap = src.capabilities()
        out.append(cap)
    for sid, src in _extra_adapters.items():
        if hasattr(src, "capabilities"):
            cap = src.capabilities()
        else:
            cap = {"source_id": sid, "name": getattr(src, "name", sid)}
        out.append(cap)
    return out


def get_source(source: str) -> SourceClient:
    """Return a client for *source*, including structured unavailable clients.

    Extra (plugin/test) adapters registered via ``register_adapter()``
    take precedence over built-in sources.
    """
    if source in _extra_adapters:
        return _extra_adapters[source]  # type: ignore[no-any-return]
    reg = registry()
    if source not in reg:
        raise KeyError(f"Bilinmeyen kaynak: {source}. Geçerli: {', '.join(reg)}")
    return reg[source]  # type: ignore[no-any-return]


async def smoke_all(online: bool = False) -> list[SourceSmokeResult]:
    """Run offline/online smoke for all registered sources."""
    results: list[SourceSmokeResult] = []
    all_sources = list(registry().items()) + list(_extra_adapters.items())
    for sid, src in all_sources:
        try:
            result = await src.smoke(online=online)
            results.append(result)
        except Exception as exc:
            results.append(SourceSmokeResult(
                source_id=sid, offline_ok=False,
                errors=[f"smoke() raised: {exc}"],
            ))
    return results


def smoke_all_sync(online: bool = False) -> list[dict[str, Any]]:
    """Synchronous wrapper for smoke_all (for CLI)."""
    from ..concurrency import run_sync
    return [r.model_dump(mode="json") for r in run_sync(smoke_all(online=online))]
