"""Faz 2a geri doldurma: ``mevzuat_degisiklik`` tablosunu doldurur ve
madde başlıklarını (``baslik`` + yeni ``ust_baslik``) yeniden hesaplar.

Kullanım:

    python scripts/mevzuat_degisiklik_doldur.py --db <veri-dizini>\\cache.sqlite3
    python scripts/mevzuat_degisiklik_doldur.py --db ... --limit 20   # deneme
    python scripts/mevzuat_degisiklik_doldur.py --db ... --mevzuat-no 6098

Yalnızca ``mevzuat_madde`` ve ``mevzuat_degisiklik`` tablolarına yazar
(madde metni yalnız bölücü farklı metin üretirse yazılır, gömme bunu
``metin_hash`` ile görüp maddeyi yeniden gömer);
``mevzuat_dokuman`` ve ``documents_v2`` okunur bile değişmez. Metin
değişmediği için yeniden çekim gerekmez: kaydedilmiş konsolide metin
``legislation_corpus.maddelere_bol`` ile yeniden ayrıştırılır.

Canlı MCP sunucusu aynı SQLite dosyasını okuduğundan yazma BELGE BAŞINA tek
ve kısa bir transaction'dır; iki belge arasında ``--uyku`` kadar beklenir.
Kesilirse aynı komutla sürdürülebilir (her belge idempotent yeniden yazılır).

DİKKAT: gecelik ``EmsalMevzuatPull`` görevi ile aynı anda ÇALIŞTIRMAYIN —
ikisi de ``mevzuat_madde``ye yazar.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dayanak.legislation_corpus import (  # noqa: E402
    _DEGISIKLIK_INSERT,
    _degisiklik_row,
    ensure_schema,
    maddelere_bol,
)


def _belgeler(
    db: sqlite3.Connection, mevzuat_no: str | None, limit: int | None
) -> list[tuple[str, str, str]]:
    sql = "SELECT mevzuat_id, mevzuat_no, ad FROM mevzuat_dokuman"
    params: list[object] = []
    if mevzuat_no:
        sql += " WHERE mevzuat_no = ?"
        params.append(mevzuat_no)
    sql += " ORDER BY mevzuat_id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return db.execute(sql, params).fetchall()


def belge_isle(db: sqlite3.Connection, mevzuat_id: str) -> tuple[int, int, int]:
    """Tek belgeyi yeniden ayrıştırıp yaz.

    Dönüş: (madde, degisiklik, metni değişen madde) sayısı. Madde metni yalnız
    farklıysa yazılır: FTS tetikleyicisi ve artımlı gömme (metin_hash) yalnız
    gerçekten değişen maddeye dokunsun. Bölücü sonraki maddenin başlığını önceki
    gövdeden keser; bu kesim eklenmeden önce çekilmiş belgelerde metin eskiydi
    (4.11.2026: 2659 m.26 "BEŞİNCİ BÖLÜM ... İkinci görev aylığı: [10]" ile
    bitiyordu).
    """
    row = db.execute(
        "SELECT metin, kaynak FROM mevzuat_dokuman WHERE mevzuat_id = ?", (mevzuat_id,)
    ).fetchone()
    if not row or not row[0]:
        return (0, 0, 0)
    # Kaynağa göre bölücü: RG metni için alıntı maddeler katlanır.
    maddeler = maddelere_bol(row[0], row[1] or "")
    if not maddeler:
        return (0, 0, 0)
    mevcut = dict(db.execute(
        "SELECT sira, metin FROM mevzuat_madde WHERE mevzuat_id = ?", (mevzuat_id,)
    ).fetchall())
    metin_guncel = [
        (m["metin"], mevzuat_id, m["sira"]) for m in maddeler
        if m["sira"] in mevcut and (mevcut[m["sira"]] or "") != m["metin"]
    ]
    degisiklikler = [
        _degisiklik_row(mevzuat_id, m["sira"], d)
        for m in maddeler for d in m["degisiklikler"]
    ]
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM mevzuat_degisiklik WHERE mevzuat_id = ?", (mevzuat_id,))
        db.executemany(
            "UPDATE mevzuat_madde SET baslik = ?, ust_baslik = ?, degisiklik_notu = ?"
            " WHERE mevzuat_id = ? AND sira = ?",
            [
                (m["baslik"], m["ust_baslik"], m["degisiklik_notu"], mevzuat_id, m["sira"])
                for m in maddeler
            ],
        )
        db.executemany(_DEGISIKLIK_INSERT, degisiklikler)
        db.executemany(
            "UPDATE mevzuat_madde SET metin = ? WHERE mevzuat_id = ? AND sira = ?",
            metin_guncel,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return (len(maddeler), len(degisiklikler), len(metin_guncel))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="SQLite dosyası (cache.sqlite3)")
    ap.add_argument("--mevzuat-no", default=None, help="Yalnız bu mevzuat numarası")
    ap.add_argument("--limit", type=int, default=None, help="En çok N belge")
    ap.add_argument("--uyku", type=float, default=0.05,
                    help="Belgeler arası bekleme (sn); canlı sunucuyu boğmamak için")
    ap.add_argument("--kuru", action="store_true", help="Yazma, yalnız say")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=30.0)
    db.execute("PRAGMA busy_timeout=30000")
    ensure_schema(db)

    belgeler = _belgeler(db, args.mevzuat_no, args.limit)
    print(f"{len(belgeler)} belge işlenecek", flush=True)
    t0 = time.time()
    madde_top = deg_top = metin_top = 0
    for i, (mevzuat_id, no, ad) in enumerate(belgeler, 1):
        if args.kuru:
            row = db.execute(
                "SELECT metin, kaynak FROM mevzuat_dokuman WHERE mevzuat_id = ?", (mevzuat_id,)
            ).fetchone()
            maddeler = maddelere_bol(row[0], row[1] or "") if row and row[0] else []
            m, d = len(maddeler), sum(len(x["degisiklikler"]) for x in maddeler)
            mt = 0
        else:
            m, d, mt = belge_isle(db, mevzuat_id)
        madde_top += m
        deg_top += d
        metin_top += mt
        print(f"[{i}/{len(belgeler)}] {no} {(ad or '')[:50]}: {m} madde, "
              f"{d} değişiklik, {mt} metin güncellendi", flush=True)
        if args.uyku and not args.kuru:
            time.sleep(args.uyku)
    db.close()
    print(f"BİTTİ: {len(belgeler)} belge, {madde_top} madde, {deg_top} değişiklik, "
          f"{metin_top} metin güncellendi, {time.time() - t0:.1f} sn", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
