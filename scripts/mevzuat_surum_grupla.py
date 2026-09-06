"""Aynı adla yeniden yayımlanan mevzuat sürümlerini grupla (Faz 2d doldurma).

``mevzuat_dokuman.ad_anahtari`` / ``grup_anahtari`` / ``guncel`` sütunlarını
doldurur. Mantığın tamamı ``legislation_corpus.gruplari_yenile`` içinde;
bu betik yalnız CLI kabuğu.

Kullanım::

    python scripts/mevzuat_surum_grupla.py --db D:\\emsal-data\\cache.sqlite3 --dry-run
    python scripts/mevzuat_surum_grupla.py --db D:\\emsal-data\\cache.sqlite3

``--dry-run`` hiçbir şey yazmaz, yalnız serileri ve seri SAYILMAYAN aynı-adlı
grupları listeler (yanlış katlamayı elle gözden geçirmek için).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emsal_mcp.legislation_corpus import gruplari_yenile  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="cache.sqlite3 yolu")
    ap.add_argument("--dry-run", action="store_true", help="yazma, yalnız listele")
    ap.add_argument("--limit-liste", type=int, default=100)
    a = ap.parse_args()

    db = sqlite3.connect(a.db)
    db.execute("PRAGMA busy_timeout = 30000")
    t0 = time.time()
    rapor = gruplari_yenile(db, uygula=not a.dry_run)
    sure = time.time() - t0
    db.close()

    print(f"belge: {rapor['belge']:,}  ad grubu: {rapor['ad_grubu']:,}  "
          f"çok üyeli: {rapor['cok_uyeli_grup']}")
    print(f"sürüm serisi: {rapor['seri_grup']} grup / {rapor['seri_belge']} belge  "
          f"katlanan eski sürüm: {rapor['katlanan_eski_surum']}")
    print(f"süre: {sure:.2f} s  yazıldı: {rapor['uygulandi']}\n")

    print("--- SÜRÜM SERİLERİ (en yeni yürürlükte sayılır) ---")
    for x in rapor["seriler"][: a.limit_liste]:
        print(f"  [{x['uye']:3}] {x['tur']:10} {x['ilk']} → {x['guncel_rg']}  {x['ad'][:80]}")

    print("\n--- AYNI ADLI AMA SERİ SAYILMAYAN (katlanmaz) ---")
    for x in rapor["seri_sayilmayan"][: a.limit_liste]:
        print(f"  [{x['uye']:3}] {x['tur']:10} {x['ad'][:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
