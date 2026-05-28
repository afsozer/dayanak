"""Cache v2 with extended document store, local search, and maintenance operations.

Backward-compatible: existing cache/v0.2 table structure preserved.
New documents_v2 table supports rich metadata and access tracking.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CachedDocument, Document, Draft, InputPack


DEFAULT_CACHE = Path.home() / ".emsal-mcp" / "cache.sqlite3"


class Cache:
    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_CACHE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

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
        # Legacy table
        self.db.execute(
            "REPLACE INTO documents(document_id, source, value, content_hash) VALUES(?, ?, ?, ?)",
            (doc.document_id, doc.source, doc.model_dump_json(), doc.content_hash),
        )
        # v2 table
        cached = CachedDocument.from_document(doc)
        self._upsert_cached_document(cached)
        self.db.commit()

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
        doc_count = self.db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
        legacy_count = self.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        cache_entries = self.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        history_entries = self.db.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        pack_count = self.db.execute("SELECT COUNT(*) FROM packs").fetchone()[0]
        draft_count = self.db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]

        sources = self.db.execute(
            "SELECT source, COUNT(*) as cnt FROM documents_v2 GROUP BY source ORDER BY cnt DESC"
        ).fetchall()

        return {
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
        conditions: list[str] = []
        params: list[Any] = []
        if source:
            conditions.append("source = ?")
            params.append(source)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        sql = f"SELECT * FROM documents_v2{where} ORDER BY last_accessed_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.db.execute(sql, params).fetchall()
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
        return v2 > 0

    def prune_search_cache(self, max_age_days: int = 30) -> int:
        """Remove old search cache entries (key LIKE 'search:%')."""
        self.db.execute(
            "DELETE FROM cache WHERE key LIKE 'search:%' AND created_at < datetime('now', ?)",
            (f"-{max_age_days} days",),
        )
        count = self.db.execute("SELECT changes()").fetchone()[0]
        self.db.commit()
        return count

    def backup_cache(self, backup_path: str | Path) -> Path:
        """Create a backup of the cache database."""
        dest = Path(backup_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.db.execute("VACUUM INTO ?", (str(dest),))
        return dest

    def export_json(self, export_path: str | Path) -> Path:
        """Export all cached documents to a JSON file."""
        rows = self.db.execute("SELECT * FROM documents_v2 ORDER BY source, document_id").fetchall()
        documents = [dict(row) for row in rows]
        out = Path(export_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(documents, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return out

    def import_json(self, import_path: str | Path) -> int:
        """Import cached documents from a JSON file. Returns count imported."""
        data = json.loads(Path(import_path).read_text(encoding="utf-8"))
        count = 0
        for item in data:
            cached = CachedDocument(**{
                k: v for k, v in item.items()
                if k in CachedDocument.model_fields
            })
            self._upsert_cached_document(cached)
            count += 1
        self.db.commit()
        return count

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

    def close(self) -> None:
        self.db.close()
