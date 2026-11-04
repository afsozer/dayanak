"""Resmi Gazete'deki kanunların tam metnini mevzuat korpusuna alır.

Kullanım:

    python scripts/rg_kanun_cek.py               # korpusta olmayan tüm kanunlar
    python scripts/rg_kanun_cek.py --liste       # yalnız say, çekme
    python scripts/rg_kanun_cek.py --no 7571     # tek kanun (birden çok kez verilebilir)
    python scripts/rg_kanun_cek.py --limit 20    # deneme

Neden: mevzuat.gov.tr birçok değişiklik kanununu hiç listelemiyor. 4.11.2026
ölçümü: RG dizinindeki 2.672 kanun kaleminin 2.347'si korpusta yoktu; bunların
1.401'i uluslararası anlaşma onayı, 570'i numaralı başka kanun (7571 TCK
değişikliği, 7574 KTK, 7577, 7593 Çocuk Koruma ...), gerisi numarasız eski
kalemler. Kanunun kendi geçici maddeleri ve yürürlük hükümleri yalnız bu
metinde durur.

Hangi kalemler: RG başlık dizininde (``resmigazete.sqlite3``) kategorisi KANUN
ya da KANUNLAR olan, numarası rakam olan, HTML yayımlanmış kalemler. Numarası
korpusta mevzuat.gov.tr kaynağıyla zaten bulunan kanun atlanır (konsolide metin
daha iyi). mevzuat.gov.tr bir kanunu sonradan listelerse RG kopyası silinir.

Belge kimliği ``rg.<kalem>`` (ör. ``rg.20251225-33``), ``kaynak='resmigazete'``,
``tur='KANUN'``. Maddeler ``legislation_corpus.split_degisiklik_kanunu`` ile
bölünür: tırnak içindeki alıntı maddeler kanunun kendi maddesi sayılmaz.

Çıkış kodu: 0 = en az bir belge yazıldı ya da silindi (semantik indeks
yenilenmeli), 3 = değişiklik yok, 1 = hata (hiçbir belge yazılamadı).
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

from mevzuat_pull import _MIN_TEXT, _ikili, _log, _with_backoff  # noqa: E402

_KABUL_RE = re.compile(r"Kabul\s+Tarihi\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)


def _kalemler(rg, nolar: list[str]) -> tuple[list[dict], dict[str, int]]:
    """Çekilebilir RG kanun kalemleri (numara başına ilk yayım) ve eleme sayıları."""
    rows = rg.execute(
        "SELECT item_id, tarih, sayi_no, numara, baslik, url, ext FROM rg_ogeler"
        " WHERE upper(kategori) IN ('KANUN', 'KANUNLAR') ORDER BY tarih, item_id"
    ).fetchall()
    sayac = {"numarasiz": 0, "pdf": 0, "tekrar": 0}
    secilen: dict[str, dict] = {}
    for item_id, tarih, sayi, numara, baslik, url, ext in rows:
        no = (numara or "").strip()
        if not no.isdigit():
            sayac["numarasiz"] += 1
            continue
        if nolar and no not in nolar:
            continue
        if (ext or "").lower() not in ("htm", "html"):
            sayac["pdf"] += 1
            continue
        if no in secilen:
            sayac["tekrar"] += 1
            continue
        secilen[no] = {"item_id": item_id, "tarih": tarih, "sayi": sayi or "",
                       "no": no, "baslik": baslik or "", "url": url or ""}
    return list(secilen.values()), sayac


def _rg_tarihi(iso: str) -> str:
    y, a, g = iso[:10].split("-")
    return f"{g}.{a}.{y}"


async def run(nolar: list[str], liste: bool, limit: int | None, sleep: float) -> int:
    from dayanak import legislation_corpus as lc
    from dayanak import rg_index
    from dayanak.cache import Cache
    from dayanak.models import ContentStatus
    from dayanak.sources.resmigazete import ResmiGazeteClient

    rg = rg_index.open_readonly()
    if rg is None:
        _log("HATA: RG başlık dizini yok (dayanak rg backfill)")
        return 1
    cache = Cache()
    db = cache.db
    lc.ensure_schema(db)

    konsolide = {
        r[0] for r in db.execute(
            "SELECT mevzuat_no FROM mevzuat_dokuman"
            " WHERE tur = 'KANUN' AND COALESCE(kaynak, '') != 'resmigazete'"
        )
    }
    mevcut_rg = {
        r[0]: r[1] for r in db.execute(
            "SELECT mevzuat_id, mevzuat_no FROM mevzuat_dokuman WHERE kaynak = 'resmigazete'"
        )
    }

    # mevzuat.gov.tr sonradan listelediyse RG kopyası gereksiz: sil.
    silinen = 0
    for mid, no in sorted(mevcut_rg.items()):
        if no in konsolide and not liste:
            lc.belge_sil(db, mid)
            silinen += 1
            _log(f"  SİL {mid} ({no}): mevzuat.gov.tr artık listeliyor")

    kalemler, sayac = _kalemler(rg, nolar)
    rg.close()
    hedef = [
        k for k in kalemler
        if k["no"] not in konsolide and f"rg.{k['item_id']}" not in mevcut_rg
    ]
    if limit:
        hedef = hedef[:limit]
    n_konsolide = sum(1 for k in kalemler if k["no"] in konsolide)
    n_rg = sum(1 for k in kalemler if "rg." + k["item_id"] in mevcut_rg)
    _log(f"RG kanun kalemi {len(kalemler)} (numarasız {sayac['numarasiz']}, pdf "
         f"{sayac['pdf']}, tekrar {sayac['tekrar']} elendi); konsolide olarak var "
         f"{n_konsolide}, RG kopyası var {n_rg}; çekilecek {len(hedef)}")
    if liste:
        for k in hedef[:40]:
            _log(f"  {k['item_id']} {k['no']} {k['baslik'][:70]}")
        cache.close()
        return 3

    client = ResmiGazeteClient()
    yazilan = hata = maddesiz = 0
    t0 = time.time()
    for i, k in enumerate(hedef, 1):
        try:
            doc = await _with_backoff(lambda: client.get_document(k["item_id"]),
                                      f"RG {k['item_id']}")
        except Exception as exc:  # ağ dışı hata: kaydet, sürdür
            hata += 1
            _log(f"  HATA {k['item_id']} {k['no']}: {type(exc).__name__}: {exc}")
            await asyncio.sleep(sleep)
            continue
        metin = doc.full_text or ""
        if (doc.content_status != ContentStatus.HTML_MARKDOWN or len(metin) < _MIN_TEXT
                or _ikili(metin)):
            hata += 1
            _log(f"  HATA {k['item_id']} {k['no']}: status={doc.content_status} len={len(metin)}")
            await asyncio.sleep(sleep)
            continue
        kabul = _KABUL_RE.search(metin)
        rg_t = _rg_tarihi(k["tarih"])
        res = lc.upsert_document(
            db, mevzuat_id=f"rg.{k['item_id']}", metin=metin, kaynak="resmigazete",
            tur="KANUN", mevzuat_no=k["no"], tertip="", ad=k["baslik"],
            kabul_tarihi=kabul.group(1) if kabul else "", rg_tarihi=rg_t,
            rg_sayisi=k["sayi"], guncelleme_tarihi=rg_t,
            kaynak_url=k["url"] or (doc.source_url or ""),
            meta={"rg_item_id": k["item_id"], "metin_turu": "resmi_gazete_ilk_yayim"},
        )
        yazilan += 1
        if not res["madde_sayisi"]:
            maddesiz += 1
            _log(f"  UYARI {k['item_id']} {k['no']}: madde ayrılamadı")
        if i % 25 == 0 or i == len(hedef):
            _log(f"  {i}/{len(hedef)}: yazılan {yazilan}, hata {hata}, "
                 f"maddesiz {maddesiz} ({time.time() - t0:.0f} s)")
        await asyncio.sleep(sleep)

    cache.close()
    _log(f"BİTTİ: yazılan {yazilan}, silinen {silinen}, hata {hata}, maddesiz {maddesiz}")
    if yazilan or silinen:
        return 0
    return 1 if hata else 3


def yeniden_bol() -> int:
    """Ağa çıkmadan, kayıtlı RG metinlerinden maddeleri yeniden böl.

    Bölücü (``split_degisiklik_kanunu``) geliştiğinde RG belgelerini yeniden
    çekmeye gerek yok. Metin aynı kaldığı için semantik indeks yalnız değişen
    maddeleri gömer.
    """
    import json

    from dayanak import legislation_corpus as lc
    from dayanak.cache import Cache

    cache = Cache()
    db = cache.db
    lc.ensure_schema(db)
    ids = [r[0] for r in db.execute(
        "SELECT mevzuat_id FROM mevzuat_dokuman WHERE kaynak = 'resmigazete' ORDER BY mevzuat_id")]
    _log(f"yeniden bölünecek RG belgesi: {len(ids)}")
    madde = maddesiz = 0
    for i, mid in enumerate(ids, 1):
        row = db.execute(
            """SELECT tur, mevzuat_no, tertip, ad, kabul_tarihi, rg_tarihi, rg_sayisi,
                      guncelleme_tarihi, metin, kaynak_url, meta_json
               FROM mevzuat_dokuman WHERE mevzuat_id = ?""",
            (mid,),
        ).fetchone()
        res = lc.upsert_document(
            db, mevzuat_id=mid, metin=row[8] or "", kaynak="resmigazete", tur=row[0] or "",
            mevzuat_no=row[1] or "", tertip=row[2] or "", ad=row[3] or "",
            kabul_tarihi=row[4] or "", rg_tarihi=row[5] or "", rg_sayisi=row[6] or "",
            guncelleme_tarihi=row[7] or "", kaynak_url=row[9] or "",
            meta=json.loads(row[10] or "{}"), force=True,
        )
        madde += res["madde_sayisi"]
        if not res["madde_sayisi"]:
            maddesiz += 1
            _log(f"  UYARI {mid}: madde ayrılamadı")
        if i % 200 == 0 or i == len(ids):
            _log(f"  {i}/{len(ids)}: {madde} madde, maddesiz {maddesiz}")
    cache.close()
    _log(f"BİTTİ: {len(ids)} belge, {madde} madde, maddesiz {maddesiz}")
    return 0 if ids else 3


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no", action="append", default=[],
                    help="Yalnız bu kanun numarası; birden çok kez verilebilir")
    ap.add_argument("--liste", action="store_true", help="Yalnız say ve listele")
    ap.add_argument("--limit", type=int, default=None, help="En çok N kalem çek")
    ap.add_argument("--sleep", type=float, default=0.7,
                    help="İstekler arası bekleme (sn); RG dizin çekimiyle aynı tempo")
    ap.add_argument("--yeniden-bol", action="store_true",
                    help="Ağa çıkmadan kayıtlı RG metinlerini yeniden böl")
    args = ap.parse_args()
    t0 = time.time()
    if args.yeniden_bol:
        rc = yeniden_bol()
        _log(f"süre {time.time() - t0:.1f} sn, rc={rc}")
        sys.exit(rc)
    rc = asyncio.run(run([n.strip() for n in args.no if n.strip()], args.liste,
                         args.limit, args.sleep))
    _log(f"süre {time.time() - t0:.1f} sn, rc={rc}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
