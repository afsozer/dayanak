from __future__ import annotations

from typing import Any

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
from emsal_mcp.models import ContentStatus, Document, SearchResult, SourceCapability, SourceStatus


class YargitayClient(BedestenClient):
    source_id = "yargitay"
    name = "Yargıtay/Bedesten"


# ---------------------------------------------------------------------------
# KIK — unavailable placeholder.  No live API; metadata-only skeleton.
# ---------------------------------------------------------------------------

class _KikUnavailableClient:
    """Placeholder for Kayitli Isyerleri Kurumu (KIK).

    Currently no public search API or token-free EKAP v2 flow is supported.
    The placeholder returns structured unavailable/metadata-only payloads so
    MCP clients can degrade gracefully instead of failing with a tool error.
    """

    source_id = "kik"
    name = "Kamu İhale Kurumu / EKAP v2"
    public = True

    _capability_status: SourceStatus = SourceStatus.UNAVAILABLE
    _supports_search: bool = False
    _supports_get_document: bool = True
    _supports_full_text: bool = False
    _supports_pdf_link: bool = False
    _supports_metadata_only: bool = True
    _supports_workflow: bool = False
    _live_smoke_recommended: bool = False
    _known_limitations: list[str] = [
        "Canlı EKAP v2 search önceki QC'de HTTP 401 döndürdü.",
        "Login, token bypass, CAPTCHA/proxy veya şifreli KararId akışı uygulanmaz.",
        "Tam metin alınmaz; yalnızca metadata-only/unavailable placeholder döner.",
    ]
    _notes: str = "KİK intentionally registered as unavailable placeholder for contract stability."

    _UNAVAIL_MSG = "KİK/EKAP canlı araması şu anda kullanılamıyor; token/auth akışı uygulanmadı."

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

    async def search(self, query: str, limit: int = 10, **kw: Any):
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

    async def get_document(self, document_id: str, **kw: Any):
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
        "kik": _KikUnavailableClient(),
    }


def capabilities() -> list[dict[str, Any]]:
    """Return the full capability matrix for all sources (including unavailable KIK).

    Each entry is a dict with canonical snake_case keys plus legacy camelCase
    aliases for backward compatibility.
    """
    out: list[dict[str, Any]] = []
    for sid, src in registry().items():
        cap = src.capabilities()
        out.append(cap)
    return out


def get_source(source: str):
    """Return a client for *source*, including structured unavailable clients."""
    reg = registry()
    if source not in reg:
        raise KeyError(f"Bilinmeyen kaynak: {source}. Geçerli: {', '.join(reg)}")
    return reg[source]
