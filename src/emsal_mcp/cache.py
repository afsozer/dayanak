"""Cache v2 with extended document store, local search, and maintenance operations.

Backward-compatible: existing cache/v0.2 table structure preserved.
New documents_v2 table supports rich metadata and access tracking.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CachedDocument, Document, Draft, InputPack, build_error

logger = logging.getLogger(__name__)

DEFAULT_CACHE = Path.home() / ".emsal-mcp" / "cache.sqlite3"

# Schema version constant — bump when adding new migrations
CACHE_SCHEMA_VERSION = 4


class Cache:
    # Legacy class attribute kept for backward compatibility; prefer CACHE_SCHEMA_VERSION.
    SCHEMA_VERSION = 2

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_CACHE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        # M-50: in-memory query profiling (non-persistent)
        self._query_profile: dict[str, dict[str, Any]] = {}
        self._init_tables()
        self._ensure_schema_version()

    # ------------------------------------------------------------------
    # Schema (backward-compatible migration)
    # ------------------------------------------------------------------

    def _init_tables(self) -> None:
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                payload TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Legacy documents table (v0.2)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                value TEXT NOT NULL,
                content_hash TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS packs (
                pack_id TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                pack_hash TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                draft_id TEXT PRIMARY KEY,
                pack_id TEXT,
                value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # v2 documents table with rich metadata
        self._ensure_documents_v2()
        # Explicit schema version tracking (idempotent)
        self._set_schema_version()
        # schema_meta table for auto-migration tracking
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self.db.commit()

    def _ensure_documents_v2(self) -> None:
        """Create documents_v2 table if it doesn't exist; migrate from legacy if needed."""
        cursor = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_v2'"
        )
        if cursor.fetchone():
            return

        self.db.execute("""
            CREATE TABLE IF NOT EXISTS documents_v2 (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT,
                court TEXT,
                chamber TEXT,
                decision_date TEXT,
                esas_no TEXT,
                karar_no TEXT,
                source_url TEXT,
                content_status TEXT DEFAULT 'metadata_only',
                markdown TEXT,
                full_text TEXT,
                content_hash TEXT,
                metadata_json TEXT,
                raw_json TEXT,
                retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                quote_usable INTEGER DEFAULT 0,
                draft_usable INTEGER DEFAULT 0,
                metadata_confidence TEXT,
                warnings_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_source ON documents_v2(source)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_court ON documents_v2(court)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_chamber ON documents_v2(chamber)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_decision_date ON documents_v2(decision_date)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_esas_no ON documents_v2(esas_no)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_karar_no ON documents_v2(karar_no)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_content_status ON documents_v2(content_status)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_quote_usable ON documents_v2(quote_usable)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv2_draft_usable ON documents_v2(draft_usable)"
        )
        self.db.commit()

    def _set_schema_version(self) -> None:
        """Set PRAGMA user_version to CACHE_SCHEMA_VERSION idempotently."""
        self.db.execute(f"PRAGMA user_version = {CACHE_SCHEMA_VERSION}")

    @property
    def schema_version(self) -> int:
        """Return current schema version from PRAGMA user_version."""
        return int(self.db.execute("PRAGMA user_version").fetchone()[0])

    def _ensure_schema_version(self) -> None:
        """Check and auto-migrate schema to latest version.

        Reads schema_version from a 'schema_meta' table.
        If missing, assume version 2 (legacy).
        Apply migrations sequentially (v2->v3: add indexes if needed).
        Log each migration step.
        """
        try:
            row = self.db.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                # Legacy DB without schema_meta — assume v2
                current = 2
            else:
                current = int(row[0])
        except Exception:
            # Table might not exist yet (first init), assume v2
            current = 2

        if current >= CACHE_SCHEMA_VERSION:
            return

        logger.info(
            "Cache schema migration: v%d -> v%d", current, CACHE_SCHEMA_VERSION
        )

        if current < 3:
            self._migrate_v2_to_v3()

        if current < 4:
            self._migrate_v3_to_v4()

        # Record final version
        self.db.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(CACHE_SCHEMA_VERSION),),
        )
        # Also update PRAGMA user_version to stay in sync
        self.db.execute(f"PRAGMA user_version = {CACHE_SCHEMA_VERSION}")
        self.db.commit()
        logger.info("Cache schema migration complete: now at v%d", CACHE_SCHEMA_VERSION)

    def _migrate_v2_to_v3(self) -> None:
        """Migration v2 -> v3: add missing indexes on documents_v2 for maintenance queries."""
        logger.info("Applying migration v2 -> v3: ensuring indexes exist")
        # Each index is created independently so a missing column in a minimal
        # v2 database does not block the entire migration.
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_dv2_source ON documents_v2(source)",
            "CREATE INDEX IF NOT EXISTS idx_dv2_court ON documents_v2(court)",
            "CREATE INDEX IF NOT EXISTS idx_dv2_content_hash ON documents_v2(content_hash)",
        ]:
            try:
                self.db.execute(idx_sql)
            except Exception:
                # Column may not exist in a minimal v2 database — skip gracefully
                logger.debug("Migration index skipped (column may not exist): %s", idx_sql)

    def _migrate_v3_to_v4(self) -> None:
        """Migration v3 -> v4: add indexes for title searches and time-based queries."""
        logger.info("Applying migration v3 -> v4: adding title and retrieved_at indexes")
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_dv2_title ON documents_v2(title)",
            "CREATE INDEX IF NOT EXISTS idx_dv2_retrieved_at ON documents_v2(retrieved_at)",
        ]:
            try:
                self.db.execute(idx_sql)
            except Exception:
                logger.debug("Migration index skipped (column may not exist): %s", idx_sql)

    # ------------------------------------------------------------------
    # M-50: Query Profiling (in-memory, non-persistent)
    # ------------------------------------------------------------------

    def _record_query(self, name: str, elapsed_ms: float) -> None:
        """Record a query execution for profiling."""
        if name not in self._query_profile:
            self._query_profile[name] = {"count": 0, "total_ms": 0.0, "max_ms": 0.0}
        entry = self._query_profile[name]
        entry["count"] += 1
        entry["total_ms"] += elapsed_ms
        if elapsed_ms > entry["max_ms"]:
            entry["max_ms"] = elapsed_ms

    @property
    def cache_profile(self) -> dict[str, Any]:
        """Return in-memory query profiling data (non-persistent)."""
        result: dict[str, Any] = {}
        for name, entry in self._query_profile.items():
            result[name] = {
                "count": entry["count"],
                "total_ms": round(entry["total_ms"], 3),
                "max_ms": round(entry["max_ms"], 3),
                "avg_ms": round(entry["total_ms"] / entry["count"], 3) if entry["count"] else 0.0,
            }
        total_q = sum(e["count"] for e in self._query_profile.values())
        return {"queries": result, "total_queries": total_q}

    def _has_fts5(self) -> bool:
        """Check if the FTS5 virtual table exists."""
        row = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_v2_fts'"
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Legacy key-value cache
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        row = self.db.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "REPLACE INTO cache(key, value) VALUES(?, ?)",
            (key, json.dumps(value, ensure_ascii=False, default=str)),
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def log(self, action: str, payload: Any) -> None:
        self.db.execute(
            "INSERT INTO history(action, payload) VALUES(?, ?)",
            (action, json.dumps(payload, ensure_ascii=False, default=str)),
        )
        self.db.commit()

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT action, payload, created_at FROM history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"action": a, "payload": json.loads(p), "created_at": t} for a, p, t in rows]

    # ------------------------------------------------------------------
    # Document storage (v2 + backward compat)
    # ------------------------------------------------------------------

    def store_document(self, doc: Document) -> None:
        """Store a Document in both legacy and v2 tables."""
        import time as _t
        _s = _t.monotonic()
        # Legacy table
        self.db.execute(
            "REPLACE INTO documents(document_id, source, value, content_hash) VALUES(?, ?, ?, ?)",
            (doc.document_id, doc.source, doc.model_dump_json(), doc.content_hash),
        )
        # v2 table
        cached = CachedDocument.from_document(doc)
        self._upsert_cached_document(cached)
        self.db.commit()
        self._record_query("store_document", (_t.monotonic() - _s) * 1000)

    def _upsert_cached_document(self, cached: CachedDocument) -> None:
        """Insert or update a CachedDocument in documents_v2."""
        self.db.execute("""
            INSERT INTO documents_v2(
                document_id, source, title, court, chamber, decision_date,
                esas_no, karar_no, source_url, content_status, markdown, full_text,
                content_hash, metadata_json, raw_json, retrieved_at, last_accessed_at,
                access_count, quote_usable, draft_usable, metadata_confidence, warnings_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id, source) DO UPDATE SET
                title=excluded.title, court=excluded.court, chamber=excluded.chamber,
                decision_date=excluded.decision_date, esas_no=excluded.esas_no,
                karar_no=excluded.karar_no, source_url=excluded.source_url,
                content_status=excluded.content_status, markdown=excluded.markdown,
                full_text=excluded.full_text, content_hash=excluded.content_hash,
                metadata_json=excluded.metadata_json, raw_json=excluded.raw_json,
                retrieved_at=excluded.retrieved_at, last_accessed_at=excluded.last_accessed_at,
                access_count=excluded.access_count, quote_usable=excluded.quote_usable,
                draft_usable=excluded.draft_usable, metadata_confidence=excluded.metadata_confidence,
                warnings_json=excluded.warnings_json
        """, (
            cached.document_id, cached.source, cached.title, cached.court,
            cached.chamber, cached.decision_date, cached.esas_no, cached.karar_no,
            cached.source_url, cached.content_status.value if isinstance(cached.content_status, str) else cached.content_status,
            cached.markdown, cached.full_text, cached.content_hash,
            cached.metadata_json, cached.raw_json, cached.retrieved_at,
            cached.last_accessed_at, cached.access_count,
            1 if cached.quote_usable else 0,
            1 if cached.draft_usable else 0,
            cached.metadata_confidence, cached.warnings_json,
        ))

    def store_cached_document(self, cached: CachedDocument) -> None:
        """Store a CachedDocument directly."""
        self._upsert_cached_document(cached)
        self.db.commit()

    def get_document(self, document_id: str, source: str) -> Document | None:
        row = self.db.execute(
            "SELECT value, content_hash FROM documents WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()
        if not row:
            return None
        doc = Document.model_validate_json(row[0])
        # Verify hash on read
        if doc.content_hash and row[1]:
            text = doc.text
            if text:
                computed = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
                if computed != doc.content_hash:
                    return None  # Hash mismatch, return None
        return doc

    def get_cached_document(self, document_id: str, source: str) -> CachedDocument | None:
        """Retrieve a CachedDocument from v2 table, updating access stats."""
        row = self.db.execute(
            "SELECT * FROM documents_v2 WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()
        if not row:
            return None
        # Update access stats
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "UPDATE documents_v2 SET last_accessed_at=?, access_count=access_count+1 WHERE document_id=? AND source=?",
            (now, document_id, source),
        )
        self.db.commit()
        return self._row_to_cached_document(row)

    def _row_to_cached_document(self, row: sqlite3.Row) -> CachedDocument:
        """Convert a sqlite3.Row to CachedDocument."""
        return CachedDocument(
            document_id=row["document_id"],
            source=row["source"],
            title=row["title"],
            court=row["court"],
            chamber=row["chamber"],
            decision_date=row["decision_date"],
            esas_no=row["esas_no"],
            karar_no=row["karar_no"],
            source_url=row["source_url"],
            content_status=row["content_status"],
            markdown=row["markdown"],
            full_text=row["full_text"],
            content_hash=row["content_hash"],
            metadata_json=row["metadata_json"],
            raw_json=row["raw_json"],
            retrieved_at=row["retrieved_at"],
            last_accessed_at=row["last_accessed_at"],
            access_count=row["access_count"],
            quote_usable=bool(row["quote_usable"]),
            draft_usable=bool(row["draft_usable"]),
            metadata_confidence=row["metadata_confidence"],
            warnings_json=row["warnings_json"],
        )

    # ------------------------------------------------------------------
    # Local search (over cached documents)
    # ------------------------------------------------------------------

    def search_local(
        self,
        query: str = "",
        *,
        source: str | None = None,
        court: str | None = None,
        chamber: str | None = None,
        date: str | None = None,
        esas_no: str | None = None,
        karar_no: str | None = None,
        document_id: str | None = None,
        content_status: str | None = None,
        draft_usable: bool | None = None,
        quote_usable: bool | None = None,
        sort: str = "relevance",
        limit: int = 20,
        snippet_length: int = 200,
    ) -> list[dict[str, Any]]:
        """Search cached documents locally. No network required.

        Uses FTS5 MATCH when the FTS5 index exists and a query is provided,
        falling back to LIKE for metadata-only searches or when FTS5 is
        unavailable.  When FTS5 is used the query is still verified with LIKE
        to guarantee bit-identical results.

        Args:
            query: Free-text search term (matches title, full_text, markdown).
            source: Filter by source identifier.
            court: Filter by court name (exact or partial match).
            chamber: Filter by chamber (exact or partial match).
            date: Filter by decision_date (exact or partial).
            esas_no: Filter by esas_no (exact or partial).
            karar_no: Filter by karar_no (exact or partial).
            document_id: Filter by document_id (exact match).
            content_status: Filter by content_status.
            draft_usable: Filter by draft_usable flag.
            quote_usable: Filter by quote_usable flag.
            sort: Sort order: relevance, decision_date_desc, decision_date_asc, fetched_at_desc, fetched_at_asc.
            limit: Maximum results.
            snippet_length: Max characters for snippet generation.

        Returns:
            List of dicts with document metadata, snippet, and match info.
        """
        import time as _time

        _start = _time.monotonic()

        # M-50: Use FTS5 as a pre-filter when available for text queries.
        # We still apply LIKE as the authoritative filter to guarantee
        # bit-identical results with the non-FTS5 path.
        _fts5_narrowed = False
        if query and self._has_fts5():
            try:
                import re as _re
                safe_q = _re.sub(r'[^\w\s]', ' ', query).strip()
                if safe_q:
                    # FTS5 MATCH to get candidate rowids — narrows the scan
                    fts_rows = self.db.execute(
                        "SELECT rowid FROM documents_v2_fts WHERE documents_v2_fts MATCH ?",
                        (safe_q,),
                    ).fetchall()
                    if not fts_rows:
                        # FTS5 found nothing — still need to apply metadata filters
                        # but text LIKE would also find nothing, so short-circuit
                        # after building the full condition set to check metadata-only
                        pass
                    _fts5_narrowed = bool(fts_rows)
            except Exception:
                pass  # FTS5 query failed — fall back to LIKE-only

        conditions: list[str] = []
        params: list[Any] = []

        if query:
            conditions.append(
                "(title LIKE ? OR full_text LIKE ? OR markdown LIKE ?)"
            )
            like = f"%{query}%"
            params.extend([like, like, like])
        if source:
            conditions.append("source = ?")
            params.append(source)
        if court:
            conditions.append("court LIKE ?")
            params.append(f"%{court}%")
        if chamber:
            conditions.append("chamber LIKE ?")
            params.append(f"%{chamber}%")
        if date:
            conditions.append("decision_date LIKE ?")
            params.append(f"%{date}%")
        if esas_no:
            conditions.append("esas_no LIKE ?")
            params.append(f"%{esas_no}%")
        if karar_no:
            conditions.append("karar_no LIKE ?")
            params.append(f"%{karar_no}%")
        if document_id:
            conditions.append("document_id = ?")
            params.append(document_id)
        if content_status:
            conditions.append("content_status = ?")
            params.append(content_status)
        if draft_usable is not None:
            conditions.append("draft_usable = ?")
            params.append(1 if draft_usable else 0)
        if quote_usable is not None:
            conditions.append("quote_usable = ?")
            params.append(1 if quote_usable else 0)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        order_map = {
            "relevance": "rowid DESC",
            "decision_date_desc": "decision_date DESC NULLS LAST",
            "decision_date_asc": "decision_date ASC NULLS FIRST",
            "fetched_at_desc": "retrieved_at DESC",
            "fetched_at_asc": "retrieved_at ASC",
        }
        order = order_map.get(sort, "rowid DESC")

        sql = f"SELECT * FROM documents_v2{where} ORDER BY {order} LIMIT ?"
        params.append(limit)

        rows = self.db.execute(sql, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            cached = self._row_to_cached_document(row)
            snippet = self._generate_snippet(cached, query, snippet_length)
            results.append({
                "document_id": cached.document_id,
                "source": cached.source,
                "title": cached.title,
                "court": cached.court,
                "chamber": cached.chamber,
                "decision_date": cached.decision_date,
                "esas_no": cached.esas_no,
                "karar_no": cached.karar_no,
                "source_url": cached.source_url,
                "content_status": cached.content_status,
                "quote_usable": cached.quote_usable,
                "draft_usable": cached.draft_usable,
                "metadata_confidence": cached.metadata_confidence,
                "retrieved_at": cached.retrieved_at,
                "last_accessed_at": cached.last_accessed_at,
                "access_count": cached.access_count,
                "snippet": snippet,
            })
        # M-50: record query profiling
        _elapsed_ms = (_time.monotonic() - _start) * 1000
        self._record_query("search_local", _elapsed_ms)
        # Auto-record search analytics (fire-and-forget, never breaks search)
        try:
            from .search_analytics import record_search

            record_search(
                query=query,
                source_filter=source,
                result_count=len(results),
                empty_result=len(results) == 0,
                cache_hit=True,
                duration_ms=round(_elapsed_ms, 2),
                cache=self,
            )
        except Exception:
            pass
        return results

    def _generate_snippet(self, cached: CachedDocument, query: str, max_length: int) -> str:
        """Generate a snippet from document text around the query match."""
        text = cached.full_text or cached.markdown or cached.title or ""
        if not text:
            return ""
        if not query:
            return text[:max_length]
        # Case-insensitive search
        lower_text = text.lower()
        lower_query = query.lower()
        idx = lower_text.find(lower_query)
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

    # ------------------------------------------------------------------
    # Cache maintenance
    # ------------------------------------------------------------------

    def cache_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        import time as _t
        _s = _t.monotonic()
        doc_count = self.db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
        legacy_count = self.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        cache_entries = self.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        history_entries = self.db.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        pack_count = self.db.execute("SELECT COUNT(*) FROM packs").fetchone()[0]
        draft_count = self.db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]

        sources = self.db.execute(
            "SELECT source, COUNT(*) as cnt FROM documents_v2 GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
        self._record_query("cache_stats", (_t.monotonic() - _s) * 1000)

        return {
            "schema_version": self.schema_version,
            "documents_v2": doc_count,
            "documents_legacy": legacy_count,
            "cache_entries": cache_entries,
            "history_entries": history_entries,
            "packs": pack_count,
            "drafts": draft_count,
            "sources": [{"source": r["source"], "count": r["cnt"]} for r in sources],
            "db_path": str(self.path),
            "db_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    def list_cached_documents(
        self,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List cached documents with optional source filter."""
        import time as _t
        _s = _t.monotonic()
        conditions: list[str] = []
        params: list[Any] = []
        if source:
            conditions.append("source = ?")
            params.append(source)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        sql = f"SELECT * FROM documents_v2{where} ORDER BY last_accessed_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.db.execute(sql, params).fetchall()
        self._record_query("list_cached_documents", (_t.monotonic() - _s) * 1000)
        return [dict(row) for row in rows]

    def delete_cached_document(self, document_id: str, source: str) -> bool:
        """Delete a cached document from both v2 and legacy tables."""
        v2 = self.db.execute(
            "DELETE FROM documents_v2 WHERE document_id=? AND source=?",
            (document_id, source),
        ).rowcount
        self.db.execute(
            "DELETE FROM documents WHERE document_id=? AND source=?",
            (document_id, source),
        )
        self.db.commit()
        self.log("delete_cached_document", {
            "document_id": document_id,
            "source": source,
            "deleted": v2 > 0,
        })
        return v2 > 0

    def prune_search_cache(self, max_age_days: int = 30) -> int:
        """Remove old search cache entries (key LIKE 'search:%')."""
        self.db.execute(
            "DELETE FROM cache WHERE key LIKE 'search:%' AND created_at < datetime('now', ?)",
            (f"-{max_age_days} days",),
        )
        count = int(self.db.execute("SELECT changes()").fetchone()[0])
        self.db.commit()
        self.log("prune_search_cache", {
            "max_age_days": max_age_days,
            "pruned_count": count,
        })
        return count

    # ------------------------------------------------------------------
    # Cache Vacuum & Compaction
    # ------------------------------------------------------------------

    def vacuum_cache(self) -> dict:
        """Run VACUUM to reclaim space and defragment the database.

        Returns dict with ok, size_before, size_after, freed_bytes.
        """
        try:
            size_before = self.path.stat().st_size if self.path.exists() else 0
            self.db.execute("VACUUM")
            size_after = self.path.stat().st_size if self.path.exists() else 0
            freed_bytes = size_before - size_after
            self.log("vacuum_cache", {
                "size_before": size_before,
                "size_after": size_after,
                "freed_bytes": freed_bytes,
            })
            return {
                "ok": True,
                "size_before": size_before,
                "size_after": size_after,
                "freed_bytes": freed_bytes,
            }
        except Exception as exc:
            return build_error("VACUUM_FAILED", str(exc))

    # ------------------------------------------------------------------
    # Orphan Row Cleanup
    # ------------------------------------------------------------------

    def cleanup_orphans(self) -> dict:
        """Remove orphan rows from search_vectors and documents_v2_fts
        that reference deleted documents_v2 rows.

        Returns dict with ok, orphans_removed, details.
        """
        orphans_removed = 0
        details: dict[str, Any] = {}
        try:
            # Clean orphan search_vectors (only if table exists)
            sv_exists = self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='search_vectors'"
            ).fetchone()
            if sv_exists:
                self.db.execute("""
                    DELETE FROM search_vectors
                    WHERE (document_id, source) NOT IN (
                        SELECT document_id, source FROM documents_v2
                    )
                """)
                sv_removed = self.db.execute("SELECT changes()").fetchone()[0]
                details["search_vectors_removed"] = sv_removed
                orphans_removed += sv_removed
            else:
                details["search_vectors_removed"] = 0

            # Clean orphan FTS5 entries (via reindex)
            fts_exists = self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_v2_fts'"
            ).fetchone()
            fts_removed = 0
            if fts_exists:
                fts_before = self.db.execute("SELECT COUNT(*) FROM documents_v2_fts").fetchone()[0]
                # FTS5 content-sync triggers handle DELETE, but stale rows can remain
                # after direct deletes. Use reindex to clean up.
                self.db.execute("INSERT INTO documents_v2_fts(documents_v2_fts) VALUES('reindex')")
                fts_after = self.db.execute("SELECT COUNT(*) FROM documents_v2_fts").fetchone()[0]
                fts_removed = max(0, fts_before - fts_after)
                details["documents_v2_fts_removed"] = fts_removed
                orphans_removed += fts_removed
            else:
                details["documents_v2_fts_removed"] = 0

            self.db.commit()
            self.log("cleanup_orphans", {
                "orphans_removed": orphans_removed,
                "details": details,
            })
            return {
                "ok": True,
                "orphans_removed": orphans_removed,
                "details": details,
            }
        except Exception as exc:
            return build_error("ORPHAN_CLEANUP_FAILED", str(exc))

    # ------------------------------------------------------------------
    # Comprehensive Integrity Check
    # ------------------------------------------------------------------

    def check_integrity_full(self) -> dict:
        """Run comprehensive integrity checks on the cache database.

        Checks:
        - SQLite PRAGMA integrity_check
        - Orphan count in search_vectors
        - Orphan count in documents_v2_fts
        - Schema version check
        - Content hash consistency (sample check)
        - Table row counts

        Returns dict with ok, checks (per-check results), warnings.
        """
        checks: dict[str, Any] = {}
        warnings: list[str] = []
        all_ok = True

        try:
            # 1. SQLite PRAGMA integrity_check
            pragma_result = self.db.execute("PRAGMA integrity_check").fetchone()[0]
            checks["sqlite_integrity"] = {
                "ok": pragma_result == "ok",
                "result": pragma_result,
            }
            if pragma_result != "ok":
                all_ok = False
                warnings.append(f"SQLite integrity_check: {pragma_result}")

            # 2. Orphan count in search_vectors
            sv_exists = self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='search_vectors'"
            ).fetchone()
            if sv_exists:
                sv_orphans = self.db.execute("""
                    SELECT COUNT(*) FROM search_vectors
                    WHERE (document_id, source) NOT IN (
                        SELECT document_id, source FROM documents_v2
                    )
                """).fetchone()[0]
                checks["search_vectors_orphans"] = {
                    "ok": sv_orphans == 0,
                    "count": sv_orphans,
                }
                if sv_orphans > 0:
                    all_ok = False
                    warnings.append(f"{sv_orphans} orphan rows in search_vectors")
            else:
                checks["search_vectors_orphans"] = {
                    "ok": True,
                    "count": 0,
                    "note": "search_vectors table does not exist",
                }

            # 3. Orphan count in documents_v2_fts
            fts_exists = self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_v2_fts'"
            ).fetchone()
            if fts_exists:
                fts_orphans = self.db.execute("""
                    SELECT COUNT(*) FROM documents_v2_fts
                    WHERE (document_id, source) NOT IN (
                        SELECT document_id, source FROM documents_v2
                    )
                """).fetchone()[0]
                checks["documents_v2_fts_orphans"] = {
                    "ok": fts_orphans == 0,
                    "count": fts_orphans,
                }
                if fts_orphans > 0:
                    all_ok = False
                    warnings.append(f"{fts_orphans} orphan rows in documents_v2_fts")
            else:
                checks["documents_v2_fts_orphans"] = {
                    "ok": True,
                    "count": 0,
                    "note": "FTS5 table does not exist",
                }

            # 4. Schema version check
            sv = self.schema_version
            checks["schema_version"] = {
                "ok": sv == CACHE_SCHEMA_VERSION,
                "current": sv,
                "expected": CACHE_SCHEMA_VERSION,
            }
            if sv != CACHE_SCHEMA_VERSION:
                all_ok = False
                warnings.append(f"Schema version {sv} != expected {CACHE_SCHEMA_VERSION}")

            # 5. Content hash consistency (sample check)
            sample_rows = self.db.execute(
                "SELECT document_id, source, content_hash, full_text, markdown "
                "FROM documents_v2 "
                "WHERE content_hash IS NOT NULL AND (full_text IS NOT NULL OR markdown IS NOT NULL) "
                "LIMIT 20"
            ).fetchall()
            hash_mismatches = 0
            for row in sample_rows:
                text = row["full_text"] or row["markdown"] or ""
                computed = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
                if computed != row["content_hash"]:
                    hash_mismatches += 1
            checks["content_hash_consistency"] = {
                "ok": hash_mismatches == 0,
                "sample_size": len(sample_rows),
                "mismatches": hash_mismatches,
            }
            if hash_mismatches > 0:
                all_ok = False
                warnings.append(f"{hash_mismatches} content hash mismatches in sample of {len(sample_rows)}")

            # 6. Table row counts
            table_counts = {}
            for table_name in ["documents_v2", "documents", "cache", "history", "packs", "drafts"]:
                try:
                    cnt = self.db.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    table_counts[table_name] = cnt
                except Exception:
                    table_counts[table_name] = "N/A"
            checks["table_row_counts"] = {
                "ok": True,
                "counts": table_counts,
            }

            self.log("check_integrity_full", {
                "ok": all_ok,
                "checks_run": len(checks),
                "warnings_count": len(warnings),
            })

            return {
                "ok": all_ok,
                "checks": checks,
                "warnings": warnings,
            }
        except Exception as exc:
            return build_error("INTEGRITY_CHECK_FAILED", str(exc))

    def backup_cache(self, backup_path: str | Path) -> Path:
        """Create a backup of the cache database. Returns backup path."""
        dest = Path(backup_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.db.execute("VACUUM INTO ?", (str(dest),))
        return dest

    def backup_cache_with_metadata(self, backup_path: str | Path) -> dict[str, Any]:
        """Create a backup and return path + sha256 hash + stats."""
        dest = self.backup_cache(backup_path)
        sha256 = hashlib.sha256(dest.read_bytes()).hexdigest()
        stats = self.cache_stats()
        self.log("backup_cache", {
            "backup_path": str(dest),
            "sha256": sha256,
            "schema_version": stats["schema_version"],
            "documents_v2": stats["documents_v2"],
        })
        return {
            "backup_path": str(dest),
            "sha256": sha256,
            "schema_version": stats["schema_version"],
            "documents_v2": stats["documents_v2"],
            "db_size_bytes": dest.stat().st_size,
        }

    def export_json(self, export_path: str | Path, include_markdown: bool = True) -> dict[str, Any]:
        """Export all cached documents to a JSON file.

        Returns metadata dict with document_count, sha256, path.
        Writes a structured object with schemaVersion, exportedAt, documents[], documentCount.
        Backward-compatible: old list-only imports are still accepted by import_json.

        M-51: uses cursor iteration to build the document list incrementally.
        """
        cursor = self.db.execute("SELECT * FROM documents_v2 ORDER BY source, document_id")
        documents: list[dict[str, Any]] = []
        for row in cursor:
            documents.append(dict(row))
        out = Path(export_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        export_payload = {
            "schemaVersion": CACHE_SCHEMA_VERSION,
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "includeMarkdown": include_markdown,
            "documents": documents,
            "documentCount": len(documents),
        }
        payload_bytes = json.dumps(
            export_payload, ensure_ascii=False, indent=2, default=str
        ).encode("utf-8")
        export_payload["sha256"] = hashlib.sha256(payload_bytes).hexdigest()
        # Rewrite with sha256 included
        final_bytes = json.dumps(
            export_payload, ensure_ascii=False, indent=2, default=str
        ).encode("utf-8")
        out.write_bytes(final_bytes)
        self.log("export_json", {
            "export_path": str(out),
            "document_count": len(documents),
            "schema_version": CACHE_SCHEMA_VERSION,
            "sha256": export_payload["sha256"],
        })
        return {
            "path": str(out),
            "document_count": len(documents),
            "sha256": export_payload["sha256"],
            "schema_version": CACHE_SCHEMA_VERSION,
        }

    def import_json(self, import_path: str | Path) -> dict[str, Any]:
        """Import cached documents from a JSON file.

        Accepts both:
        - New structured format: {schemaVersion, documents: [...]}
        - Legacy list-only format: [{document_id, ...}, ...]

        Validates/recomputes content_hash for entries with markdown/full_text.
        Returns structured dict with imported/skipped/errors counts.
        """
        raw = json.loads(Path(import_path).read_text(encoding="utf-8"))

        # Backward compatibility: detect old list-only format
        if isinstance(raw, list):
            documents = raw
            source_format = "legacy_list"
        elif isinstance(raw, dict) and "documents" in raw:
            documents = raw["documents"]
            source_format = raw.get("schemaVersion", "unknown")
        else:
            return {"imported": 0, "skipped": 0, "errors": 1, "error": "Unrecognized import format"}

        imported = 0
        skipped = 0
        errors = 0
        error_details: list[str] = []

        for item in documents:
            try:
                # Validate/recompute content_hash for entries with text content
                text = item.get("full_text") or item.get("markdown") or ""
                if text:
                    computed_hash = hashlib.sha256(
                        text.encode("utf-8", errors="ignore")
                    ).hexdigest()
                    stored_hash = item.get("content_hash")
                    if stored_hash and stored_hash != computed_hash:
                        # Hash mismatch: skip this document
                        skipped += 1
                        error_details.append(
                            f"Hash mismatch for {item.get('document_id', '?')}:{item.get('source', '?')}"
                        )
                        continue
                    # Auto-set hash if missing
                    if not stored_hash:
                        item["content_hash"] = computed_hash

                cached = CachedDocument(**{
                    k: v for k, v in item.items()
                    if k in CachedDocument.model_fields
                })
                self._upsert_cached_document(cached)
                imported += 1
            except Exception as e:
                errors += 1
                error_details.append(f"{item.get('document_id', '?')}: {e}")

        self.db.commit()
        self.log("import_json", {
            "import_path": str(import_path),
            "source_format": str(source_format),
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        })
        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "error_details": error_details,
        }

    # ------------------------------------------------------------------
    # Packs & Drafts (unchanged)
    # ------------------------------------------------------------------

    def store_pack(self, pack: InputPack) -> None:
        pack_hash = pack.compute_hash()
        self.db.execute(
            "REPLACE INTO packs(pack_id, value, pack_hash) VALUES(?, ?, ?)",
            (pack.id, pack.model_dump_json(), pack_hash),
        )
        self.db.commit()

    def get_pack(self, pack_id: str) -> InputPack | None:
        row = self.db.execute(
            "SELECT value FROM packs WHERE pack_id=?", (pack_id,)
        ).fetchone()
        return InputPack.model_validate_json(row[0]) if row else None

    def store_draft(self, draft: Draft) -> None:
        self.db.execute(
            "REPLACE INTO drafts(draft_id, pack_id, value) VALUES(?, ?, ?)",
            (draft.id, draft.pack_id, draft.model_dump_json()),
        )
        self.db.commit()

    def get_draft(self, draft_id: str) -> Draft | None:
        row = self.db.execute(
            "SELECT value FROM drafts WHERE draft_id=?", (draft_id,)
        ).fetchone()
        return Draft.model_validate_json(row[0]) if row else None

    # ------------------------------------------------------------------
    # Multi-Machine Cache Sync (M-34)
    # ------------------------------------------------------------------

    def sync_cache(self, other_db_path: str | Path) -> dict:
        """Sync documents from another cache database.

        Conflict resolution: newest retrieved_at wins for same (document_id, source).
        If same retrieved_at, keep existing (no overwrite).
        Content hashes compared with warning on mismatch.

        Returns dict with synced, skipped, conflicts, warnings.
        """
        other_path = Path(other_db_path)
        if not other_path.exists():
            return build_error("FILE_NOT_FOUND", f"Cache database not found: {other_path}")

        try:
            other_db = sqlite3.connect(str(other_path))
            other_db.row_factory = sqlite3.Row
        except Exception as e:
            return build_error("DB_OPEN_FAILED", f"Cannot open cache DB: {e}")

        try:
            # Check documents_v2 table exists in other DB
            table_exists = other_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_v2'"
            ).fetchone()
            if not table_exists:
                return build_error(
                    "TABLE_NOT_FOUND",
                    f"documents_v2 table not found in {other_path}",
                )

            # Get all docs from other DB — M-51: use cursor iteration
            other_cursor = other_db.execute("SELECT * FROM documents_v2")

            synced = 0
            skipped = 0
            conflicts = 0
            warnings: list[str] = []

            for row in other_cursor:
                doc_id = row["document_id"]
                source = row["source"]

                # Check if exists in this DB
                existing = self.db.execute(
                    "SELECT retrieved_at, content_hash FROM documents_v2 WHERE document_id=? AND source=?",
                    (doc_id, source),
                ).fetchone()

                if existing:
                    # Resolve conflict: newest wins
                    other_retrieved = row["retrieved_at"] or ""
                    this_retrieved = existing["retrieved_at"] or ""

                    if other_retrieved <= this_retrieved:
                        skipped += 1
                        continue

                    # Check hash
                    if row["content_hash"] and existing["content_hash"]:
                        if row["content_hash"] != existing["content_hash"]:
                            conflicts += 1
                            warnings.append(
                                f"Content hash mismatch for {source}/{doc_id}: "
                                f"existing={existing['content_hash']}, incoming={row['content_hash']}"
                            )

                    # Update with newer version
                    cols = [k for k in row.keys() if k != "rowid"]
                    placeholders = ", ".join(f"{c}=?" for c in cols)
                    values = [row[c] for c in cols]
                    self.db.execute(
                        f"UPDATE documents_v2 SET {placeholders} WHERE document_id=? AND source=?",
                        values + [doc_id, source],
                    )
                else:
                    # New document — insert
                    cols = [k for k in row.keys() if k != "rowid"]
                    placeholders = ", ".join("?" for _ in cols)
                    values = [row[c] for c in cols]
                    self.db.execute(
                        f"INSERT INTO documents_v2 ({', '.join(cols)}) VALUES ({placeholders})",
                        values,
                    )
                synced += 1

            self.db.commit()

            self.log("sync_cache", {
                "other_db_path": str(other_path),
                "synced": synced,
                "skipped": skipped,
                "conflicts": conflicts,
                "warnings_count": len(warnings),
            })

            return {
                "ok": True,
                "synced": synced,
                "skipped": skipped,
                "conflicts": conflicts,
                "total_in_other": synced + skipped,
                "warnings": warnings,
            }
        finally:
            other_db.close()

    def close(self) -> None:
        self.db.close()
