from __future__ import annotations

import os
from typing import Any

from .base import SourceClient
from .bedesten import BedestenClient
from .mevzuat import MevzuatClient
from .simple_public import (
    AymClient,
    DanistayClient,
    GibClient,
    RekabetClient,
    SayistayClient,
    UyusmazlikClient,
)
from emsal_mcp.models import ContentStatus, Document, SearchResult, SourceCapability, SourceSmokeResult, SourceStatus


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
# KIK — optional token-based activation.  No live API without token.
# ---------------------------------------------------------------------------

class _KikClient:
    """Kamu İhale Kurumu / EKAP v2 source client with optional token auth.

    If a token is found in KIK_API_TOKEN or EKAP_API_TOKEN environment
    variables, the client becomes EXPERIMENTAL and supports search via
    the EKAP v2 API.  Without a token the source stays UNAVAILABLE and
    returns structured placeholder payloads — identical to the previous
    hardcoded placeholder behaviour.
    """

    source_id = "kik"
    name = "Kamu İhale Kurumu / EKAP v2"
    public = True

    _EKAP_BASE = "https://ekap.kik.gov.tr"

    def __init__(self) -> None:
        self._token: str | None = (
            os.environ.get("KIK_API_TOKEN") or os.environ.get("EKAP_API_TOKEN")
        )
        if self._token:
            self._capability_status: SourceStatus = SourceStatus.EXPERIMENTAL
        else:
            self._capability_status = SourceStatus.UNAVAILABLE

    # ── capability flags ────────────────────────────────────────────────

    @property
    def _supports_search(self) -> bool:
        return self._token is not None

    _supports_get_document: bool = True
    _supports_full_text: bool = False
    _supports_pdf_link: bool = False
    _supports_metadata_only: bool = True
    _supports_workflow: bool = False

    @property
    def _live_smoke_recommended(self) -> bool:
        return self._token is not None

    @property
    def _known_limitations(self) -> list[str]:
        if self._token:
            return [
                "EXPERIMENTAL — token auth active, API endpoint not fully documented.",
                "Search results may be incomplete; response schema under investigation.",
                "Tam metin henüz desteklenmiyor; yalnızca metadata/metadata-only.",
            ]
        return [
            "Canlı EKAP v2 search önceki QC'de HTTP 401 döndürdü.",
            "Token yapılandırılmadı; KİK/EKAP araması kullanılamıyor.",
            "Login, token bypass, CAPTCHA/proxy veya şifreli KararId akışı uygulanmaz.",
            "Tam metin alınmaz; yalnızca metadata-only/unavailable placeholder döner.",
        ]

    @property
    def _notes(self) -> str:
        if self._token:
            return "KİK token auth active via EKAP_API_TOKEN / KIK_API_TOKEN env vars."
        return "KİK registered as unavailable placeholder; set EKAP_API_TOKEN to activate."

    # ── capability model ────────────────────────────────────────────────

    def capability_model(self) -> SourceCapability:
        return SourceCapability(
            source_id=self.source_id,
            display_name=self.name,
            status=self._capability_status,
            public=self.public,
            supports_search=self._supports_search,
            supports_get_document=self._supports_get_document,
            supports_full_text=self._supports_full_text,
            supports_pdf_link=self._supports_pdf_link,
            supports_metadata_only=self._supports_metadata_only,
            supports_workflow=self._supports_workflow,
            live_smoke_recommended=self._live_smoke_recommended,
            known_limitations=list(self._known_limitations),
            notes=self._notes,
        )

    def capabilities(self) -> dict[str, Any]:
        return self.capability_model().to_legacy_dict()

    # ── search ──────────────────────────────────────────────────────────

    _UNAVAIL_MSG = "KİK/EKAP canlı araması şu anda kullanılamıyor; token/auth akışı uygulanmadı."

    async def search(self, query: str, limit: int = 10, **kw: Any) -> list[SearchResult]:
        if not self._token:
            return [
                SearchResult(
                    source=self.source_id,
                    document_id="unavailable:kik-search",
                    title="KİK/EKAP araması kullanılamıyor",
                    summary=self._UNAVAIL_MSG,
                    court="Kamu İhale Kurumu",
                    content_status=ContentStatus.UNAVAILABLE,
                    metadata={"query": query, "knownLimitations": self._known_limitations},
                    recommended_next_step="KİK kararları için resmi EKAP erişimi/auth akışı manuel doğrulanmalıdır.",
                )
            ][: max(0, min(int(limit), 1))]

        # Token present — attempt live search (gated, no unauth calls)
        try:
            return await self._search_with_token(query, limit=limit, **kw)
        except Exception as exc:
            return [
                SearchResult(
                    source=self.source_id,
                    document_id="error:kik-search",
                    title="KİK/EKAP arama hatası",
                    summary=f"Token ile arama başarısız: {exc}",
                    court="Kamu İhale Kurumu",
                    content_status=ContentStatus.UNAVAILABLE,
                    metadata={
                        "query": query,
                        "error": str(exc),
                        "knownLimitations": self._known_limitations,
                    },
                    recommended_next_step="KİK API erişimi manuel olarak doğrulanmalıdır.",
                )
            ][: max(0, min(int(limit), 1))]

    async def _search_with_token(self, query: str, *, limit: int = 10, **kw: Any) -> list[SearchResult]:
        """Perform live search using the EKAP token.

        NOTE: The exact endpoint and response schema are not fully documented.
        This implementation uses the best-guess endpoint and parses common fields.
        If the endpoint is wrong, the exception handler in search() will produce
        an appropriate error result rather than crashing.
        """
        import httpx

        from emsal_mcp import __version__

        search_url = f"{self._EKAP_BASE}/api/v2/ihale/arama"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": f"EmsalMcp/{__version__} (+https://github.com/fatihsozer/emsal-mcp)",
        }
        payload = {"aramaMetni": query, "sayfa": 1, "sayfaBoyutu": min(limit, 20)}

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            resp = await http.post(search_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        items = (
            data.get("data", {}).get("ihaleListesi", [])
            or data.get("data", {}).get("data", [])
            or data.get("ihaleListesi", [])
            or []
        )
        for item in items[:limit]:
            doc_id = str(item.get("ihaleId", item.get("id", "")))
            title = item.get("ihaleAdi", item.get("baslik", "KİK İhale Kaydı"))
            results.append(
                SearchResult(
                    source=self.source_id,
                    document_id=f"kik:{doc_id}" if doc_id else "kik:unknown",
                    title=title,
                    summary=item.get("aciklama", item.get("idariAdi", "")) or None,
                    court="Kamu İhale Kurumu",
                    content_status=ContentStatus.METADATA_ONLY,
                    metadata={
                        "ihaleId": item.get("ihaleId"),
                        "ihaleTarihi": item.get("ihaleTarihi"),
                        "turu": item.get("turu"),
                    },
                    recommended_next_step="İhale detayları için resmi EKAP ekranından doğrulama gerekir.",
                )
            )
        return results

    # ── get_document ────────────────────────────────────────────────────

    async def get_document(self, document_id: str, **kw: Any) -> Document:
        if not self._token:
            return Document(
                source=self.source_id,
                document_id=document_id,
                title="KİK/EKAP belge placeholder",
                court="Kamu İhale Kurumu",
                summary=self._UNAVAIL_MSG,
                content_status=ContentStatus.METADATA_ONLY,
                metadata={"knownLimitations": self._known_limitations},
                recommended_next_step="Belge içeriği için resmi EKAP ekranından manuel doğrulama gerekir.",
            )

        # Token present — attempt live fetch
        try:
            return await self._get_document_with_token(document_id)
        except Exception as exc:
            return Document(
                source=self.source_id,
                document_id=document_id,
                title="KİK/EKAP belge hatası",
                court="Kamu İhale Kurumu",
                summary=f"Token ile belge alınamadı: {exc}",
                content_status=ContentStatus.UNAVAILABLE,
                metadata={"error": str(exc), "knownLimitations": self._known_limitations},
                recommended_next_step="Belge için resmi EKAP ekranından manuel doğrulama gerekir.",
            )

    async def _get_document_with_token(self, document_id: str) -> Document:
        """Fetch a single tender document using the EKAP token."""
        import httpx

        from emsal_mcp import __version__

        # Strip kik: prefix if present
        raw_id = document_id.removeprefix("kik:")
        url = f"{self._EKAP_BASE}/api/v2/ihale/{raw_id}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": f"EmsalMcp/{__version__} (+https://github.com/fatihsozer/emsal-mcp)",
        }

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            resp = await http.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        item = data.get("data", data)
        return Document(
            source=self.source_id,
            document_id=document_id,
            title=item.get("ihaleAdi", item.get("baslik", "KİK İhale Kaydı")),
            court="Kamu İhale Kurumu",
            summary=item.get("aciklama", item.get("idariAdi", "")) or None,
            content_status=ContentStatus.METADATA_ONLY,
            metadata={
                "ihaleId": item.get("ihaleId"),
                "ihaleTarihi": item.get("ihaleTarihi"),
                "turu": item.get("turu"),
            },
            recommended_next_step="İhale detayları için resmi EKAP ekranından doğrulama gerekir.",
        )

    # ── smoke test ──────────────────────────────────────────────────────

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        if not self._token:
            return SourceSmokeResult(
                source_id=self.source_id,
                offline_ok=True,
                search_callable=False,
                get_document_callable=True,
                min_content_length_ok=True,
                warnings=["No KIK API token configured; source is UNAVAILABLE."],
            )

        if not online:
            return SourceSmokeResult(
                source_id=self.source_id,
                offline_ok=True,
                search_callable=True,
                get_document_callable=True,
                min_content_length_ok=True,
                warnings=["KIK token present but online smoke not requested."],
            )

        # Online smoke — test token with a lightweight request
        try:
            import httpx

            from emsal_mcp import __version__

            test_url = f"{self._EKAP_BASE}/api/v2/ihale/arama"
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": f"EmsalMcp/{__version__} (+https://github.com/fatihsozer/emsal-mcp)",
            }
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as http:
                resp = await http.post(
                    test_url, json={"aramaMetni": "test", "sayfa": 1, "sayfaBoyutu": 1}, headers=headers
                )
                # 200-299 means token is accepted; 401/403 means bad token
                if resp.status_code in (401, 403):
                    return SourceSmokeResult(
                        source_id=self.source_id,
                        offline_ok=True,
                        online_ok=False,
                        search_callable=True,
                        get_document_callable=True,
                        min_content_length_ok=True,
                        warnings=[f"KIK token rejected (HTTP {resp.status_code})."],
                    )
                resp.raise_for_status()
            return SourceSmokeResult(
                source_id=self.source_id,
                offline_ok=True,
                online_ok=True,
                search_callable=True,
                get_document_callable=True,
                min_content_length_ok=True,
            )
        except Exception as exc:
            return SourceSmokeResult(
                source_id=self.source_id,
                offline_ok=True,
                online_ok=False,
                search_callable=True,
                get_document_callable=True,
                min_content_length_ok=True,
                warnings=[f"KIK auth test failed: {exc}"],
            )


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
        "Search relies on HTML scraping of the AYM information bank.",
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
        "kik": _KikClient(),
    }


def capabilities() -> list[dict[str, Any]]:
    """Return the full capability matrix for all sources (including unavailable KIK).

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
        return _extra_adapters[source]
    reg = registry()
    if source not in reg:
        raise KeyError(f"Bilinmeyen kaynak: {source}. Geçerli: {', '.join(reg)}")
    return reg[source]


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
    import asyncio
    return [r.model_dump(mode="json") for r in asyncio.run(smoke_all(online=online))]
