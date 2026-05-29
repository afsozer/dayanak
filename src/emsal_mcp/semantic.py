"""Emsal-mcp Semantic/Hybrid Search – v0.11

Hybrid search combining SQLite FTS5 BM25 ranking with TF-IDF cosine similarity.
No external ML dependencies — pure Python + SQLite FTS5.

This module adds semantic search on top of the existing Cache v2 SQLite database.
It accesses the SAME database file that Cache uses, creating FTS5 virtual tables
and TF-IDF vector storage for enhanced search capabilities.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from typing import Any

from .cache import Cache

SEMANTIC_VERSION = "0.11.0"

# ---------------------------------------------------------------------------
# Tokenizer & Vector Math
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'\b\w+\b', re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase word tokens."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors (dicts)."""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in set(vec_a) | set(vec_b))
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    denom = norm_a * norm_b
    return dot / denom if denom > 0 else 0.0


# ---------------------------------------------------------------------------
# DB Connection Helper
# ---------------------------------------------------------------------------

def _get_db(cache: Cache | None = None) -> tuple[sqlite3.Connection, bool]:
    """Get DB connection. Returns (db, own_cache).

    If a Cache instance with an active connection is provided, returns that
    connection and ``own_cache=False`` (caller must NOT close the cache).
    Otherwise creates a fresh Cache and returns ``own_cache=True``.
    """
    if cache is not None and cache.db is not None:
        return cache.db, False
    c = Cache()
    return c.db, True  # caller must close c if own_cache


# ---------------------------------------------------------------------------
# FTS5 Index Setup
# ---------------------------------------------------------------------------

_FTS5_CREATE = """\
CREATE VIRTUAL TABLE IF NOT EXISTS documents_v2_fts USING fts5(
    document_id, source, title, full_text, markdown,
    content='documents_v2',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);"""

_TRIGGER_AI = """\
CREATE TRIGGER IF NOT EXISTS documents_v2_ai AFTER INSERT ON documents_v2 BEGIN
    INSERT INTO documents_v2_fts(rowid, document_id, source, title, full_text, markdown)
    VALUES (new.rowid, new.document_id, new.source, new.title, new.full_text, new.markdown);
END;"""

_TRIGGER_AD = """\
CREATE TRIGGER IF NOT EXISTS documents_v2_ad AFTER DELETE ON documents_v2 BEGIN
    INSERT INTO documents_v2_fts(documents_v2_fts, rowid, document_id, source, title, full_text, markdown)
    VALUES ('delete', old.rowid, old.document_id, old.source, old.title, old.full_text, old.markdown);
END;"""

_TRIGGER_AU = """\
CREATE TRIGGER IF NOT EXISTS documents_v2_au AFTER UPDATE ON documents_v2 BEGIN
    INSERT INTO documents_v2_fts(documents_v2_fts, rowid, document_id, source, title, full_text, markdown)
    VALUES ('delete', old.rowid, old.document_id, old.source, old.title, old.full_text, old.markdown);
    INSERT INTO documents_v2_fts(rowid, document_id, source, title, full_text, markdown)
    VALUES (new.rowid, new.document_id, new.source, new.title, new.full_text, new.markdown);
END;"""


def _ensure_fts5(db: sqlite3.Connection) -> bool:
    """Create FTS5 virtual table and content-sync triggers if missing.

    Returns True if the FTS5 table already existed (or was just created).
    """
    existing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_v2_fts'"
    ).fetchone()
    already_existed = existing is not None

    db.execute(_FTS5_CREATE)
    db.execute(_TRIGGER_AI)
    db.execute(_TRIGGER_AD)
    db.execute(_TRIGGER_AU)
    db.commit()

    # If table was just created, populate from existing data
    if not already_existed:
        row_count = db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
        if row_count > 0:
            db.execute("""\
                INSERT INTO documents_v2_fts(rowid, document_id, source, title, full_text, markdown)
                SELECT rowid, document_id, source, title, full_text, markdown FROM documents_v2
            """)
            db.commit()

    return already_existed


# ---------------------------------------------------------------------------
# TF-IDF Vector Storage
# ---------------------------------------------------------------------------

_VECTORS_TABLE = """\
CREATE TABLE IF NOT EXISTS search_vectors (
    document_id TEXT NOT NULL,
    source TEXT NOT NULL,
    vector_json TEXT NOT NULL,  -- {"word": tfidf_score, ...}
    norm REAL DEFAULT 0.0,     -- precomputed L2 norm for fast cosine
    indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_id, source)
);"""


def _ensure_search_vectors(db: sqlite3.Connection) -> bool:
    """Create the search_vectors table if it does not exist.

    Returns True if the table already existed.
    """
    existing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='search_vectors'"
    ).fetchone()
    already_existed = existing is not None
    db.execute(_VECTORS_TABLE)
    db.commit()
    return already_existed


def _compute_tfidf_vectors(db: sqlite3.Connection, limit: int = 1000) -> int:
    """Compute TF-IDF vectors for all documents with text content.

    Reads documents from documents_v2, tokenizes their text, computes IDF
    across the corpus, builds per-document TF-IDF vectors, and stores them
    in the search_vectors table.

    Returns the number of documents indexed.
    """
    rows = db.execute(
        "SELECT document_id, source, full_text, markdown FROM documents_v2 LIMIT ?",
        (limit,),
    ).fetchall()

    if not rows:
        return 0

    # Step 1: tokenize all documents and compute document frequency
    doc_tokens: list[tuple[str, str, Counter]] = []  # (doc_id, source, token_counter)
    df: Counter = Counter()  # document frequency per term
    n_docs = 0

    for row in rows:
        doc_id, source, full_text, markdown = row
        text = full_text or markdown or ""
        if not text.strip():
            continue
        tokens = _tokenize(text)
        if not tokens:
            continue
        token_counts = Counter(tokens)
        doc_tokens.append((doc_id, source, token_counts))
        for term in set(tokens):
            df[term] += 1
        n_docs += 1

    if n_docs == 0:
        return 0

    # Step 2: compute IDF: idf(term) = log(N / df[term])
    idf: dict[str, float] = {}
    for term, freq in df.items():
        idf[term] = math.log(n_docs / freq)

    # Step 3: compute TF-IDF for each document and store
    db.execute("DELETE FROM search_vectors")
    indexed = 0
    for doc_id, source, token_counts in doc_tokens:
        total_tokens = sum(token_counts.values())
        vector: dict[str, float] = {}
        for term, count in token_counts.items():
            tf = count / total_tokens
            vector[term] = tf * idf.get(term, 0.0)

        # Precompute L2 norm
        norm = math.sqrt(sum(v * v for v in vector.values())) if vector else 0.0
        vector_json = json.dumps(vector, ensure_ascii=False)

        db.execute(
            "INSERT OR REPLACE INTO search_vectors(document_id, source, vector_json, norm) VALUES(?, ?, ?, ?)",
            (doc_id, source, vector_json, norm),
        )
        indexed += 1

    db.commit()
    return indexed


# ---------------------------------------------------------------------------
# Snippet Generation
# ---------------------------------------------------------------------------

def _generate_snippet(text: str, query: str, max_length: int = 200) -> str:
    """Generate a snippet from document text around the query match."""
    if not text:
        return ""
    if not query:
        return text[:max_length]
    lower_text = text.lower()
    lower_query = query.lower()
    idx = lower_text.find(lower_query)
    if idx == -1:
        # Try matching individual query tokens
        tokens = _tokenize(query)
        for t in tokens:
            idx = lower_text.find(t)
            if idx != -1:
                break
        if idx == -1:
            return text[:max_length]
    start = max(0, idx - max_length // 3)
    end = min(len(text), idx + len(query) + 2 * max_length // 3)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


# ---------------------------------------------------------------------------
# Filter Helpers
# ---------------------------------------------------------------------------

def _apply_filters(
    results: list[dict[str, Any]],
    filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Apply metadata filters to a scored result list. Filters applied AFTER scoring."""
    if not filters:
        return results
    filtered = []
    for r in results:
        ok = True
        if "source" in filters and filters["source"]:
            if r.get("source") != filters["source"]:
                ok = False
        if "court" in filters and filters["court"]:
            if filters["court"].lower() not in (r.get("court") or "").lower():
                ok = False
        if "chamber" in filters and filters["chamber"]:
            if filters["chamber"].lower() not in (r.get("chamber") or "").lower():
                ok = False
        if "content_status" in filters and filters["content_status"]:
            if r.get("content_status") != filters["content_status"]:
                ok = False
        if "quote_usable" in filters and filters["quote_usable"] is not None:
            if bool(r.get("quote_usable")) != bool(filters["quote_usable"]):
                ok = False
        if "draft_usable" in filters and filters["draft_usable"] is not None:
            if bool(r.get("draft_usable")) != bool(filters["draft_usable"]):
                ok = False
        if ok:
            filtered.append(r)
    return filtered


def _fetch_doc_row(db: sqlite3.Connection, document_id: str, source: str) -> dict[str, Any] | None:
    """Fetch a single document row as a dict."""
    row = db.execute(
        "SELECT document_id, source, title, content_status, quote_usable, draft_usable, "
        "court, chamber, decision_date, full_text, markdown "
        "FROM documents_v2 WHERE document_id=? AND source=?",
        (document_id, source),
    ).fetchone()
    if not row:
        return None
    return {
        "document_id": row["document_id"],
        "source": row["source"],
        "title": row["title"],
        "court": row["court"],
        "chamber": row["chamber"],
        "decision_date": row["decision_date"],
        "content_status": row["content_status"],
        "quote_usable": bool(row["quote_usable"]),
        "draft_usable": bool(row["draft_usable"]),
        "full_text": row["full_text"] or "",
        "markdown": row["markdown"] or "",
    }


def _build_query_vector(query: str, idf: dict[str, float] | None = None) -> dict[str, float]:
    """Build a TF-IDF vector for the query string.

    If idf is provided, uses corpus IDF values; otherwise uses a flat weighting
    (all terms weight 1.0) which is a reasonable approximation for single queries.
    """
    tokens = _tokenize(query)
    if not tokens:
        return {}
    token_counts = Counter(tokens)
    total = sum(token_counts.values())
    vec: dict[str, float] = {}
    for term, count in token_counts.items():
        tf = count / total
        idf_val = idf.get(term, 1.0) if idf else 1.0
        vec[term] = tf * idf_val
    return vec


def _load_idf_from_vectors(db: sqlite3.Connection) -> dict[str, float]:
    """Approximate IDF from stored vectors.

    Uses the stored vector norms and term frequencies to derive an approximate
    IDF.  For a small corpus this is good enough; for larger ones the exact IDF
    from _compute_tfidf_vectors is preferred (and already stored in vectors).
    """
    rows = db.execute("SELECT vector_json FROM search_vectors").fetchall()
    if not rows:
        return {}
    n_docs = len(rows)
    df: Counter = Counter()
    for (vjson,) in rows:
        vec = json.loads(vjson)
        for term in vec:
            df[term] += 1
    idf: dict[str, float] = {}
    for term, freq in df.items():
        idf[term] = math.log(n_docs / freq) if freq > 0 else 0.0
    return idf


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_semantic_index(cache: Cache | None = None, force_rebuild: bool = False) -> dict[str, Any]:
    """Build FTS5 and TF-IDF indices.

    Args:
        cache: Optional Cache instance for DB injection.  If None a fresh Cache
               is created.
        force_rebuild: If True, drop and recreate all index tables first.

    Returns:
        Status dict with ok, fts5_exists, fts5_row_count, vectors_count, etc.
    """
    db, own_cache = _get_db(cache)
    warnings: list[str] = []
    try:
        if force_rebuild:
            # Drop existing FTS5 table and triggers
            db.execute("DROP TRIGGER IF EXISTS documents_v2_ai")
            db.execute("DROP TRIGGER IF EXISTS documents_v2_ad")
            db.execute("DROP TRIGGER IF EXISTS documents_v2_au")
            db.execute("DROP TABLE IF EXISTS documents_v2_fts")
            db.execute("DROP TABLE IF EXISTS search_vectors")
            db.commit()
            warnings.append("Existing FTS5 and vector indices were dropped for rebuild.")

        fts5_existed = _ensure_fts5(db)
        _ensure_search_vectors(db)
        vectors_count = _compute_tfidf_vectors(db)

        fts5_row_count = db.execute("SELECT COUNT(*) FROM documents_v2_fts").fetchone()[0]
        docs_total = db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]

        if vectors_count == 0 and docs_total > 0:
            warnings.append("No documents with text content found; vectors table is empty.")

        return {
            "ok": True,
            "fts5_exists": fts5_existed or not force_rebuild,
            "fts5_row_count": fts5_row_count,
            "vectors_count": vectors_count,
            "documents_total": docs_total,
            "warnings": warnings,
            "recommended_next_steps": [
                "Use hybrid_search() to query the index.",
                "Call get_index_status() to verify index health.",
            ],
            "version": SEMANTIC_VERSION,
        }
    except Exception as exc:
        return {
            "ok": False,
            "fts5_exists": False,
            "fts5_row_count": 0,
            "vectors_count": 0,
            "documents_total": 0,
            "warnings": [str(exc)],
            "recommended_next_steps": ["Check database permissions and schema."],
            "version": SEMANTIC_VERSION,
        }
    finally:
        if own_cache:
            try:
                db.close()
            except Exception:
                pass


def semantic_search(
    query: str,
    limit: int = 10,
    cache: Cache | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search using TF-IDF cosine similarity only.

    Args:
        query: Free-text search query.
        limit: Maximum results to return.
        cache: Optional Cache instance for DB injection.
        filters: Optional metadata filters applied after scoring.

    Returns:
        Dict with ok, results, total_matches, method, warnings, version.
    """
    db, own_cache = _get_db(cache)
    warnings: list[str] = []
    try:
        # Ensure indices exist
        _ensure_fts5(db)
        _ensure_search_vectors(db)

        # Check if vectors exist
        vec_count = db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]
        if vec_count == 0:
            # Try computing vectors on-the-fly
            computed = _compute_tfidf_vectors(db)
            if computed == 0:
                return {
                    "ok": True,
                    "query": query,
                    "results": [],
                    "total_matches": 0,
                    "method": "tfidf_cosine",
                    "warnings": ["No indexed documents found. Call build_semantic_index() first."],
                    "version": SEMANTIC_VERSION,
                }

        # Load IDF from stored vectors
        idf = _load_idf_from_vectors(db)
        query_vec = _build_query_vector(query, idf)

        if not query_vec:
            return {
                "ok": True,
                "query": query,
                "results": [],
                "total_matches": 0,
                "method": "tfidf_cosine",
                "warnings": ["Query produced no meaningful tokens."],
                "version": SEMANTIC_VERSION,
            }

        # Load all vectors
        rows = db.execute("SELECT document_id, source, vector_json FROM search_vectors").fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            doc_id, source, vjson = row
            doc_vec = json.loads(vjson)
            cosine_score = _cosine_similarity(query_vec, doc_vec)

            if cosine_score <= 0:
                continue

            doc_info = _fetch_doc_row(db, doc_id, source)
            if doc_info is None:
                continue

            snippet = _generate_snippet(
                doc_info["full_text"] or doc_info["markdown"],
                query,
            )

            scored.append({
                "document_id": doc_id,
                "source": source,
                "title": doc_info["title"],
                "court": doc_info.get("court"),
                "chamber": doc_info.get("chamber"),
                "decision_date": doc_info.get("decision_date"),
                "score": round(cosine_score, 6),
                "snippet": snippet,
                "content_status": doc_info["content_status"],
                "quote_usable": doc_info["quote_usable"],
                "draft_usable": doc_info["draft_usable"],
            })

        # Apply filters
        scored = _apply_filters(scored, filters)

        # Sort by score descending
        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:limit]

        return {
            "ok": True,
            "query": query,
            "results": top,
            "total_matches": len(scored),
            "method": "tfidf_cosine",
            "warnings": warnings,
            "version": SEMANTIC_VERSION,
        }
    except Exception as exc:
        return {
            "ok": False,
            "query": query,
            "results": [],
            "total_matches": 0,
            "method": "tfidf_cosine",
            "warnings": [str(exc)],
            "version": SEMANTIC_VERSION,
        }
    finally:
        if own_cache:
            try:
                db.close()
            except Exception:
                pass


def hybrid_search(
    query: str,
    limit: int = 10,
    cache: Cache | None = None,
    filters: dict[str, Any] | None = None,
    hybrid_weight: float = 0.6,
) -> dict[str, Any]:
    """Combined FTS5 BM25 + TF-IDF cosine hybrid search.

    Args:
        query: Free-text search query.
        limit: Maximum results to return.
        cache: Optional Cache instance for DB injection.
        filters: Optional metadata filters applied after scoring.
        hybrid_weight: Weight for BM25 component (1-hybrid_weight for cosine).
            Default 0.6 means 60% BM25, 40% cosine.

    Returns:
        Dict with ok, results, total_matches, method, hybrid_weight, warnings, version.
    """
    db, own_cache = _get_db(cache)
    warnings: list[str] = []
    recommended: list[str] = []
    try:
        # Ensure indices exist
        _ensure_fts5(db)
        _ensure_search_vectors(db)

        # Check for data
        docs_total = db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
        if docs_total == 0:
            return {
                "ok": True,
                "query": query,
                "results": [],
                "total_matches": 0,
                "method": "hybrid",
                "hybrid_weight": hybrid_weight,
                "warnings": ["No documents in cache. Store documents first."],
                "recommended_next_steps": ["Use store_document() to add documents."],
                "version": SEMANTIC_VERSION,
            }

        # ---- FTS5 BM25 Search ----
        bm25_results: dict[tuple[str, str], float] = {}
        try:
            # Escape special FTS5 characters in query for MATCH
            safe_query = re.sub(r'[^\w\s]', ' ', query).strip()
            if safe_query:
                fts_rows = db.execute(
                    """\
                    SELECT d.document_id, d.source, bm25(documents_v2_fts) as bm25_score
                    FROM documents_v2_fts f
                    JOIN documents_v2 d ON d.rowid = f.rowid
                    WHERE documents_v2_fts MATCH ?
                    ORDER BY bm25_score
                    LIMIT ?
                    """,
                    (safe_query, limit * 3),  # fetch extra for merge
                ).fetchall()
                for row in fts_rows:
                    bm25_results[(row["document_id"], row["source"])] = row["bm25_score"]
        except Exception:
            warnings.append("FTS5 query failed; falling back to cosine-only scoring.")

        # ---- TF-IDF Cosine Search ----
        cosine_results: dict[tuple[str, str], float] = {}
        vec_count = db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]
        if vec_count == 0:
            computed = _compute_tfidf_vectors(db)
            if computed == 0:
                warnings.append("No text content available for TF-IDF indexing.")
            vec_count = computed

        if vec_count > 0:
            idf = _load_idf_from_vectors(db)
            query_vec = _build_query_vector(query, idf)
            if query_vec:
                rows = db.execute("SELECT document_id, source, vector_json FROM search_vectors").fetchall()
                for row in rows:
                    doc_id, source, vjson = row
                    doc_vec = json.loads(vjson)
                    cs = _cosine_similarity(query_vec, doc_vec)
                    if cs > 0:
                        cosine_results[(doc_id, source)] = cs

        # ---- Merge Scores ----
        all_keys = set(bm25_results.keys()) | set(cosine_results.keys())
        if not all_keys:
            return {
                "ok": True,
                "query": query,
                "results": [],
                "total_matches": 0,
                "method": "hybrid",
                "hybrid_weight": hybrid_weight,
                "warnings": warnings,
                "recommended_next_steps": ["Try a broader query or check index status."],
                "version": SEMANTIC_VERSION,
            }

        # Normalize BM25 to [0, 1] range
        # BM25 scores are negative (lower = better match), so invert
        merged: list[dict[str, Any]] = []
        for key in all_keys:
            doc_id, source = key
            bm25_raw = bm25_results.get(key, 0.0)
            cosine_raw = cosine_results.get(key, 0.0)

            # Normalize BM25: lower (more negative) = better match
            # Map to [0, 1]: bm25_norm = 1.0 / (1.0 + abs(bm25_score))
            bm25_norm = 1.0 / (1.0 + abs(bm25_raw)) if bm25_raw != 0 else 0.0
            # Cosine is already in [0, 1] by definition

            final_score = hybrid_weight * bm25_norm + (1.0 - hybrid_weight) * cosine_raw

            doc_info = _fetch_doc_row(db, doc_id, source)
            if doc_info is None:
                continue

            snippet = _generate_snippet(
                doc_info["full_text"] or doc_info["markdown"],
                query,
            )

            merged.append({
                "document_id": doc_id,
                "source": source,
                "title": doc_info["title"],
                "court": doc_info.get("court"),
                "chamber": doc_info.get("chamber"),
                "decision_date": doc_info.get("decision_date"),
                "bm25_score": round(bm25_raw, 6),
                "cosine_score": round(cosine_raw, 6),
                "hybrid_score": round(final_score, 6),
                "snippet": snippet,
                "content_status": doc_info["content_status"],
                "quote_usable": doc_info["quote_usable"],
                "draft_usable": doc_info["draft_usable"],
            })

        # Apply filters
        merged = _apply_filters(merged, filters)

        # Sort by hybrid_score descending
        merged.sort(key=lambda x: x["hybrid_score"], reverse=True)
        top = merged[:limit]

        if not bm25_results:
            recommended.append("FTS5 index may be empty. Run build_semantic_index() to rebuild.")
        if not cosine_results:
            recommended.append("TF-IDF vectors may be empty. Run build_semantic_index() to rebuild.")

        return {
            "ok": True,
            "query": query,
            "results": top,
            "total_matches": len(merged),
            "method": "hybrid",
            "hybrid_weight": hybrid_weight,
            "warnings": warnings,
            "recommended_next_steps": recommended,
            "version": SEMANTIC_VERSION,
        }
    except Exception as exc:
        return {
            "ok": False,
            "query": query,
            "results": [],
            "total_matches": 0,
            "method": "hybrid",
            "hybrid_weight": hybrid_weight,
            "warnings": [str(exc)],
            "recommended_next_steps": [],
            "version": SEMANTIC_VERSION,
        }
    finally:
        if own_cache:
            try:
                db.close()
            except Exception:
                pass


def get_index_status(cache: Cache | None = None) -> dict[str, Any]:
    """Check index health and statistics.

    Returns:
        Dict with fts5_exists, fts5_document_count, vectors_table_exists,
        vectors_count, total_cached_documents, unindexed_documents, warnings,
        recommended_next_steps, version.
    """
    db, own_cache = _get_db(cache)
    try:
        # Check FTS5 table
        fts5_exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_v2_fts'"
        ).fetchone() is not None

        fts5_document_count = 0
        if fts5_exists:
            fts5_document_count = db.execute("SELECT COUNT(*) FROM documents_v2_fts").fetchone()[0]

        # Check vectors table
        vectors_table_exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_vectors'"
        ).fetchone() is not None

        vectors_count = 0
        if vectors_table_exists:
            vectors_count = db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]

        # Total cached documents
        total_cached = db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]

        unindexed = max(0, total_cached - vectors_count)

        warnings: list[str] = []
        recommended: list[str] = []

        if not fts5_exists:
            warnings.append("FTS5 virtual table does not exist.")
            recommended.append("Call build_semantic_index() to create the FTS5 index.")
        elif fts5_document_count < total_cached:
            warnings.append(
                f"FTS5 index has {fts5_document_count} entries but cache has {total_cached} documents."
            )
            recommended.append("Call build_semantic_index(force_rebuild=True) to resync.")

        if not vectors_table_exists:
            warnings.append("search_vectors table does not exist.")
            recommended.append("Call build_semantic_index() to create TF-IDF vectors.")
        elif vectors_count < total_cached:
            warnings.append(
                f"TF-IDF vectors cover {vectors_count} of {total_cached} documents."
            )
            recommended.append("Call build_semantic_index() to index remaining documents.")

        if unindexed > 0:
            recommended.append(f"{unindexed} documents are not yet TF-IDF indexed.")

        return {
            "ok": True,
            "fts5_exists": fts5_exists,
            "fts5_document_count": fts5_document_count,
            "vectors_table_exists": vectors_table_exists,
            "vectors_count": vectors_count,
            "total_cached_documents": total_cached,
            "unindexed_documents": unindexed,
            "warnings": warnings,
            "recommended_next_steps": recommended,
            "version": SEMANTIC_VERSION,
        }
    except Exception as exc:
        return {
            "ok": False,
            "fts5_exists": False,
            "fts5_document_count": 0,
            "vectors_table_exists": False,
            "vectors_count": 0,
            "total_cached_documents": 0,
            "unindexed_documents": 0,
            "warnings": [str(exc)],
            "recommended_next_steps": ["Check database accessibility."],
            "version": SEMANTIC_VERSION,
        }
    finally:
        if own_cache:
            try:
                db.close()
            except Exception:
                pass


def rebuild_index(cache: Cache | None = None) -> dict[str, Any]:
    """Force rebuild of both FTS5 and TF-IDF indices.

    Convenience wrapper around build_semantic_index(force_rebuild=True).

    Returns:
        Status dict from build_semantic_index.
    """
    return build_semantic_index(cache=cache, force_rebuild=True)
