"""v0.14 Citation graph: extract court decision references and build citation edges.

Extracts citation candidates from cached document texts using ``citation.py``
patterns, matches them against the local cache, and stores verified edges in a
``citation_edges`` table.  Never fabricates — only detectable, verifiable
references are graphed.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .cache import Cache
from .citation import CitationCandidate, extract_citation_candidates
from .models import build_error

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

_CREATE_EDGES_SQL = """
CREATE TABLE IF NOT EXISTS citation_edges (
    citing_doc_id TEXT NOT NULL,
    citing_source TEXT NOT NULL,
    cited_doc_id TEXT NOT NULL,
    cited_source TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'low',
    match_type TEXT NOT NULL DEFAULT 'unknown',
    extracted_from TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (citing_doc_id, citing_source, cited_doc_id, cited_source)
)
"""


def _ensure_edge_table(cache: Cache) -> None:
    """Create citation_edges table if it doesn't exist."""
    cache.db.execute(_CREATE_EDGES_SQL)
    cache.db.commit()


_GRAPH_NEVER_BUILT_WARNING = (
    "Atıf grafı hiç oluşturulmamış: citation_edges tablosu boş (0 kayıt). "
    "Aşağıdaki sonuç 'atıf bulunamadı' değil, 'graf hiç kurulmadı' anlamına gelir."
)
_GRAPH_BUILT_BUT_EMPTY_WARNING = (
    "Atıf grafı en son {when} tarihinde oluşturulmuş ama citation_edges tablosu "
    "boş (0 kayıt) — o çalışma hiç atıf eşleştirememiş. Aşağıdaki sonuç 'atıf "
    "bulunamadı' değil, 'graf kullanılabilir durumda değil' anlamına gelir."
)
_GRAPH_NEVER_BUILT_RECOMMENDATION = (
    "build_citation_graph() çağırarak atıf grafını oluşturun."
)


def _last_graph_build(cache: Cache) -> str | None:
    """Timestamp of the last build_citation_graph() run, if any.

    Single indexed row lookup against the history table that
    ``build_citation_graph()`` already writes on every run.
    """
    row = cache.db.execute(
        "SELECT created_at FROM history WHERE action='build_citation_graph' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["created_at"] if row else None


def _graph_build_state(cache: Cache) -> tuple[int, list[str], list[str]]:
    """Report whether the citation graph has ever been populated.

    Returns ``(total_edges, warnings, recommended_next_steps)``. When
    ``total_edges`` is 0 the ``citation_edges`` table is empty overall —
    a materially different situation from "this specific document has no
    citations" in an already-populated graph. Callers use this to attach an
    unmistakable warning to the former case while leaving the latter
    warning-free.

    The empty case is split in two, because they need different wording and
    different follow-up: a graph that has never run at all, versus one that
    ran and matched nothing. The latter is what the real corpus shows — a
    build dated 2026-05-29, executed back when the corpus held only a handful
    of test fixtures, that produced zero edges. Saying "never built" there
    would contradict the timestamp the same response reports.
    """
    total_edges = cache.db.execute("SELECT COUNT(*) FROM citation_edges").fetchone()[0]
    if total_edges == 0:
        last_built = _last_graph_build(cache)
        warning = (
            _GRAPH_BUILT_BUT_EMPTY_WARNING.format(when=last_built)
            if last_built else _GRAPH_NEVER_BUILT_WARNING
        )
        return 0, [warning], [_GRAPH_NEVER_BUILT_RECOMMENDATION]
    return total_edges, [], []


# ---------------------------------------------------------------------------
# Internal matching helpers
# ---------------------------------------------------------------------------

def _normalize_no(val: str | None) -> str | None:
    """Normalize a number string for comparison (strip whitespace, lowercase)."""
    if val is None:
        return None
    return val.strip().lower()


def _match_exact_esas_karar(
    candidate: CitationCandidate,
    doc: dict[str, Any],
) -> bool:
    """High-confidence match: both esas_no AND karar_no match AND court matches."""
    c_esas = _normalize_no(candidate.esas_no)
    d_esas = _normalize_no(doc.get("esas_no"))
    c_karar = _normalize_no(candidate.karar_no)
    d_karar = _normalize_no(doc.get("karar_no"))

    if not c_esas or not d_esas or not c_karar or not d_karar:
        return False

    if c_esas != d_esas or c_karar != d_karar:
        return False

    # Court must also match (or both be None)
    if candidate.court and doc.get("court"):
        if candidate.court.lower() not in doc["court"].lower() and doc["court"].lower() not in candidate.court.lower():
            return False

    return True


def _match_karar_only(candidate: CitationCandidate, doc: dict[str, Any]) -> bool:
    """Medium-confidence match: karar_no matches (esas may differ)."""
    c_karar = _normalize_no(candidate.karar_no)
    d_karar = _normalize_no(doc.get("karar_no"))
    if not c_karar or not d_karar:
        return False
    return c_karar == d_karar


def _match_court_date(
    candidate: CitationCandidate,
    doc: dict[str, Any],
    *,
    year_tolerance: int = 1,
) -> bool:
    """Medium-confidence match: court matches AND decision_date within tolerance."""
    if not candidate.court or not doc.get("court"):
        return False
    if not candidate.date or not doc.get("decision_date"):
        return False

    # Court must match
    if candidate.court.lower() not in doc["court"].lower() and doc["court"].lower() not in candidate.court.lower():
        return False

    # Date within tolerance (compare years)
    try:
        cand_year = int(candidate.date[:4])
        doc_year = int(doc["decision_date"][:4])
        if abs(cand_year - doc_year) <= year_tolerance:
            return True
    except (ValueError, IndexError):
        pass
    return False


def _match_title_keyword(candidate: CitationCandidate, doc: dict[str, Any]) -> bool:
    """Low-confidence match: title keyword overlap."""
    title = doc.get("title") or ""
    if not title or not candidate.court:
        return False
    # Simple check: court name appears in title
    return candidate.court.lower() in title.lower()


def _classify_match(
    candidate: CitationCandidate,
    doc: dict[str, Any],
) -> tuple[str, str] | None:
    """Try matching strategies in priority order. Returns (confidence, match_type) or None."""
    if _match_exact_esas_karar(candidate, doc):
        return ("high", "exact_esas_karar")
    if _match_karar_only(candidate, doc):
        return ("medium", "karar_no_match")
    if _match_court_date(candidate, doc):
        return ("medium", "court_date_match")
    if _match_title_keyword(candidate, doc):
        return ("low", "title_fuzzy")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_citation_graph(
    cache: Cache | None = None,
    sources_override: dict[str, Any] | None = None,  # unused, kept for interface compat
    limit_docs: int = 100,
) -> dict[str, Any]:
    """Build the citation graph by extracting references from cached documents.

    1. Select up to ``limit_docs`` documents with full_text or markdown.
    2. Extract citation candidates from each document.
    3. Search local cache for matching documents.
    4. Insert verified edges into ``citation_edges`` table.

    Args:
        cache: Optional Cache instance (creates one if None).
        sources_override: Unused; kept for interface compatibility.
        limit_docs: Maximum documents to process.

    Returns:
        Dict with ok, edges_created, docs_processed, citations_found,
        matches_found, confidence_distribution, warnings.
    """
    t0 = time.time()
    c = cache or Cache()
    own_cache = cache is None
    warnings: list[str] = []

    try:
        _ensure_edge_table(c)

        # 1. Select documents with content — M-51: use cursor iteration
        cursor = c.db.execute(
            """SELECT document_id, source, title, court, chamber, decision_date,
                      esas_no, karar_no, full_text, markdown
               FROM documents_v2
               WHERE full_text IS NOT NULL OR markdown IS NOT NULL
               ORDER BY last_accessed_at DESC
               LIMIT ?""",
            (limit_docs,),
        )

        first_row = cursor.fetchone()
        if not first_row:
            return {
                "ok": True,
                "edges_created": 0,
                "docs_processed": 0,
                "citations_found": 0,
                "matches_found": 0,
                "confidence_distribution": {"high": 0, "medium": 0, "low": 0},
                "warnings": ["Cached document bulunamadı; graf oluşturulamadı."],
                "timing_ms": round((time.time() - t0) * 1000, 1),
            }

        edges_created = 0
        citations_found = 0
        matches_found = 0
        docs_processed = 0
        conf_dist: dict[str, int] = {"high": 0, "medium": 0, "low": 0}

        def _process_row(row: Any) -> None:
            nonlocal edges_created, citations_found, matches_found, docs_processed
            doc_id = row["document_id"]
            source = row["source"]
            text = row["full_text"] or row["markdown"] or ""
            if not text or len(text.strip()) < 20:
                return

            docs_processed += 1

            # Extract citation candidates
            candidates = extract_citation_candidates(text, limit=10)
            citations_found += len(candidates)

            for cand in candidates:
                # Search cache for matching documents
                matched_docs = _search_cache_for_match(c, cand, exclude=(doc_id, source))

                for match_doc in matched_docs:
                    result = _classify_match(cand, match_doc)
                    if result is None:
                        continue
                    confidence, match_type = result
                    matches_found += 1
                    conf_dist[confidence] = conf_dist.get(confidence, 0) + 1

                    # Insert edge (idempotent via UPSERT)
                    c.db.execute(
                        """INSERT OR IGNORE INTO citation_edges
                           (citing_doc_id, citing_source, cited_doc_id, cited_source,
                            confidence, match_type, extracted_from)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            doc_id, source,
                            match_doc["document_id"], match_doc["source"],
                            confidence, match_type,
                            cand.raw_text[:500],
                        ),
                    )
                    edges_created += 1

        # M-51: process first row, then iterate remaining via cursor
        _process_row(first_row)
        for row in cursor:
            _process_row(row)

        c.db.commit()
        c.log("build_citation_graph", {
            "docs_processed": docs_processed,
            "citations_found": citations_found,
            "matches_found": matches_found,
            "edges_created": edges_created,
        })

        return {
            "ok": True,
            "edges_created": edges_created,
            "docs_processed": docs_processed,
            "citations_found": citations_found,
            "matches_found": matches_found,
            "confidence_distribution": conf_dist,
            "warnings": warnings,
            "timing_ms": round((time.time() - t0) * 1000, 1),
        }
    except Exception as exc:
        return build_error("GRAPH_BUILD_FAILED", f"Citation graph oluşturulamadı: {exc}")
    finally:
        if own_cache:
            c.close()


def _search_cache_for_match(
    cache: Cache,
    candidate: CitationCandidate,
    *,
    exclude: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Search cache for documents matching a citation candidate.

    Uses OR logic between fields to maximize recall: a document matching
    on karar_no but not esas_no should still be found for medium-confidence
    classification.
    """
    or_conditions: list[str] = []
    params: list[Any] = []

    # Try esas_no match
    if candidate.esas_no:
        or_conditions.append("esas_no LIKE ?")
        params.append(f"%{candidate.esas_no}%")

    # Try karar_no match
    if candidate.karar_no:
        or_conditions.append("karar_no LIKE ?")
        params.append(f"%{candidate.karar_no}%")

    # Try court + title match
    if candidate.court:
        or_conditions.append("(court LIKE ? OR title LIKE ?)")
        params.append(f"%{candidate.court}%")
        params.append(f"%{candidate.court}%")

    # Exclude the citing document itself
    exclude_clause = ""
    if exclude:
        exclude_clause = " AND NOT (document_id = ? AND source = ?)"
        params.extend(list(exclude))

    if not or_conditions:
        return []

    where = " WHERE (" + " OR ".join(or_conditions) + ")" + exclude_clause
    sql = f"SELECT document_id, source, title, court, chamber, decision_date, esas_no, karar_no FROM documents_v2{where} LIMIT 20"
    rows = cache.db.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_citation_graph(
    document_id: str,
    source: str,
    cache: Cache | None = None,
    direction: str = "both",
    max_depth: int = 1,
) -> dict[str, Any]:
    """Get citation relationships for a document.

    Args:
        document_id: The document ID.
        source: The source identifier.
        cache: Optional Cache instance.
        direction: 'citing' (docs that cite this), 'cited' (docs this cites),
                   or 'both'.
        max_depth: Traversal depth (1 = direct only).

    Returns:
        Dict with ok, document, citing, cited_by, total_edges, warnings,
        recommended_next_steps. ``warnings``/``recommended_next_steps`` are
        only populated when the citation graph has never been built
        (citation_edges table is empty overall) — a document that simply has
        no citations in an already-built graph gets an empty warnings list.
    """
    c = cache or Cache()
    own_cache = cache is None

    try:
        _ensure_edge_table(c)

        # Get the document info
        doc_row = c.db.execute(
            "SELECT document_id, source, title, court, chamber, esas_no, karar_no FROM documents_v2 WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()
        if not doc_row:
            return build_error("DOC_NOT_FOUND", f"Belge bulunamadı: {source}:{document_id}")
        doc_info = dict(doc_row)

        _, warnings, recommended = _graph_build_state(c)

        citing: list[dict[str, Any]] = []
        cited_by: list[dict[str, Any]] = []

        if direction in ("cited", "both"):
            # Docs this document cites
            rows = c.db.execute(
                """SELECT cited_doc_id, cited_source, confidence, match_type, extracted_from, created_at
                   FROM citation_edges
                   WHERE citing_doc_id=? AND citing_source=?
                   ORDER BY confidence""",
                (document_id, source),
            ).fetchall()
            for row in rows:
                # Enrich with document title
                target = c.db.execute(
                    "SELECT title FROM documents_v2 WHERE document_id=? AND source=?",
                    (row["cited_doc_id"], row["cited_source"]),
                ).fetchone()
                cited_by.append({
                    "document_id": row["cited_doc_id"],
                    "source": row["cited_source"],
                    "title": target["title"] if target else None,
                    "confidence": row["confidence"],
                    "match_type": row["match_type"],
                    "extracted_from": row["extracted_from"],
                    "created_at": row["created_at"],
                })

        if direction in ("citing", "both"):
            # Docs that cite this document
            rows = c.db.execute(
                """SELECT citing_doc_id, citing_source, confidence, match_type, extracted_from, created_at
                   FROM citation_edges
                   WHERE cited_doc_id=? AND cited_source=?
                   ORDER BY confidence""",
                (document_id, source),
            ).fetchall()
            for row in rows:
                target = c.db.execute(
                    "SELECT title FROM documents_v2 WHERE document_id=? AND source=?",
                    (row["citing_doc_id"], row["citing_source"]),
                ).fetchone()
                citing.append({
                    "document_id": row["citing_doc_id"],
                    "source": row["citing_source"],
                    "title": target["title"] if target else None,
                    "confidence": row["confidence"],
                    "match_type": row["match_type"],
                    "extracted_from": row["extracted_from"],
                    "created_at": row["created_at"],
                })

        total_edges = len(citing) + len(cited_by)

        return {
            "ok": True,
            "document": doc_info,
            "citing": citing,
            "cited_by": cited_by,
            "total_edges": total_edges,
            "warnings": warnings,
            "recommended_next_steps": recommended,
        }
    except Exception as exc:
        return build_error("GRAPH_QUERY_FAILED", f"Sorgu başarısız: {exc}")
    finally:
        if own_cache:
            c.close()


def find_citing_documents(
    document_id: str,
    source: str,
    cache: Cache | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Find documents that cite the given document.

    Args:
        document_id: The cited document ID.
        source: The cited document source.
        cache: Optional Cache instance.
        limit: Maximum results.

    Returns:
        Dict with ok, document, citing_documents list, warnings,
        recommended_next_steps. ``warnings``/``recommended_next_steps`` are
        only populated when the citation graph has never been built
        (citation_edges table is empty overall) — a document that simply has
        no citing documents in an already-built graph gets an empty
        warnings list.
    """
    c = cache or Cache()
    own_cache = cache is None

    try:
        _ensure_edge_table(c)

        # Verify document exists
        doc_row = c.db.execute(
            "SELECT document_id, source, title FROM documents_v2 WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()
        if not doc_row:
            return build_error("DOC_NOT_FOUND", f"Belge bulunamadı: {source}:{document_id}")

        _, warnings, recommended = _graph_build_state(c)

        rows = c.db.execute(
            """SELECT citing_doc_id, citing_source, confidence, match_type, extracted_from
               FROM citation_edges
               WHERE cited_doc_id=? AND cited_source=?
               ORDER BY confidence
               LIMIT ?""",
            (document_id, source, limit),
        ).fetchall()

        citing_docs: list[dict[str, Any]] = []
        for row in rows:
            target = c.db.execute(
                "SELECT title FROM documents_v2 WHERE document_id=? AND source=?",
                (row["citing_doc_id"], row["citing_source"]),
            ).fetchone()
            citing_docs.append({
                "document_id": row["citing_doc_id"],
                "source": row["citing_source"],
                "title": target["title"] if target else None,
                "confidence": row["confidence"],
                "match_type": row["match_type"],
                "extracted_from": row["extracted_from"],
            })

        return {
            "ok": True,
            "document": {
                "document_id": document_id,
                "source": source,
                "title": dict(doc_row)["title"],
            },
            "citing_documents": citing_docs,
            "total": len(citing_docs),
            "warnings": warnings,
            "recommended_next_steps": recommended,
        }
    except Exception as exc:
        return build_error("GRAPH_QUERY_FAILED", f"Sorgu başarısız: {exc}")
    finally:
        if own_cache:
            c.close()


def find_cited_documents(
    document_id: str,
    source: str,
    cache: Cache | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Find documents that the given document cites.

    Args:
        document_id: The citing document ID.
        source: The citing document source.
        cache: Optional Cache instance.
        limit: Maximum results.

    Returns:
        Dict with ok, document, cited_documents list, warnings,
        recommended_next_steps. ``warnings``/``recommended_next_steps`` are
        only populated when the citation graph has never been built
        (citation_edges table is empty overall) — a document that simply has
        no cited documents in an already-built graph gets an empty
        warnings list.
    """
    c = cache or Cache()
    own_cache = cache is None

    try:
        _ensure_edge_table(c)

        # Verify document exists
        doc_row = c.db.execute(
            "SELECT document_id, source, title FROM documents_v2 WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()
        if not doc_row:
            return build_error("DOC_NOT_FOUND", f"Belge bulunamadı: {source}:{document_id}")

        _, warnings, recommended = _graph_build_state(c)

        rows = c.db.execute(
            """SELECT cited_doc_id, cited_source, confidence, match_type, extracted_from
               FROM citation_edges
               WHERE citing_doc_id=? AND citing_source=?
               ORDER BY confidence
               LIMIT ?""",
            (document_id, source, limit),
        ).fetchall()

        cited_docs: list[dict[str, Any]] = []
        for row in rows:
            target = c.db.execute(
                "SELECT title FROM documents_v2 WHERE document_id=? AND source=?",
                (row["cited_doc_id"], row["cited_source"]),
            ).fetchone()
            cited_docs.append({
                "document_id": row["cited_doc_id"],
                "source": row["cited_source"],
                "title": target["title"] if target else None,
                "confidence": row["confidence"],
                "match_type": row["match_type"],
                "extracted_from": row["extracted_from"],
            })

        return {
            "ok": True,
            "document": {
                "document_id": document_id,
                "source": source,
                "title": dict(doc_row)["title"],
            },
            "cited_documents": cited_docs,
            "total": len(cited_docs),
            "warnings": warnings,
            "recommended_next_steps": recommended,
        }
    except Exception as exc:
        return build_error("GRAPH_QUERY_FAILED", f"Sorgu başarısız: {exc}")
    finally:
        if own_cache:
            c.close()


def get_citation_graph_stats(cache: Cache | None = None) -> dict[str, Any]:
    """Get statistics about the citation graph.

    Args:
        cache: Optional Cache instance.

    Returns:
        Dict with ok, total_edges, total_docs_with_citations,
        most_cited_docs, avg_citations_per_doc, confidence_distribution,
        total_cached_documents, documents_in_graph, graph_coverage_ratio,
        last_built_at, warnings, recommended_next_steps. When
        citation_edges is empty overall, ``warnings`` explains the graph was
        never built (rather than "no citations exist") and
        ``recommended_next_steps`` names build_citation_graph().
    """
    c = cache or Cache()
    own_cache = cache is None

    try:
        _ensure_edge_table(c)

        total_edges, warnings, recommended = _graph_build_state(c)

        # Docs that appear as citing
        citing_docs = c.db.execute(
            "SELECT COUNT(DISTINCT citing_doc_id || ':' || citing_source) FROM citation_edges"
        ).fetchone()[0]

        # Docs that appear as cited
        cited_docs = c.db.execute(
            "SELECT COUNT(DISTINCT cited_doc_id || ':' || cited_source) FROM citation_edges"
        ).fetchone()[0]

        total_docs_with_citations = citing_docs + cited_docs

        # Most cited documents
        most_cited_rows = c.db.execute(
            """SELECT cited_doc_id, cited_source, COUNT(*) as citation_count
               FROM citation_edges
               GROUP BY cited_doc_id, cited_source
               ORDER BY citation_count DESC
               LIMIT 10"""
        ).fetchall()

        most_cited_docs: list[dict[str, Any]] = []
        for row in most_cited_rows:
            doc = c.db.execute(
                "SELECT title FROM documents_v2 WHERE document_id=? AND source=?",
                (row["cited_doc_id"], row["cited_source"]),
            ).fetchone()
            most_cited_docs.append({
                "document_id": row["cited_doc_id"],
                "source": row["cited_source"],
                "title": doc["title"] if doc else None,
                "citation_count": row["citation_count"],
            })

        # Average citations per doc
        avg_citations = 0.0
        if citing_docs > 0:
            avg_citations = round(total_edges / citing_docs, 2)

        # Confidence distribution
        conf_rows = c.db.execute(
            """SELECT confidence, COUNT(*) as cnt
               FROM citation_edges
               GROUP BY confidence"""
        ).fetchall()
        conf_dist = {row["confidence"]: row["cnt"] for row in conf_rows}

        # Coverage: distinct documents that appear anywhere in the graph vs.
        # total cached corpus size. Both queries are cheap aggregates (single
        # COUNT(*) each, no per-row Python processing / no join) — mirrors
        # how get_index_status() reports TF-IDF vector coverage.
        total_cached_documents = c.db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
        documents_in_graph = c.db.execute(
            """SELECT COUNT(*) FROM (
                   SELECT citing_doc_id AS document_id, citing_source AS source FROM citation_edges
                   UNION
                   SELECT cited_doc_id, cited_source FROM citation_edges
               )"""
        ).fetchone()[0]
        graph_coverage_ratio = (
            round(documents_in_graph / total_cached_documents, 4) if total_cached_documents > 0 else 0.0
        )

        # Last build time, if ever run — build_citation_graph() logs to the
        # history table on every successful run, so this is a single indexed
        # row lookup (no scan of citation_edges or documents_v2).
        last_built_at = _last_graph_build(c)

        return {
            "ok": True,
            "total_edges": total_edges,
            "total_docs_with_citations": total_docs_with_citations,
            "citing_docs_count": citing_docs,
            "cited_docs_count": cited_docs,
            "most_cited_docs": most_cited_docs,
            "avg_citations_per_doc": avg_citations,
            "confidence_distribution": conf_dist,
            "total_cached_documents": total_cached_documents,
            "documents_in_graph": documents_in_graph,
            "graph_coverage_ratio": graph_coverage_ratio,
            "last_built_at": last_built_at,
            "warnings": warnings,
            "recommended_next_steps": recommended,
        }
    except Exception as exc:
        return build_error("GRAPH_STATS_FAILED", f"İstatistik alınamadı: {exc}")
    finally:
        if own_cache:
            c.close()


# ---------------------------------------------------------------------------
# Export (M-39)
# ---------------------------------------------------------------------------

def export_graph(
    format: str = "json",
    cache: Cache | None = None,
    document_id: str | None = None,
    source: str | None = None,
    max_depth: int = 2,
) -> dict[str, Any]:
    """Export citation graph in various formats.

    Args:
        format: 'json' (node-link), 'dot' (Graphviz), 'mermaid'.
        cache: Optional Cache instance.
        document_id: Optional — if provided, export sub-graph centered on this doc.
        source: Optional source filter for sub-graph.
        max_depth: For sub-graph, how many hops.

    Returns:
        Dict with ok, format, export_text, node_count, edge_count, warnings,
        recommended_next_steps. ``warnings``/``recommended_next_steps`` are
        only populated when the citation graph has never been built
        (citation_edges table is empty overall) — a sub-graph centered on a
        document that simply has no citations gets an empty warnings list.
    """
    c = cache or Cache()
    own_cache = cache is None

    try:
        _ensure_edge_table(c)

        _, warnings, recommended = _graph_build_state(c)

        # Collect nodes and edges
        node_ids: set[tuple[str, str]] = set()
        edges: list[dict[str, Any]] = []

        if document_id:
            # Sub-graph: BFS from document_id up to max_depth
            visited: set[tuple[str, str]] = set()
            frontier: list[tuple[str, str, int]] = []

            start_source = source or ""
            frontier.append((document_id, start_source, 0))
            while frontier:
                doc_id, doc_src, depth = frontier.pop(0)
                key = (doc_id, doc_src)
                if key in visited or depth > max_depth:
                    continue
                visited.add(key)
                node_ids.add(key)

                # Outgoing edges (this doc cites others)
                rows = c.db.execute(
                    """SELECT cited_doc_id, cited_source, confidence, match_type
                       FROM citation_edges
                       WHERE citing_doc_id=? AND citing_source=?""",
                    (doc_id, doc_src),
                ).fetchall()
                for row in rows:
                    target = (row["cited_doc_id"], row["cited_source"])
                    node_ids.add(target)
                    edges.append({
                        "source": f"{doc_src}:{doc_id}",
                        "target": f"{row['cited_source']}:{row['cited_doc_id']}",
                        "confidence": row["confidence"],
                        "match_type": row["match_type"],
                    })
                    if target not in visited:
                        frontier.append((target[0], target[1], depth + 1))

                # Incoming edges (others cite this doc)
                rows = c.db.execute(
                    """SELECT citing_doc_id, citing_source, confidence, match_type
                       FROM citation_edges
                       WHERE cited_doc_id=? AND cited_source=?""",
                    (doc_id, doc_src),
                ).fetchall()
                for row in rows:
                    source_key = (row["citing_doc_id"], row["citing_source"])
                    node_ids.add(source_key)
                    edges.append({
                        "source": f"{row['citing_source']}:{row['citing_doc_id']}",
                        "target": f"{doc_src}:{doc_id}",
                        "confidence": row["confidence"],
                        "match_type": row["match_type"],
                    })
                    if source_key not in visited:
                        frontier.append((source_key[0], source_key[1], depth + 1))
        else:
            # Full graph export
            rows = c.db.execute("SELECT * FROM citation_edges").fetchall()
            for row in rows:
                src = (row["citing_doc_id"], row["citing_source"])
                tgt = (row["cited_doc_id"], row["cited_source"])
                node_ids.add(src)
                node_ids.add(tgt)
                edges.append({
                    "source": f"{row['citing_source']}:{row['citing_doc_id']}",
                    "target": f"{row['cited_source']}:{row['cited_doc_id']}",
                    "confidence": row["confidence"],
                    "match_type": row["match_type"],
                })

        # Enrich node labels from documents_v2
        nodes: list[dict[str, Any]] = []
        for nid, nsrc in node_ids:
            label_row = c.db.execute(
                "SELECT title, court, chamber FROM documents_v2 WHERE document_id=? AND source=?",
                (nid, nsrc),
            ).fetchone()
            label = nid
            if label_row:
                title = label_row["title"] or ""
                court = label_row["court"] or ""
                label = f"{court} — {title}" if court else (title or nid)
            nodes.append({
                "id": f"{nsrc}:{nid}",
                "label": label,
                "document_id": nid,
                "source": nsrc,
            })

        # Format export
        if format == "json":
            export_text = json.dumps(
                {"nodes": nodes, "edges": edges},
                ensure_ascii=False,
                indent=2,
            )
        elif format == "dot":
            lines = ["digraph citations {"]
            lines.append("  rankdir=LR;")
            lines.append("  node [shape=box, fontsize=10];")
            for node in nodes:
                escaped_label = node["label"].replace('"', '\\"')
                lines.append(f'  "{node["id"]}" [label="{escaped_label}"];')
            for edge in edges:
                style = "solid" if edge["confidence"] == "high" else "dashed"
                lines.append(
                    f'  "{edge["source"]}" -> "{edge["target"]}" '
                    f'[style={style}, label="{edge["match_type"]}"];'
                )
            lines.append("}")
            export_text = "\n".join(lines)
        elif format == "mermaid":
            lines = ["graph LR"]
            id_map: dict[str, str] = {}
            for i, node in enumerate(nodes):
                short_id = f"N{i}"
                id_map[node["id"]] = short_id
                escaped_label = node["label"].replace('"', "'")
                lines.append(f'    {short_id}["{escaped_label}"]')
            for edge in edges:
                src_id = id_map.get(edge["source"], edge["source"])
                tgt_id = id_map.get(edge["target"], edge["target"])
                lines.append(f"    {src_id} -->|{edge['match_type']}| {tgt_id}")
            export_text = "\n".join(lines)
        else:
            return build_error("INVALID_FORMAT", f"Unknown format: {format}. Supported: json, dot, mermaid")

        return {
            "ok": True,
            "format": format,
            "export_text": export_text,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "sub_graph": document_id is not None,
            "warnings": warnings,
            "recommended_next_steps": recommended,
        }
    except Exception as exc:
        return build_error("GRAPH_EXPORT_FAILED", f"Graf dışa aktarılamadı: {exc}")
    finally:
        if own_cache:
            c.close()
