"""Faz 3: ``mevzuat_madde.ust_baslik`` sütununu saklı metinden yeniden doldur.

Neden: ``ust_baslik`` 298.854 maddenin yalnız %19,1'inde doluydu (ölçüldü
6 Eyl 2026). ``legislation_corpus._Hiyerarsi`` belge boyu bir başlık yığını
tutar; bu betik saklı ``mevzuat_dokuman.metin``i yeniden ayrıştırıp YALNIZCA
``ust_baslik`` sütununu günceller.

Sözleşme:

* Ağa ÇIKMAZ. Tek girdi veritabanındaki metin.
* ``madde_no``, ``sira``, ``baslik``, ``metin`` DEĞİŞMEZ. Eşleştirme
  ``(mevzuat_id, sira)`` üzerinden; ayrıştırma madde sayısını değiştirirse o
  belge ATLANIR (hizalama bozulmasın).
* ``mevzuat_madde_fts`` ``ust_baslik`` içermez (madde_no/baslik/metin), o yüzden
  FTS'in yeniden kurulması GEREKMEZ; ``mevzuat_madde_au`` tetikleyicisi her
  UPDATE'te satırı aynı değerlerle yeniden indeksler, sonuç değişmez.
* ``scripts/embed_mevzuat_madde.madde_metni`` gömme metnine ``ust_baslik``i
  KATAR ve ``metin_hash``i ondan üretir; değişen maddeler artımlı gömmede
  kendiliğinden yeniden gömülür. Betik sonunda bu sayıyı raporlar.

Kullanım::

    python scripts/mevzuat_ust_baslik_doldur.py --db <veri-dizini>\\cache.sqlite3
    python scripts/mevzuat_ust_baslik_doldur.py --db ... --mevzuat-no 6098
    python scripts/mevzuat_ust_baslik_doldur.py --db ... --limit 50 --kuru
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emsal_mcp.legislation_corpus import split_articles


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--limit", type=int, default=0, help="en fazla N belge")
    ap.add_argument("--mevzuat-no", default="", help="yalnız bu mevzuat numarası")
    ap.add_argument("--tur", default="", help="yalnız bu tür (KANUN, YONETMELIK…)")
    ap.add_argument("--kuru", action="store_true", help="yazma, yalnız say")
    ap.add_argument("--commit-arasi", type=int, default=200, help="N belgede bir commit")
    a = ap.parse_args()

    db = sqlite3.connect(a.db)
    db.execute("PRAGMA journal_mode=WAL")
    kosul, parametre = [], []
    if a.mevzuat_no:
        kosul.append("mevzuat_no = ?")
        parametre.append(a.mevzuat_no)
    if a.tur:
        kosul.append("UPPER(tur) = ?")
        parametre.append(a.tur.upper())
    where = (" WHERE " + " AND ".join(kosul)) if kosul else ""
    limit = f" LIMIT {a.limit}" if a.limit else ""
    belgeler = db.execute(
        f"SELECT mevzuat_id FROM mevzuat_dokuman{where} ORDER BY mevzuat_id{limit}",
        parametre,
    ).fetchall()

    t0 = time.time()
    islenen = atlanan = degisen = bosalan = dolan = 0
    for i, (mid,) in enumerate(belgeler, 1):
        row = db.execute(
            "SELECT metin FROM mevzuat_dokuman WHERE mevzuat_id = ?", (mid,)
        ).fetchone()
        if not row or not row[0]:
            atlanan += 1
            continue
        maddeler = split_articles(row[0])
        mevcut = db.execute(
            "SELECT sira, ust_baslik FROM mevzuat_madde WHERE mevzuat_id = ? ORDER BY sira",
            (mid,),
        ).fetchall()
        if len(mevcut) != len(maddeler):
            # Ayrıştırma bu belgede farklı sayıda madde üretiyor: hizalama
            # garanti değil, ust_baslik'i YANLIŞ maddeye yazmaktansa atla.
            atlanan += 1
            continue
        guncellemeler = []
        for (sira, eski), yeni in zip(mevcut, maddeler):
            y = yeni["ust_baslik"] or ""
            if (eski or "") == y:
                continue
            guncellemeler.append((y, mid, sira))
            if not (eski or "") and y:
                dolan += 1
            elif (eski or "") and not y:
                bosalan += 1
        if guncellemeler and not a.kuru:
            db.executemany(
                "UPDATE mevzuat_madde SET ust_baslik = ? WHERE mevzuat_id = ? AND sira = ?",
                guncellemeler,
            )
        degisen += len(guncellemeler)
        islenen += 1
        if not a.kuru and i % a.commit_arasi == 0:
            db.commit()
            print(f"  … {i}/{len(belgeler)} belge, {degisen} madde güncellendi",
                  flush=True)
    if not a.kuru:
        db.commit()

    n, dolu = db.execute(
        "SELECT COUNT(*), SUM(CASE WHEN ust_baslik IS NOT NULL AND ust_baslik <> ''"
        " THEN 1 ELSE 0 END) FROM mevzuat_madde"
    ).fetchone()
    print(f"belge: {len(belgeler)} (işlenen {islenen}, atlanan {atlanan})")
    print(f"değişen madde: {degisen} (boş→dolu {dolan}, dolu→boş {bosalan})")
    print(f"ust_baslik doluluk: {dolu}/{n} = {100 * (dolu or 0) / max(n, 1):.1f}%")
    print(f"süre: {time.time() - t0:.1f} sn")
    if degisen and not a.kuru:
        print("NOT: FTS yeniden kurulmasına GEREK YOK (ust_baslik FTS'te değil).")
        print("NOT: semantik indeks için scripts/embed_mevzuat_madde.py (artımlı)"
              " + scripts/build_mevzuat_index.py yeniden koşturulmalı.")


if __name__ == "__main__":
    main()
