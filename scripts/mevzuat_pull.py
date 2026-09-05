"""Mevzuat korpusunu doldurur: listele → tam metni çek → maddelere böl → yaz.

Kullanım:

    python scripts/mevzuat_pull.py --tur KANUN
    python scripts/mevzuat_pull.py --tur KANUN --tur KHK --tur CBK
    python scripts/mevzuat_pull.py --tur KANUN --limit 5      # deneme

Kaldığı yerden devam eder: metni değişmemiş mevzuat atlanır (``metin_hash`` +
``guncelleme_tarihi`` karşılaştırması), yani yarıda kesilen bir çekim aynı
komutla sürdürülebilir.

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


async def _list_all(client, tur_name: str, code: int, page_size: int, limit: int | None):
    """Bir türün tüm kayıtlarını sayfa sayfa listele; recordsTotal ile doğrula."""
    rows: list = []
    page = 1
    total = None
    while True:
        sp = await client.search_page("", limit=page_size, page=page, mevzuat_tur=code)
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
        await asyncio.sleep(0.5)
    if limit is None and total is not None and len(rows) != total:
        _log(f"UYARI {tur_name}: listelenen {len(rows)} != bildirilen {total}")
    return rows, total


async def _fetch_text(mg_client, bd_client, doc_id: str, mevzuat_no: str, tur_name: str):
    """(metin, kaynak, kaynak_url, hata) — önce mevzuatgov, sonra Bedesten."""
    from emsal_mcp.models import ContentStatus

    try:
        doc = await mg_client.get_document(doc_id)
        text = doc.full_text or ""
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
        if len(btext) >= _MIN_TEXT:
            return btext, "mevzuat", bdoc.source_url or "", ""
        return "", "", "", f"{mg_err}; bedesten len={len(btext)}"
    except Exception as exc:
        return "", "", "", f"{mg_err}; bedesten {type(exc).__name__}: {exc}"


async def run(turler: list[str], limit: int | None, sleep: float, page_size: int,
              force: bool) -> int:
    from emsal_mcp.cache import Cache
    from emsal_mcp import legislation_corpus as lc
    from emsal_mcp.sources.mevzuat import MevzuatClient
    from emsal_mcp.sources.mevzuatgov import TYPE_CODES, MevzuatGovClient

    unknown = [t for t in turler if t not in TYPE_CODES]
    if unknown:
        _log(f"HATA: bilinmeyen tür {unknown}; geçerli: {sorted(TYPE_CODES)}")
        return 2

    cache = Cache()
    db = cache.db
    lc.ensure_schema(db)
    _log(f"cache: {cache.path}")

    mg = MevzuatGovClient()
    bd = MevzuatClient()

    toplam = {"belge": 0, "madde": 0, "yeni": 0, "guncel": 0, "atlanan": 0, "hata": 0}
    hatalar: list[tuple[str, str, str]] = []
    t0 = time.time()

    for tur_name in turler:
        code = TYPE_CODES[tur_name]
        rows, total = await _list_all(mg, tur_name, code, page_size, limit)
        _log(f"{tur_name}: {len(rows)} kayıt işlenecek")
        for i, r in enumerate(rows, 1):
            meta = r.metadata or {}
            no = str(meta.get("mevzuat_no") or r.karar_no or "")
            metin, kaynak, url, err = await _fetch_text(mg, bd, r.document_id, no, tur_name)
            if not metin:
                toplam["hata"] += 1
                hatalar.append((r.document_id, r.title[:60], err[:160]))
                _log(f"  HATA {r.document_id} {r.title[:50]} — {err[:120]}")
                await asyncio.sleep(sleep)
                continue
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
    ap.add_argument("--resplit", action="store_true",
                    help="Ağa çıkmadan saklanan metinlerden maddeleri yeniden böl")
    args = ap.parse_args()
    if args.resplit:
        sys.exit(resplit())
    if not args.tur:
        ap.error("--tur ya da --resplit verin")
    sys.exit(asyncio.run(run([t.strip().upper() for t in args.tur], args.limit,
                             args.sleep, args.page_size, args.force)))


if __name__ == "__main__":
    main()
