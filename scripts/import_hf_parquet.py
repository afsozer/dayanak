"""HF `hamzabagirsakci/turkish-court-decisions` parquet setini emsal-mcp cache'ine al.

Kaynak eşlemesi (2 Eyl 2026 ölçümü: desktop bedesten korpusundan 2.000 örnek
document_id'nin %97,7'si HF yargitay/emsal/danistay içinde AYNI kimlikle bulundu):

    HF yargitay  -> source='bedesten', court='Yargıtay Kararı',          chamber=daire
    HF emsal     -> source='bedesten',
                    court='İstinaf Hukuk Mahkemesi Kararı' / 'Yerel Hukuk Mahkemesi Kararı'
    HF danistay  -> source='bedesten', court='Danıştay Kararı'
    HF aym_bb    -> source='aym',      court='Anayasa Mahkemesi', chamber=Bölüm
    HF aym_norm  -> source='aym',      court='Anayasa Mahkemesi', chamber='Norm Denetimi'

Bedesten satırları mevcut crawl korpusuyla aynı (document_id, source) anahtarını
paylaşır; ON CONFLICT DO NOTHING ile crawl'dan gelen satır korunur. Köken her
zaman metadata_json.origin = 'hf_turkish_court_decisions' olarak işaretlenir.

decision_date mevcut korpusla uyumlu olsun diye dd.mm.yyyy yazılır; ISO tarih,
mevzuat_atif, masked_count, raw_sha256 metadata_json'da saklanır.

Kullanım:
    python scripts/import_hf_parquet.py --src ~/Developer/emsal-mcp-data/hf \
        --only aym_norm --dry-run
    python scripts/import_hf_parquet.py --src ~/Developer/emsal-mcp-data/hf            # hepsi
    python scripts/import_hf_parquet.py --src ... --only yargitay --min-year 2015     # alt küme
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

ORIGIN = "hf_turkish_court_decisions"
DEFAULT_CACHE = os.environ.get("EMSAL_CACHE_PATH") or str(
    Path.home() / ".emsal-mcp" / "cache.sqlite3"
)

COLS = ("document_id, source, title, court, chamber, decision_date, esas_no, karar_no, "
        "source_url, content_status, markdown, full_text, content_hash, metadata_json, "
        "raw_json, retrieved_at, last_accessed_at, access_count, quote_usable, draft_usable, "
        "metadata_confidence, warnings_json")
SQL = (f"INSERT INTO documents_v2({COLS}) VALUES(" + ",".join(["?"] * 22) + ") "
       "ON CONFLICT(document_id, source) DO NOTHING")

READ_COLS = ["source", "document_id", "court", "esas_no", "karar_no", "karar_tarihi",
             "year", "text", "text_len", "masked_count", "raw_sha256", "mevzuat_atif"]


def iso_to_tr(iso: str | None) -> str | None:
    if not iso or len(iso) < 10:
        return None
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}"


def map_row(r: dict, now: str) -> tuple | None:
    src = r["source"]
    did = r["document_id"]
    text = r["text"] or ""
    if not did or len(text) < 50:
        return None
    hf_court = r["court"] or ""
    if src == "yargitay":
        source, court, chamber = "bedesten", "Yargıtay Kararı", hf_court or None
    elif src == "danistay":
        source, court, chamber = "bedesten", "Danıştay Kararı", hf_court or None
    elif src == "emsal":
        source = "bedesten"
        court = ("İstinaf Hukuk Mahkemesi Kararı" if "Bölge Adliye" in hf_court
                 else "Yerel Hukuk Mahkemesi Kararı")
        chamber = hf_court or None
    elif src == "aym_bb":
        source, court, chamber = "aym", "Anayasa Mahkemesi", hf_court or "Bireysel Başvuru"
    elif src == "aym_norm":
        source, court, chamber = "aym", "Anayasa Mahkemesi", "Norm Denetimi"
    else:
        return None

    date_tr = iso_to_tr(r["karar_tarihi"])
    esas = (r["esas_no"] or "").strip() or None
    karar = (r["karar_no"] or "").strip() or None
    title = " | ".join(str(x) for x in (court, chamber, date_tr, esas, karar) if x) or did

    if source == "bedesten":
        url = f"https://mevzuat.adalet.gov.tr/ictihat/{did}"
    else:
        url = None  # AYM kararlar bilgi bankası kimliği; URL deseni doğrulanmadı, uydurma
    meta = {
        "origin": ORIGIN,
        "hf_source": src,
        "karar_tarihi_iso": r["karar_tarihi"],
        "year": r["year"],
        "text_len": r["text_len"],
        "masked_count": r["masked_count"],
        "raw_sha256": r["raw_sha256"],
        "mevzuat_atif": r["mevzuat_atif"] or [],
    }
    if source == "bedesten":
        meta["alternate_url"] = f"https://emsal.uyap.gov.tr/getDokuman?id={did}"
    chash = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    return (
        did, source, title, court, chamber, date_tr, esas, karar, url,
        "html_markdown", None, text, chash, json.dumps(meta, ensure_ascii=False),
        None, now, now, 0, 1, 1, "high", None,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="parquet kök dizini (data/<kaynak>/*.parquet)")
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--only", action="append", help="yalnız bu HF kaynağı (tekrarlanabilir)")
    ap.add_argument("--min-year", type=int, default=0, help="bu yıldan eski kararları atla")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="dry-run/deneme için satır sınırı")
    ap.add_argument("--batch", type=int, default=2000)
    args = ap.parse_args()

    subs = sorted(d for d in os.listdir(args.src) if os.path.isdir(os.path.join(args.src, d)))
    if args.only:
        subs = [s for s in subs if s in set(args.only)]
    files = [f for s in subs for f in sorted(glob.glob(os.path.join(args.src, s, "*.parquet")))]
    print(f"kaynaklar={subs} dosya={len(files)} cache={args.cache} dry_run={args.dry_run}")

    dst = None
    if not args.dry_run:
        dst = sqlite3.connect(args.cache, timeout=120)
        dst.execute("PRAGMA busy_timeout=120000")
        dst.execute("PRAGMA journal_mode=WAL")
        dst.execute("PRAGMA synchronous=NORMAL")
        dst.execute("PRAGMA cache_size=-524288")  # 512 MB
        dst.execute("PRAGMA temp_store=MEMORY")
        have = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "documents_v2" not in have:
            sys.exit("documents_v2 yok: önce emsal-mcp şemasını oluştur (örn. `emsal-mcp doctor`).")
        fts = "var" if "documents_v2_fts" in have else "YOK (import sonrası FTS kurulur)"
        print("FTS tetikleyicileri:", fts)

    now = datetime.now(timezone.utc).isoformat()
    seen = inserted = skipped_short = skipped_year = 0
    t0 = time.time()
    batch: list[tuple] = []
    sample_printed = 0

    def flush() -> None:
        nonlocal inserted
        if dst is None or not batch:
            batch.clear()
            return
        cur = dst.executemany(SQL, batch)
        dst.commit()
        inserted += max(cur.rowcount, 0)
        batch.clear()

    for f in files:
        pf = pq.ParquetFile(f)
        for rg in range(pf.num_row_groups):
            tbl = pf.read_row_group(rg, columns=READ_COLS)
            for r in tbl.to_pylist():
                seen += 1
                if args.min_year and (r["year"] or 0) < args.min_year:
                    skipped_year += 1
                    continue
                row = map_row(r, now)
                if row is None:
                    skipped_short += 1
                    continue
                if args.dry_run and sample_printed < 2:
                    sample_printed += 1
                    print("  ÖRNEK:", {k: (v[:120] if isinstance(v, str) else v)
                                        for k, v in zip(COLS.split(", "), row)})
                batch.append(row)
                if len(batch) >= args.batch:
                    flush()
                if args.limit and seen >= args.limit:
                    break
            if args.limit and seen >= args.limit:
                break
            el = time.time() - t0
            print(f"  {os.path.basename(os.path.dirname(f))}/{os.path.basename(f)} rg{rg} "
                  f"görülen={seen:,} eklenen={inserted:,} {seen/el:,.0f} satır/sn",
                  end="\r", flush=True)
        if args.limit and seen >= args.limit:
            break
    flush()
    el = time.time() - t0
    print(f"\nBitti {el:,.0f} sn. görülen={seen:,} eklenen={inserted:,} "
          f"kısa/atlanan={skipped_short:,} yıl_filtresi={skipped_year:,}")
    if dst is not None:
        total = dst.execute("SELECT count(*) FROM documents_v2").fetchone()[0]
        print("documents_v2 toplam:", total)
        print("kaynak dağılımı:", dst.execute(
            "SELECT source, count(*) FROM documents_v2 GROUP BY 1").fetchall())
        dst.close()


if __name__ == "__main__":
    main()
