"""Micro-benchmark Suite for Emsal-mcp – v1.0

Deterministic benchmarks for indexing, search, and embedding operations.
Uses a fixed synthetic corpus for reproducibility.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .cache import Cache
from .models import ContentStatus, Document


def _build_synthetic_corpus(cache: Cache, size: int = 50) -> int:
    """Build a synthetic corpus of legal documents for benchmarking."""
    templates = [
        (
            "Sözleşme İhlali Kararı #{i}",
            "Taraflar arasındaki sözleşme hükümleri ihlal edilmiştir. "
            "Borçlar Kanunu madde {art} uyarınca tazminat talep edilebilir. "
            "Yargıtay {daire}. Hukuk Dairesi kararı incelenmiştir.",
        ),
        (
            "İş Kazası Tazminat Davası #{i}",
            "İş kazası sonucu oluşan maddi zararın tazmini istemiyle açılan dava. "
            "İşverenin kusur oranı bilirkişi raporuyla tespit edilmiştir. "
            "SGK kayıtları ve tanık beyanları değerlendirilmiştir.",
        ),
        (
            "İdari Para Cezası İptali #{i}",
            "İdari para cezasının iptali talebiyle açılan davada, "
            "idarenin yetkisiz olduğu anlaşılmıştır. Kabahatler Kanunu "
            "kapsamında değerlendirme yapılmıştır.",
        ),
        (
            "Vergi Davası Kararı #{i}",
            "Vergi Usul Kanunu kapsamında yapılan tarhiyatın iptali istemiyle "
            "açılan davada mahkeme, vergi matrahının hatalı hesaplandığına "
            "karar vermiştir. Danıştay içtihadı doğrultusunda değerlendirme yapılmıştır.",
        ),
        (
            "Tazminat Hukuku Kararı #{i}",
            "Haksız fiil sonucu oluşan manevi zararın tazmini talebiyle "
            "açılan davada, Türk Borçlar Kanunu m. 49 vd. hükümleri "
            "değerlendirilmiş, kusur oranı ve zarar miktarı belirlenmiştir.",
        ),
    ]

    sources = ["yargitay", "danistay", "bedesten"]
    courts = ["Yargitay", "Danistay", "Ankara Bölge İdare Mahkemesi"]
    chambers = ["3. Hukuk Dairesi", "10. Hukuk Dairesi", "Vergi Dava Dairesi"]

    count = 0
    for i in range(size):
        tmpl = templates[i % len(templates)]
        title = tmpl[0].format(i=i)
        text = tmpl[1].format(i=i, art=90 + (i % 20), daire=i % 13 + 1)

        doc = Document(
            source=sources[i % len(sources)],
            document_id=f"bench-{i:04d}",
            title=title,
            court=courts[i % len(courts)],
            chamber=chambers[i % len(chambers)],
            content_status=ContentStatus.FULL_TEXT,
            full_text=text,
            decision_date=f"2024-{((i % 12) + 1):02d}-15",
        )
        cache.store_document(doc)
        count += 1
    return count


def run_benchmarks(
    *,
    corpus_size: int = 50,
    repetitions: int = 1,
) -> dict[str, Any]:
    """Run the full benchmark suite.

    Args:
        corpus_size: Number of synthetic documents to create.
        repetitions: Number of times to repeat each benchmark (only first run timed).

    Returns:
        Dict with ok, benchmarks (per-test timings), summary.
    """
    from .semantic import (
        build_semantic_index,
        build_embedding_index,
        hybrid_search,
    )

    benchmarks: dict[str, Any] = {}
    total_start = time.monotonic()

    # Use temp in-memory DB for benchmarks
    tmp_path = Path(__import__("tempfile").mkdtemp(prefix="emsal_bench_"))
    db_path = tmp_path / "bench.sqlite3"

    try:
        cache = Cache(db_path)

        # 1. Corpus creation
        t0 = time.monotonic()
        doc_count = _build_synthetic_corpus(cache, size=corpus_size)
        t1 = time.monotonic()
        benchmarks["corpus_creation"] = {
            "documents": doc_count,
            "elapsed_ms": round((t1 - t0) * 1000, 1),
        }

        # 2. Build semantic index (FTS5 + TF-IDF)
        t0 = time.monotonic()
        index_result = build_semantic_index(cache=cache)
        t1 = time.monotonic()
        benchmarks["build_semantic_index"] = {
            "vectors_count": index_result.get("vectors_count", 0),
            "fts5_row_count": index_result.get("fts5_row_count", 0),
            "elapsed_ms": round((t1 - t0) * 1000, 1),
        }

        # 3. Build embedding index
        t0 = time.monotonic()
        emb_result = build_embedding_index(cache=cache, provider="local-hash-v1")
        t1 = time.monotonic()
        benchmarks["build_embedding_index"] = {
            "documents_indexed": emb_result.get("documents_indexed", 0),
            "provider": emb_result.get("provider", ""),
            "elapsed_ms": round((t1 - t0) * 1000, 1),
        }

        # 4. Hybrid search (warmup + timed)
        t0 = time.monotonic()
        search_result = hybrid_search("tazminat sözleşme", cache=cache)
        t1 = time.monotonic()
        benchmarks["hybrid_search"] = {
            "query": "tazminat sözleşme",
            "total_matches": search_result.get("total_matches", 0),
            "elapsed_ms": round((t1 - t0) * 1000, 1),
        }

        # 5. Dense search
        from .semantic import embedding_search
        t0 = time.monotonic()
        dense_result = embedding_search("tazminat sözleşme", cache=cache, provider="local-hash-v1")
        t1 = time.monotonic()
        benchmarks["embedding_search"] = {
            "query": "tazminat sözleşme",
            "total_matches": dense_result.get("total_matches", 0),
            "elapsed_ms": round((t1 - t0) * 1000, 1),
        }

        total_end = time.monotonic()

        return {
            "ok": True,
            "corpus_size": corpus_size,
            "benchmarks": benchmarks,
            "total_elapsed_ms": round((total_end - total_start) * 1000, 1),
            "version": "1.0.0",
        }
    except Exception as exc:
        from .models import build_error
        return build_error("BENCHMARK_FAILED", str(exc))
    finally:
        # Cleanup
        try:
            cache.close()
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(tmp_path, ignore_errors=True)
        except Exception:
            pass
