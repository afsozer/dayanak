"""Import the offline UYAP Mevzuat (2020) içtihat archive into the emsal-mcp cache.

Source: the unencrypted SQLite DB shipped inside UYAPMevzuat_Setup.msi (table
``ictihat``, ~46.7k full-text decisions: Yargıtay, Danıştay, Uyuşmazlık, AYM, AİHM).

Writes lean rows directly into ``documents_v2`` (FTS auto-syncs via triggers) —
NO legacy ``documents`` table, NO raw_json, NO markdown duplicate — under a
distinct source id so it never collides with the live crawl corpus.

Usage:
    python scripts/import_uyap_archive.py --src "<arsiv-yolu>/uyap_mevzuat_2020.sqlite" --dry-run
    python scripts/import_uyap_archive.py --src "...uyap_mevzuat_2020.sqlite"   # real import
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SOURCE_ID = "uyap_arsiv"
DEFAULT_CACHE = str(Path.home() / ".emsal-mcp" / "cache.sqlite3")

# dokumanTuru.id -> human label (içtihat category only; mevzuat types excluded)
TYPE_LABEL = {
    0: "Yargıtay Kararı",
    1: "Danıştay Kararı",
    2: "Anayasa Mahkemesi Kararı",
    3: "Avrupa İnsan Hakları Mahkemesi Kararı",
    4: "Uyuşmazlık Mahkemesi Kararı",
    33: "Diğer İçtihat",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_NL = re.compile(r"\n{3,}")


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", s)
    s = _TAG.sub("", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    s = _WS.sub(" ", s)
    s = _NL.sub("\n\n", s)
    return s.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="UYAP offline SQLite (the 'db' file)")
    ap.add_argument("--cache", default=DEFAULT_CACHE, help="emsal-mcp cache.sqlite3")
    ap.add_argument("--dry-run", action="store_true", help="report mapping, write nothing")
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()

    src = sqlite3.connect(f"file:{args.src}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    daire = {r["daireNo"]: r["daireAdi"] for r in src.execute("SELECT daireNo, daireAdi FROM daireList")}

    total = src.execute("SELECT count(*) FROM ictihat").fetchone()[0]
    print(f"Kaynak ictihat: {total}")

    if args.dry_run:
        print("\n=== Tür dağılımı (import edilecek) ===")
        for r in src.execute("SELECT dokumanTuru, count(*) c FROM ictihat GROUP BY dokumanTuru ORDER BY c DESC"):
            print(f"  {TYPE_LABEL.get(r[0], '?'+str(r[0])):42} {r[1]}")
        print("\n=== Örnek 2 eşlenmiş kayıt ===")
        for row in src.execute("SELECT * FROM ictihat WHERE length(metin)>500 LIMIT 2"):
            doc = build_row(row, daire)
            print(f"  document_id={doc['document_id']}  source={SOURCE_ID}")
            print(f"  court={doc['court']}  chamber={doc['chamber']}  E={doc['esas_no']} K={doc['karar_no']} tarih={doc['decision_date']}")
            print(f"  title={doc['title']!r}")
            print(f"  full_text[:160]={doc['full_text'][:160]!r}")
            print(f"  status={doc['content_status']}  metadata_json={doc['metadata_json'][:120]}...")
            print()
        print("DRY-RUN — hiçbir şey yazılmadı.")
        return

    dst = sqlite3.connect(args.cache, timeout=60)
    dst.execute("PRAGMA busy_timeout=60000")
    dst.execute("PRAGMA journal_mode=WAL")

    cols = ("document_id, source, title, court, chamber, decision_date, esas_no, karar_no, "
            "source_url, content_status, markdown, full_text, content_hash, metadata_json, "
            "raw_json, retrieved_at, last_accessed_at, access_count, quote_usable, draft_usable, "
            "metadata_confidence, warnings_json")
    sql = (f"INSERT INTO documents_v2({cols}) VALUES("
           "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
           "ON CONFLICT(document_id, source) DO NOTHING")

    inserted = skipped = 0
    batch: list[tuple] = []
    for row in src.execute("SELECT * FROM ictihat"):
        d = build_row(row, daire)
        batch.append((
            d["document_id"], SOURCE_ID, d["title"], d["court"], d["chamber"],
            d["decision_date"], d["esas_no"], d["karar_no"], None, d["content_status"],
            None, d["full_text"] or None, d["content_hash"], d["metadata_json"], None,
            d["now"], d["now"], 0, d["quote_usable"], d["draft_usable"], "high", None,
        ))
        if len(batch) >= args.batch:
            cur = dst.executemany(sql, batch)
            dst.commit()
            inserted += cur.rowcount if cur.rowcount > 0 else 0
            skipped += len(batch) - (cur.rowcount if cur.rowcount > 0 else 0)
            batch.clear()
            print(f"  ... {inserted} eklendi", end="\r")
    if batch:
        dst.executemany(sql, batch)
        dst.commit()

    new_total = dst.execute("SELECT count(*) FROM documents_v2 WHERE source=?", (SOURCE_ID,)).fetchone()[0]
    print(f"\nBitti. source='{SOURCE_ID}' toplam satır: {new_total}")
    print("documents_v2 GENEL toplam:", dst.execute("SELECT count(*) FROM documents_v2").fetchone()[0])
    dst.close()


def build_row(row: sqlite3.Row, daire: dict) -> dict:
    text = html_to_text(row["metin"])
    kavram = (row["kavram"] or "").strip()
    court_label = TYPE_LABEL.get(row["dokumanTuru"], "İçtihat")
    chamber = daire.get(row["daireID"])
    # Prefer baslik, then kavram's first meaningful line, else a citation-style title.
    title = (row["baslik"] or "").strip()
    if len(title) < 3:
        first = next((ln.strip() for ln in kavram.splitlines() if len(ln.strip()) >= 3), "")
        title = first[:100] or " ".join(p for p in (chamber or court_label,
                 (row["esasNo"] or "").strip(), (row["kararNo"] or "").strip()) if p) or None
    now = datetime.now(timezone.utc).isoformat()
    has_text = len(text) > 50
    meta = {
        "ictihatID": row["ictihatID"],
        "kavram": kavram or None,
        "kararTuru": row["kararTuru"],
        "rgTarihi": row["rgTarihi"],
        "rgSayisi": row["rgSayisi"],
        "arsiv": "uyap_mevzuat_2020",
    }
    return {
        "document_id": f"uyap:{row['ictihatID']}",
        "title": title,
        "court": court_label,
        "chamber": chamber,
        "decision_date": (row["kararTarihi"] or "").strip() or None,
        "esas_no": (row["esasNo"] or "").strip() or None,
        "karar_no": (row["kararNo"] or "").strip() or None,
        "content_status": "html_markdown" if has_text else "metadata_only",
        "full_text": text if has_text else "",
        "content_hash": hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest() if has_text else None,
        "metadata_json": json.dumps(meta, ensure_ascii=False),
        "quote_usable": 1 if has_text else 0,
        "draft_usable": 1 if has_text else 0,
        "now": now,
    }


if __name__ == "__main__":
    main()
