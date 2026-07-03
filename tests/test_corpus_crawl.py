"""Tests for crawl_full_text incremental mode (cache-aware skip + early stop)."""
import sys
import tempfile
from pathlib import Path

import pytest

from emsal_mcp.cache import Cache
from emsal_mcp.models import ContentStatus, Document, SearchResult
import emsal_mcp.corpus_builder as cb
import emsal_mcp.sources.registry  # noqa: F401 — ensure submodule is in sys.modules


def _sr(did: str) -> SearchResult:
    return SearchResult(
        source="bedesten", document_id=did, title="k",
        content_status=ContentStatus.HTML_MARKDOWN,
    )


def _doc(did: str) -> Document:
    return Document(
        source="bedesten", document_id=did, title="k",
        content_status=ContentStatus.HTML_MARKDOWN, full_text="tam " + did,
    )


class _Fake:
    """Fake source client; ``ids`` is the full newest-first list."""

    def __init__(self, ids):
        self.ids = ids
        self.fetches = 0

    async def search(self, phrase, limit, page, item_type, sort_direction, **kwargs):
        start = (page - 1) * limit
        return [_sr(d) for d in self.ids[start:start + limit]]

    async def get_document(self, document_id):
        self.fetches += 1
        return _doc(document_id)


@pytest.fixture()
def patched_source(monkeypatch):
    regmod = sys.modules["emsal_mcp.sources.registry"]

    def _install(client):
        monkeypatch.setattr(regmod, "get_source", lambda s: client)
        return client

    return _install


@pytest.fixture()
def cache():
    tmp = Path(tempfile.mkdtemp()) / "c.sqlite3"
    c = Cache(tmp)
    yield c
    c.close()


def test_incremental_fetches_only_new_and_stops_when_caught_up(patched_source, cache):
    base = [f"d{i:04d}" for i in range(300)]
    patched_source(_Fake(base))
    # Seed the cache with the newest 100.
    cb.crawl_full_text(cache=cache, max_docs=100, page_size=100, sort_direction="desc")

    # 10 brand-new decisions appear at the top; incremental run should fetch ONLY
    # those, skip the cached ones, and stop on caught_up.
    fresh = _Fake([f"new{i:02d}" for i in range(10)] + base)
    patched_source(fresh)
    r = cb.crawl_full_text(
        cache=cache, max_docs=1000, page_size=100, sort_direction="desc",
        incremental=True, stop_after_seen=20,
    )
    assert r["stored"] == 10            # only genuinely new
    assert fresh.fetches == 10          # no re-download of cached docs
    assert r["skipped_cached"] == 20    # hit the early-stop threshold
    assert r["stopped_reason"] == "caught_up"


def test_non_incremental_redownloads_everything(patched_source, cache):
    base = [f"d{i:04d}" for i in range(50)]
    patched_source(_Fake(base))
    cb.crawl_full_text(cache=cache, max_docs=100, page_size=100, sort_direction="desc")

    again = _Fake(base)
    patched_source(again)
    r = cb.crawl_full_text(cache=cache, max_docs=100, page_size=100, sort_direction="desc")
    # Without incremental, already-cached docs are re-fetched and re-stored.
    assert again.fetches == 50
    assert r["skipped_cached"] == 0
