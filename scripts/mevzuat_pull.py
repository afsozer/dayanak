"""Mevzuat korpusunu doldurur: listele → tam metni çek → maddelere böl → yaz.

Kullanım:

    python scripts/mevzuat_pull.py --tur KANUN
    python scripts/mevzuat_pull.py --tur KANUN --tur KHK --tur CBK
    python scripts/mevzuat_pull.py --tur KANUN --limit 5      # deneme
    python scripts/mevzuat_pull.py --tur KANUN --only-changed # haftalık

Kaldığı yerden devam eder: metni değişmemiş mevzuat atlanır (``metin_hash`` +
``guncelleme_tarihi`` karşılaştırması), yani yarıda kesilen bir çekim aynı
komutla sürdürülebilir. AMA bu atlama metin İNDİRİLDİKTEN sonra olur; tam
çekimin maliyeti belge sayısı × ~0,45 s'dir.

``--only-changed`` (Faz 2b) bu maliyeti kaldırır: metni indirmeden önce
"değişmiş mi" sorusu ucuz sinyallerle cevaplanır —

* Bedesten ``kayitTarihi`` (UYAP konsolide metni ne zaman yeniden yükledi),
  tür başına KAYIT_TARIHI azalan tek listeleme;
* listelemedeki RG tarih/sayısının DB'dekinden farklı olması;
* korpusta hiç bulunmama.

ÖLÇÜM (05.09.2026): mevzuat.gov.tr listelemesinde güncelleme tarihi ALANI YOK;
tek değişim sinyali Bedesten ``kayitTarihi``. Ayrıntı ``legislation_update``
modülünün başındaki nota bakın.

Değişen bir mevzuatın ESKİ metni üzerine yazılmadan önce
``mevzuat_dokuman_gecmis`` tablosuna arşivlenir.

Kaynak sırası: önce mevzuat.gov.tr (resmî konsolide metin), o başarısız
olursa Bedesten (``mevzuatNo`` ile arayıp ``getDocumentContent``). İkisi de
aynı konsolide metni veriyor; mevzuat.gov.tr güncel olanı.

Canlı MCP sunucusu aynı SQLite dosyasını okuduğu için yazmalar tek tek ve kısa
transaction'larla yapılır (``legislation_corpus.upsert_document``).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# mevzuat.gov.tr tür adı → Bedesten mevzuatTurList değeri (yedek kaynak).
BEDESTEN_TUR = {
    "KANUN": "KANUN",
    "KHK": "KHK",
    "TUZUK": "TUZUK",
    "YONETMELIK": "YONETMELIK",
    "CBK": "CB_KARARNAME",
    "CB_YONETMELIK": "CB_YONETMELIK",
    "CB_KARAR": "CB_KARAR",
    "KKY": "KKY",
    "UY": "UY",
    "TEBLIGLER": "TEBLIGLER",
    "MULGA": "MULGA",
}

# Kaynağın kendi "404 - Sayfa Bulunamadı" sayfası ~1,8 KB metin üretiyor;
# gerçek mevzuatın en kısası bile bunun çok üstünde. Yine de metin uzunluğuna
# değil, ContentStatus'e bakıyoruz — bu eşik sadece "boş geldi" kontrolü.
_MIN_TEXT = 200


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# mevzuat.gov.tr guvenlik duvari ~70 istek/5 dk sonra baglantiyi ~30 s kesiyor
# (ConnectError, 4xx yok; 5 Eyl 2026 olcumu: 70. sayfada dustu, 30 s sonra
# toparladi). Ag hatasinda bekleyip yeniden dene; cekim saatlerce surecegi icin
# tek bir kesinti butun kosuyu dusurmesin.
_BACKOFF = (30, 60, 120, 300, 600)


async def _with_backoff(fn, what: str):
    import httpx
    for i, wait in enumerate((*_BACKOFF, None)):
        try:
            return await fn()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError,
                httpx.ReadError, httpx.ConnectTimeout) as exc:
            if wait is None:
                raise
            _log(f"  ag hatasi ({what}): {type(exc).__name__}; {wait} s bekleniyor "
                 f"(deneme {i + 1}/{len(_BACKOFF)})")
            await asyncio.sleep(wait)


async def _list_all(client, tur_name: str, code: int, page_size: int, limit: int | None):
    """Bir türün tüm kayıtlarını sayfa sayfa listele; recordsTotal ile doğrula."""
    rows: list = []
    page = 1
    total = None
    while True:
        sp = await _with_backoff(
            lambda: client.search_page("", limit=page_size, page=page, mevzuat_tur=code),
            f"{tur_name} listeleme s.{page}",
        )
        if total is None:
            total = sp.total
            _log(f"{tur_name}: kaynak {total} kayıt bildiriyor")
        if not sp.results:
            break
        rows.extend(sp.results)
        if limit and len(rows) >= limit:
            rows = rows[:limit]
            break
        if total is not None and len(rows) >= total:
            break
        page += 1
        await asyncio.sleep(0.8)
    if limit is None and total is not None and len(rows) != total:
        _log(f"UYARI {tur_name}: listelenen {len(rows)} != bildirilen {total}")
    return rows, total


def _ikili(text: str) -> bool:
    """Ham PDF/ikili icerik metin diye gelmis mi? (13.09.2026: 3.619 CB karari %PDF- ile depolandi)"""
    head = text.lstrip()[:8]
    return head.startswith("%PDF") or "\x00" in text[:2000]


async def _fetch_text(mg_client, bd_client, doc_id: str, mevzuat_no: str, tur_name: str):
    """(metin, kaynak, kaynak_url, hata) — önce mevzuatgov, sonra Bedesten."""
    from emsal_mcp.models import ContentStatus

    try:
        doc = await _with_backoff(lambda: mg_client.get_document(doc_id), f"belge {doc_id}")
        text = doc.full_text or ""
        if _ikili(text):
            return "", "", "", "mevzuatgov: PDF ikili icerik (taranmis belge)"
        if doc.content_status == ContentStatus.HTML_MARKDOWN and len(text) >= _MIN_TEXT:
            return text, "mevzuatgov", doc.source_url or "", ""
        mg_err = f"mevzuatgov status={doc.content_status} len={len(text)}"
    except Exception as exc:  # ağ/parse hatası — yedek kaynağa düş
        mg_err = f"mevzuatgov {type(exc).__name__}: {exc}"

    bd_tur = BEDESTEN_TUR.get(tur_name)
    try:
        hits = await bd_client.search(
            "", limit=5, mevzuat_no=mevzuat_no,
            **({"mevzuat_tur_list": [bd_tur]} if bd_tur else {}),
        )
        if not hits:
            return "", "", "", f"{mg_err}; bedesten: kayıt yok"
        bdoc = await bd_client.get_document(hits[0].document_id)
        btext = bdoc.full_text or ""
        if _ikili(btext):
            return "", "", "", f"{mg_err}; bedesten: PDF ikili icerik"
        if len(btext) >= _MIN_TEXT:
            return btext, "mevzuat", bdoc.source_url or "", ""
        return "", "", "", f"{mg_err}; bedesten len={len(btext)}"
    except Exception as exc:
        return "", "", "", f"{mg_err}; bedesten {type(exc).__name__}: {exc}"


async def run(turler: list[str], limit: int | None, sleep: float, page_size: int,
              force: bool, only_changed: bool = False,
              gun_sayisi: int = 10) -> int:
    from emsal_mcp.cache import Cache
    from emsal_mcp import legislation_corpus as lc
    from emsal_mcp import legislation_update as lu
    from emsal_mcp.sources.mevzuat import MevzuatClient
    from emsal_mcp.sources.mevzuatgov import TYPE_CODES, MevzuatGovClient

    unknown = [t for t in turler if t not in TYPE_CODES]
    if unknown:
        _log(f"HATA: bilinmeyen tür {unknown}; geçerli: {sorted(TYPE_CODES)}")
        return 2

    cache = Cache()
    db = cache.db
    lc.ensure_schema(db)
    lu.ensure_update_schema(db)
    _log(f"cache: {cache.path}")

    mg = MevzuatGovClient()
    bd = MevzuatClient()

    toplam = {"belge": 0, "madde": 0, "yeni": 0, "guncel": 0, "atlanan": 0, "hata": 0}
    hatalar: list[tuple[str, str, str]] = []
    t0 = time.time()

    # ── --only-changed: ucuz değişim sinyallerini bir kez topla ──────────
    ozet: dict[str, dict[str, str]] = {}
    taze: set[tuple[str, str]] = set()
    if only_changed:
        ozet = lu.db_ozet(db)
        esik = (datetime.now(timezone.utc) - timedelta(days=gun_sayisi)).date().isoformat()
        t_taze = time.time()
        taze, taze_detay = await lu.taze_kayitlar(bd, turler, esik)
        _log(
            f"only-changed: korpusta {len(ozet)} belge; Bedesten'de {esik} sonrası "
            f"yeniden yüklenen {len(taze)} kayıt ({time.time() - t_taze:.1f} s)"
        )
        for d in taze_detay[:30]:
            _log(f"  taze: {d['tur']} {d['mevzuat_no']} {d['kayit_tarihi']} {d['ad'][:50]}")

    kosu_zamani = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for tur_name in turler:
        code = TYPE_CODES[tur_name]
        t_tur = time.time()
        tur_sayac = {"degisen": 0, "yeni": 0, "hata": 0}
        rows, total = await _list_all(mg, tur_name, code, page_size, limit)
        _log(f"{tur_name}: {len(rows)} kayıt işlenecek")
        for i, r in enumerate(rows, 1):
            meta = r.metadata or {}
            no = str(meta.get("mevzuat_no") or r.karar_no or "")
            if only_changed and not force:
                cek, sebep = lu.cekilsin_mi(
                    r.document_id, tur=tur_name, mevzuat_no=no,
                    rg_tarihi=str(meta.get("resmi_gazete_tarihi") or ""),
                    rg_sayisi=str(meta.get("resmi_gazete_sayisi") or ""),
                    ozet=ozet, taze=taze,
                )
                if not cek:
                    toplam["atlanan"] += 1
                    continue
                tur_sayac["yeni" if sebep == "yeni" else "degisen"] += 1
                _log(f"  ÇEK ({sebep}) {r.document_id} {r.title[:60]}")
            metin, kaynak, url, err = await _fetch_text(mg, bd, r.document_id, no, tur_name)
            if not metin:
                toplam["hata"] += 1
                tur_sayac["hata"] += 1
                hatalar.append((r.document_id, r.title[:60], err[:160]))
                _log(f"  HATA {r.document_id} {r.title[:50]} — {err[:120]}")
                await asyncio.sleep(sleep)
                continue
            # Üzerine yazmadan önce eski metni arşivle (metin gerçekten
            # değiştiyse; aynıysa arşiv kopyası çöp olurdu).
            eski = ozet.get(r.document_id) if only_changed else None
            if eski is None:
                eski_row = db.execute(
                    "SELECT metin_hash FROM mevzuat_dokuman WHERE mevzuat_id = ?",
                    (r.document_id,),
                ).fetchone()
                eski_hash = eski_row[0] if eski_row else None
            else:
                eski_hash = eski.get("metin_hash") or None
            if eski_hash and eski_hash != lc._hash(metin):
                lu.arsivle(db, r.document_id)
            res = lc.upsert_document(
                db,
                mevzuat_id=r.document_id,
                metin=metin,
                kaynak=kaynak,
                tur=tur_name,
                mevzuat_no=no,
                tertip=str(meta.get("mevzuat_tertip") or ""),
                ad=r.title,
                kabul_tarihi=str(meta.get("kabul_tarihi") or ""),
                rg_tarihi=str(meta.get("resmi_gazete_tarihi") or ""),
                rg_sayisi=str(meta.get("resmi_gazete_sayisi") or ""),
                guncelleme_tarihi=str(meta.get("resmi_gazete_tarihi") or ""),
                kaynak_url=url or (r.source_url or ""),
                meta=meta,
                force=force,
            )
            toplam["belge"] += 1
            toplam["madde"] += res["madde_sayisi"]
            key = {"inserted": "yeni", "updated": "guncel", "skipped": "atlanan"}[res["status"]]
            toplam[key] += 1
            if i % 25 == 0 or i == len(rows):
                _log(
                    f"  {tur_name} {i}/{len(rows)} — yeni {toplam['yeni']}, "
                    f"güncel {toplam['guncel']}, atlanan {toplam['atlanan']}, "
                    f"hata {toplam['hata']}, madde {toplam['madde']}"
                )
            if res["status"] != "skipped":
                await asyncio.sleep(sleep)
        lu.kosu_yaz(
            db, tur=tur_name, listelenen=len(rows),
            degisen=tur_sayac["degisen"], yeni=tur_sayac["yeni"],
            hata=tur_sayac["hata"], sure_s=time.time() - t_tur,
            kosu_zamani=kosu_zamani,
        )

    stats = lc.corpus_stats(db)
    cache.close()
    sure = time.time() - t0
    _log("─" * 60)
    _log(f"BİTTİ ({sure/60:.1f} dk) — işlenen {toplam['belge']} belge, "
         f"{toplam['madde']} madde")
    _log(f"  yeni={toplam['yeni']} güncel={toplam['guncel']} "
         f"atlanan={toplam['atlanan']} hata={toplam['hata']}")
    _log(f"  korpus toplamı: {stats['belge_sayisi']} belge, "
         f"{stats['madde_sayisi']} madde, türler={stats['turler']}")
    if hatalar:
        _log(f"HATALI KİMLİKLER ({len(hatalar)}):")
        for did, ad, err in hatalar:
            _log(f"  {did} | {ad} | {err}")
    return 1 if toplam["hata"] and not toplam["belge"] else 0


def resplit() -> int:
    """Ağa çıkmadan, saklanan metinden maddeleri yeniden böl.

    Madde ayrıştırıcısı (başlık çıkarımı, değişiklik notu) geliştiğinde
    korpusu yeniden çekmeye gerek yok: metin zaten kayıtlı.
    """
    from emsal_mcp.cache import Cache
    from emsal_mcp import legislation_corpus as lc

    cache = Cache()
    db = cache.db
    lc.ensure_schema(db)
    ids = [r[0] for r in db.execute("SELECT mevzuat_id FROM mevzuat_dokuman")]
    _log(f"yeniden bölünecek: {len(ids)} belge")
    madde = 0
    for i, mid in enumerate(ids, 1):
        row = db.execute(
            """SELECT kaynak, tur, mevzuat_no, tertip, ad, kabul_tarihi, rg_tarihi,
                      rg_sayisi, guncelleme_tarihi, metin, kaynak_url, meta_json
               FROM mevzuat_dokuman WHERE mevzuat_id = ?""",
            (mid,),
        ).fetchone()
        res = lc.upsert_document(
            db, mevzuat_id=mid, metin=row[9] or "", kaynak=row[0] or "", tur=row[1] or "",
            mevzuat_no=row[2] or "", tertip=row[3] or "", ad=row[4] or "",
            kabul_tarihi=row[5] or "", rg_tarihi=row[6] or "", rg_sayisi=row[7] or "",
            guncelleme_tarihi=row[8] or "", kaynak_url=row[10] or "",
            meta=json.loads(row[11] or "{}"), force=True,
        )
        madde += res["madde_sayisi"]
        if i % 100 == 0 or i == len(ids):
            _log(f"  {i}/{len(ids)} — {madde} madde")
    stats = lc.corpus_stats(db)
    cache.close()
    _log(f"BİTTİ — korpus: {stats['belge_sayisi']} belge, {stats['madde_sayisi']} madde")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Mevzuat korpusunu doldur")
    ap.add_argument("--tur", action="append",
                    help="Mevzuat türü (KANUN, KHK, CBK, YONETMELIK, TEBLIGLER, ...); "
                         "birden çok kez verilebilir")
    ap.add_argument("--limit", type=int, default=None, help="Tür başına en fazla N kayıt")
    ap.add_argument("--sleep", type=float, default=0.5, help="İstekler arası bekleme (sn)")
    ap.add_argument("--page-size", type=int, default=100, help="Listeleme sayfa boyutu")
    ap.add_argument("--force", action="store_true", help="Değişmemiş olsa da yeniden yaz")
    ap.add_argument("--only-changed", action="store_true",
                    help="Yalnız yeni/değişmiş mevzuatın metnini indir "
                         "(Bedesten kayitTarihi + RG tarih/sayı sinyalleri)")
    ap.add_argument("--gun", type=int, default=10,
                    help="--only-changed eşiği: son N günde yeniden yüklenenler "
                         "(haftalık koşu için 10; bir günlük pay bırakır)")
    ap.add_argument("--resplit", action="store_true",
                    help="Ağa çıkmadan saklanan metinlerden maddeleri yeniden böl")
    args = ap.parse_args()
    if args.resplit:
        sys.exit(resplit())
    if not args.tur:
        ap.error("--tur ya da --resplit verin")
    sys.exit(asyncio.run(run([t.strip().upper() for t in args.tur], args.limit,
                             args.sleep, args.page_size, args.force,
                             args.only_changed, args.gun)))


if __name__ == "__main__":
    main()
