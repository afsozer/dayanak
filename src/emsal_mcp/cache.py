from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import Document, Draft, InputPack


DEFAULT_CACHE = Path.home() / ".emsal-mcp" / "cache.sqlite3"


class Cache:
    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_CACHE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

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
        self.db.commit()

    def get(self, key: str) -> Any | None:
        row = self.db.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "REPLACE INTO cache(key, value) VALUES(?, ?)",
            (key, json.dumps(value, ensure_ascii=False, default=str)),
        )
        self.db.commit()

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

    def store_document(self, doc: Document) -> None:
        self.db.execute(
            "REPLACE INTO documents(document_id, source, value, content_hash) VALUES(?, ?, ?, ?)",
            (doc.document_id, doc.source, doc.model_dump_json(), doc.content_hash),
        )
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
