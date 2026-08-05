"""Emsal-mcp Semantic/Hybrid Search – v0.14

Hybrid search combining SQLite FTS5 BM25 ranking with TF-IDF cosine similarity
and dense embeddings (LocalHashProvider or optional FastEmbed).
Supports weighted linear fusion and Reciprocal Rank Fusion (RRF).
No external ML dependencies — pure Python + SQLite FTS5.

This module adds semantic search on top of the existing Cache v2 SQLite database.
It accesses the SAME database file that Cache uses, creating FTS5 virtual tables
and TF-IDF vector storage for enhanced search capabilities.
"""
from __future__ import annotations

import gc
import json
import math
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .cache import Cache
from .embeddings import EMBEDDING_VERSION
from .models import build_error  # noqa: F401


SEMANTIC_VERSION = "0.13.0"

# ---------------------------------------------------------------------------
# Tokenizer & Vector Math
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'\b\w+\b', re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase word tokens."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


# ---------------------------------------------------------------------------
# Turkish Query Expansion (Heuristic Suffix Stripping)
# ---------------------------------------------------------------------------

# Turkish suffix stripping rules (heuristic, deterministic).
# Applied longest-match-first to generate stemmed variants for FTS5 OR queries.
_TR_SUFFIX_PATTERNS = [
    (r'(lar|ler)$', ''),           # plural
    (r'(nın|nin|nun|nün)$', ''),  # genitive
    (r'(da|de|ta|te)$', ''),       # locative
    (r'(dan|den|tan|ten)$', ''),   # ablative
    (r'(ın|in|un|ün)$', ''),       # possessive
    (r'(a|e)$', ''),               # dative
    (r'(ı|i|u|ü)$', ''),          # accusative
    (r'(la|le)$', ''),             # instrumental
    (r'(dir|dır|dur|dür|tir|tır|tur|tür)$', ''),  # copula
    (r'(mek|mak)$', ''),           # infinitive
    (r'(me|ma)$', ''),             # negation
]


def _strip_turkish_suffix(word: str) -> list[str]:
    """Strip Turkish suffixes from a single word, returning possible stems.

    Uses a heuristic longest-match approach.  Returns a list of unique
    stemmed variants (may include the original word if no suffix matched).
    This is NOT a full morphological analyzer — it's an approximation
    designed to improve recall for FTS5 queries on Turkish legal text.
    """
    variants: list[str] = []
    lower = word.lower()
    if len(lower) < 3:
        return [lower]  # too short to strip

    # Try each suffix pattern
    for pattern, replacement in _TR_SUFFIX_PATTERNS:
        stemmed = re.sub(pattern, replacement, lower)
        if stemmed != lower and len(stemmed) >= 2:
            variants.append(stemmed)
            # Also try stripping one more suffix from the stemmed result
            for pattern2, replacement2 in _TR_SUFFIX_PATTERNS:
                stemmed2 = re.sub(pattern2, replacement2, stemmed)
                if stemmed2 != stemmed and len(stemmed2) >= 2:
                    variants.append(stemmed2)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def _expand_query(query: str) -> list[str]:
    """Expand a search query with Turkish suffix-stripped variants.

    Tokenizes the query, generates stemmed variants for each token,
    and returns the original tokens plus stemmed variants for use in
    FTS5 OR queries.

    Example: "sözleşmelerin" -> ["sözleşmelerin", "sözleşme", "sözleş"]
    English words will typically produce no additional variants (harmless).

    Returns:
        List of unique terms: original tokens + stemmed variants.
    """
    tokens = _tokenize(query)
    expanded: list[str] = list(tokens)  # start with originals
    for token in tokens:
        stems = _strip_turkish_suffix(token)
        for s in stems:
            if s not in expanded:
                expanded.append(s)
    return expanded


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors (dicts)."""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in set(vec_a) | set(vec_b))
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    denom = norm_a * norm_b
    return dot / denom if denom > 0 else 0.0


def _cosine_similarity_with_norm(
    vec_a: dict[str, float], vec_b: dict[str, float], norm_b: float,
) -> float:
    """Cosine similarity using pre-computed norm for vec_b (optimization).

    Avoids recomputing the L2 norm of vec_b when it's already stored
    (e.g. in the search_vectors table).  norm_a is still computed from
    vec_a (the query vector) since it changes per query.
    """
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in set(vec_a) | set(vec_b))
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
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


# ---------------------------------------------------------------------------
# TF-IDF Corpus Statistics (frozen IDF snapshot — M-108 consistency fix)
# ---------------------------------------------------------------------------
#
# Bug this fixes: the previous implementation computed document-frequency
# (and therefore IDF) from whichever rows a single call happened to touch
# (a `LIMIT`-bounded batch, or the whole table when unlimited), then
# unconditionally deleted the ENTIRE search_vectors table before writing
# that batch. Two consequences: (1) vectors written by different calls were
# scaled by different, batch-local IDF values, so cosine similarity across
# documents from different batches was not meaningful; (2) any call made
# with a bounded `limit` silently destroyed all previously indexed vectors,
# leaving only the last batch. Both were confirmed against the live corpus:
# a single `limit=1000` diagnostic call reduced search_vectors from 112,692
# rows to 1,000.
#
# Fix: IDF is computed exactly once per "epoch" over the WHOLE corpus in a
# dedicated streaming pass (`_compute_corpus_idf`), then persisted to
# `tfidf_corpus_stats`. Every subsequent vector-writing call — regardless of
# batch size, and regardless of how many separate calls it takes to cover
# the corpus — reuses that SAME frozen IDF snapshot. This guarantees any two
# vectors ever written under one snapshot are on an identical basis, and
# batches never delete existing rows (only fill in documents that are still
# missing), making the build resumable and interruption-safe.

_TFIDF_STATS_TABLE = """\
CREATE TABLE IF NOT EXISTS tfidf_corpus_stats (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    n_docs INTEGER NOT NULL,
    idf_json TEXT NOT NULL,
    computed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);"""


def _ensure_tfidf_stats(db: sqlite3.Connection) -> bool:
    """Create the tfidf_corpus_stats table if it does not exist.

    Returns True if the table already existed.
    """
    existing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tfidf_corpus_stats'"
    ).fetchone()
    already_existed = existing is not None
    db.execute(_TFIDF_STATS_TABLE)
    db.commit()
    return already_existed


def _compute_corpus_idf(db: sqlite3.Connection) -> tuple[dict[str, float], int]:
    """Stream the WHOLE corpus once to compute document frequency / IDF.

    Only aggregate counts are kept in memory (a term->df Counter plus a doc
    count) — per-document token lists are discarded immediately after
    updating the counter, so peak memory is O(vocabulary size), not
    O(corpus size). This is the "pass 1" of the two-pass build; its result
    is persisted to tfidf_corpus_stats so later vector-writing calls do not
    need to repeat it.

    Returns (idf_map, n_docs). If no document has usable text, returns
    ({}, 0) and does NOT persist a stats row (so a later call, once real
    text exists, will recompute rather than being stuck with an empty
    snapshot).
    """
    cursor = db.execute("SELECT full_text, markdown FROM documents_v2")
    df: Counter = Counter()
    n_docs = 0
    for full_text, markdown in cursor:
        text = full_text or markdown or ""
        if not text.strip():
            continue
        tokens = _tokenize(text)
        if not tokens:
            continue
        for term in set(tokens):
            df[term] += 1
        n_docs += 1

    if n_docs == 0:
        return {}, 0

    idf: dict[str, float] = {term: math.log(n_docs / freq) for term, freq in df.items()}

    _ensure_tfidf_stats(db)
    db.execute(
        "INSERT OR REPLACE INTO tfidf_corpus_stats(id, n_docs, idf_json, computed_at) "
        "VALUES (1, ?, ?, CURRENT_TIMESTAMP)",
        (n_docs, json.dumps(idf, ensure_ascii=False)),
    )
    db.commit()
    return idf, n_docs


def _load_corpus_idf(db: sqlite3.Connection) -> tuple[dict[str, float], int] | None:
    """Load the persisted IDF snapshot, if one has been computed.

    Returns (idf_map, n_docs) or None if tfidf_corpus_stats has no row yet.
    """
    _ensure_tfidf_stats(db)
    row = db.execute("SELECT n_docs, idf_json FROM tfidf_corpus_stats WHERE id = 1").fetchone()
    if row is None:
        return None
    n_docs, idf_json = row
    try:
        idf = json.loads(idf_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return idf, n_docs


def _get_or_build_corpus_idf(
    db: sqlite3.Connection, idf_refresh: bool = False
) -> tuple[dict[str, float], int]:
    """Return the frozen IDF snapshot, computing it if missing or refresh is requested."""
    if not idf_refresh:
        cached = _load_corpus_idf(db)
        if cached is not None:
            return cached
    return _compute_corpus_idf(db)


def _compute_tfidf_vectors(
    db: sqlite3.Connection,
    limit: int = 1000,
    *,
    idf_refresh: bool = False,
    since: str | None = None,
) -> int:
    """Write TF-IDF vectors for documents not yet indexed, using a frozen IDF.

    Two-pass, resumable, non-destructive:

    - Pass 1 (once per IDF "epoch"): a full streaming scan of the corpus to
      compute document frequency / IDF (see `_compute_corpus_idf`). Skipped
      if a snapshot is already cached in tfidf_corpus_stats, unless
      ``idf_refresh=True``.
    - Pass 2 (this call): stream documents_v2 LEFT JOIN search_vectors,
      selecting only rows with no existing vector (optionally restricted to
      ``since``), tokenize, score with the frozen IDF, and INSERT OR REPLACE
      into search_vectors. Never deletes existing rows. Commits periodically
      so a long run can be interrupted without losing prior progress, and a
      subsequent call simply picks up the remaining missing documents.

    Self-healing: if search_vectors already has rows but no IDF snapshot
    exists (the signature of the old batch-scoped implementation, or of an
    interrupted legacy run), those rows cannot be trusted to share one IDF
    basis with anything written going forward — they are wiped so the corpus
    is rebuilt cleanly under a single snapshot.

    Args:
        limit: Max documents to WRITE this call (0 = no cap, process all
            currently-missing documents). Does not bound the IDF pass, which
            always covers the whole corpus.
        idf_refresh: Force recomputation of the IDF snapshot even if one is
            cached. Callers that do this should also have dropped/rewritten
            all existing vectors (see build_semantic_index force_rebuild),
            since old vectors would otherwise be scored under a stale IDF.
        since: Optional ISO timestamp; only consider documents whose
            documents_v2.retrieved_at is >= this value (used by incremental
            update_indexes()).

    Returns:
        Number of documents newly written to search_vectors in this call.
    """
    _ensure_search_vectors(db)
    _ensure_tfidf_stats(db)

    stats = None if idf_refresh else _load_corpus_idf(db)
    if stats is None:
        existing_vec_count = db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]
        if existing_vec_count > 0:
            # Legacy/inconsistent vectors — cannot trust their IDF basis.
            db.execute("DELETE FROM search_vectors")
            db.commit()
        idf, _n_docs = _compute_corpus_idf(db)
    else:
        idf, _n_docs = stats

    if not idf:
        return 0

    where_clauses = ["sv.document_id IS NULL"]
    params: list[Any] = []
    if since:
        where_clauses.append("dv.retrieved_at >= ?")
        params.append(since)

    query = f"""
        SELECT dv.document_id, dv.source, dv.full_text, dv.markdown
        FROM documents_v2 dv
        LEFT JOIN search_vectors sv
          ON dv.document_id = sv.document_id AND dv.source = sv.source
        WHERE {' AND '.join(where_clauses)}
    """
    if limit and limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    cursor = db.execute(query, params)

    indexed = 0
    _COMMIT_EVERY = 2000
    for doc_id, source, full_text, markdown in cursor:
        text = full_text or markdown or ""
        if not text.strip():
            continue
        tokens = _tokenize(text)
        if not tokens:
            continue
        token_counts = Counter(tokens)
        total_tokens = sum(token_counts.values())
        vector: dict[str, float] = {}
        for term, count in token_counts.items():
            tf = count / total_tokens
            vector[term] = tf * idf.get(term, 0.0)

        norm = math.sqrt(sum(v * v for v in vector.values())) if vector else 0.0
        vector_json = json.dumps(vector, ensure_ascii=False)

        db.execute(
            "INSERT OR REPLACE INTO search_vectors(document_id, source, vector_json, norm) VALUES(?, ?, ?, ?)",
            (doc_id, source, vector_json, norm),
        )
        indexed += 1
        if indexed % _COMMIT_EVERY == 0:
            db.commit()

    db.commit()
    return indexed


# ---------------------------------------------------------------------------
# Snippet Generation
# ---------------------------------------------------------------------------

def _generate_snippet(
    text: str,
    query: str,
    max_length: int = 200,
    highlight: bool = True,
) -> tuple[str, bool]:
    """Generate a snippet from document text around the query match.

    If *highlight* is True, matching query terms in the snippet are wrapped
    in ``**...**`` markers for Markdown-style bold highlighting.

    Returns:
        Tuple of (snippet_text, was_highlighted).
    """
    if not text:
        return "", False
    if not query:
        return text[:max_length], False

    tokens = _tokenize(query)
    lower_text = text.lower()

    # Find the first matching term position
    idx = -1
    matched_token = ""
    for t in tokens:
        pos = lower_text.find(t)
        if pos != -1:
            idx = pos
            matched_token = t
            break

    if idx == -1:
        return text[:max_length], False

    # Extract window around match
    start = max(0, idx - max_length // 3)
    end = min(len(text), idx + len(query) + 2 * max_length // 3)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    # Apply highlighting: wrap matching tokens in **...**
    was_highlighted = False
    if highlight and matched_token:
        # Case-insensitive replacement wrapping matched tokens in **
        pattern = re.compile(re.escape(matched_token), re.IGNORECASE)
        highlighted = pattern.sub(lambda m: f"**{m.group()}**", snippet)
        if highlighted != snippet:
            snippet = highlighted
            was_highlighted = True

    return snippet, was_highlighted


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
    """Reconstruct an approximate IDF from stored vectors (legacy fallback only).

    Treats "documents currently present in search_vectors" as the corpus and
    counts term presence across their stored vector_json. This is only an
    approximation and is NOT guaranteed to match the IDF that was actually
    used when a given document's vector was written — prefer
    `_load_query_idf`, which uses the exact persisted snapshot in
    tfidf_corpus_stats when available. This function remains as a fallback
    for databases that predate that table.
    M-51: uses cursor iteration to reduce peak memory.
    """
    cursor = db.execute("SELECT vector_json FROM search_vectors")
    n_docs = 0
    df: Counter = Counter()
    for (vjson,) in cursor:
        try:
            vec = json.loads(vjson)
        except (json.JSONDecodeError, TypeError):
            continue
        for term in vec:
            df[term] += 1
        n_docs += 1
    if n_docs == 0:
        return {}
    idf: dict[str, float] = {}
    for term, freq in df.items():
        idf[term] = math.log(n_docs / freq) if freq > 0 else 0.0
    return idf


def _load_query_idf(db: sqlite3.Connection) -> dict[str, float]:
    """Load the IDF map to use for scoring a query.

    Prefers the exact IDF snapshot persisted in tfidf_corpus_stats — the
    same weights used when the currently-stored document vectors were
    written — so query scoring is on the same basis as the index. Falls
    back to the older per-vector reconstruction only if no snapshot exists
    yet (e.g. a legacy database before its next build/update self-heals).
    """
    cached = _load_corpus_idf(db)
    if cached is not None:
        return cached[0]
    return _load_idf_from_vectors(db)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_semantic_index(
    cache: Cache | None = None, force_rebuild: bool = False, limit: int = 0
) -> dict[str, Any]:
    """Build FTS5 and TF-IDF indices.

    Args:
        cache: Optional Cache instance for DB injection.  If None a fresh Cache
               is created.
        force_rebuild: If True, drop and recreate all index tables (including
            the frozen IDF snapshot) first, so IDF is recomputed fresh over
            the whole corpus and every vector is rewritten under it.
        limit: Cap on how many still-missing documents to write THIS call
            (0 = no cap, process all of them). Use a bounded value to drive
            a long build in resumable chunks — each call only fills gaps
            (it never deletes existing vectors), and reuses the same cached
            IDF snapshot across calls, so partial progress is always
            internally consistent. Re-running with the same or larger corpus
            picks up exactly where the previous call left off.

    Returns:
        Status dict with ok, fts5_exists, fts5_row_count, vectors_count,
        newly_indexed, remaining_unindexed, elapsed_seconds, etc.
    """
    import time

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
            # Drop the frozen IDF snapshot too — force_rebuild means every
            # vector is rewritten, so IDF must be recomputed over the
            # current whole corpus rather than reusing a stale snapshot.
            db.execute("DROP TABLE IF EXISTS tfidf_corpus_stats")
            db.commit()
            warnings.append("Existing FTS5 and vector indices were dropped for rebuild.")

        fts5_existed = _ensure_fts5(db)
        _ensure_search_vectors(db)

        t0 = time.time()
        newly_indexed = _compute_tfidf_vectors(db, limit=limit)
        elapsed = round(time.time() - t0, 3)

        vectors_count = db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]
        fts5_row_count = db.execute("SELECT COUNT(*) FROM documents_v2_fts").fetchone()[0]
        docs_total = db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
        remaining_unindexed = max(0, docs_total - vectors_count)

        if vectors_count == 0 and docs_total > 0:
            warnings.append("No documents with text content found; vectors table is empty.")
        if limit and remaining_unindexed > 0:
            warnings.append(
                f"{remaining_unindexed} document(s) still unindexed after this batch "
                "(limit was applied). Call build_semantic_index() again to continue."
            )

        return {
            "ok": True,
            "fts5_exists": fts5_existed or not force_rebuild,
            "fts5_row_count": fts5_row_count,
            "vectors_count": vectors_count,
            "newly_indexed": newly_indexed,
            "remaining_unindexed": remaining_unindexed,
            "documents_total": docs_total,
            "elapsed_seconds": elapsed,
            "warnings": warnings,
            "recommended_next_steps": [
                "Use hybrid_search() to query the index.",
                "Call get_index_status() to verify index health.",
            ],
            "version": SEMANTIC_VERSION,
        }
    except Exception as exc:
        return build_error(
            "INDEX_BUILD_FAILED",
            str(exc),
            fts5_exists=False,
            fts5_row_count=0,
            vectors_count=0,
            documents_total=0,
            warnings=[str(exc)],
            recommended_next_steps=["Check database permissions and schema."],
            version=SEMANTIC_VERSION,
        )
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
                    "expanded_query_terms": _expand_query(query),
                    "snippet_highlighted": False,
                    "version": SEMANTIC_VERSION,
                }

        # Expand query with Turkish suffix stripping
        expanded_terms = _expand_query(query)

        # Load IDF — prefers the exact snapshot used when vectors were written
        idf = _load_query_idf(db)
        query_vec = _build_query_vector(query, idf)

        if not query_vec:
            return {
                "ok": True,
                "query": query,
                "results": [],
                "total_matches": 0,
                "method": "tfidf_cosine",
                "warnings": ["Query produced no meaningful tokens."],
                "expanded_query_terms": expanded_terms,
                "snippet_highlighted": False,
                "version": SEMANTIC_VERSION,
            }

        # Load all vectors — M-51: use cursor iteration
        # M-53: fetch pre-computed norm to avoid recomputing per-vector L2 norm
        cursor = db.execute(
            "SELECT document_id, source, vector_json, norm FROM search_vectors"
        )

        scored: list[dict[str, Any]] = []
        any_highlighted = False
        for row in cursor:
            doc_id, source, vjson, stored_norm = row
            doc_vec = json.loads(vjson)
            stored_norm = stored_norm or 0.0
            cosine_score = (
                _cosine_similarity_with_norm(query_vec, doc_vec, stored_norm)
                if stored_norm > 0
                else _cosine_similarity(query_vec, doc_vec)
            )

            if cosine_score <= 0:
                continue

            doc_info = _fetch_doc_row(db, doc_id, source)
            if doc_info is None:
                continue

            snippet, hl = _generate_snippet(
                doc_info["full_text"] or doc_info["markdown"],
                query,
            )
            if hl:
                any_highlighted = True

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
            "expanded_query_terms": expanded_terms,
            "snippet_highlighted": any_highlighted,
            "version": SEMANTIC_VERSION,
        }
    except Exception as exc:
        return build_error(
            "SEARCH_FAILED",
            str(exc),
            query=query,
            results=[],
            total_matches=0,
            method="tfidf_cosine",
            warnings=[str(exc)],
            expanded_query_terms=[],
            snippet_highlighted=False,
            version=SEMANTIC_VERSION,
        )
    finally:
        if own_cache:
            try:
                db.close()
            except Exception:
                pass


# ── FTS5 / TF-IDF search helpers for RRF fusion (M-69) ──────────────────────


def _fts5_search(
    query: str, limit: int, cache: Cache | None = None, filters: dict | None = None
) -> list[dict[str, Any]]:
    """Run BM25 FTS5 search and return results in standard format.

    ``search_local`` orders by BM25; RRF fuses on rank position alone, so the
    per-item score is not needed and is left at 0.0.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        raw = c.search_local(query=query, limit=limit, **(filters or {}))
        # Convert search_local format to standard result dict
        return [
            {
                "document_id": r.get("document_id", ""),
                "source": r.get("source", ""),
                "title": r.get("title", ""),
                "court": r.get("court"),
                "chamber": r.get("chamber"),
                "decision_date": r.get("decision_date"),
                "score": 0.0,  # RRF fuses on rank, not score
                "content_status": r.get("content_status", ""),
                "quote_usable": r.get("quote_usable", False),
                "draft_usable": r.get("draft_usable", False),
                "snippet": r.get("snippet", ""),
            }
            for r in raw
        ]
    finally:
        if own_cache:
            c.close()


def _tfidf_search(
    query: str, limit: int, cache: Cache | None = None, filters: dict | None = None
) -> list[dict[str, Any]]:
    """Run TF-IDF cosine search and return results in standard format."""
    sr = semantic_search(query=query, limit=limit, cache=cache, filters=filters)
    return sr.get("results", []) if sr.get("ok") else []


# ── Reciprocal Rank Fusion (RRF) — M-69 ──────────────────────────────────────

_RRF_K = 60  # RRF constant (standard value)


def _rrf_fusion(
    bm25_results: list[dict[str, Any]],
    tfidf_results: list[dict[str, Any]],
    dense_results: list[dict[str, Any]] | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Fuse result lists using Reciprocal Rank Fusion.

    RRF does not require score normalization — it only uses rank positions.
    Formula: score(d) = sum_{ranker} 1 / (k + rank_i(d))

    Returns top ``limit`` documents sorted by RRF score descending.
    """
    scores: dict[tuple[str, str], float] = {}  # (doc_id, source) -> rrf_score

    # Merge scores from each ranker
    rankers = [bm25_results, tfidf_results]
    if dense_results:
        rankers.append(dense_results)

    # Collect document metadata for the merged results
    doc_meta: dict[tuple[str, str], dict[str, Any]] = {}

    for ranker_results in rankers:
        for rank, item in enumerate(ranker_results):
            key = (item.get("document_id", ""), item.get("source", ""))
            if not key[0]:
                continue
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
            if key not in doc_meta:
                doc_meta[key] = item

    # Sort by RRF score descending
    sorted_keys = sorted(scores, key=lambda k: scores[k], reverse=True)

    merged = []
    for key in sorted_keys[:limit]:
        item = dict(doc_meta[key])
        item["rrf_score"] = round(scores[key], 6)
        merged.append(item)

    return merged


def hybrid_search_rrf(
    query: str,
    limit: int = 10,
    cache: Cache | None = None,
    filters: dict[str, Any] | None = None,
    include_dense: bool = False,
) -> dict[str, Any]:
    """Hybrid search using Reciprocal Rank Fusion (RRF) instead of weighted linear fusion.

    RRF avoids the need for score calibration between heterogeneous rankers
    (BM25, TF-IDF cosine, dense cosine).  Results from each ranker are merged
    by rank position only.

    Args:
        query: Search query.
        limit: Max results.
        cache: Optional Cache.
        filters: Optional metadata filters.
        include_dense: Whether to include dense embeddings in fusion.

    Returns:
        Dict with ok, results (with rrf_score), method="rrf".
    """
    from .embeddings import get_embedding_provider

    own_cache = cache is None
    c = cache or Cache()
    try:
        # 1. BM25 (FTS5)
        bm25 = _fts5_search(query, limit=limit * 2, cache=c, filters=filters)

        # 2. TF-IDF cosine
        tfidf = _tfidf_search(query, limit=limit * 2, cache=c, filters=filters)

        # 3. Dense (optional)
        dense: list[dict[str, Any]] | None = None
        dense_provider = None
        if include_dense:
            prov = get_embedding_provider()
            if prov is not None:
                dr = embedding_search(query=query, limit=limit * 2, cache=c, filters=filters)
                if dr.get("ok"):
                    dense = dr.get("results", [])
                    dense_provider = prov.id

        merged = _rrf_fusion(bm25, tfidf, dense, limit)

        return {
            "ok": True,
            "query": query,
            "results": merged,
            "total_matches": len(merged),
            "method": "rrf",
            "rrf_k": _RRF_K,
            "dense_included": include_dense,
            "dense_provider": dense_provider,
            "warnings": [],
            "recommended_next_steps": [],
            "version": "0.14.0",
        }
    finally:
        if own_cache:
            c.close()


def hybrid_search(
    query: str,
    limit: int = 10,
    cache: Cache | None = None,
    filters: dict[str, Any] | None = None,
    hybrid_weight: float = 0.6,
    dense_weight: float | None = None,
    rerank: bool = False,
) -> dict[str, Any]:
    """Combined FTS5 BM25 + TF-IDF cosine hybrid search (v3 with optional dense).

    When dense_weight is None or 0.0, behaviour is identical to v2 (regression safe).
    When dense_weight > 0, a third dense-embedding signal is merged into the score.

    Args:
        query: Free-text search query.
        limit: Maximum results to return.
        cache: Optional Cache instance for DB injection.
        filters: Optional metadata filters applied after scoring.
            Supported keys: source, court, chamber, content_status,
            quote_usable, draft_usable.
        hybrid_weight: Weight for BM25 component (1-hybrid_weight for cosine).
            Must be between 0.0 and 1.0.  Default 0.6 means 60% BM25, 40%
            cosine.
        dense_weight: Optional weight for dense embedding component.
            When None, defaults to config value.  Set to 0.0 to disable.
        rerank: Optional cross-encoder reranking of top results.
            When True, re-scores top candidates with a cross-encoder model
            if available.  Gracefully passes through when unavailable.

    Returns:
        Dict with ok, results, total_matches, method, hybrid_weight,
        dense_weight, expanded_query_terms, snippet_highlighted, warnings, version.
    """
    # Validate hybrid_weight
    if not (0.0 <= hybrid_weight <= 1.0):
        return build_error(
            "INVALID_HYBRID_WEIGHT",
            f"hybrid_weight must be between 0.0 and 1.0, got {hybrid_weight}",
            query=query,
            results=[],
            total_matches=0,
            method="hybrid",
            hybrid_weight=hybrid_weight,
            warnings=[],
            recommended_next_steps=["Set hybrid_weight to a value between 0.0 and 1.0."],
            expanded_query_terms=[],
            snippet_highlighted=False,
            version=SEMANTIC_VERSION,
        )

    # Resolve dense_weight: explicit arg > env config > 0.0 (disabled)
    if dense_weight is None:
        from .config import config as _cfg

        dense_weight = _cfg.hybrid_w_dense

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
                "dense_weight": dense_weight,
                "reranked": False,
                "warnings": ["No documents in cache. Store documents first."],
                "recommended_next_steps": ["Use store_document() to add documents."],
                "expanded_query_terms": [],
                "snippet_highlighted": False,
                "version": SEMANTIC_VERSION,
            }

        # ---- Query Expansion (Turkish suffix stripping) ----
        expanded_terms = _expand_query(query)
        expanded_query = " OR ".join(expanded_terms) if expanded_terms else query

        # ---- FTS5 BM25 Search ----
        bm25_results: dict[tuple[str, str], float] = {}
        try:
            # Escape special FTS5 characters in expanded query for MATCH
            safe_query = re.sub(r'[^\w\s]', ' ', expanded_query).strip()
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
            idf = _load_query_idf(db)
            query_vec = _build_query_vector(query, idf)
            if query_vec:
                # M-53: fetch pre-computed norm to skip per-vector L2 recomputation
                cursor = db.execute(
                    "SELECT document_id, source, vector_json, norm FROM search_vectors"
                )
                for row in cursor:
                    doc_id, source, vjson, stored_norm = row
                    doc_vec = json.loads(vjson)
                    stored_norm = stored_norm or 0.0
                    cs = (
                        _cosine_similarity_with_norm(query_vec, doc_vec, stored_norm)
                        if stored_norm > 0
                        else _cosine_similarity(query_vec, doc_vec)
                    )
                    if cs > 0:
                        cosine_results[(doc_id, source)] = cs

        # ---- Dense Embedding Search (optional, v3) ----
        dense_results: dict[tuple[str, str], float] = {}
        dense_provider: str | None = None
        if dense_weight is not None and dense_weight > 0:
            try:
                dr = embedding_search(query=query, limit=limit * 3, cache=cache, filters=None)
                if dr.get("ok"):
                    for r in dr.get("results", []):
                        dense_results[(r["document_id"], r["source"])] = r["score"]
                    dense_provider = dr.get("provider")
            except Exception:
                warnings.append("Dense embedding search failed; proceeding without dense signal.")

        # ---- Merge Scores ----
        all_keys = set(bm25_results.keys()) | set(cosine_results.keys()) | set(dense_results.keys())
        if not all_keys:
            return {
                "ok": True,
                "query": query,
                "results": [],
                "total_matches": 0,
                "method": "hybrid",
                "hybrid_weight": hybrid_weight,
                "dense_weight": dense_weight,
                "reranked": False,
                "warnings": warnings,
                "recommended_next_steps": ["Try a broader query or check index status."],
                "expanded_query_terms": expanded_terms,
                "snippet_highlighted": False,
                "version": SEMANTIC_VERSION,
            }

        # Normalize BM25 to [0, 1] range
        # BM25 scores are negative (lower = better match), so invert
        merged: list[dict[str, Any]] = []
        any_highlighted = False
        for key in all_keys:
            doc_id, source = key
            bm25_raw = bm25_results.get(key, 0.0)
            cosine_raw = cosine_results.get(key, 0.0)
            dense_raw = dense_results.get(key, 0.0)

            # Normalize BM25: lower (more negative) = better match
            # Map to [0, 1]: bm25_norm = 1.0 / (1.0 + abs(bm25_score))
            bm25_norm = 1.0 / (1.0 + abs(bm25_raw)) if bm25_raw != 0 else 0.0
            # Cosine is already in [0, 1] by definition
            # Dense is already in [0, 1] by definition

            # 3-signal merge when dense_weight > 0, else 2-signal (regression safe)
            if dense_weight and dense_weight > 0:
                # Normalize weights to sum to 1.0
                total_w = hybrid_weight + (1.0 - hybrid_weight) + dense_weight
                w_bm25 = hybrid_weight / total_w
                w_tfidf = (1.0 - hybrid_weight) / total_w
                w_dense = dense_weight / total_w
                final_score = w_bm25 * bm25_norm + w_tfidf * cosine_raw + w_dense * dense_raw
            else:
                final_score = hybrid_weight * bm25_norm + (1.0 - hybrid_weight) * cosine_raw

            doc_info = _fetch_doc_row(db, doc_id, source)
            if doc_info is None:
                continue

            snippet, hl = _generate_snippet(
                doc_info["full_text"] or doc_info["markdown"],
                query,
            )
            if hl:
                any_highlighted = True

            entry: dict[str, Any] = {
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
            }
            if dense_weight and dense_weight > 0:
                entry["dense_score"] = round(dense_raw, 6)
            merged.append(entry)

        # Apply filters
        merged = _apply_filters(merged, filters)

        # Sort by hybrid_score descending
        merged.sort(key=lambda x: x["hybrid_score"], reverse=True)
        top = merged[:limit]

        # ---- Optional cross-encoder reranking (M-25) ----
        was_reranked = False
        if rerank and top:
            from .embeddings import rerank_results

            rr = rerank_results(query, list(top), top_k=limit)
            if rr.get("was_reranked"):
                top = rr["results"]
                was_reranked = True
            if rr.get("warnings"):
                warnings.extend(rr["warnings"])

        if not bm25_results:
            recommended.append("FTS5 index may be empty. Run build_semantic_index() to rebuild.")
        if not cosine_results:
            recommended.append("TF-IDF vectors may be empty. Run build_semantic_index() to rebuild.")
        if dense_weight and dense_weight > 0 and not dense_results:
            recommended.append(
                "Dense embedding index may be empty. Run build_embedding_index() to index."
            )

        return {
            "ok": True,
            "query": query,
            "results": top,
            "total_matches": len(merged),
            "method": "hybrid",
            "hybrid_weight": hybrid_weight,
            "dense_weight": dense_weight,
            "dense_provider": dense_provider,
            "reranked": was_reranked,
            "warnings": warnings,
            "recommended_next_steps": recommended,
            "expanded_query_terms": expanded_terms,
            "snippet_highlighted": any_highlighted,
            "version": SEMANTIC_VERSION,
        }
    except Exception as exc:
        return build_error(
            "SEARCH_FAILED",
            str(exc),
            query=query,
            results=[],
            total_matches=0,
            method="hybrid",
            hybrid_weight=hybrid_weight,
            dense_weight=dense_weight,
            warnings=[str(exc)],
            recommended_next_steps=[],
            expanded_query_terms=[],
            snippet_highlighted=False,
            version=SEMANTIC_VERSION,
        )
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
        return build_error(
            "INDEX_QUERY_FAILED",
            str(exc),
            fts5_exists=False,
            fts5_document_count=0,
            vectors_table_exists=False,
            vectors_count=0,
            total_cached_documents=0,
            unindexed_documents=0,
            warnings=[str(exc)],
            recommended_next_steps=["Check database accessibility."],
            version=SEMANTIC_VERSION,
        )
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


# ---------------------------------------------------------------------------
# Dense Embedding Vectors (M-24)
# ---------------------------------------------------------------------------


def _ensure_embedding_vectors(db: sqlite3.Connection) -> bool:
    """Create the embedding_vectors table for dense embedding storage.

    ``chunk_index`` is part of the primary key.  Documents are chunked before
    embedding (see ``chunking.py``; the e5 model caps at 512 tokens and real
    decisions run to thousands), so a decision routinely owns hundreds of
    vectors — one real document in the corpus has 1,798.  The original key was
    ``(document_id, source, provider_id)``, which can hold exactly one vector
    per document and silently overwrites every chunk but the last.

    Returns True if the table already existed.
    """
    existing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='embedding_vectors'"
    ).fetchone()
    already_existed = existing is not None
    db.execute("""
        CREATE TABLE IF NOT EXISTS embedding_vectors (
            document_id TEXT NOT NULL,
            source TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            dim INTEGER NOT NULL,
            vector BLOB NOT NULL,
            norm REAL DEFAULT 0.0,
            indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            content_hash TEXT,
            PRIMARY KEY (document_id, source, provider_id, chunk_index)
        )
    """)
    # Pre-chunking databases lack the column entirely.  Adding it keeps them
    # readable; the narrow primary key stays until the table is rebuilt, so
    # such a database can still only hold one vector per document.
    cols = {r[1] for r in db.execute("PRAGMA table_info(embedding_vectors)")}
    if "chunk_index" not in cols:
        db.execute(
            "ALTER TABLE embedding_vectors "
            "ADD COLUMN chunk_index INTEGER NOT NULL DEFAULT 0"
        )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ev_provider ON embedding_vectors(provider_id)"
    )
    db.commit()
    return already_existed


def embedding_table_supports_chunks(db: sqlite3.Connection) -> bool:
    """True when ``embedding_vectors`` can hold more than one vector per doc.

    A database created before chunking has ``chunk_index`` outside the primary
    key, so chunked inserts collapse onto a single row.  Callers that write
    chunk-level vectors must check this instead of assuming.
    """
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='embedding_vectors'"
    ).fetchone()
    if not row or not row[0]:
        return False
    sql = row[0].lower()
    return "primary key" in sql and "chunk_index" in sql.split("primary key", 1)[1]


def build_embedding_index(
    cache: Cache | None = None,
    provider: str | None = None,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Build dense embedding index from cached documents.

    Args:
        cache: Optional Cache instance for DB injection.
        provider: Provider ID (default from config/env).
        force_rebuild: If True, re-embed all documents.

    Returns:
        Status dict with ok, documents_indexed, provider, dimensions, etc.
    """
    import time

    from .embeddings import get_embedding_provider, pack_vector

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        _ensure_embedding_vectors(db)

        prov = get_embedding_provider(provider)
        if prov is None:
            return build_error(
                "EMBEDDING_BACKEND_UNAVAILABLE",
                f"Embedding provider '{provider or 'default'}' unavailable. "
                "Install fastembed or use local-hash-v1.",
            )

        # Get documents with text content — M-51: use cursor iteration
        cursor = db.execute(
            """
            SELECT document_id, source, full_text, markdown, content_hash
            FROM documents_v2
            WHERE (full_text IS NOT NULL AND full_text != '')
               OR (markdown IS NOT NULL AND markdown != '')
        """
        )

        first_row = cursor.fetchone()
        if not first_row:
            return {
                "ok": True,
                "documents_indexed": 0,
                "provider": prov.id,
                "dimensions": prov.dimensions,
                "warnings": ["No documents with text content."],
            }

        indexed = 0
        skipped = 0
        t0 = time.time()

        def _process_emb_row(row: Any) -> None:
            nonlocal indexed, skipped
            doc_id = row["document_id"]
            source = row["source"]
            text = row["full_text"] or row["markdown"] or ""
            content_hash = row["content_hash"]

            if not force_rebuild:
                existing = db.execute(
                    "SELECT content_hash FROM embedding_vectors "
                    "WHERE document_id=? AND source=? AND provider_id=?",
                    (doc_id, source, prov.id),
                ).fetchone()
                if existing and existing["content_hash"] == content_hash:
                    skipped += 1
                    return

            # Embed — use embed_document() if provider supports it (E5 prefix)
            if hasattr(prov, "embed_document"):
                vec = prov.embed_document(text)  # type: ignore[union-attr]
            else:
                vec = prov.embed_text(text)
            blob = pack_vector(vec)
            norm = math.sqrt(sum(v * v for v in vec))

            db.execute(
                """
                INSERT OR REPLACE INTO embedding_vectors
                (document_id, source, provider_id, dim, vector, norm, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (doc_id, source, prov.id, prov.dimensions, blob, norm, content_hash),
            )
            indexed += 1

        # M-51: process first row, then iterate remaining via cursor
        _process_emb_row(first_row)
        for row in cursor:
            _process_emb_row(row)

        db.commit()
        elapsed = round(time.time() - t0, 3)

        return {
            "ok": True,
            "documents_indexed": indexed,
            "skipped": skipped,
            "provider": prov.id,
            "dimensions": prov.dimensions,
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        return build_error(
            "EMBEDDING_INDEX_FAILED",
            str(exc),
            documents_indexed=0,
            provider=provider,
            warnings=[str(exc)],
        )
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


#: Rows pulled per batch.  384 float32 per vector → ~75 MB of BLOBs per batch,
#: which keeps peak memory well under the ~1.8 GB free on the target machine.
_EMBED_SCAN_BATCH = 50_000


# ---------------------------------------------------------------------------
# Memory-mapped vector matrix (sidecar files next to the cache DB)
# ---------------------------------------------------------------------------
#
# Reading 1.3M vectors out of SQLite costs ~110s per query: every BLOB is a
# separate row with its own header, so the scan is random-ish I/O over 2.6 GB.
# The same numbers written once as a contiguous float32 matrix are a single
# sequential read, and after the first query the OS page cache serves them.
#
# The matrix is memory-mapped rather than loaded: the file is ~2 GB and this
# machine has ~1.8 GB free, but a read-only mmap can be evicted for free (it
# is backed by the file, never by swap), whereas a Python-owned array of the
# same size would not fit.
#
# Document ids are deliberately NOT stored alongside: 1.3M of them would be
# tens of MB to parse on every query.  Rows are keyed by the SQLite rowid they
# came from, and ids are resolved for the top-k only.


#: Storage precision for the scan matrix.
#:
#: float16 was tried to halve the file (1944 MB → 972 MB) on the theory that
#: disk I/O dominated.  Measured, it was the opposite: the file is served from
#: the page cache either way, and numpy has no float16 BLAS kernel, so every
#: query paid a 509M-element upcast.  Same hardware, 400k rows, minimum of 3:
#:     float16 → float32 upcast + matmul   0.244 s
#:     float32 matmul straight off the mmap 0.038 s
#: 6.4x, and it scales linearly with corpus size.  Storage is cheap; the
#: conversion is not.
_MATRIX_DTYPE = "float32"
#: Bumped when the sidecar layout changes so old files are rebuilt, not read.
_MATRIX_FORMAT = 3
#: Rows per matmul block: 384 float32 → ~150 MB at 100k.
_MATMUL_BLOCK = 100_000
#: Per-process memo of the expensive half of the freshness check, keyed by
#: (meta path, build timestamp, max rowid).  Any of those changing re-verifies.
_MATRIX_VERIFIED: dict[tuple, bool] = {}


def _sidecar_stem(db_path: Path, provider_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", provider_id)
    return db_path.parent / f"embed-{safe}"


def _sidecar_meta_path(db_path: Path, provider_id: str) -> Path:
    """Path of the small JSON file naming the current data generation."""
    return _sidecar_stem(db_path, provider_id).with_suffix(".meta.json")


def _sidecar_data_paths(
    db_path: Path, provider_id: str, token: str,
) -> dict[str, Path]:
    """Paths of one generation of data files.

    Data files are versioned by *token* and never overwritten.  Windows
    refuses both an in-place write and an ``os.replace`` onto a file that any
    process still has memory-mapped — a live search holds exactly that map, so
    a rebuild against a fixed filename failed with OSError 22 / WinError 5 and
    silently kept the old matrix.  Writing a new generation sidesteps the lock
    entirely, and a reader mid-query keeps its own files until it reloads.
    """
    stem = _sidecar_stem(db_path, provider_id)
    return {
        "matrix": stem.with_suffix(f".{token}.vectors.npy"),
        "rowids": stem.with_suffix(f".{token}.rowids.npy"),
        "norms": stem.with_suffix(f".{token}.norms.npy"),
    }


def _sidecar_paths(db_path: Path, provider_id: str) -> dict[str, Path]:
    """Meta path plus the data paths of the generation it points at."""
    meta_path = _sidecar_meta_path(db_path, provider_id)
    token = ""
    if meta_path.exists():
        try:
            token = json.loads(meta_path.read_text(encoding="utf-8")).get("token", "")
        except Exception:
            token = ""
    out: dict[str, Path] = {"meta": meta_path}
    out.update(_sidecar_data_paths(db_path, provider_id, token or "0"))
    return out


def _purge_old_generations(
    db_path: Path, provider_id: str, keep_token: str,
) -> list[str]:
    """Delete data files from superseded generations.

    Best effort: a file another process still has mapped cannot be removed on
    Windows, and that is fine — it will be collected on a later rebuild.
    """
    stem = _sidecar_stem(db_path, provider_id)
    removed: list[str] = []
    for path in stem.parent.glob(f"{stem.name}.*"):
        if path.name.endswith(".meta.json"):
            continue
        parts = path.name[len(stem.name) + 1:].split(".")
        if not parts or parts[0] in (keep_token, ""):
            continue
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    return removed


def build_embedding_matrix(
    provider_id: str,
    cache: Cache | None = None,
    *,
    force: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Write the contiguous vector matrix used by fast dense search.

    Reads every vector for *provider_id* once and writes three sidecar arrays
    plus a metadata file.  Rebuild after adding vectors — a stale sidecar is
    detected and refused, never silently searched.
    """
    import json

    import numpy as np

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        paths = _sidecar_paths(Path(c.path), provider_id)
        _ensure_embedding_vectors(db)

        row = db.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid), 0), COALESCE(MIN(dim), 0) "
            "FROM embedding_vectors WHERE provider_id=?",
            (provider_id,),
        ).fetchone()
        count, max_rowid, dim = int(row[0]), int(row[1]), int(row[2])
        if count == 0:
            return build_error(
                "NO_VECTORS",
                f"'{provider_id}' için vektör yok; önce embedding üretin.",
                provider=provider_id,
            )

        if not force and paths["meta"].exists():
            try:
                meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
                if meta.get("count") == count and meta.get("max_rowid") == max_rowid:
                    return {
                        "ok": True, "rebuilt": False, "reason": "güncel",
                        "provider": provider_id, "count": count, "dim": dim,
                        "path": str(paths["matrix"]),
                    }
            except Exception:
                pass  # unreadable meta → rebuild

        t0 = time.time()
        # Write a NEW generation rather than overwriting the current one; see
        # _sidecar_data_paths for why in-place rebuilds cannot work here.
        db_path = Path(c.path)
        # The token must be unique, not merely current: two rebuilds inside
        # the same second collided, and deleting the colliding files first
        # would defeat the point — those are exactly the files a live reader
        # still has mapped.
        base = time.strftime("%Y%m%d%H%M%S")
        token, bump = base, 0
        while any(
            p.exists()
            for p in _sidecar_data_paths(db_path, provider_id, token).values()
        ):
            bump += 1
            token = f"{base}-{bump}"
        new_paths = _sidecar_data_paths(db_path, provider_id, token)

        mat = np.lib.format.open_memmap(
            new_paths["matrix"], mode="w+", dtype=_MATRIX_DTYPE,
            shape=(count, dim),
        )
        rowids = np.empty(count, dtype=np.int64)
        norms = np.empty(count, dtype=np.float32)

        cursor = db.execute(
            "SELECT rowid, vector, norm FROM embedding_vectors "
            "WHERE provider_id=? AND dim=? ORDER BY rowid",
            (provider_id, dim),
        )
        n = 0
        while n < count:
            rows = cursor.fetchmany(_EMBED_SCAN_BATCH)
            if not rows:
                break
            blob = b"".join(r["vector"][: dim * 4] for r in rows)
            chunk = np.frombuffer(blob, dtype=np.float32).reshape(len(rows), dim)
            mat[n:n + len(rows)] = chunk.astype(_MATRIX_DTYPE)
            rowids[n:n + len(rows)] = [r["rowid"] for r in rows]
            norms[n:n + len(rows)] = [r["norm"] or 0.0 for r in rows]
            n += len(rows)
            if progress_callback:
                progress_callback({"ok": True, "written": n, "total": count})

        mat.flush()
        del mat
        gc.collect()  # drop our own map before rewriting the file below

        # A short read means rows with a different dim were skipped; trim so
        # the arrays never contain uninitialised tail garbage.
        if n < count:
            full = np.load(new_paths["matrix"], mmap_mode="r")
            trimmed = np.array(full[:n])
            del full
            gc.collect()
            np.save(new_paths["matrix"], trimmed)
        np.save(new_paths["rowids"], rowids[:n])
        np.save(new_paths["norms"], norms[:n])

        # Publish by rewriting the small metadata file — the only step that
        # makes the new generation live.  Until this succeeds, readers keep
        # using the previous generation, which is still on disk and intact.
        meta_path = _sidecar_meta_path(db_path, provider_id)
        meta_tmp = meta_path.with_suffix(".tmp.json")
        meta_tmp.write_text(json.dumps({
            "provider": provider_id, "token": token,
            "dim": dim, "count": count, "written": n, "max_rowid": max_rowid,
            "dtype": np.dtype(_MATRIX_DTYPE).name,
            "format": _MATRIX_FORMAT,
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False), encoding="utf-8")
        os.replace(meta_tmp, meta_path)
        _MATRIX_VERIFIED.clear()

        removed = _purge_old_generations(db_path, provider_id, token)

        return {
            "ok": True, "rebuilt": True, "provider": provider_id,
            "count": n, "dim": dim, "elapsed_s": round(time.time() - t0, 1),
            "path": str(new_paths["matrix"]),
            "size_mb": round(new_paths["matrix"].stat().st_size / 1024 / 1024, 1),
            "superseded_files_removed": len(removed),
        }
    finally:
        if own_cache:
            c.close()


def embedding_matrix_status(
    provider_id: str, cache: Cache | None = None,
) -> dict[str, Any]:
    """Report whether the sidecar matrix exists and matches the database."""
    import json

    own_cache = cache is None
    c = cache or Cache()
    try:
        paths = _sidecar_paths(Path(c.path), provider_id)
        # A database that has never embedded anything has no table at all;
        # reporting that is the job here, so do not raise on it.
        _ensure_embedding_vectors(c.db)
        row = c.db.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM embedding_vectors "
            "WHERE provider_id=?", (provider_id,),
        ).fetchone()
        db_count, db_max = int(row[0]), int(row[1])

        if not paths["meta"].exists() or not paths["matrix"].exists():
            return {
                "ok": True, "exists": False, "fresh": False,
                "provider": provider_id, "db_vector_count": db_count,
                "recommended_next_steps": [
                    "emsal-mcp semantic build-matrix ile hızlı arama matrisini kurun."
                ],
            }
        meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
        current = meta.get("count") == db_count and meta.get("max_rowid") == db_max
        # Layout matters as much as row count: a matrix written by an older
        # format is refused by the search path, so reporting it as "fresh"
        # would explain a slow query as a fast one.
        compatible = meta.get("format") == _MATRIX_FORMAT
        fresh = current and compatible
        out = {
            "ok": True, "exists": True, "fresh": fresh,
            "provider": provider_id, "db_vector_count": db_count,
            "matrix_vector_count": meta.get("written", meta.get("count")),
            "dim": meta.get("dim"), "dtype": meta.get("dtype"),
            "format": meta.get("format"), "expected_format": _MATRIX_FORMAT,
            "built_at": meta.get("built_at"),
            "path": str(paths["matrix"]),
        }
        warnings: list[str] = []
        if not current:
            warnings.append(
                f"Matris bayat: veritabanında {db_count} vektör var, matris "
                f"{meta.get('count')} vektörle kurulmuş."
            )
        if not compatible:
            warnings.append(
                f"Matris eski biçimde (format {meta.get('format')}, beklenen "
                f"{_MATRIX_FORMAT}); arama bunu kullanmaz."
            )
        if warnings:
            warnings.append(
                "Arama yavaş yola düşecek. 'emsal-mcp semantic build-matrix "
                "--force' ile yeniden kurun."
            )
            out["warnings"] = warnings
            out["recommended_next_steps"] = [
                "emsal-mcp semantic build-matrix --force"
            ]
        return out
    finally:
        if own_cache:
            c.close()


def best_dense_provider(cache: Cache | None = None) -> str | None:
    """Provider id with the most vectors in this corpus, or None if empty.

    The configured default is ``local-hash-v1`` — a dependency-free toy
    provider — so a caller that omits ``provider`` was silently searching
    8,547 hash vectors while 1.3M real embeddings sat unused in the same
    table.  Picking by vector count makes the good index the default without
    hard-coding a model name.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        _ensure_embedding_vectors(c.db)
        row = c.db.execute(
            "SELECT provider_id, COUNT(*) n FROM embedding_vectors "
            "GROUP BY 1 ORDER BY n DESC LIMIT 1"
        ).fetchone()
        return row[0] if row and row[1] else None
    except Exception:
        return None
    finally:
        if own_cache:
            c.close()


def _score_vectors_mmap(
    db: Any,
    db_path: Path,
    provider_id: str,
    q_vec: list[float],
    q_norm: float,
    *,
    limit: int,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    """Score via the sidecar matrix, or None when it is missing or stale.

    Returning None (rather than an empty list) matters: a stale index must
    fall back to the slow-but-correct scan, never answer "no results".
    """
    import json

    import numpy as np

    paths = _sidecar_paths(db_path, provider_id)
    if not (paths["matrix"].exists() and paths["meta"].exists()):
        return None
    try:
        meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    except Exception:
        return None

    if meta.get("format") != _MATRIX_FORMAT or meta.get("dim") != len(q_vec):
        return None

    # Freshness: MAX(rowid) first — it is an index lookup, whereas COUNT(*)
    # walks 1.3M rows and measured ~1s, which was a sixth of the whole query.
    # Rows are only ever appended here, so a changed maximum already proves
    # staleness; the count is confirmation, checked once per process.
    max_row = int(db.execute(
        "SELECT COALESCE(MAX(rowid), 0) FROM embedding_vectors "
        "WHERE provider_id=?", (provider_id,),
    ).fetchone()[0])
    if meta.get("max_rowid") != max_row:
        return None

    fingerprint = (str(paths["meta"]), meta.get("built_at"), max_row)
    if _MATRIX_VERIFIED.get(fingerprint) is None:
        count = int(db.execute(
            "SELECT COUNT(*) FROM embedding_vectors WHERE provider_id=?",
            (provider_id,),
        ).fetchone()[0])
        _MATRIX_VERIFIED[fingerprint] = meta.get("count") == count
    if not _MATRIX_VERIFIED[fingerprint]:
        return None

    mat = np.load(paths["matrix"], mmap_mode="r")
    rowids = np.load(paths["rowids"], mmap_mode="r")
    norms = np.load(paths["norms"], mmap_mode="r")

    # Shortlist pass.  Blocked so a memmap wider than RAM is walked
    # sequentially rather than faulted in all at once; each block is already
    # float32, so this stays on the BLAS fast path.
    q32 = np.asarray(q_vec, dtype=np.float32)
    n_rows = mat.shape[0]
    dots = np.empty(n_rows, dtype=np.float32)
    for start in range(0, n_rows, _MATMUL_BLOCK):
        stop = min(start + _MATMUL_BLOCK, n_rows)
        dots[start:stop] = mat[start:stop] @ q32
    denom = np.asarray(norms, dtype=np.float32) * np.float32(q_norm)
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = np.where(denom > 0, dots.astype(np.float32) / denom, np.float32(0.0))

    keep = min(max(limit * 20, 200), sims.shape[0])
    idx = np.argpartition(-sims, keep - 1)[:keep]
    idx = [int(i) for i in idx if float(sims[i]) > 0]
    if not idx:
        return []

    # Exact pass: re-score the shortlist against the ORIGINAL float32 vectors.
    # The scan may be float16, but nothing float16 reaches the caller — the
    # scores returned here match a full float32 scan.
    want = [int(rowids[i]) for i in idx]
    placeholders = ",".join("?" * len(want))
    rows = db.execute(
        "SELECT v.rowid AS rid, v.document_id, v.source, v.vector, v.norm, "
        "       v.dim, d.title, d.content_status "
        "FROM embedding_vectors v "
        "LEFT JOIN documents_v2 d ON d.document_id = v.document_id "
        "                        AND d.source = v.source "
        "WHERE v.rowid IN (%s)" % placeholders,
        want,
    ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        dim = int(r["dim"])
        if dim != q32.shape[0]:
            continue
        vec = np.frombuffer(r["vector"][: dim * 4], dtype=np.float32)
        d = float(np.dot(vec, q32))
        denom_i = float(r["norm"] or 0.0) * q_norm
        score = d / denom_i if denom_i > 0 else 0.0
        if score <= 0:
            continue
        out.append({
            "document_id": r["document_id"],
            "source": r["source"],
            "title": r["title"] or "",
            "score": round(score, 6),
            "content_status": r["content_status"] or "unknown",
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    if filters:
        out = _apply_filters(out, filters)
    return out


def _score_vectors_batched(
    db: Any,
    provider_id: str,
    q_vec: list[float],
    q_norm: float,
    *,
    limit: int,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Cosine-score every stored vector for *provider_id*, keeping the best.

    Reads in batches and scores each batch with one numpy matmul instead of a
    Python loop per vector, then resolves document metadata for the surviving
    candidates only — the previous version issued one SELECT per positively
    scoring row, which on a 1.3M-vector corpus meant over a million queries.

    Peak memory is one batch, not the whole matrix: the full corpus would be
    ~2 GB of float32 and cannot be held resident here.
    """
    import numpy as np

    q = np.asarray(q_vec, dtype=np.float32)
    dim = int(q.shape[0])

    # Over-fetch so post-scoring filters still have candidates to work with.
    keep = max(limit * 20, 200)
    best: list[tuple[float, str, str]] = []

    cursor = db.execute(
        "SELECT document_id, source, vector, norm FROM embedding_vectors "
        "WHERE provider_id=? AND dim=?",
        (provider_id, dim),
    )
    while True:
        rows = cursor.fetchmany(_EMBED_SCAN_BATCH)
        if not rows:
            break
        blob = b"".join(r["vector"][: dim * 4] for r in rows)
        mat = np.frombuffer(blob, dtype=np.float32).reshape(len(rows), dim)
        norms = np.asarray([r["norm"] or 0.0 for r in rows], dtype=np.float32)

        dots = mat @ q
        denom = norms * q_norm
        with np.errstate(divide="ignore", invalid="ignore"):
            sims = np.where(denom > 0, dots / denom, 0.0)

        take = min(keep, sims.shape[0])
        idx = np.argpartition(-sims, take - 1)[:take] if take else []
        for i in idx:
            score = float(sims[i])
            if score > 0:
                best.append((score, rows[i]["document_id"], rows[i]["source"]))

        # Trim between batches so `best` cannot grow with corpus size.
        if len(best) > keep * 4:
            best.sort(key=lambda t: t[0], reverse=True)
            del best[keep:]

    best.sort(key=lambda t: t[0], reverse=True)
    del best[keep:]
    if not best:
        return []

    # One metadata round-trip for the survivors, not one per scored vector.
    placeholders = ",".join("?" * len(best))
    meta = {
        (r["document_id"], r["source"]): r
        for r in db.execute(
            "SELECT document_id, source, title, content_status "
            "FROM documents_v2 WHERE document_id IN (%s)" % placeholders,
            [t[1] for t in best],
        )
    }

    out: list[dict[str, Any]] = []
    for score, doc_id, source in best:
        row = meta.get((doc_id, source))
        out.append({
            "document_id": doc_id,
            "source": source,
            "title": row["title"] if row else "",
            "score": round(score, 6),
            "content_status": row["content_status"] if row else "unknown",
        })

    if filters:
        out = _apply_filters(out, filters)
    return out


def embedding_search(
    query: str,
    limit: int = 10,
    provider: str | None = None,
    cache: Cache | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search using dense embeddings with brute-force cosine similarity.

    Args:
        query: Free-text search query.
        limit: Maximum results to return.
        provider: Provider ID (default from config/env).
        cache: Optional Cache instance for DB injection.
        filters: Optional metadata filters applied after scoring.

    Returns:
        Dict with ok, results, total_matches, method, provider, version.
    """
    from .embeddings import get_embedding_provider

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db

        prov = get_embedding_provider(provider)
        if prov is None:
            return build_error(
                "EMBEDDING_BACKEND_UNAVAILABLE",
                "Embedding provider unavailable.",
            )

        # Embed query — use embed_query() if provider supports it (E5 prefix)
        if hasattr(prov, "embed_query"):
            q_vec = prov.embed_query(query)  # type: ignore[union-attr]
        else:
            q_vec = prov.embed_text(query)
        q_norm = math.sqrt(sum(v * v for v in q_vec))

        if q_norm == 0:
            return {
                "ok": True,
                "results": [],
                "total_matches": 0,
                "method": "dense",
                "provider": prov.id,
                "version": EMBEDDING_VERSION,
            }

        # Brute-force scan, but scored in numpy batches rather than per-vector
        # Python arithmetic.  Measured on the real corpus (1,327,036 vectors):
        # the old row-at-a-time loop cost ~951s PER QUERY — 2.5s of pure-Python
        # dot products per 20k vectors, plus one metadata SELECT for every
        # positively-scoring row.  Batching keeps peak memory bounded (the full
        # matrix would be ~2 GB, and this machine has ~1.8 GB free) while
        # collapsing the arithmetic into a single matmul per batch.
        # Fast path: the sidecar matrix, when it matches the database exactly.
        # It returns None (not []) when absent or stale, so a stale index can
        # never masquerade as "no matching decisions".
        method = "dense_mmap"
        warnings: list[str] = []
        scores = _score_vectors_mmap(
            db, Path(c.path), prov.id, q_vec, q_norm,
            limit=limit, filters=filters,
        )
        if scores is None:
            method = "dense_scan"
            status = embedding_matrix_status(prov.id, cache=c)
            if status.get("exists") and not status.get("fresh"):
                warnings.extend(status.get("warnings", []))
            else:
                warnings.append(
                    "Hızlı arama matrisi kurulu değil; her sorgu tüm vektörleri "
                    "veritabanından okuyor (büyük korpusta dakikalar sürer). "
                    "'emsal-mcp semantic build-matrix' ile kurun."
                )
            scores = _score_vectors_batched(
                db, prov.id, q_vec, q_norm, limit=limit, filters=filters,
            )

        result = {
            "ok": True,
            "results": scores[:limit],
            "total_matches": len(scores),
            "method": method,
            "provider": prov.id,
            "version": EMBEDDING_VERSION,
        }
        if warnings:
            result["warnings"] = warnings
        return result
    except Exception as exc:
        return build_error(
            "EMBEDDING_SEARCH_FAILED",
            str(exc),
            results=[],
            total_matches=0,
            method="dense",
            warnings=[str(exc)],
        )
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


def get_embedding_index_status(cache: Cache | None = None) -> dict[str, Any]:
    """Check dense embedding index status.

    Returns per-provider vector counts and dimensions.

    Returns:
        Dict with ok, providers list, version.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        _ensure_embedding_vectors(db)
        rows = db.execute(
            """
            SELECT provider_id, COUNT(*) as cnt, dim FROM embedding_vectors
            GROUP BY provider_id
        """
        ).fetchall()
        return {
            "ok": True,
            "providers": [dict(r) for r in rows],
            "version": EMBEDDING_VERSION,
        }
    except Exception as exc:
        return build_error(
            "EMBEDDING_STATUS_FAILED",
            str(exc),
            providers=[],
        )
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Incremental Index Update (M-26)
# ---------------------------------------------------------------------------


def _table_exists(db: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists in the database."""
    return db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone() is not None


def update_indexes(
    cache: Cache | None = None,
    since: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Incrementally update both TF-IDF and dense indexes.

    Only processes documents that are:
    - New (not in search_vectors/embedding_vectors)
    - Changed (content_hash differs from indexed hash, dense only)

    After incremental update, cleans orphan vectors.

    Args:
        cache: Optional Cache instance for DB injection.
        since: Optional ISO timestamp — only process docs fetched after this time.
        provider: Optional embedding provider for dense index updates.

    Returns:
        Dict with ok, tfidf_updated, dense_updated, skipped, warnings.
    """
    results: dict[str, Any] = {
        "ok": True,
        "tfidf_updated": 0,
        "dense_updated": 0,
        "skipped": 0,
        "warnings": [],
    }

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db

        # Ensure tables exist
        _ensure_fts5(db)
        _ensure_search_vectors(db)

        # --- TF-IDF incremental ---
        # Delegates to _compute_tfidf_vectors, which reuses the SAME frozen
        # IDF snapshot (tfidf_corpus_stats) used by build_semantic_index.
        # Previously this block computed its own ad hoc "existing + new"
        # IDF merge with a formula (log(N/df) + 1.0) that didn't even match
        # the one used elsewhere (log(N/df)) — two inconsistent IDF
        # definitions for the same table. Sharing one implementation means
        # documents indexed via update_indexes() are on the exact same basis
        # as those indexed via build_semantic_index(), regardless of which
        # path wrote them or in how many calls.
        tfidf_updated = _compute_tfidf_vectors(db, limit=0, since=since)
        results["tfidf_updated"] = tfidf_updated
        if tfidf_updated == 0:
            results["skipped"] += db.execute(
                "SELECT COUNT(*) FROM search_vectors"
            ).fetchone()[0]

        # --- Dense incremental ---
        if provider:
            from .embeddings import get_embedding_provider, pack_vector

            prov = get_embedding_provider(provider)
            if prov:
                _ensure_embedding_vectors(db)
                # Find docs not in embedding_vectors, or with different content_hash
                dense_query = """
                    SELECT dv.document_id, dv.source, dv.full_text, dv.markdown, dv.content_hash
                    FROM documents_v2 dv
                    LEFT JOIN embedding_vectors ev
                      ON dv.document_id = ev.document_id
                      AND dv.source = ev.source
                      AND ev.provider_id = ?
                    WHERE ev.document_id IS NULL
                      AND ((dv.full_text IS NOT NULL AND dv.full_text != '')
                        OR (dv.markdown IS NOT NULL AND dv.markdown != ''))
                """
                dense_params: list[Any] = [prov.id]
                if since:
                    dense_query += " AND dv.retrieved_at >= ?"
                    dense_params.append(since)

                new_dense_docs = db.execute(dense_query, dense_params).fetchall()

                for row in new_dense_docs:
                    doc_id = row["document_id"]
                    source = row["source"]
                    content_hash = row["content_hash"]
                    text = row["full_text"] or row["markdown"] or ""
                    vec = prov.embed_text(text)
                    blob = pack_vector(vec)
                    norm_val = math.sqrt(sum(v * v for v in vec))
                    db.execute(
                        """
                        INSERT OR REPLACE INTO embedding_vectors
                        (document_id, source, provider_id, dim, vector, norm, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (doc_id, source, prov.id, prov.dimensions, blob, norm_val, content_hash),
                    )
                    results["dense_updated"] += 1
            else:
                results["warnings"].append(
                    f"Embedding provider '{provider}' unavailable; dense index skipped."
                )

        db.commit()

        # Clean orphans (delegate to existing cleanup method)
        try:
            c.cleanup_orphans()
        except Exception:
            pass

        return results
    except Exception as exc:
        return build_error(
            "INCREMENTAL_INDEX_FAILED",
            str(exc),
            tfidf_updated=0,
            dense_updated=0,
            skipped=0,
            warnings=[str(exc)],
            recommended_next_steps=["Check database permissions and schema."],
        )
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


def get_index_sync_status(cache: Cache | None = None) -> dict[str, Any]:
    """Report how many documents are out of sync with indexes.

    Compares total documents with text content against the number
    of documents indexed in TF-IDF (search_vectors) and dense
    (embedding_vectors) stores.

    Args:
        cache: Optional Cache instance for DB injection.

    Returns:
        Dict with ok, total_documents, tfidf_indexed, dense_indexed,
        tfidf_out_of_sync, dense_out_of_sync.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        total = db.execute(
            "SELECT COUNT(*) FROM documents_v2 "
            "WHERE (full_text IS NOT NULL AND full_text != '') "
            "OR (markdown IS NOT NULL AND markdown != '')"
        ).fetchone()[0]

        in_tfidf = 0
        if _table_exists(db, "search_vectors"):
            in_tfidf = db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]

        in_dense = 0
        if _table_exists(db, "embedding_vectors"):
            in_dense = db.execute(
                "SELECT COUNT(DISTINCT document_id || '|' || source) FROM embedding_vectors"
            ).fetchone()[0]

        return {
            "ok": True,
            "total_documents": total,
            "tfidf_indexed": in_tfidf,
            "dense_indexed": in_dense,
            "tfidf_out_of_sync": max(0, total - in_tfidf),
            "dense_out_of_sync": max(0, total - in_dense),
        }
    except Exception as exc:
        return build_error(
            "INDEX_SYNC_STATUS_FAILED",
            str(exc),
            total_documents=0,
            tfidf_indexed=0,
            dense_indexed=0,
            tfidf_out_of_sync=0,
            dense_out_of_sync=0,
        )
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass
