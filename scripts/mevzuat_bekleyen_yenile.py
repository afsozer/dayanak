"""Ertelenmiş yürürlüğü gelmiş değişiklikleri korpusa almak için belgeyi
zorla yeniden çeker.

Kullanım:

    python scripts/mevzuat_bekleyen_yenile.py               # günlük görev
    python scripts/mevzuat_bekleyen_yenile.py --liste       # yalnız listele
    python scripts/mevzuat_bekleyen_yenile.py --mevzuat-id 1.5.4721 --mevzuat-id 1.5.6100

Neden: haftalık ``--only-changed`` koşusu metni Bedesten ``kayitTarihi``
sinyaline göre yeniden çeker. Ertelenmiş yürürlüklü bir değişikliği
mevzuat.gov.tr yürürlük günü konsolide metne işlediğinde bu sinyal
gelmeyebiliyor: 4.11.2026'da TMK 444 ve HMK 149 kaynakta güncellenmişti,
1.11.2026 haftalık koşusu "güncel=0" bildirdi. Bu betik sinyale bakmaz;
dipnotunda "Mevzuat Bilgi Sistemine işlenecek" yazan ve yürürlük tarihi
gelmiş maddelerin belgelerini doğrudan yeniden çeker. Kaynak henüz
işlememişse metin aynı gelir, hiçbir şey yazılmaz; ertesi gün yine denenir.

Çıkış kodu: 0 = en az bir belge güncellendi (semantik indeks yenilenmeli),
3 = güncellenen yok, 1 = hata (hiçbir belge çekilemedi).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

# Kaynak sırası ve PDF/boş metin korumaları haftalık çekimle aynı kalsın.
from mevzuat_pull import _fetch_text, _log  # noqa: E402

# Kaynak bu kadar gün sonra hala işlememişse log'a uyarı düşülür.
_GECIKME_UYARI_GUN = 14


def _hedefler(db, ids: list[str], bugun: date) -> tuple[list[str], dict[str, list[dict]]]:
    from dayanak import legislation_corpus as lc

    bekleyen = lc.bekleyen_yururlukler(db, bugun=bugun)
    gruplu: dict[str, list[dict]] = {}
    for b in bekleyen:
        gruplu.setdefault(b["mevzuat_id"], []).append(b)
    hedef = list(ids) if ids else list(gruplu)
    return hedef, gruplu


async def run(ids: list[str], liste: bool, sleep: float) -> int:
    from dayanak.cache import Cache
    from dayanak import legislation_corpus as lc
    from dayanak import legislation_update as lu
    from dayanak.sources.mevzuat import MevzuatClient
    from dayanak.sources.mevzuatgov import MevzuatGovClient

    bugun = date.today()
    cache = Cache()
    db = cache.db
    lc.ensure_schema(db)
    lu.ensure_update_schema(db)

    hedef, gruplu = _hedefler(db, ids, bugun)
    _log(f"bugün {bugun.isoformat()}: yürürlüğü gelmiş ama işlenmemiş "
         f"{sum(len(v) for v in gruplu.values())} madde, {len(gruplu)} belge; "
         f"çekilecek {len(hedef)} belge")
    for mid, maddeler in gruplu.items():
        for b in maddeler:
            gecikme = (bugun - date.fromisoformat(b["yururluk_tarihi"])).days
            ek = f" UYARI: kaynak {gecikme} gündür işlemedi" if gecikme >= _GECIKME_UYARI_GUN else ""
            _log(f"  bekleyen {b['tur']} {b['mevzuat_no']} m.{b['madde_no']} "
                 f"({b['degistiren_no']}/{b['degistiren_madde']}, yürürlük "
                 f"{b['yururluk_tarihi']}){ek}")
    if liste or not hedef:
        cache.close()
        return 3

    mg, bd = MevzuatGovClient(), MevzuatClient()
    sayac = {"guncel": 0, "ayni": 0, "hata": 0}
    for mid in hedef:
        row = db.execute(
            """SELECT kaynak, tur, mevzuat_no, tertip, ad, kabul_tarihi, rg_tarihi,
                      rg_sayisi, guncelleme_tarihi, kaynak_url, meta_json, metin_hash
               FROM mevzuat_dokuman WHERE mevzuat_id = ?""",
            (mid,),
        ).fetchone()
        if not row:
            _log(f"  HATA {mid}: korpusta yok (yeni belgeyi mevzuat_pull.py çeker)")
            sayac["hata"] += 1
            continue
        tur, no, ad = row[1] or "", row[2] or "", row[4] or ""
        metin, kaynak, url, err = await _fetch_text(mg, bd, mid, no, tur)
        if not metin:
            _log(f"  HATA {mid} {ad[:50]}: {err[:160]}")
            sayac["hata"] += 1
            await asyncio.sleep(sleep)
            continue
        if lc._hash(metin) == (row[11] or ""):
            sayac["ayni"] += 1
            neden = ("kaynak henüz işlememiş" if mid in gruplu
                     else "metin kaynakla aynı, yazılmadı")
            _log(f"  AYNI {mid} {ad[:50]}: {neden}")
            await asyncio.sleep(sleep)
            continue
        lu.arsivle(db, mid)
        res = lc.upsert_document(
            db, mevzuat_id=mid, metin=metin, kaynak=kaynak or row[0] or "", tur=tur,
            mevzuat_no=no, tertip=row[3] or "", ad=ad, kabul_tarihi=row[5] or "",
            rg_tarihi=row[6] or "", rg_sayisi=row[7] or "",
            guncelleme_tarihi=row[8] or "", kaynak_url=url or row[9] or "",
            meta=json.loads(row[10] or "{}"), force=True,
        )
        sayac["guncel"] += 1
        kalan = [b for b in lc.bekleyen_yururlukler(db, bugun=bugun) if b["mevzuat_id"] == mid]
        durum = (f"{len(kalan)} madde hala bekliyor" if kalan
                 else "bekleyen madde kalmadı")
        _log(f"  GÜNCEL {mid} {ad[:50]}: {res['madde_sayisi']} madde yazıldı; {durum}")
        await asyncio.sleep(sleep)

    cache.close()
    _log(f"BİTTİ: güncellenen {sayac['guncel']}, aynı {sayac['ayni']}, hata {sayac['hata']}")
    if sayac["guncel"]:
        return 0
    if sayac["hata"] and not sayac["ayni"]:
        return 1
    return 3


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mevzuat-id", action="append", default=[],
                    help="Bekleyen listesine bakmadan bu belgeyi zorla yeniden çek "
                         "(ör. 1.5.4721); birden çok kez verilebilir")
    ap.add_argument("--liste", action="store_true", help="Yalnız listele, çekme")
    ap.add_argument("--sleep", type=float, default=1.0, help="İstekler arası bekleme (sn)")
    args = ap.parse_args()
    t0 = time.time()
    rc = asyncio.run(run([i.strip() for i in args.mevzuat_id if i.strip()],
                         args.liste, args.sleep))
    _log(f"süre {time.time() - t0:.1f} sn, rc={rc}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
