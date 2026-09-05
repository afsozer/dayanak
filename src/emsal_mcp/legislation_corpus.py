"""Yerel mevzuat korpusu — şema, madde ayrımı, FTS5 araması, değişiklik ayrımı.

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
  dipnot numaraları ``degisiklik_notu``na HAM olarak da tutulmaya devam eder;
  Faz 2a bunları AYRICA ``mevzuat_degisiklik`` tablosuna yapılandırarak yazar
  (``parse_degisiklik``). Ayrıştırılamayan not KAYBOLMAZ, ``ham`` alanında
  durur — ölçüm için ``tarih``in dolu olup olmadığına bakılır.
* Belge sonundaki ``[n]`` dipnot gövdeleri (``parse_footnotes``) maddedeki
  ``[n]`` işaretiyle eşlenir; "hangi kanun bu fıkrayı ne zaman değiştirdi"
  bilgisinin parantezlerde olmayan yarısı oradadır.
* ``ensure_schema`` üretimde 72 GB'lık canlı cache üzerinde çalışıyor:
  yalnızca CREATE IF NOT EXISTS / eksikse tek ALTER yapar, ``documents_v2``ye
  dokunmaz, tam tablo taraması yapmaz.
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

# Faz 2a: madde başlığının üstündeki hiyerarşik kenar başlıkları ("F. Konut ve
# çatılı işyeri kiralarında sözleşmenin sona ermesi > I. Bildirim yoluyla").
# ALTER ile eklenir; Faz 1'de doldurulmuş tabloları düşürmemek için.
_MADDE_UST_BASLIK_COL = "ALTER TABLE mevzuat_madde ADD COLUMN ust_baslik TEXT"

_DEGISIKLIK_TABLE = """\
CREATE TABLE IF NOT EXISTS mevzuat_degisiklik (
    mevzuat_id TEXT NOT NULL,
    sira INTEGER NOT NULL,
    kapsam TEXT,
    tur TEXT,
    tarih TEXT,
    degistiren_no TEXT,
    degistiren_madde TEXT,
    rg_tarihi TEXT,
    rg_sayisi TEXT,
    aym_esas TEXT,
    aym_karar TEXT,
    ham TEXT,
    dipnot_no INTEGER
);"""

_DEGISIKLIK_INDEX = (
    "CREATE INDEX IF NOT EXISTS mevzuat_degisiklik_madde "
    "ON mevzuat_degisiklik(mevzuat_id, sira);"
)
_DEGISIKLIK_KAYNAK_INDEX = (
    "CREATE INDEX IF NOT EXISTS mevzuat_degisiklik_kaynak "
    "ON mevzuat_degisiklik(degistiren_no, tarih);"
)

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
    cols = {r[1] for r in db.execute("PRAGMA table_info(mevzuat_madde)").fetchall()}
    if "ust_baslik" not in cols:
        db.execute(_MADDE_UST_BASLIK_COL)
    db.execute(_DEGISIKLIK_TABLE)
    db.execute(_DEGISIKLIK_INDEX)
    db.execute(_DEGISIKLIK_KAYNAK_INDEX)
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
    r"^\(\s*(?:De[ğg]i[şs]ik|De[ğg]i[şs]tirilerek|M[üu]lga|Ek|[İIi]ptal"
    r"|Aynen\s+kabul|Yeniden\s+d[üu]zenle|Y[üu]r[üu]rl[üu]kten)",
    re.IGNORECASE,
)
# Gerçek bir değişiklik notu ya bir tarih ya da bir AYM kararı içerir.
# Ölçüldü (5 Eyl 2026, 29 kanun): bu süzgeç olmadan "(ek gösterge dahil)",
# "(Ekim ayı dahil)", "(Ek Madde 1, Ek Madde 2, …)" gibi 17 yanlış eşleşme
# değişiklik notu diye kaydediliyordu.
_NOTE_EVIDENCE_RE = re.compile(
    r"\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{4}|Anayasa\s+Mahkemesi", re.IGNORECASE
)
_FOOTNOTE_RE = re.compile(r"\[\d+\]")


def _is_note(chunk: str) -> bool:
    return bool(_NOTE_HEAD_RE.match(chunk) and _NOTE_EVIDENCE_RE.search(chunk))


# ── Madde başlığı ───────────────────────────────────────────────────────────

# Kaynak metinde "\r\n" YUMUŞAK satır kaydırmasıdır (bir paragrafın içi),
# çıplak "\n" ise blok sınırıdır (başlık / madde başlangıcı). Ölçüldü
# (5 Eyl 2026): 2004'te 6035 CRLF'e karşı 3760 çıplak LF. Faz 1'de
# ``splitlines()`` ikisini ayırmadığı için "F. … sözleşmenin sona\r\nermesi"
# başlığı "ermesi" diye kırpılıp bir üst başlığa yapışıyordu (TBK 347).
_BLOCK_SPLIT_RE = re.compile(r"(?<!\r)\n")
# Başlık olamayacak bloklar: sırf dipnot numarası, sırf rakam/noktalama.
_HEADING_SKIP_RE = re.compile(r"^(?:\[\d+\]|[\d\W_]+)$")
_HEADING_MAX = 160
_HEADING_LOOKBACK = 8
_HEADING_WINDOW = 3000


def _blocks(text: str) -> list[str]:
    """Metni bloklara ayır; yumuşak kaydırmayı boşluğa çevir."""
    out = []
    for block in _BLOCK_SPLIT_RE.split(text):
        block = _FOOTNOTE_RE.sub(" ", block.replace("\r\n", " "))
        out.append(re.sub(r"[ \t\xa0]+", " ", block).strip())
    return out


# "a. Genel olarak", "b) Oy hakkı", "1. Mülkiyet karinesi", "III. Dinî eğitim"
# — hiyerarşik kenar başlığı numaralandırması.
_ENUM_RE = re.compile(r"^(?:[A-Za-zÇĞİÖŞÜçğıöşü]|[IVXivx]{1,4}|\d+)\s*[.)–-]\s*\S")


def _is_heading(block: str) -> bool:
    if not block or len(block) > _HEADING_MAX or _HEADING_SKIP_RE.match(block):
        return False
    # ".)" / ".”" gibi kapanışlarla biten bloklar da cümledir: 492 m.14'te
    # "(… karar verilir.)" paragrafı üst başlık sanılıyordu.
    block = block.rstrip(")]}»”’\"' ")
    # Cümle sonu = önceki maddenin gövdesi, başlık değil. Faz 1'de ":" de
    # elenmişti; oysa eski usul kanunlarda madde başlığı iki nokta ile biter
    # ("Temyiz:", "b) İtirazın kesin olarak kaldırılması:") — İİK 68 bu yüzden
    # boş kalıyordu.
    return not block.endswith((".", "!", "?", ";"))


def _heading_before(text: str, pos: int) -> tuple[str, str]:
    """``pos`` konumundan önceki kenar başlığı ve üst başlık zinciri.

    Dönüş ``(baslik, ust_baslik)``. Türk mevzuatında madde başlığı "MADDE 12 -"
    bloğunun hemen üstündeki kısa bloktur; medeni/borçlar kanunu tipi
    metinlerde bunun üstünde hiyerarşik kenar başlıkları vardır
    ("F. … > I. Bildirim yoluyla > 1. Genel olarak"). En alttaki başlık
    ``baslik``, üstündekiler " > " ile ``ust_baslik`` olur.
    """
    # Yalnızca pos'tan önceki pencere ayrıştırılır: Faz 1'de tüm ön ek her
    # madde için yeniden bölünüyordu (490 maddelik 400 KB'lık VUK'ta O(n²)).
    pencere = text[max(0, pos - _HEADING_WINDOW):pos].rstrip()
    blocks = _blocks(pencere)
    found: list[str] = []
    for block in reversed(blocks[-_HEADING_LOOKBACK:]):
        if not block or _HEADING_SKIP_RE.match(block):
            continue
        if not _is_heading(block):
            break
        found.insert(0, block)
        if len(found) >= 4:
            break
    if not found:
        return "", ""
    # Bir başlık nadiren ÇIPLAK "\n" ile de bölünüyor ("İsticvap olunacak\n
    # kişilerin belirlenmesi" — 6100 m.170). Küçük harfle başlayan ve
    # numaralandırma taşımayan blok, üstündekinin devamıdır.
    birlesik: list[str] = []
    for block in found:
        if (
            birlesik
            and block[:1].islower()
            and not _ENUM_RE.match(block)
        ):
            birlesik[-1] = f"{birlesik[-1]} {block}"
        else:
            birlesik.append(block)
    return birlesik[-1][:200], " > ".join(birlesik[:-1])[:400]


def _degisiklik_notu(body: str) -> str:
    """Madde gövdesindeki değişiklik parantezleri + dipnot numaraları (ham)."""
    parts: list[str] = []
    for m in _NOTE_PAREN_RE.finditer(body):
        chunk = re.sub(r"\s+", " ", m.group(0)).strip()
        if _is_note(chunk):
            parts.append(chunk)
    parts.extend(_FOOTNOTE_RE.findall(body))
    # Aynı parantez birden çok fıkrada tekrar edebilir; sırayı bozmadan tekille.
    seen: set[str] = set()
    uniq = [p for p in parts if not (p in seen or seen.add(p))]
    return " | ".join(uniq)


# ── Değişiklik/yürürlük ayrıştırması (Faz 2a) ───────────────────────────────

# "(Değişik birinci fıkra: 17/7/2003-4949/16 md.; Mülga: 2/3/2005-5311/28 md.)"
# — bir parantezde birden çok değişiklik olabilir. Etiketleri bulup aralarını
# dilimliyoruz; ";" ile bölmek olmuyor çünkü AYM künyesi de ";" içeriyor
# ("E.:2022/6; K.:2024/225").
_LABEL_RE = re.compile(
    r"(?:(?<=\()|(?<=;)|(?<=\(\s))\s*"
    r"(?P<label>(?:De[ğg]i[şs]tirilerek\s+kabul|De[ğg]i[şs]ik|M[üu]lga|Ek"
    r"|[İIi]ptal|Aynen\s+kabul|Yeniden\s+[Dd][üu]zenleme"
    r"|Y[üu]r[üu]rl[üu]kten\s+kald[ıi]r[ıi]lm[ıi][şs])"
    r"(?:[^:;()\d]{0,40}?))\s*(?::|(?=\s*\d)|(?=\s*[-–—]\s*\d)|(?=\s*Anayasa))",
    re.IGNORECASE,
)

# "23/1/2008-5728/47 md." | "2/7/2018 – KHK-703/119 md." | "22/5/2003/4857/120 md."
_KAYNAK_RE = re.compile(
    r"(?P<gun>\d{1,2})\s*/\s*(?P<ay>\d{1,2})\s*/\s*(?P<yil>\d{4})"
    r"\s*[-–—/]?\s*"
    r"(?P<khk>KHK)?\s*[-–—/]?\s*"
    r"(?P<no>\d{2,4})\s*/\s*(?P<md>\d+(?:\s*/\s*[A-Za-zÇĞİÖŞÜ])?)\s*(?:nci|ncı|uncu|üncü)?\s*md",
    re.IGNORECASE,
)

# "Anayasa Mahkemesinin 25/12/2024 tarihli ve E.:2022/6; K.:2024/225 sayılı Kararı"
_AYM_RE = re.compile(
    r"Anayasa\s+Mahkemesi(?:['’`]?n[iı]n)?\s*"
    r"(?:(?P<gun>\d{1,2})\s*/\s*(?P<ay>\d{1,2})\s*/\s*(?P<yil>\d{4})\s*[Tt]arihli\s+ve\s*)?"
    r"E\s*\.?\s*:?\s*(?P<esas>\d{4}\s*/\s*\d+)\s*[,;]?\s*"
    r"K\s*\.?\s*:?\s*(?P<karar>\d{4}\s*/\s*\d+)",
    re.IGNORECASE,
)

# Resmî Gazete künyesi, dipnot gövdelerinde geçtiğinde.
_RG_RE = re.compile(
    r"(?P<gun>\d{1,2})/(?P<ay>\d{1,2})/(?P<yil>\d{4})\s+tarih(?:li)?\s+ve\s+"
    r"(?P<sayi>\d{4,6})\s*(?:\([^)]{0,25}\)\s*)?say[ıi]l[ıi]\s+Resm[îi]\s+Gazete",
    re.IGNORECASE,
)

# Dipnot gövdesindeki değiştiren mevzuat künyesi:
# "22/7/1998 tarih ve 4369 sayılı Kanunun 81 inci maddesiyle …"
# "2/7/2018 tarihli 703 sayılı KHK'nin 68 inci maddesiyle …"
# Sayıdan önce "/" olmaması şart: "97/9218 sayılı Bakanlar Kurulu Kararı"
# künyesi kanun numarası değildir, ham kalır.
_DIPNOT_KAYNAK_RE = re.compile(
    r"(?P<gun>\d{1,2})\s*/\s*(?P<ay>\d{1,2})\s*/\s*(?P<yil>\d{4})\s+tarih(?:li)?\s+"
    r"(?:ve\s+)?(?<![\d/])(?P<no>\d{2,5})\s+say[ıi]l[ıi]\s+"
    r"(?P<tip>Kanun\s+H[üu]k[mn][üu]nde\s+Kararname|KHK|Kanun|Cumhurba[şs]kanl[ıi][ğg][ıi])",
    re.IGNORECASE,
)

_KAPSAM_SIRA = (
    ("başlı", "başlık"), ("basli", "başlık"),
    ("fıkra", "fıkra"), ("fikra", "fıkra"),
    ("bent", "bent"), ("bend", "bent"),
    ("cümle", "cümle"), ("cumle", "cümle"),
    ("ibare", "ibare"),
    ("paragraf", "paragraf"),
    ("hüküm", "hüküm"), ("hukum", "hüküm"),
    ("madde", "madde"),
)

_TUR_SIRA = (
    ("değiştirilerek kabul", "degistirilerek_kabul"),
    ("degistirilerek kabul", "degistirilerek_kabul"),
    ("aynen kabul", "aynen_kabul"),
    ("yeniden düzenleme", "yeniden_duzenleme"),
    ("yeniden duzenleme", "yeniden_duzenleme"),
    ("yeniden düzenlen", "yeniden_duzenleme"),
    ("yeniden duzenlen", "yeniden_duzenleme"),
    ("değişik", "degisik"), ("degisik", "degisik"),
    ("degişik", "degisik"), ("değisik", "degisik"),
    ("mülga", "mulga"), ("mulga", "mulga"),
    ("yürürlükten", "mulga"), ("yururlukten", "mulga"),
    ("iptal", "iptal"),
    ("ek", "ek"),
)


def _lower_tr(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def _kapsam_of(label: str) -> str:
    low = _lower_tr(label)
    for key, val in _KAPSAM_SIRA:
        if key in low:
            return val
    return "madde"


def _tur_of(label: str) -> str:
    low = _lower_tr(label).strip()
    for key, val in _TUR_SIRA:
        if low.startswith(key):
            return val
    return ""


def _iso(gun: str, ay: str, yil: str) -> str:
    return f"{int(yil):04d}-{int(ay):02d}-{int(gun):02d}"


def _bos_kayit(kapsam: str, tur: str, ham: str, dipnot_no: int | None) -> dict[str, Any]:
    return {
        "kapsam": kapsam, "tur": tur, "tarih": "", "degistiren_no": "",
        "degistiren_madde": "", "rg_tarihi": "", "rg_sayisi": "",
        "aym_esas": "", "aym_karar": "", "ham": ham, "dipnot_no": dipnot_no,
    }


def _kayit_from_item(kapsam: str, tur: str, item: str, ham: str) -> dict[str, Any]:
    kayit = _bos_kayit(kapsam, tur, ham, None)
    aym = _AYM_RE.search(item)
    if aym:
        kayit["aym_esas"] = re.sub(r"\s+", "", aym.group("esas"))
        kayit["aym_karar"] = re.sub(r"\s+", "", aym.group("karar"))
        if aym.group("yil"):
            kayit["tarih"] = _iso(aym.group("gun"), aym.group("ay"), aym.group("yil"))
        if not tur:
            kayit["tur"] = "anayasa_mahkemesi"
        return kayit
    kaynak = _KAYNAK_RE.search(item)
    if kaynak:
        kayit["tarih"] = _iso(kaynak.group("gun"), kaynak.group("ay"), kaynak.group("yil"))
        no = kaynak.group("no")
        kayit["degistiren_no"] = f"KHK-{no}" if kaynak.group("khk") else no
        kayit["degistiren_madde"] = re.sub(r"\s+", "", kaynak.group("md"))
    return kayit


def parse_paren(chunk: str) -> list[dict[str, Any]]:
    """Tek bir değişiklik parantezini kayıtlara çevir.

    Bir parantez birden çok değişiklik taşıyabilir:
    ``(Ek: 17/7/2003-4949/50 md.; Mülga: 28/2/2018-7101/65 md.)`` → iki kayıt.
    Hiçbir etiket yakalanamazsa tek bir ``ham`` kayıt döner; hiç tarih/AYM
    kanıtı yoksa (``(ek gösterge dahil)`` gibi) hiç kayıt dönmez.
    """
    chunk = re.sub(r"\s+", " ", chunk).strip()
    if not _is_note(chunk):
        return []
    marks = list(_LABEL_RE.finditer(chunk))
    if not marks:
        return [_kayit_from_item("madde", "", chunk, chunk)]
    out: list[dict[str, Any]] = []
    for i, m in enumerate(marks):
        son = marks[i + 1].start() if i + 1 < len(marks) else len(chunk)
        item = chunk[m.end():son].rstrip(") ;")
        label = m.group("label")
        out.append(_kayit_from_item(_kapsam_of(label), _tur_of(label), item, chunk))
    return out


def parse_footnotes(metin: str) -> dict[int, str]:
    """Belge sonundaki ``[n]`` dipnot gövdelerini numarasıyla eşle.

    Dipnotlar belgenin sonunda, kendi başına bir blok olan ``[n]``
    işaretinden bir sonraki işarete kadar uzanan düz metindir. Gövde
    metninde geçen ``[n]`` işaretleri satır başında yalnız durmadığı için
    karışmaz; ayrıca yalnızca artan son dizi (1, 2, 3, …) alınır.
    """
    marks = [
        (int(m.group(1)), m.start(), m.end())
        for m in re.finditer(r"(?:(?<=\n)|^)\[(\d+)\][ \t\r]*(?=\n)", metin)
    ]
    if not marks:
        return {}
    # Artan son diziyi bul: dipnot listesi belge sonunda 1'den başlar.
    start = 0
    for i in range(len(marks) - 1, 0, -1):
        if marks[i][0] != marks[i - 1][0] + 1:
            start = i
            break
    dizi = marks[start:]
    out: dict[int, str] = {}
    for i, (no, _, end) in enumerate(dizi):
        son = dizi[i + 1][1] if i + 1 < len(dizi) else len(metin)
        govde = re.sub(r"\s+", " ", metin[end:son].replace("\xa0", " ")).strip()
        if govde:
            out[no] = govde
    return out


# Dipnot gövdesindeki eylem: "…değiştirilmiştir", "…eklenmiştir", "…iptal
# edilmiştir", "…madde metninden çıkarılmıştır"/"yürürlükten kaldırılmıştır".
_DIPNOT_TUR = (
    (re.compile(r"iptal\s+edil", re.IGNORECASE), "iptal"),
    (re.compile(r"y[üu]r[üu]rl[üu]kten\s+kald[ıi]r|madde\s+metninden\s+[çc][ıi]kar"
                r"|mülga|y[üu]r[üu]rl[üu][ğg][üu]\s+kald", re.IGNORECASE), "mulga"),
    (re.compile(r"eklen(miş|mis)|gelmek\s+[üu]zere", re.IGNORECASE), "ek"),
    (re.compile(r"de[ğg]i[şs]tiril", re.IGNORECASE), "degisik"),
)
_DIPNOT_KAPSAM = (
    (re.compile(r"madde\s+ba[şs]l[ıi][ğg][ıi]|ba[şs]l[ıi][ğg][ıi]\s*[“\"]",
                re.IGNORECASE), "başlık"),
    (re.compile(r"\bbu\s+f[ıi]krada?\b|f[ıi]kras[ıi]nda", re.IGNORECASE), "fıkra"),
    (re.compile(r"\bbu\s+ben[dt]", re.IGNORECASE), "bent"),
    (re.compile(r"\bc[üu]mle", re.IGNORECASE), "cümle"),
    (re.compile(r"\bibare", re.IGNORECASE), "ibare"),
)


def parse_dipnot(no: int, govde: str) -> dict[str, Any]:
    """Bir dipnot gövdesini kayda çevir.

    Örnek: "2/3/2024 tarihli ve 7499 sayılı Kanunun 37 nci maddesiyle bu
    fıkrada yer alan … şeklinde değiştirilmiştir." →
    ``tur='degisik'``, ``kapsam='fıkra'``, ``tarih='2024-03-02'``,
    ``degistiren_no='7499'``, ``degistiren_madde='37'``.
    """
    kapsam = "madde"
    for rx, val in _DIPNOT_KAPSAM:
        if rx.search(govde):
            kapsam = val
            break
    tur = ""
    for rx, val in _DIPNOT_TUR:
        if rx.search(govde):
            tur = val
            break
    kayit = _bos_kayit(kapsam, tur, govde[:1000], no)
    aym = _AYM_RE.search(govde)
    if aym:
        kayit["aym_esas"] = re.sub(r"\s+", "", aym.group("esas"))
        kayit["aym_karar"] = re.sub(r"\s+", "", aym.group("karar"))
        if aym.group("yil"):
            kayit["tarih"] = _iso(aym.group("gun"), aym.group("ay"), aym.group("yil"))
        if not tur:
            kayit["tur"] = "anayasa_mahkemesi"
    else:
        m = _DIPNOT_KAYNAK_RE.search(govde)
        if m:
            kayit["tarih"] = _iso(m.group("gun"), m.group("ay"), m.group("yil"))
            tip = _lower_tr(m.group("tip"))
            khk = "khk" in tip or "kararname" in tip
            kayit["degistiren_no"] = (
                f"KHK-{m.group('no')}" if khk else m.group("no")
            )
            md = re.search(
                r"(\d+(?:\s*/\s*[A-Za-zÇĞİÖŞÜ])?)\s*(?:nci|ncı|uncu|üncü|inci|ıncı)?\s*"
                r"maddesi(?:yle|nin|\b)",
                govde[m.end():m.end() + 120], re.IGNORECASE,
            )
            if md:
                kayit["degistiren_madde"] = re.sub(r"\s+", "", md.group(1))
    rg = _RG_RE.search(govde)
    if rg:
        kayit["rg_tarihi"] = _iso(rg.group("gun"), rg.group("ay"), rg.group("yil"))
        kayit["rg_sayisi"] = rg.group("sayi")
    return kayit


def parse_degisiklik(
    madde_metni: str, dipnotlar: dict[int, str] | None = None
) -> list[dict[str, Any]]:
    """Madde gövdesindeki değişiklik/yürürlük bilgisini yapılandır.

    İki kaynak birleştirilir: (1) gövdedeki ``(Değişik: …)`` türü parantezler,
    (2) gövdedeki ``[n]`` dipnot işaretlerinin belge sonundaki gövdeleri
    (``dipnotlar`` sözlüğü, ``parse_footnotes`` çıktısı).
    """
    ham_kayitlar: list[dict[str, Any]] = []
    for m in _NOTE_PAREN_RE.finditer(madde_metni):
        ham_kayitlar.extend(parse_paren(m.group(0)))
    if dipnotlar:
        for m in _FOOTNOTE_RE.finditer(madde_metni):
            no = int(m.group(0)[1:-1])
            govde = dipnotlar.get(no)
            if govde:
                ham_kayitlar.append(parse_dipnot(no, govde))
    # Aynı parantez birden çok fıkrada tekrar edebilir (İİK 68'de "(Değişik:
    # 9/11/1988-3494/2 md.)" iki kez geçiyor); aynı dipnot işareti de. Sırayı
    # bozmadan tekille — ``degisiklik_notu`` da aynı sözleşmeyle çalışıyor.
    out: list[dict[str, Any]] = []
    gorulen: set[tuple[Any, ...]] = set()
    for k in ham_kayitlar:
        anahtar = tuple(k[a] for a in _DEGISIKLIK_ALANLAR)
        if anahtar not in gorulen:
            gorulen.add(anahtar)
            out.append(k)
    return out


def _strip_trailing_heading(metin: str, next_baslik: str) -> str:
    """Bir sonraki maddenin kenar başlığını gövdenin sonundan at.

    ``_ARTICLE_RE`` maddeyi "MADDE n"den "MADDE n+1"e kadar alıyor; aradaki
    kenar başlığı bu yüzden ÖNCEKİ maddenin gövdesinin sonuna yapışıyor.
    Ölçüldü (5 Eyl 2026): 4857 m.23'ün metni "İşçinin haklı nedenle derhal
    fesih hakkı" ile bitiyordu ve o sorgu m.23'ü m.24'ten önce getiriyordu.
    """
    if not next_baslik:
        return metin
    hedef = {x.strip() for x in next_baslik.split(" > ") if x.strip()}
    parcalar = _BLOCK_SPLIT_RE.split(metin.rstrip())
    kesim = len(parcalar)
    for j in range(len(parcalar) - 1, max(-1, len(parcalar) - 6), -1):
        norm = re.sub(r"[ \t\xa0]+", " ", parcalar[j].replace("\r\n", " ")).strip()
        norm = _FOOTNOTE_RE.sub(" ", norm).strip()
        if norm and norm not in hedef:
            break
        kesim = j
    if kesim == len(parcalar):
        return metin
    return "\n".join(parcalar[:kesim]).rstrip()


def split_articles(text: str) -> list[dict[str, Any]]:
    """Konsolide metni maddelere böl.

    ``legislation._parse_articles`` numarayı ve gövdeyi verir; buraya ek olarak
    kenar başlığı ve ham değişiklik notu çıkarılır. İki liste aynı regex'in
    aynı sırayla ürettiği eşleşmeler olduğu için birebir hizalıdır.
    """
    parsed = _parse_articles(text)
    body = _normative_body(text)
    dipnotlar = parse_footnotes(text)
    spans = [m.start() for m in _ARTICLE_RE.finditer(body)]
    out: list[dict[str, Any]] = []
    for i, art in enumerate(parsed):
        pos = spans[i] if i < len(spans) else 0
        baslik, ust = _heading_before(body, pos) if pos else ("", "")
        out.append({
            "madde_no": art["number"],
            "sira": i + 1,
            "baslik": baslik,
            "ust_baslik": ust,
            "metin": art["raw_text"],
            "degisiklik_notu": _degisiklik_notu(art["text"]),
            "degisiklikler": parse_degisiklik(art["text"], dipnotlar),
        })
    for i in range(len(out) - 1):
        nxt = out[i + 1]
        kesilecek = " > ".join(x for x in (nxt["ust_baslik"], nxt["baslik"]) if x)
        out[i]["metin"] = _strip_trailing_heading(out[i]["metin"], kesilecek)
    return out


# ── Yazma ───────────────────────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


_DEGISIKLIK_ALANLAR = (
    "kapsam", "tur", "tarih", "degistiren_no", "degistiren_madde",
    "rg_tarihi", "rg_sayisi", "aym_esas", "aym_karar", "ham", "dipnot_no",
)
_DEGISIKLIK_INSERT = (
    "INSERT INTO mevzuat_degisiklik (mevzuat_id, sira, "
    + ", ".join(_DEGISIKLIK_ALANLAR)
    + ") VALUES (" + ",".join("?" * (len(_DEGISIKLIK_ALANLAR) + 2)) + ")"
)


def _degisiklik_row(mevzuat_id: str, sira: int, d: dict[str, Any]) -> tuple[Any, ...]:
    return (mevzuat_id, sira, *(d.get(k) for k in _DEGISIKLIK_ALANLAR))


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
        db.execute("DELETE FROM mevzuat_degisiklik WHERE mevzuat_id = ?", (mevzuat_id,))
        db.executemany(
            """INSERT INTO mevzuat_madde
               (mevzuat_id, madde_no, sira, baslik, ust_baslik, metin, degisiklik_notu)
               VALUES (?,?,?,?,?,?,?)""",
            [
                (
                    mevzuat_id, m["madde_no"], m["sira"], m["baslik"],
                    m["ust_baslik"], m["metin"], m["degisiklik_notu"],
                )
                for m in maddeler
            ],
        )
        db.executemany(_DEGISIKLIK_INSERT, [
            _degisiklik_row(mevzuat_id, m["sira"], d)
            for m in maddeler for d in m["degisiklikler"]
        ])
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


def madde_degisiklikleri(
    db: sqlite3.Connection, mevzuat_id: str, sira: int
) -> list[dict[str, Any]]:
    """Bir maddenin yapılandırılmış değişiklik kayıtları (tarihe göre sıralı)."""
    rows = db.execute(
        "SELECT " + ", ".join(_DEGISIKLIK_ALANLAR)
        + " FROM mevzuat_degisiklik WHERE mevzuat_id = ? AND sira = ?"
        " ORDER BY (tarih = '') , tarih, rowid",
        (mevzuat_id, sira),
    ).fetchall()
    return [
        {k: v for k, v in zip(_DEGISIKLIK_ALANLAR, r) if v not in (None, "")}
        for r in rows
    ]


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
                  m.madde_no, m.sira, m.baslik, m.metin, m.degisiklik_notu,
                  m.ust_baslik
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
                "ust_baslik": r[10] or "",
                "metin": r[8],
                "degisiklik_notu": r[9],
                "degisiklikler": madde_degisiklikleri(db, r[0], r[6]),
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
