"""Yerel mevzuat korpusu — şema, madde ayrımı ve FTS5 araması (Faz 1).

Neden var: ``legislation.py`` her soruda kaynağa (mevzuat.gov.tr / Bedesten)
gidiyor; tek bir maddeyi görmek için 300 KB'lık konsolide metin indiriliyor ve
"hangi kanunun hangi maddesi bu kavramı düzenliyor" sorusu hiç cevaplanamıyor.
Bu modül aynı ``cache.sqlite3`` içinde iki tablo tutar (``mevzuat_dokuman``,
``mevzuat_madde``) ve maddeleri FTS5 üzerinden aratır.

Tasarım notları:

* Madde ayrımı için YENİ bir ayrıştırıcı yazılmadı — ``legislation._ARTICLE_RE``
  ve ``legislation._parse_articles`` yeniden kullanılıyor. İki farklı madde
  numaralandırması (biri araçta, biri korpusta) en kötü hata türü olurdu.
* ``(Değişik: …)`` / ``(Mülga: …)`` / ``(Ek: …)`` parantezleri ve ``[n]``
  dipnot numaraları ``degisiklik_notu``na HAM olarak toplanır. Tarih/sayı
  ayrıştırması Faz 2 işidir; burada ayrıştırmak, yanlış ayrıştırmayı veriye
  yazmak demek olurdu.
* ``ensure_schema`` üretimde 72 GB'lık canlı cache üzerinde çalışıyor:
  yalnızca CREATE IF NOT EXISTS yapar, ``documents_v2``ye dokunmaz, tam tablo
  taraması yapmaz.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .legislation import _ARTICLE_RE, _normative_body, _norm_article_no, _parse_articles

CORPUS_VERSION = "1.0.0"

# ── Şema ────────────────────────────────────────────────────────────────────

_DOKUMAN_TABLE = """\
CREATE TABLE IF NOT EXISTS mevzuat_dokuman (
    mevzuat_id TEXT PRIMARY KEY,
    kaynak TEXT,
    tur TEXT,
    mevzuat_no TEXT,
    tertip TEXT,
    ad TEXT,
    kabul_tarihi TEXT,
    rg_tarihi TEXT,
    rg_sayisi TEXT,
    guncelleme_tarihi TEXT,
    metin TEXT,
    metin_hash TEXT,
    madde_sayisi INTEGER,
    cekim_zamani TEXT,
    kaynak_url TEXT,
    meta_json TEXT
);"""

_DOKUMAN_NO_INDEX = (
    "CREATE INDEX IF NOT EXISTS mevzuat_dokuman_no ON mevzuat_dokuman(mevzuat_no, tur);"
)

_MADDE_TABLE = """\
CREATE TABLE IF NOT EXISTS mevzuat_madde (
    mevzuat_id TEXT NOT NULL,
    madde_no TEXT,
    sira INTEGER NOT NULL,
    baslik TEXT,
    metin TEXT,
    degisiklik_notu TEXT,
    PRIMARY KEY (mevzuat_id, sira)
);"""

_MADDE_NO_INDEX = (
    "CREATE INDEX IF NOT EXISTS mevzuat_madde_no ON mevzuat_madde(mevzuat_id, madde_no);"
)

_MADDE_FTS = """\
CREATE VIRTUAL TABLE IF NOT EXISTS mevzuat_madde_fts USING fts5(
    madde_no, baslik, metin,
    content='mevzuat_madde',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);"""

_MADDE_TRIGGER_AI = """\
CREATE TRIGGER IF NOT EXISTS mevzuat_madde_ai AFTER INSERT ON mevzuat_madde BEGIN
    INSERT INTO mevzuat_madde_fts(rowid, madde_no, baslik, metin)
    VALUES (new.rowid, new.madde_no, new.baslik, new.metin);
END;"""

_MADDE_TRIGGER_AD = """\
CREATE TRIGGER IF NOT EXISTS mevzuat_madde_ad AFTER DELETE ON mevzuat_madde BEGIN
    INSERT INTO mevzuat_madde_fts(mevzuat_madde_fts, rowid, madde_no, baslik, metin)
    VALUES ('delete', old.rowid, old.madde_no, old.baslik, old.metin);
END;"""

_MADDE_TRIGGER_AU = """\
CREATE TRIGGER IF NOT EXISTS mevzuat_madde_au AFTER UPDATE ON mevzuat_madde BEGIN
    INSERT INTO mevzuat_madde_fts(mevzuat_madde_fts, rowid, madde_no, baslik, metin)
    VALUES ('delete', old.rowid, old.madde_no, old.baslik, old.metin);
    INSERT INTO mevzuat_madde_fts(rowid, madde_no, baslik, metin)
    VALUES (new.rowid, new.madde_no, new.baslik, new.metin);
END;"""


def ensure_schema(db: sqlite3.Connection) -> bool:
    """Korpus tablolarını/tetikleyicilerini kur (idempotent).

    ``semantic._ensure_fts5`` ile aynı sözleşme: tablolar zaten varsa True
    döner. Var olan satırlara dokunmaz.
    """
    existing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mevzuat_dokuman'"
    ).fetchone()
    already_existed = existing is not None

    db.execute(_DOKUMAN_TABLE)
    db.execute(_DOKUMAN_NO_INDEX)
    db.execute(_MADDE_TABLE)
    db.execute(_MADDE_NO_INDEX)
    db.execute(_MADDE_FTS)
    db.execute(_MADDE_TRIGGER_AI)
    db.execute(_MADDE_TRIGGER_AD)
    db.execute(_MADDE_TRIGGER_AU)
    db.commit()
    return already_existed


# ── Madde ayrımı ────────────────────────────────────────────────────────────

# Bir maddenin gövdesindeki değişiklik parantezleri. İç içe bir seviye
# parantez kapsanır: "(Değişik: 6/12/2019-7196/54 md.)" gibi kısa olanlar da,
# "(Ek fıkra: … (Değişik ibare: …) …)" gibi bir seviye iç içe olanlar da.
_NOTE_PAREN_RE = re.compile(
    r"\((?:[^()]|\([^()]*\))*\)",
)
_NOTE_HEAD_RE = re.compile(
    r"^\(\s*(?:De[ğg]i[şs]ik|M[üu]lga|Ek|[İIi]ptal|Yeniden\s+d[üu]zenle|Y[üu]r[üu]rl[üu]kten)",
    re.IGNORECASE,
)
_FOOTNOTE_RE = re.compile(r"\[\d+\]")
# Madde başlığı olamayacak satırlar: sırf dipnot numarası, sırf sayfa/­bölüm
# işareti ya da bir önceki maddenin son cümlesi (nokta ile biten uzun satır).
_HEADING_SKIP_RE = re.compile(r"^(?:\[\d+\]|[\d\W_]+)$")


def _heading_before(text: str, pos: int) -> str:
    """``pos`` konumundan önceki kenar başlığı (madde başlığı).

    Türk mevzuatında madde başlığı, "MADDE 12 -" satırının hemen üstündeki
    kısa satırdır ("Zamanaşımı", "Görev ve yetki"). Bir önceki maddenin son
    cümlesini başlık sanmamak için nokta ile biten ve uzun olan satırlar
    elenir.
    """
    head = text[:pos].rstrip()
    parts: list[str] = []
    for line in reversed(head.splitlines()[-4:]):
        line = _FOOTNOTE_RE.sub("", line.strip()).strip()
        if not line or _HEADING_SKIP_RE.match(line):
            if parts:
                break
            continue
        if len(line) > 120 or line.endswith((".", "!", "?", ":", ";")):
            # Cümle sonu = bir önceki maddenin gövdesi, başlık değil (6100
            # m.390'da "...uygulanır." satırı başlığa yapışıyordu).
            break
        # Başlık kaynak markup'ında satırlara bölünmüş olabiliyor ("Yeni" /
        # "işverenin sorumluluğu" — 4857 m.23'te ölçüldü). Yalnız son satırı
        # almak başlığın yarısını kaybettiriyordu; başlık boyuna ulaşana kadar
        # geriye doğru birleştir.
        parts.insert(0, line)
        if len(" ".join(parts)) >= 40:
            break
    return " ".join(parts)[:200]


def _degisiklik_notu(body: str) -> str:
    """Madde gövdesindeki değişiklik parantezleri + dipnot numaraları (ham)."""
    parts: list[str] = []
    for m in _NOTE_PAREN_RE.finditer(body):
        chunk = m.group(0)
        if _NOTE_HEAD_RE.match(chunk):
            parts.append(re.sub(r"\s+", " ", chunk).strip())
    parts.extend(_FOOTNOTE_RE.findall(body))
    # Aynı parantez birden çok fıkrada tekrar edebilir; sırayı bozmadan tekille.
    seen: set[str] = set()
    uniq = [p for p in parts if not (p in seen or seen.add(p))]
    return " | ".join(uniq)


def _strip_trailing_heading(metin: str, next_baslik: str) -> str:
    """Bir sonraki maddenin kenar başlığını gövdenin sonundan at.

    ``_ARTICLE_RE`` maddeyi "MADDE n"den "MADDE n+1"e kadar alıyor; aradaki
    kenar başlığı bu yüzden ÖNCEKİ maddenin gövdesinin sonuna yapışıyor.
    Ölçüldü (5 Eyl 2026): 4857 m.23'ün metni "İşçinin haklı nedenle derhal
    fesih hakkı" ile bitiyordu ve o sorgu m.23'ü m.24'ten önce getiriyordu.
    """
    if not next_baslik:
        return metin
    lines = metin.rstrip().split("\n")
    for j in range(1, min(5, len(lines)) + 1):
        tail = " ".join(x.strip() for x in lines[-j:]).strip()
        if tail == next_baslik.strip():
            return "\n".join(lines[:-j]).rstrip()
    return metin


def split_articles(text: str) -> list[dict[str, Any]]:
    """Konsolide metni maddelere böl.

    ``legislation._parse_articles`` numarayı ve gövdeyi verir; buraya ek olarak
    kenar başlığı ve ham değişiklik notu çıkarılır. İki liste aynı regex'in
    aynı sırayla ürettiği eşleşmeler olduğu için birebir hizalıdır.
    """
    parsed = _parse_articles(text)
    body = _normative_body(text)
    spans = [m.start() for m in _ARTICLE_RE.finditer(body)]
    out: list[dict[str, Any]] = []
    for i, art in enumerate(parsed):
        pos = spans[i] if i < len(spans) else 0
        out.append({
            "madde_no": art["number"],
            "sira": i + 1,
            "baslik": _heading_before(body, pos) if pos else "",
            "metin": art["raw_text"],
            "degisiklik_notu": _degisiklik_notu(art["text"]),
        })
    for i in range(len(out) - 1):
        out[i]["metin"] = _strip_trailing_heading(out[i]["metin"], out[i + 1]["baslik"])
    return out


# ── Yazma ───────────────────────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def upsert_document(
    db: sqlite3.Connection,
    *,
    mevzuat_id: str,
    metin: str,
    kaynak: str = "",
    tur: str = "",
    mevzuat_no: str = "",
    tertip: str = "",
    ad: str = "",
    kabul_tarihi: str = "",
    rg_tarihi: str = "",
    rg_sayisi: str = "",
    guncelleme_tarihi: str = "",
    kaynak_url: str = "",
    meta: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Bir mevzuatı (ve maddelerini) yaz. Değişmemişse dokunma.

    Dönüş: ``{"status": "inserted"|"updated"|"skipped", "madde_sayisi": n}``.
    ``status`` "skipped" ise tek bir yazma bile yapılmaz — çekim kaldığı
    yerden devam edebilsin diye.

    Yazma tek ve kısa bir transaction'dır: canlı sunucu aynı WAL dosyasını
    okuyor, uzun transaction yazarı bloklar.
    """
    metin_hash = _hash(metin)
    row = db.execute(
        "SELECT metin_hash, guncelleme_tarihi FROM mevzuat_dokuman WHERE mevzuat_id = ?",
        (mevzuat_id,),
    ).fetchone()
    if row and not force:
        if row[0] == metin_hash and (row[1] or "") == (guncelleme_tarihi or ""):
            n = db.execute(
                "SELECT COUNT(*) FROM mevzuat_madde WHERE mevzuat_id = ?", (mevzuat_id,)
            ).fetchone()[0]
            return {"status": "skipped", "madde_sayisi": n}

    maddeler = split_articles(metin)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM mevzuat_madde WHERE mevzuat_id = ?", (mevzuat_id,))
        db.execute(
            """INSERT OR REPLACE INTO mevzuat_dokuman (
                mevzuat_id, kaynak, tur, mevzuat_no, tertip, ad, kabul_tarihi,
                rg_tarihi, rg_sayisi, guncelleme_tarihi, metin, metin_hash,
                madde_sayisi, cekim_zamani, kaynak_url, meta_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mevzuat_id, kaynak, tur, str(mevzuat_no), str(tertip), ad,
                kabul_tarihi, rg_tarihi, rg_sayisi, guncelleme_tarihi, metin,
                metin_hash, len(maddeler), now, kaynak_url,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        db.executemany(
            """INSERT INTO mevzuat_madde
               (mevzuat_id, madde_no, sira, baslik, metin, degisiklik_notu)
               VALUES (?,?,?,?,?,?)""",
            [
                (
                    mevzuat_id, m["madde_no"], m["sira"], m["baslik"],
                    m["metin"], m["degisiklik_notu"],
                )
                for m in maddeler
            ],
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"status": "updated" if row else "inserted", "madde_sayisi": len(maddeler)}


# ── Arama ───────────────────────────────────────────────────────────────────

# FTS5'in sorgu dilinde anlamı olan her şey ("AND", tırnak, yıldız, iki nokta,
# parantez) kullanıcı sorgusundan temizlenir: aksi hâlde "m. 6/A" gibi bir
# ifade sözdizimi hatasıyla düşer.
_FTS_TOKEN_RE = re.compile(r"[0-9A-Za-zÇçĞğIıİiÖöŞşÜü]+")


def _fts_query(query: str) -> str:
    """Ham kelimeleri AND'li, tırnaklanmış bir FTS5 sorgusuna çevir."""
    tokens = _FTS_TOKEN_RE.findall(query or "")
    return " AND ".join(f'"{t}"' for t in tokens)


def search_madde(
    db: sqlite3.Connection,
    query: str,
    mevzuat_no: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Korpustaki maddelerde FTS5 (BM25) araması.

    Dönüş: ``{"ok": True, "query": ..., "results": [...], "total_matches": n}``.
    Her sonuçta mevzuat adı/numarası, madde numarası, başlık, snippet ve
    kaynak URL bulunur.
    """
    ensure_schema(db)
    match = _fts_query(query)
    if not match:
        return {
            "ok": False,
            "errorCode": "INVALID_INPUT",
            "message": "Sorgu boş ya da yalnızca noktalama içeriyor.",
            "results": [],
            "total_matches": 0,
        }

    sql = """
        SELECT d.mevzuat_id, d.mevzuat_no, d.tur, d.ad, d.kaynak_url,
               m.madde_no, m.baslik, m.degisiklik_notu,
               snippet(mevzuat_madde_fts, 2, '«', '»', ' … ', 24) AS snip,
               bm25(mevzuat_madde_fts) AS skor
        FROM mevzuat_madde_fts
        JOIN mevzuat_madde m ON m.rowid = mevzuat_madde_fts.rowid
        JOIN mevzuat_dokuman d ON d.mevzuat_id = m.mevzuat_id
        WHERE mevzuat_madde_fts MATCH ?
    """
    params: list[Any] = [match]
    if mevzuat_no is not None and str(mevzuat_no).strip():
        sql += " AND d.mevzuat_no = ?"
        params.append(str(mevzuat_no).strip())
    sql += " ORDER BY skor LIMIT ?"
    params.append(max(1, int(limit)))

    rows = db.execute(sql, params).fetchall()
    results = [
        {
            "mevzuat_id": r[0],
            "mevzuat_no": r[1],
            "tur": r[2],
            "mevzuat_adi": r[3],
            "kaynak_url": r[4],
            "madde_no": r[5],
            "baslik": r[6],
            "degisiklik_notu": r[7],
            "snippet": r[8],
            "skor": round(float(r[9]), 4),
        }
        for r in rows
    ]
    return {
        "ok": True,
        "query": query,
        "fts_query": match,
        "results": results,
        "total_matches": len(results),
    }


def get_madde(
    db: sqlite3.Connection,
    mevzuat_no: str,
    madde_no: str,
) -> dict[str, Any]:
    """Tek bir maddenin tam metni.

    ``madde_no`` "12", "12/A", "Geçici 1", "geçici 1" hepsi aynı maddeye
    çözülür — karşılaştırma ``legislation._norm_article_no`` ile yapılır, yani
    araç yüzeyindeki numaralandırmayla birebir aynı.
    """
    ensure_schema(db)
    rows = db.execute(
        """SELECT d.mevzuat_id, d.mevzuat_no, d.tur, d.ad, d.kaynak_url,
                  m.madde_no, m.sira, m.baslik, m.metin, m.degisiklik_notu
           FROM mevzuat_madde m
           JOIN mevzuat_dokuman d ON d.mevzuat_id = m.mevzuat_id
           WHERE d.mevzuat_no = ?
           ORDER BY m.sira""",
        (str(mevzuat_no).strip(),),
    ).fetchall()
    if not rows:
        return {
            "ok": False,
            "errorCode": "NOT_FOUND",
            "message": (
                f"{mevzuat_no} sayılı mevzuat yerel korpusta yok. Korpus yalnızca "
                "çekilmiş mevzuatı içerir; çekmek için scripts/mevzuat_pull.py, "
                "canlı sorgu için search_legislation/get_legislation kullanın."
            ),
        }

    target = _norm_article_no(str(madde_no))
    for r in rows:
        if _norm_article_no(str(r[5])) == target:
            return {
                "ok": True,
                "mevzuat_id": r[0],
                "mevzuat_no": r[1],
                "tur": r[2],
                "mevzuat_adi": r[3],
                "kaynak_url": r[4],
                "madde_no": r[5],
                "sira": r[6],
                "baslik": r[7],
                "metin": r[8],
                "degisiklik_notu": r[9],
            }
    return {
        "ok": False,
        "errorCode": "NOT_FOUND",
        "message": (
            f"{mevzuat_no} sayılı mevzuatta '{madde_no}' maddesi bulunamadı "
            f"({len(rows)} madde kayıtlı)."
        ),
        "mevzuat_adi": rows[0][3],
        "mevcut_madde_sayisi": len(rows),
    }


def corpus_stats(db: sqlite3.Connection) -> dict[str, Any]:
    """Korpus özeti (belge/madde sayısı, türlere göre dağılım)."""
    ensure_schema(db)
    belge = db.execute("SELECT COUNT(*) FROM mevzuat_dokuman").fetchone()[0]
    madde = db.execute("SELECT COUNT(*) FROM mevzuat_madde").fetchone()[0]
    turler = {
        row[0] or "": row[1]
        for row in db.execute(
            "SELECT tur, COUNT(*) FROM mevzuat_dokuman GROUP BY tur ORDER BY 2 DESC"
        ).fetchall()
    }
    return {"belge_sayisi": belge, "madde_sayisi": madde, "turler": turler}
