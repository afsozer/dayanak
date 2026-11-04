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
from datetime import date, datetime, timezone
from statistics import median
from typing import Any

from .legislation import (
    _ARTICLE_RE,
    _ORDINAL_PAT,
    _norm_article_no,
    _normative_body,
    _parse_articles,
    _tr_word_pattern,
)

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

# Faz 2d: aynı adla yeniden yayımlanan tebliğ/yönetmelik sürümleri.
# ``ad_anahtari`` HER belgede dolu (tür + normalize ad; indeksli, upsert'te tek
# grubun yeniden hesabı tam tarama yapmasın diye). ``grup_anahtari`` YALNIZ
# sürüm serisi sayılan gruplarda dolu, ``guncel`` serinin en yeni üyesinde 1.
_DOKUMAN_AD_ANAHTARI_COL = "ALTER TABLE mevzuat_dokuman ADD COLUMN ad_anahtari TEXT"
_DOKUMAN_GRUP_COL = "ALTER TABLE mevzuat_dokuman ADD COLUMN grup_anahtari TEXT"
_DOKUMAN_GUNCEL_COL = "ALTER TABLE mevzuat_dokuman ADD COLUMN guncel INTEGER"
_DOKUMAN_AD_INDEX = (
    "CREATE INDEX IF NOT EXISTS mevzuat_dokuman_ad_anahtari "
    "ON mevzuat_dokuman(ad_anahtari);"
)
_DOKUMAN_GRUP_INDEX = (
    "CREATE INDEX IF NOT EXISTS mevzuat_dokuman_grup "
    "ON mevzuat_dokuman(grup_anahtari, guncel);"
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
    dcols = {r[1] for r in db.execute("PRAGMA table_info(mevzuat_dokuman)").fetchall()}
    if "ad_anahtari" not in dcols:
        db.execute(_DOKUMAN_AD_ANAHTARI_COL)
    if "grup_anahtari" not in dcols:
        db.execute(_DOKUMAN_GRUP_COL)
    if "guncel" not in dcols:
        db.execute(_DOKUMAN_GUNCEL_COL)
    db.execute(_DOKUMAN_AD_INDEX)
    db.execute(_DOKUMAN_GRUP_INDEX)
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
_HEADING_RUN_MAX = 8
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
    if _PREAMBLE_RE.match(block):
        # "Yayımlandığı Düstur : Tertip: 5 Cilt: 42" — kanun künyesi üstbilgisi,
        # başlık değil. Ölçüldü: 4857 m.1'in üst başlığına yapışıyordu.
        return False
    return not block.endswith((".", "!", "?", ";"))


def _heading_run(text: str, pos: int) -> list[str]:
    """``pos``'tan hemen önceki KESİNTİSİZ başlık bloğu dizisi (üstten alta).

    Türk mevzuatında madde başlığı "MADDE 12 -" bloğunun hemen üstündeki kısa
    bloktur; medeni/borçlar kanunu tipi metinlerde bunun üstünde hiyerarşik
    kenar başlıkları vardır ("F. … > I. Bildirim yoluyla > 1. Genel olarak").
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
        if len(found) >= _HEADING_RUN_MAX:
            break
    # Bir başlık nadiren ÇIPLAK "\n" ile de bölünüyor ("İsticvap olunacak\n
    # kişilerin belirlenmesi" — 6100 m.170). Küçük harfle başlayan ve
    # numaralandırma taşımayan blok, üstündekinin devamıdır.
    birlesik: list[str] = []
    for block in found:
        if (
            birlesik
            and block[:1].islower()
            and not _ENUM_RE.match(block)
            and not _STRUCT_RE.match(block)
        ):
            birlesik[-1] = f"{birlesik[-1]} {block}"
        else:
            birlesik.append(block)
    return birlesik


def _birlestir(found: list[str]) -> list[str]:
    """Çıplak "\n" ile bölünmüş başlık parçalarını birleştir (6100 m.170)."""
    birlesik: list[str] = []
    for block in found:
        if (
            birlesik
            and block[:1].islower()
            and not _ENUM_RE.match(block)
            and not _STRUCT_RE.match(block)
        ):
            birlesik[-1] = f"{birlesik[-1]} {block}"
        else:
            birlesik.append(block)
    return birlesik


def _aralik_ve_run(text: str, bas: int, son: int) -> tuple[list[str], list[str]]:
    """``[bas, son)`` aralığını "önceki bloklar" ve "kuyruk başlık koşusu" diye ayır.

    Kuyruk koşusu = ``son`` konumundaki maddenin hemen üstündeki KESİNTİSİZ
    başlık blokları (madde başlığı + kenar başlıkları). Önceki bloklar bir
    önceki maddenin gövdesidir; içinden yalnız YAPISAL başlıklar toplanır.
    """
    bloklar = _blocks(text[bas:son].rstrip())
    kuyruk: list[str] = []
    kesim = len(bloklar)
    for j in range(len(bloklar) - 1, -1, -1):
        block = bloklar[j]
        if not block or _HEADING_SKIP_RE.match(block):
            kesim = j
            continue
        if not _is_heading(block):
            break
        kuyruk.insert(0, block)
        kesim = j
        if len(kuyruk) >= _HEADING_RUN_MAX:
            break
    return bloklar[:kesim], _birlestir(kuyruk)


def _heading_before(text: str, pos: int) -> tuple[str, str]:
    """``_heading_run``'ın yalnız YEREL penceresinden ``(baslik, ust_baslik)``.

    Belge boyu hiyerarşi için ``_hierarchy`` kullanılır; bu ince sarmalayıcı
    tek bir madde parçası ayrıştıran çağrılar için korunuyor.
    """
    birlesik = _heading_run(text, pos)
    if not birlesik:
        return "", ""
    return birlesik[-1][:200], " > ".join(birlesik[:-1])[:400]


# ── Faz 3: belge boyu başlık hiyerarşisi ────────────────────────────────────
#
# Ölçüldü (6 Eyl 2026, canlı korpus): ``ust_baslik`` 298.854 maddenin yalnız
# %19,1'inde doluydu. Sebep yapısaldı — ``_heading_before`` YALNIZCA maddenin
# hemen üstündeki kesintisiz blok dizisine bakıyor. TBK 352'nin üstünde tek
# blok var ("2. Kiracıdan kaynaklanan sebeplerle"); onun üstü m.351'in gövdesi.
# Zincirin geri kalanı ("F. Konut ve çatılı işyeri … > II. Dava yoluyla")
# belgenin çok daha yukarısında, m.349/350'nin üstünde geçiyor. Aynı şekilde
# yönetmelik/tebliğde bağlam "BİRİNCİ BÖLÜM / Amaç, Kapsam…" satırında, bölümün
# ilk maddesinden sonraki maddeler için erişilemez durumda.
#
# Çözüm: belgeyi baştan sona TEK geçişte tarayıp bir hiyerarşi yığını tutmak.
# Yığın iki katmanlı: yapısal başlıklar (Kitap/Kısım/Bölüm/Ayırım) ve kenar
# başlığı numaralandırması (A. / I. / 1. / a.). ``ust_baslik`` formatı:
# "İkinci Kitap > Birinci Kısım > Üçüncü Bölüm | A. Genel olarak > I. Kapsam".

_STRUCT_WORDS = ("KITAP", "KISIM", "BOLUM", "AYIRIM", "AYRIM", "FASIL", "BAB")
_STRUCT_RE = re.compile(
    rf"^{_ORDINAL_PAT}\s+(?:{'|'.join(_tr_word_pattern(w) for w in _STRUCT_WORDS)})"
    r"\s*$",
    re.IGNORECASE,
)
# "BAŞLANGIÇ" (TMK) ve "EK BÖLÜM" gibi ordinal taşımayan yapısal başlıklar.
_STRUCT_ALT_RE = re.compile(
    r"^(?:BA[ŞS]LANGI[ÇC]"
    rf"|(?:EK|GE[ÇC][İI]C[İI])\s+(?:{'|'.join(_tr_word_pattern(w) for w in _STRUCT_WORDS)})"
    r")\s*$",
    re.IGNORECASE,
)
# Kanun künyesi/mevzuat başlığı önsözü — başlık değil, üstbilgi.
_PREAMBLE_RE = re.compile(
    r"^(?:Yay[ıi]mland[ıi][ğg][ıi]\s+D[üu]stur|Kabul\s+Tarihi|Kanun\s+Numaras[ıi]"
    r"|Resm[îi]\s+Gazete|D[üu]stur|Tertip|Cilt|Sayfa)\s*:",
    re.IGNORECASE,
)

_SEVIYE_RE = tuple(
    re.compile("|".join(_tr_word_pattern(w) for w in grup), re.IGNORECASE)
    for grup in (("KITAP",), ("KISIM",), ("BOLUM",), ("AYIRIM", "AYRIM", "FASIL", "BAB"))
)

_GECICI_NO_RE = re.compile(r"^(?:Ek|Ge[çc]ici|M[üu]kerrer)\b", re.IGNORECASE)

_ROMAN_RE = re.compile(r"^(?:I{1,3}|IV|V|VI{1,3}|IX|X|XI{1,3}|XIV|XV)$")
_ENUM_HEAD_RE = re.compile(r"^([A-Za-zÇĞİıÖŞÜçğiöşü]+|\d{1,2})\s*[.)–-]\s*(\S)")

# Kenar başlığı seviyeleri: A. → 1, I. → 2, 1. → 3, a. → 4.
# Numaralandırma taşımayan ara başlık 8, maddenin kendi başlığı 9.
_LEVEL_NONE = 8
_LEVEL_LEAF = 9


def _enum_level(block: str) -> int:
    """Bloğun kenar başlığı seviyesi; numaralandırma yoksa ``_LEVEL_NONE``."""
    m = _ENUM_HEAD_RE.match(block)
    if not m:
        return _LEVEL_NONE
    tok = m.group(1)
    if tok.isdigit():
        return 3
    if _ROMAN_RE.match(tok.upper()) and (len(tok) > 1 or tok.upper() in ("I", "V", "X")):
        # "I." Türkçe metinde roma rakamıdır; "A."/"B." harf seviyesidir.
        return 2 if tok.isupper() else 4
    if len(tok) > 1:
        return _LEVEL_NONE
    return 1 if tok.isupper() else 4


def _is_struct(block: str) -> bool:
    return bool(_STRUCT_RE.match(block) or _STRUCT_ALT_RE.match(block))


def _path(stack: dict[int, str], ust_sinir: int) -> list[str]:
    return [stack[k] for k in sorted(stack) if k < ust_sinir]


class _Hiyerarsi:
    """Belge boyunca taşınan başlık yığını."""

    def __init__(self) -> None:
        self.yapisal: dict[int, str] = {}
        self.kenar: dict[int, str] = {}
        self._bekleyen_yapisal: int | None = None
        self._yapisal_adlar: set[str] = set()

    def _yapisal_seviye(self, block: str) -> int:
        # ``_tr_fold`` Ö/Ü'yü katlamıyor ("BÖLÜM" → "BÖLÜM"); seviye tespiti
        # ``_tr_word_pattern`` ile yapılmalı. Ölçüldü (6 Eyl 2026): düz metin
        # karşılaştırmasıyla her BÖLÜM seviye 0 sanılıp KISIM'ı siliyordu.
        for seviye, kalip in enumerate(_SEVIYE_RE):
            if kalip.search(block):
                return seviye
        return 0  # BAŞLANGIÇ vb.

    def _koy(self, stack: dict[int, str], seviye: int, metin: str) -> None:
        for k in [k for k in stack if k >= seviye]:
            del stack[k]
        stack[seviye] = metin[:200]

    def aralik_tara(self, bloklar: list[str]) -> None:
        """Bir önceki maddenin gövdesindeki YAPISAL başlıkları yığına işle."""
        bekleyen: int | None = None
        for block in bloklar:
            if not block or _HEADING_SKIP_RE.match(block):
                continue
            if _is_struct(block):
                self.yapisal_blok(block)
                bekleyen = self._bekleyen_yapisal
                continue
            if bekleyen is not None:
                if _is_heading(block) and _enum_level(block) == _LEVEL_NONE:
                    self.yapisal[bekleyen] = f"{self.yapisal[bekleyen]} — {block}"[:200]
                    self._yapisal_adlar.add(block)
                bekleyen = None
                self._bekleyen_yapisal = None

    def yapisal_blok(self, block: str) -> None:
        seviye = self._yapisal_seviye(block)
        if self.yapisal.get(seviye, "").split(" — ")[0] == block:
            # Aynı yapısal başlık hem aralık taramasında hem kuyruk koşusunda
            # görülebilir; adını iki kez eklemeyelim. ``_bekleyen_yapisal``
            # KORUNUR: adı henüz görülmemiş olabilir (bkz. GEÇİCİ MADDE testi).
            return
        self._koy(self.yapisal, seviye, block)
        # Yapısal başlığın altındaki blok onun adıdır ("BİRİNCİ BÖLÜM" /
        # "Amaç, Kapsam, Dayanak ve Tanımlar"); kenar başlığı yığını sıfırlanır.
        self._bekleyen_yapisal = seviye
        self.kenar.clear()

    def blok(self, block: str) -> None:
        """Madde başlığı OLMAYAN bir başlık bloğunu yığına işle."""
        if _is_struct(block):
            self.yapisal_blok(block)
            return
        if block in self._yapisal_adlar:
            # Yapısal başlığın adı aralık taramasında zaten yığına girdi.
            return
        if self._bekleyen_yapisal is not None and _enum_level(block) == _LEVEL_NONE:
            seviye = self._bekleyen_yapisal
            self.yapisal[seviye] = f"{self.yapisal[seviye]} — {block}"[:200]
            self._bekleyen_yapisal = None
            return
        self._bekleyen_yapisal = None
        self._koy(self.kenar, _enum_level(block), block)

    def madde(self, run: list[str], gecici: bool) -> tuple[str, str]:
        """Bir maddenin ``(baslik, ust_baslik)`` değerini üret ve yığını ilerlet."""
        if gecici:
            # Geçici/Ek madde blokları hiyerarşinin dışındadır; bayat kenar
            # başlığı zinciri onlara yapışmasın.
            self.kenar.clear()
        for block in run[:-1]:
            self.blok(block)
        baslik = run[-1] if run else ""
        if baslik and _is_struct(baslik):
            # "BİRİNCİ BÖLÜM" maddenin başlığı olamaz.
            self.blok(baslik)
            baslik = ""
        if (
            baslik
            and self._bekleyen_yapisal is not None
            and _enum_level(baslik) == _LEVEL_NONE
        ):
            # "DOKUZUNCU BÖLÜM / Son Hükümler / GEÇİCİ MADDE 1": aradaki tek
            # blok maddenin başlığı değil, bölümün adıdır.
            lvl = self._bekleyen_yapisal
            self.yapisal[lvl] = f"{self.yapisal[lvl]} — {baslik}"[:200]
            self._yapisal_adlar.add(baslik)
            baslik = ""
        seviye = _enum_level(baslik) if baslik else _LEVEL_LEAF
        if baslik and seviye == _LEVEL_NONE:
            seviye = _LEVEL_LEAF
        kenar_yol = _path(self.kenar, seviye)
        yapisal_yol = _path(self.yapisal, 99)
        if baslik and seviye < _LEVEL_LEAF:
            self._koy(self.kenar, seviye, baslik)
        self._bekleyen_yapisal = None
        parcalar = []
        if yapisal_yol:
            parcalar.append(" > ".join(yapisal_yol))
        if kenar_yol:
            parcalar.append(" > ".join(kenar_yol))
        return baslik[:200], " | ".join(parcalar)[:600]


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
    uniq = [p for p in parts if not (p in seen or seen.add(p))]  # type: ignore[func-returns-value]
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
    runs: list[list[str]] = []
    hiyerarsi = _Hiyerarsi()
    onceki = 0
    # Belgenin son maddesi, sondaki dipnot listesini ("[30]\n<gövde>\n[31]...")
    # de gövdesine alıyor; listedeki işaretler o maddeye ikinci kez bağlanıyordu
    # (4.11.2026: TMK'nın son maddesi 440 ve 444'ün dipnotlarını taşıyordu).
    # Bir dipnot numarası belgede tek bir yere aittir: ilk geçtiği madde.
    atanmis_dipnot: set[int] = set()
    for i, art in enumerate(parsed):
        pos = spans[i] if i < len(spans) else 0
        if pos:
            onceki_bloklar, run = _aralik_ve_run(body, onceki, pos)
            onceki = pos
        else:
            onceki_bloklar, run = [], []
        # Yapısal tarama koşunun ÜST kısmını da kapsar; yalnız maddenin kendi
        # başlığı (koşunun son bloğu) dışarıda bırakılır ki bölüm adı sanılmasın.
        onceki_bloklar = onceki_bloklar + run[:-1]
        # Yapısal başlık (Kitap/Kısım/Bölüm/Ayırım) maddeden ÇOK önce, bir
        # önceki maddenin gövdesinin üstünde geçebilir; yalnız yerel koşuya
        # bakmak Faz 2a'da bu seviyeyi tamamen kaçırıyordu.
        hiyerarsi.aralik_tara(onceki_bloklar)
        gecici = bool(_GECICI_NO_RE.match(art["number"]))
        baslik, ust = hiyerarsi.madde(run, gecici)
        runs.append(run)
        degisiklikler = [
            d for d in parse_degisiklik(art["text"], dipnotlar)
            if d.get("dipnot_no") is None or d["dipnot_no"] not in atanmis_dipnot
        ]
        atanmis_dipnot.update(
            d["dipnot_no"] for d in degisiklikler if d.get("dipnot_no") is not None
        )
        out.append({
            "madde_no": art["number"],
            "sira": i + 1,
            "baslik": baslik,
            "ust_baslik": ust,
            "metin": art["raw_text"],
            "degisiklik_notu": _degisiklik_notu(art["text"]),
            "degisiklikler": degisiklikler,
        })
    for i in range(len(out) - 1):
        # Kesilecek başlıklar HAM koşudan gelir; ``ust_baslik`` artık belge boyu
        # yığından üretiliyor ve gövdenin sonunda birebir geçmiyor.
        kesilecek = " > ".join(runs[i + 1])
        out[i]["metin"] = _strip_trailing_heading(out[i]["metin"], kesilecek)
    return out


# ── Resmi Gazete ilk yayım metni (değişiklik kanunları) ─────────────────────
#
# mevzuat.gov.tr birçok değişiklik kanununu hiç listelemiyor (4.11.2026
# ölçümü: RG'deki uluslararası onay dışı numaralı kanunların 570'i korpusta
# yoktu; 7571, 7574, 7577, 7593 ...). Bunlar Resmi Gazete'deki ilk yayım
# metninden alınır. Bu metinde başka kanunlara eklenen ya da onların yerine
# konan maddeler tırnak içinde aynen geçer ("“MADDE 134- ..."); madde
# ayrıştırıcısı bunların bir kısmını kanunun kendi maddesi sanıyordu
# (7589'da "7, 26, 8"; 7571'de 134, 135, 223, 128/A ve 5809'a eklenen
# "Geçici 8"). İki kural alıntıyı önceki maddeye katar:
# * kanunun kendi maddeleri 1, 2, 3 diye artar, kendi geçici maddeleri 1'den
#   başlar; sıra dışı kalan madde alıntıdır;
# * önceki madde "aşağıdaki ... eklenmiştir / değiştirilmiştir" diye
#   bitiyorsa sonraki madde alıntıdır (numara tesadüfen sıraya uysa bile).
_ALINTI_GIRIS_RE = re.compile(
    r"a[şs]a[ğg][ıi]daki[^.;]{0,200}?(?:eklenmi[şs]|de[ğg]i[şs]tirilmi[şs])tir[.:]?$",
    re.IGNORECASE,
)
_GECICI_SAYI_RE = re.compile(r"^Ge[çc]ici\s+(\d+)$", re.IGNORECASE)
# RG'de madde başı ayracı yıllara göre değişiyor ve ``_ARTICLE_RE`` yalnız
# "-", U+2013 ve U+2014'ü tanıyor. 4.11.2026 geri doldurmasında görülenler:
# 2005 öncesi "MADDE 1." + U+2014 (nokta yüzünden 102 onay kanunu maddesiz
# kaldı), 2010-2017 arası U+2212 (eksi işareti) ve U+2012 (rakam tiresi; 14
# kanun, bütçe kanunları ve 6524 dahil). Ortak regex'e dokunmadan yalnız RG
# metninde ayraç düz "-"ye çevrilir.
_RG_MADDE_BAS_RE = re.compile(
    r"^((?:(?:EK\s+)?GE[ÇC][İI]C[İI]\s+|EK\s+)?MADDE\s+\d+(?:\s*/\s*[A-Z])?)"
    r"\s*\.?\s*[-‐-―−]",
    re.IGNORECASE | re.MULTILINE,
)


def split_degisiklik_kanunu(text: str) -> list[dict[str, Any]]:
    """Resmi Gazete'deki bir kanun metnini kanunun KENDİ maddelerine böl.

    ``split_articles`` çıktısındaki alıntı maddeler (başka kanuna eklenen ya
    da değiştirilen metinler) bir önceki maddenin gövdesine katılır; sıra
    numaraları yeniden verilir.
    """
    ham = split_articles(_RG_MADDE_BAS_RE.sub(r"\1 -", text))
    numaralar = [str(m["madde_no"]).strip() for m in ham]
    out: list[dict[str, Any]] = []
    beklenen, beklenen_gecici = 1, 1
    for i, m in enumerate(ham):
        no = numaralar[i]
        gec = _GECICI_SAYI_RE.match(no)
        if no.isdigit():
            sirada = int(no) == beklenen
        elif gec:
            sirada = int(gec.group(1)) == beklenen_gecici
        else:
            sirada = False
        alinti_girisi = bool(out) and bool(
            _ALINTI_GIRIS_RE.search(re.sub(r"\s+", " ", out[-1]["metin"]).rstrip()[-300:])
        )
        if not out:
            ust = True
        elif not sirada:
            ust = False
        else:
            # Sıradaki numara kanunun kendi maddesidir. Tek istisna: önceki
            # madde alıntıyı haber veriyor VE aynı numara ileride yeniden
            # geçiyor; o zaman bu, numarası tesadüfen sıraya uyan alıntıdır.
            # (Alıntı girişine tek başına güvenmek yetmiyor: alıntı kısa bir
            # satırsa ayrıştırıcı onu sonraki maddenin başlığı sanıp kesiyor
            # ve madde "eklenmiştir." diye bitiyor; 7571'de 17. maddeden
            # sonrası böyle yutuldu.)
            ust = not (alinti_girisi and no in numaralar[i + 1:])
        if ust:
            if no.isdigit():
                beklenen = int(no) + 1
            elif gec:
                beklenen_gecici = int(gec.group(1)) + 1
            out.append({**m, "degisiklikler": list(m["degisiklikler"])})
            continue
        onceki = out[-1]
        onceki["metin"] = onceki["metin"].rstrip() + "\n" + m["metin"]
        onceki["degisiklikler"].extend(m["degisiklikler"])
        onceki["degisiklik_notu"] = " | ".join(
            n for n in (onceki["degisiklik_notu"], m["degisiklik_notu"]) if n
        )
    for i, m in enumerate(out, 1):
        m["sira"] = i
    return out


def maddelere_bol(metin: str, kaynak: str = "") -> list[dict[str, Any]]:
    """Belgenin kaynağına uygun bölücüyü seç.

    Resmi Gazete'den gelen kanun metinleri ``split_degisiklik_kanunu`` ile,
    geri kalan her şey (konsolide metin) ``split_articles`` ile bölünür.
    Yeniden ayrıştıran her yol (``upsert_document``, değişiklik doldurma,
    ``--resplit``) bu fonksiyonu kullanmalı, yoksa sıra numaraları kayar.
    """
    if kaynak == "resmigazete":
        return split_degisiklik_kanunu(metin)
    return split_articles(metin)


def belge_sil(db: sqlite3.Connection, mevzuat_id: str) -> bool:
    """Bir belgeyi maddeleri, değişiklik kayıtları ve vektör satırlarıyla sil.

    FTS tablosu ``mevzuat_madde`` tetikleyicisiyle eşitlenir. Semantik indeks
    silinen maddeyi aramada zaten atlar; vektör satırları burada temizlenir.
    """
    vektor = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mevzuat_madde_vektor'"
    ).fetchone()
    try:
        db.execute("BEGIN IMMEDIATE")
        n = db.execute(
            "DELETE FROM mevzuat_dokuman WHERE mevzuat_id = ?", (mevzuat_id,)
        ).rowcount
        db.execute("DELETE FROM mevzuat_madde WHERE mevzuat_id = ?", (mevzuat_id,))
        db.execute("DELETE FROM mevzuat_degisiklik WHERE mevzuat_id = ?", (mevzuat_id,))
        if vektor:
            db.execute("DELETE FROM mevzuat_madde_vektor WHERE mevzuat_id = ?", (mevzuat_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return n > 0


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

    maddeler = maddelere_bol(metin, kaynak)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM mevzuat_madde WHERE mevzuat_id = ?", (mevzuat_id,))
        db.execute(
            """INSERT OR REPLACE INTO mevzuat_dokuman (
                mevzuat_id, kaynak, tur, mevzuat_no, tertip, ad, kabul_tarihi,
                rg_tarihi, rg_sayisi, guncelleme_tarihi, metin, metin_hash,
                madde_sayisi, cekim_zamani, kaynak_url, meta_json, ad_anahtari
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mevzuat_id, kaynak, tur, str(mevzuat_no), str(tertip), ad,
                kabul_tarihi, rg_tarihi, rg_sayisi, guncelleme_tarihi, metin,
                metin_hash, len(maddeler), now, kaynak_url,
                json.dumps(meta or {}, ensure_ascii=False),
                ad_anahtari(tur, ad),
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
    # Yeni bir yıl tebliği geldiğinde serinin güncel üyesi kaysın diye grup
    # bayrakları HER yazımdan sonra yeniden hesaplanır (indeksli, tek grup).
    grup_yenile(db, tur, ad)
    return {"status": "updated" if row else "inserted", "madde_sayisi": len(maddeler)}


# ── Arama ───────────────────────────────────────────────────────────────────

# ── Sürüm grupları (Faz 2d) ─────────────────────────────────────────────────
#
# Yıllık yeniden yayımlanan tebliğler ("AVUKATLIK ASGARİ ÜCRET TARİFESİ" adını
# 21 ayrı belge taşıyor) aramada beş yılın aynı maddesini birden döndürüyordu.
# Aynı ad + aynı türdeki belgeler bir "sürüm serisi" sayılır, RG tarihi en yeni
# olan yürürlükteki kabul edilir, eskiler aramada katlanır.

# Şapkalı harfler de katlanır: ölçüldü, "İFLÂS İDARESİ ÜCRETİ… TARİFESİ"
# ile "İFLAS İDARESİ ÜCRETİ… TARİFESİ" aynı tarifenin iki yılı (9 → 10 üye);
# çok üyeli grup sayısını değiştirmiyor (61 → 61), yani başka bir şeyi
# yanlışlıkla birleştirmiyor.
_TR_UPPER = str.maketrans("ıİşŞğĞçÇöÖüÜâÂîÎûÛ", "iisSgGcCoOuUaAiIuU")

#: Yalnız bu türlerde "aynı ad = aynı belgenin yeni sürümü" varsayımı geçerli.
#: KANUN/KHK/CBK KASTEN DIŞARIDA (ölçüldü, 6 Eyl 2026, 14.099 belge):
#: "İŞ KANUNU" adını 1475 ve 4857 birlikte taşıyor ama 1475'in 14. maddesi
#: (kıdem tazminatı) hâlâ yürürlükte; "BAZI KANUN VE KANUN HÜKMÜNDE
#: KARARNAMELERDE DEĞİŞİKLİK YAPILMASINA DAİR KANUN" adını 8 AYRI kanun,
#: "OLAĞANÜSTÜ HAL ... KHK'NIN KABULÜ ..." adını 11 ayrı kanun taşıyor.
#: Bunları katlamak maddeyi kaybettirirdi.
_SERI_TURLER = frozenset({"TEBLIGLER", "TEBLIG", "YONETMELIK"})

#: Ardışık yayımlar arasındaki medyan gün sayısı için alt sınır. Ölçüldü:
#: "ULUSAL MESLEK STANDARTLARINA DAİR TEBLİĞ" adını 51 AYRI tebliğ taşıyor
#: (her biri başka bir meslek standardı; medyan aralık 27 gün) — sürüm değil.
#: Gerçek yıllık serilerin medyanı 183-732 gün. 150 gün eşiği ikisini ayırıyor
#: ve "aynı yılda iki kez yayımlandı" istisnasını (AAÜT 2017 ve 2020) yutmuyor.
_SERI_MIN_MEDYAN_GUN = 150

# Rumi/Hicri tarihli eski belgeler ("18.02.1331") ELENİR: yıl aralığı dışı.
_RG_TARIH_RE = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})")
_RG_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _rg_date(rg: str | None) -> date | None:
    s = (rg or "").strip()
    m = _RG_TARIH_RE.match(s)
    if m:
        gun, ay, yil = int(m[1]), int(m[2]), int(m[3])
    else:
        m = _RG_ISO_RE.match(s)
        if not m:
            return None
        yil, ay, gun = int(m[1]), int(m[2]), int(m[3])
    if not (1900 <= yil <= 2100 and 1 <= ay <= 12 and 1 <= gun <= 31):
        return None
    try:
        return date(yil, ay, gun)
    except ValueError:
        return None


def _norm_ad(ad: str | None) -> str:
    """Ad normalizasyonu: Türkçe harfler, büyük/küçük harf, fazla boşluk.

    Sondaki yıl KASTEN kırpılmıyor: ölçüldü (14.099 belge), kırpmak aynı-adlı
    grup sayısını 61'den 61'e, yani hiç değiştirmiyor; buna karşılık
    "(SERİ NO: 2018/1)" gibi kimliğin parçası olan sonekleri yutma riski var.
    """
    return re.sub(r"\s+", " ", (ad or "").translate(_TR_UPPER).upper()).strip()


def ad_anahtari(tur: str | None, ad: str | None) -> str:
    """Belgenin ad kimliği (tür + normalize ad). HER belgede dolu."""
    return f"{(tur or '').strip().upper()}|{_norm_ad(ad)}"


def _grup_karari(uyeler: list[tuple[Any, ...]]) -> list[tuple[str | None, int, str]]:
    """``(mevzuat_id, tur, ad, rg_tarihi)`` üyelerinden karar üret.

    Dönüş: ``(grup_anahtari|None, guncel, mevzuat_id)`` — UPDATE parametresi
    sırasında. ``grup_anahtari`` None ise grup sürüm serisi DEĞİL; o zaman her
    belge kendi başına günceldir (``guncel = 1``).
    """
    if not uyeler:
        return []
    tekil = [(None, 1, u[0]) for u in uyeler]
    if len(uyeler) < 2:
        return tekil  # type: ignore[return-value]
    tur = (uyeler[0][1] or "").strip().upper()
    if tur not in _SERI_TURLER:
        return tekil  # type: ignore[return-value]
    tarih = {u[0]: _rg_date(u[3]) for u in uyeler}
    if any(t is None for t in tarih.values()):
        return tekil  # type: ignore[return-value]
    ds = sorted(tarih.values())  # type: ignore[type-var]
    araliklar = [(b - a).days for a, b in zip(ds, ds[1:])]  # type: ignore[operator]
    if median(araliklar) < _SERI_MIN_MEDYAN_GUN:
        return tekil  # type: ignore[return-value]
    key = ad_anahtari(uyeler[0][1], uyeler[0][2])
    en_yeni = max(uyeler, key=lambda u: (tarih[u[0]], str(u[0])))[0]
    return [(key, 1 if u[0] == en_yeni else 0, u[0]) for u in uyeler]


def grup_yenile(db: sqlite3.Connection, tur: str | None, ad: str | None) -> dict[str, Any]:
    """TEK bir ad grubunun ``grup_anahtari``/``guncel`` bayraklarını yeniden hesapla.

    ``upsert_document`` her yazımdan sonra bunu çağırır: yeni bir yıl tebliği
    gelince serinin güncel üyesi kendiliğinden kayar. ``ad_anahtari`` indeksli,
    tam tablo taraması yok.
    """
    key = ad_anahtari(tur, ad)
    rows = db.execute(
        "SELECT mevzuat_id, tur, ad, rg_tarihi FROM mevzuat_dokuman WHERE ad_anahtari = ?",
        (key,),
    ).fetchall()
    kararlar = _grup_karari([tuple(r) for r in rows])
    if kararlar:
        db.executemany(
            "UPDATE mevzuat_dokuman SET grup_anahtari = ?, guncel = ? WHERE mevzuat_id = ?",
            kararlar,
        )
        db.commit()
    seri = bool(kararlar and kararlar[0][0])
    return {"ad_anahtari": key, "uye": len(rows), "seri": seri}


def gruplari_yenile(
    db: sqlite3.Connection, *, uygula: bool = True
) -> dict[str, Any]:
    """Tüm korpusun sürüm gruplarını yeniden hesapla (doldurma betiği için).

    ``uygula=False`` yalnız planı döndürür (kuru koşum). Tablo küçük (14 bin
    satır), tam tarama saniyenin altında.
    """
    ensure_schema(db)
    rows = db.execute(
        "SELECT mevzuat_id, tur, ad, rg_tarihi FROM mevzuat_dokuman"
    ).fetchall()
    gruplar: dict[str, list[tuple[Any, ...]]] = {}
    for r in rows:
        gruplar.setdefault(ad_anahtari(r[1], r[2]), []).append(tuple(r))

    kararlar: list[tuple[str | None, int, str]] = []
    seriler: list[dict[str, Any]] = []
    reddedilen: list[dict[str, Any]] = []
    for key, uyeler in gruplar.items():
        karar = _grup_karari(uyeler)
        kararlar.extend(karar)
        if karar and karar[0][0]:
            tarihli = sorted(
                ((_rg_date(u[3]), u[2], u[0]) for u in uyeler),
                key=lambda t: t[0],  # type: ignore[arg-type,return-value]
            )
            seriler.append({
                "grup_anahtari": key,
                "ad": uyeler[0][2],
                "tur": uyeler[0][1],
                "uye": len(uyeler),
                "ilk": str(tarihli[0][0]),
                "guncel_rg": str(tarihli[-1][0]),
            })
        elif len(uyeler) > 1:
            reddedilen.append({
                "ad": uyeler[0][2], "tur": uyeler[0][1], "uye": len(uyeler),
            })

    if uygula:
        db.executemany(
            "UPDATE mevzuat_dokuman SET ad_anahtari = ? WHERE mevzuat_id = ?",
            [(ad_anahtari(r[1], r[2]), r[0]) for r in rows],
        )
        db.executemany(
            "UPDATE mevzuat_dokuman SET grup_anahtari = ?, guncel = ? WHERE mevzuat_id = ?",
            kararlar,
        )
        db.commit()
    seriler.sort(key=lambda s: -s["uye"])
    reddedilen.sort(key=lambda s: -s["uye"])
    return {
        "belge": len(rows),
        "ad_grubu": len(gruplar),
        "cok_uyeli_grup": sum(1 for v in gruplar.values() if len(v) > 1),
        "seri_grup": len(seriler),
        "seri_belge": sum(s["uye"] for s in seriler),
        "katlanan_eski_surum": sum(s["uye"] - 1 for s in seriler),
        "seriler": seriler,
        "seri_sayilmayan": reddedilen,
        "uygulandi": uygula,
    }


# ── Sürüm katlama (arama sonrası) ───────────────────────────────────────────

_KATLAMA_SNIPPET_CEVRE = 110


def _snippet_uret(metin: str, kelimeler: list[str] | None) -> str:
    """Güncel sürümün metninden snippet. Eşleşen kelimenin çevresi, yoksa baş."""
    m = (metin or "").strip()
    if kelimeler:
        low = _lower_tr(m)
        for k in kelimeler:
            i = low.find(_lower_tr(k))
            if i >= 0:
                bas = max(0, i - _KATLAMA_SNIPPET_CEVRE)
                son = min(len(m), i + len(k) + _KATLAMA_SNIPPET_CEVRE)
                return (
                    ("… " if bas else "")
                    + " ".join(m[bas:son].split())
                    + (" …" if son < len(m) else "")
                )
    kisa = " ".join(m[:400].split())
    return kisa + (" …" if len(m) > 400 else "")


def surum_katla(
    db: sqlite3.Connection,
    results: list[dict[str, Any]],
    *,
    limit: int | None = None,
    kelimeler: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Sürüm serilerinin ESKİ üyelerine ait maddeleri tek satıra indir.

    Sıra korunur. Eski sürüme ait bir madde, serinin güncel belgesinde aynı
    numarayla varsa o belgenin maddesiyle DEĞİŞTİRİLİR (snippet güncel
    metinden yeniden üretilir); yoksa satır kalır ama ``guncel: False`` ve
    ``guncel_surum`` ile işaretlenir — madde SESSİZCE KAYBOLMAZ.

    Seriye ait her satıra ``eski_surum_sayisi`` ve ``eski_surumler`` eklenir.
    Seride olmayan sonuçlara hiçbir alan eklenmez (davranış değişmez).
    """
    if not results:
        return []
    ids = [x for x in {r.get("mevzuat_id") for r in results} if x]
    if not ids:
        return results if limit is None else results[:limit]

    dok: dict[str, dict[str, Any]] = {}
    try:
        satirlar = []
        for i in range(0, len(ids), 400):
            parca = ids[i : i + 400]
            satirlar.extend(db.execute(
                "SELECT mevzuat_id, mevzuat_no, tur, ad, kaynak_url, rg_tarihi,"
                " grup_anahtari, COALESCE(guncel, 1) FROM mevzuat_dokuman"
                f" WHERE mevzuat_id IN ({','.join('?' * len(parca))})",
                parca,
            ).fetchall())
    except sqlite3.OperationalError:
        # Sürüm sütunları olmayan (ör. test fikstürü ya da göç edilmemiş) bir
        # şema: katlama bir İYİLEŞTİRME, aramayı düşürmemeli.
        return results if limit is None else results[:limit]
    for r in satirlar:
        dok[r[0]] = {
            "mevzuat_no": r[1], "tur": r[2], "ad": r[3], "kaynak_url": r[4],
            "rg_tarihi": r[5], "grup": r[6], "guncel": int(r[7] or 0),
        }

    uyeler: dict[str, list[dict[str, Any]]] = {}
    for grup in {d["grup"] for d in dok.values() if d["grup"]}:
        rows = db.execute(
            "SELECT mevzuat_id, mevzuat_no, rg_tarihi, COALESCE(guncel, 1), ad,"
            " kaynak_url, tur FROM mevzuat_dokuman WHERE grup_anahtari = ?",
            (grup,),
        ).fetchall()
        uyeler[grup] = sorted(
            (
                {
                    "mevzuat_id": r[0], "mevzuat_no": r[1], "rg_tarihi": r[2],
                    "guncel": int(r[3] or 0), "ad": r[4], "kaynak_url": r[5],
                    "tur": r[6],
                }
                for r in rows
            ),
            key=lambda u: (_rg_date(u["rg_tarihi"]) or date.min),
            reverse=True,
        )

    madde_dizin: dict[str, dict[str, tuple[Any, ...]]] = {}

    def _dizin(mid: str) -> dict[str, tuple[Any, ...]]:
        d = madde_dizin.get(mid)
        if d is None:
            d = {
                _norm_article_no(str(r[0])): tuple(r)
                for r in db.execute(
                    "SELECT madde_no, sira, baslik, degisiklik_notu, ust_baslik"
                    " FROM mevzuat_madde WHERE mevzuat_id = ?",
                    (mid,),
                ).fetchall()
            }
            madde_dizin[mid] = d
        return d

    gorulen: set[tuple[Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for r in results:
        mid = r.get("mevzuat_id")
        d = dok.get(mid)  # type: ignore[arg-type]
        grup = d["grup"] if d else None
        yeni = dict(r)
        if grup:
            liste = uyeler.get(grup, [])
            guncel_dok = next((u for u in liste if u["guncel"]), None)
            if guncel_dok is not None and guncel_dok["mevzuat_id"] != mid:
                hedef = _dizin(guncel_dok["mevzuat_id"]).get(
                    _norm_article_no(str(r.get("madde_no") or ""))
                )
                if hedef is not None:
                    metin = db.execute(
                        "SELECT metin FROM mevzuat_madde WHERE mevzuat_id = ? AND sira = ?",
                        (guncel_dok["mevzuat_id"], hedef[1]),
                    ).fetchone()
                    yeni.update({
                        "mevzuat_id": guncel_dok["mevzuat_id"],
                        "mevzuat_no": guncel_dok["mevzuat_no"],
                        "mevzuat_adi": guncel_dok["ad"],
                        "tur": guncel_dok["tur"],
                        "kaynak_url": guncel_dok["kaynak_url"],
                        "madde_no": hedef[0],
                        "sira": hedef[1],
                        "baslik": hedef[2],
                        "degisiklik_notu": hedef[3],
                        "snippet": _snippet_uret(
                            (metin[0] if metin else ""), kelimeler
                        ),
                        # FTS satırı ESKİ sürüme aitti; snippet artık güncel
                        # metinden geliyor, rowid'i taşımaya devam etmemeli.
                        "_fts_rowid": None,
                        "guncel": True,
                        "eslesen_surum": {
                            "mevzuat_no": d["mevzuat_no"], "rg_tarihi": d["rg_tarihi"],  # type: ignore[index]
                        },
                    })
                else:
                    yeni["guncel"] = False
                    yeni["guncel_surum"] = {
                        "mevzuat_no": guncel_dok["mevzuat_no"],
                        "rg_tarihi": guncel_dok["rg_tarihi"],
                        "ad": guncel_dok["ad"],
                    }
            else:
                yeni["guncel"] = True
            eski = [
                {"mevzuat_no": u["mevzuat_no"], "rg_tarihi": u["rg_tarihi"]}
                for u in liste
                if not u["guncel"]
            ]
            yeni["eski_surum_sayisi"] = len(eski)
            yeni["eski_surumler"] = eski[:10]
            yeni["grup_anahtari"] = grup

        key = (grup or yeni.get("mevzuat_id"), _norm_article_no(str(yeni.get("madde_no") or "")))
        if key in gorulen:
            continue
        gorulen.add(key)
        out.append(yeni)
        if limit is not None and len(out) >= limit:
            break
    return out


# ── Arama ──────────────────────────────────────────────────────────────────

# FTS5'in sorgu dilinde anlamı olan her şey ("AND", tırnak, yıldız, iki nokta,
# parantez) kullanıcı sorgusundan temizlenir: aksi hâlde "m. 6/A" gibi bir
# ifade sözdizimi hatasıyla düşer.
_FTS_TOKEN_RE = re.compile(r"[0-9A-Za-zÇçĞğIıİiÖöŞşÜü]+")

#: AND sorgusu bu sayının ALTINDA sonuç döndürürse aynı kelimelerle OR'a
#: düşülür. Ölçüldü: "konut kirasında kiracı tahliye taahhüdü dava yoluyla
#: sona erme" AND ile 0 satır döndürüyor, melez arama tamamen semantik
#: katmana kalıyordu; BM25 zaten çok kelime eşleşen maddeyi üste alır.
_OR_ESIK = 3


def _fts_tokens(query: str) -> list[str]:
    return _FTS_TOKEN_RE.findall(query or "")


def _fts_query(query: str, operator: str = "AND") -> str:
    """Ham kelimeleri AND'li (ya da OR'lu), tırnaklanmış bir FTS5 sorgusuna çevir."""
    return f" {operator} ".join(f'"{t}"' for t in _fts_tokens(query))


# Arama İKİ AŞAMALI: önce yalnız FTS tablosundan (rowid, bm25), sonra seçilen
# satırlar için üstveri. Ölçüldü (6 Eyl 2026, 298.854 madde, 9 kelimelik OR
# sorgusu, 20.536 eşleşme): tek birleşik sorgu 278 ms, iki aşamalı 55+14 ms.
# Fark, JOIN'lerin sıralamadan ÖNCE 20 bin satıra uygulanmasından geliyordu.
_FTS_SQL = (
    "SELECT rowid, bm25(mevzuat_madde_fts) AS skor FROM mevzuat_madde_fts"
    " WHERE mevzuat_madde_fts MATCH ? ORDER BY skor LIMIT ?"
)

_USTVERI_SQL = (
    "SELECT m.rowid, d.mevzuat_id, d.mevzuat_no, d.tur, d.ad, d.kaynak_url,"
    " m.madde_no, m.baslik, m.degisiklik_notu"
    " FROM mevzuat_madde m JOIN mevzuat_dokuman d ON d.mevzuat_id = m.mevzuat_id"
)

# mevzuat_no süzgeci varken tek sorgu kalır: süzülen satırlar üst sıraları
# yemesin diye eleme FTS ile AYNI sorguda olmalı.
_SUZGECLI_SQL = (
    "SELECT m.rowid, d.mevzuat_id, d.mevzuat_no, d.tur, d.ad, d.kaynak_url,"
    " m.madde_no, m.baslik, m.degisiklik_notu, bm25(mevzuat_madde_fts) AS skor"
    " FROM mevzuat_madde_fts"
    " JOIN mevzuat_madde m ON m.rowid = mevzuat_madde_fts.rowid"
    " JOIN mevzuat_dokuman d ON d.mevzuat_id = m.mevzuat_id"
    " WHERE mevzuat_madde_fts MATCH ? AND d.mevzuat_no = ? ORDER BY skor LIMIT ?"
)


def _fts_ara(
    db: sqlite3.Connection, match: str, mevzuat_no: str | None, limit: int
) -> list[tuple[Any, ...]]:
    """``(rowid, mevzuat_id, mevzuat_no, tur, ad, kaynak_url, madde_no, baslik,
    degisiklik_notu, skor)`` satırları, BM25 sırasında."""
    if mevzuat_no is not None and str(mevzuat_no).strip():
        return [
            tuple(r)
            for r in db.execute(
                _SUZGECLI_SQL, (match, str(mevzuat_no).strip(), limit)
            ).fetchall()
        ]
    ids = db.execute(_FTS_SQL, (match, limit)).fetchall()
    if not ids:
        return []
    skor = {r[0]: r[1] for r in ids}
    ustveri = {
        r[0]: tuple(r)
        for r in db.execute(
            _USTVERI_SQL + f" WHERE m.rowid IN ({','.join('?' * len(ids))})",
            [r[0] for r in ids],
        ).fetchall()
    }
    return [(*ustveri[r[0]], skor[r[0]]) for r in ids if r[0] in ustveri]


def _fts_snippetler(
    db: sqlite3.Connection, match: str, rowids: list[int]
) -> dict[int, str]:
    """Yalnız NİHAİ satırlar için snippet üret (katlama sonrası, ≤ limit tane)."""
    if not rowids:
        return {}
    rows = db.execute(
        "SELECT rowid, snippet(mevzuat_madde_fts, 2, '«', '»', ' … ', 24)"
        " FROM mevzuat_madde_fts WHERE mevzuat_madde_fts MATCH ?"
        f" AND rowid IN ({','.join('?' * len(rowids))})",
        [match, *rowids],
    ).fetchall()
    return {r[0]: r[1] for r in rows}


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

    İki davranış notu:

    * Kelimeler önce AND'lenir; ``_OR_ESIK``in altında sonuç gelirse aynı
      kelimelerle OR sorgusu koşulur ve ``lexical_fallback = "or"`` işaretlenir.
      Kullanılan sorgu her zaman ``fts_query`` alanındadır.
    * Aynı adla yeniden yayımlanan tebliğlerin eski sürümleri ``surum_katla``
      ile tek satıra iner (bkz. ``gruplari_yenile``).
    """
    ensure_schema(db)
    tokens = _fts_tokens(query)
    if not tokens:
        return {
            "ok": False,
            "errorCode": "INVALID_INPUT",
            "message": "Sorgu boş ya da yalnızca noktalama içeriyor.",
            "results": [],
            "total_matches": 0,
        }

    limit = max(1, int(limit))
    # Katlama payı: aynı serinin 20 yılı üst sıraları doldurabilir.
    ic_limit = min(max(limit * 3, limit + 40), 300)
    match = " AND ".join(f'"{t}"' for t in tokens)
    rows = _fts_ara(db, match, mevzuat_no, ic_limit)
    fallback = None
    if len(tokens) > 1 and len(rows) < _OR_ESIK:
        or_match = " OR ".join(f'"{t}"' for t in tokens)
        or_rows = _fts_ara(db, or_match, mevzuat_no, ic_limit)
        if len(or_rows) > len(rows):
            rows, match, fallback = or_rows, or_match, "or"

    results = [
        {
            "mevzuat_id": r[1],
            "mevzuat_no": r[2],
            "tur": r[3],
            "mevzuat_adi": r[4],
            "kaynak_url": r[5],
            "madde_no": r[6],
            "baslik": r[7],
            "degisiklik_notu": r[8],
            "snippet": "",
            "skor": round(float(r[9]), 4),
            "_fts_rowid": r[0],
        }
        for r in rows
    ]
    results = surum_katla(db, results, limit=limit, kelimeler=tokens)
    # Snippet PAHALI: yalnız katlamadan sağ çıkan satırlar için üretilir.
    snipler = _fts_snippetler(
        db, match, [r["_fts_rowid"] for r in results if r.get("_fts_rowid") and not r["snippet"]]
    )
    for r in results:
        rid = r.pop("_fts_rowid", None)
        if not r["snippet"]:
            r["snippet"] = snipler.get(rid, "")
    out: dict[str, Any] = {
        "ok": True,
        "query": query,
        "fts_query": match,
        "results": results,
        "total_matches": len(results),
    }
    if fallback:
        out["lexical_fallback"] = fallback
    return out


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


# ── Ertelenmiş yürürlük ─────────────────────────────────────────────────────
#
# mevzuat.gov.tr, ileri bir tarihte yürürlüğe girecek değişikliği konsolide
# metne o gün gelene kadar işlemez; maddeye yalnız bir dipnot düşer:
# "7589 sayılı Kanunun 12 nci maddesiyle yayımı tarihinden itibaren üç ay
# sonra (31/10/2026) yürürlüğe girmek üzere bu fıkra değiştirilmiştir. Söz
# konusu düzenleme, yürürlüğe girdiği tarihte Mevzuat Bilgi Sistemine
# işlenecek ...". Tarih geçtikten sonra korpustaki metin, kaynak işleyip biz
# yeniden çekene kadar ESKİDİR. Ölçüm (4.11.2026): TMK 444 ve HMK 149
# 31.10.2026'dan beri yürürlükteydi, mevzuat.gov.tr işlemişti, haftalık
# koşu ise "güncel=0" bildirdi (Bedesten kayitTarihi sinyali gelmedi).
# Korpusta 13 kayıt, iki kalıp: "... ay sonra (31/10/2026) yürürlüğe girmek"
# ve "... 1/1/2027 tarihinde yürürlüğe girmek".
_BEKLEYEN_TARIH_RE = re.compile(
    r"(?:\(\s*(?P<g1>\d{1,2})\s*/\s*(?P<a1>\d{1,2})\s*/\s*(?P<y1>\d{4})\s*\)"
    r"|(?P<g2>\d{1,2})\s*/\s*(?P<a2>\d{1,2})\s*/\s*(?P<y2>\d{4})\s+tarihinde)"
    r"\s*y[üu]r[üu]rl[üu][ğg]e\s+girmek",
    re.IGNORECASE,
)
_ISLENECEK_RE = re.compile(r"Mevzuat\s+Bilgi\s+Sistemine\s+i[şs]lenecek", re.IGNORECASE)


def bekleyen_yururluk_tarihi(ham: str | None) -> str | None:
    """Dipnot, konsolide metne henüz işlenmemiş ertelenmiş bir değişikliği
    anlatıyorsa o değişikliğin yürürlük tarihini (ISO) döndür, değilse None.

    İki koşul birlikte aranır: "Mevzuat Bilgi Sistemine işlenecek" ibaresi
    (değişiklik metne girmemiş) ve bir yürürlük tarihi. Kaynak değişikliği
    işlediğinde bu dipnot kalkar ya da ibare değişir; o zaman None döner.
    """
    if not ham or not _ISLENECEK_RE.search(ham):
        return None
    m = _BEKLEYEN_TARIH_RE.search(ham)
    if not m:
        return None
    if m.group("y1"):
        g, a, y = m.group("g1"), m.group("a1"), m.group("y1")
    else:
        g, a, y = m.group("g2"), m.group("a2"), m.group("y2")
    try:
        return date(int(y), int(a), int(g)).isoformat()
    except ValueError:
        return None


def _rg_gun_url(rg_tarihi: str | None) -> str:
    """O günün Resmi Gazete fihristi (kalem numarası bilinmediği için gün)."""
    try:
        d = date.fromisoformat(str(rg_tarihi or ""))
    except ValueError:
        return ""
    return f"https://www.resmigazete.gov.tr/eskiler/{d:%Y}/{d:%m}/{d:%Y%m%d}.htm"


def _tr_tarih(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def yururluk_uyarilari(
    degisiklikler: list[dict[str, Any]], bugun: date | None = None
) -> list[dict[str, Any]]:
    """Değişiklik kayıtlarından ertelenmiş yürürlük uyarıları üret.

    ``durum``:
    * ``yururlukte_islenmedi``: yürürlük tarihi geldi ama korpustaki metin
      değişikliği içermiyor, metin ESKİ.
    * ``ileride_yururluge_girecek``: metin bugün için doğru, ileride değişecek.
    """
    bugun = bugun or date.today()
    out: list[dict[str, Any]] = []
    gorulen: set[tuple[str, str, str]] = set()
    for d in degisiklikler:
        tarih = bekleyen_yururluk_tarihi(d.get("ham"))
        if not tarih:
            continue
        no, md = str(d.get("degistiren_no") or ""), str(d.get("degistiren_madde") or "")
        anahtar = (tarih, no, md)
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        ref = f"{no}/{md} md." if no and md else (f"{no} sayılı düzenleme" if no else "dipnottaki düzenleme")
        rg_t, rg_s = str(d.get("rg_tarihi") or ""), str(d.get("rg_sayisi") or "")
        rg = (
            f"{_tr_tarih(rg_t)} tarihli ve {rg_s} sayılı Resmi Gazete"
            if rg_t and rg_s else "dipnotta anılan Resmi Gazete"
        )
        yururlukte = date.fromisoformat(tarih) <= bugun
        if yururlukte:
            durum = "yururlukte_islenmedi"
            mesaj = (
                f"Bu maddeyi değiştiren {ref} {_tr_tarih(tarih)} tarihinde yürürlüğe "
                f"girdi, ama korpustaki metne henüz işlenmedi: aşağıdaki metin "
                f"değişiklikten ÖNCEKİ halidir. Güncel metin için {rg}."
            )
        else:
            durum = "ileride_yururluge_girecek"
            mesaj = (
                f"Bu maddeyi {_tr_tarih(tarih)} tarihinde değiştirecek bir düzenleme "
                f"var ({ref}); aşağıdaki metin bugün yürürlükte olan halidir. "
                f"Yeni metin için {rg}."
            )
        kayit: dict[str, Any] = {
            "durum": durum,
            "yururluk_tarihi": tarih,
            "degistiren_no": no,
            "degistiren_madde": md,
            "kapsam": d.get("kapsam", ""),
            "rg_tarihi": rg_t,
            "rg_sayisi": rg_s,
            "mesaj": mesaj,
        }
        url = _rg_gun_url(rg_t)
        if url:
            kayit["rg_url"] = url
        out.append(kayit)
    return out


def bekleyen_yururlukler(
    db: sqlite3.Connection, bugun: date | None = None, yalniz_gelmis: bool = True
) -> list[dict[str, Any]]:
    """Korpusta ertelenmiş yürürlük dipnotu taşıyan maddeler.

    ``yalniz_gelmis`` True ise yalnız yürürlük tarihi bugün ya da daha önce
    olanlar (metni eskimiş, yeniden çekilmesi gerekenler) döner.
    """
    bugun = bugun or date.today()
    rows = db.execute(
        """SELECT g.mevzuat_id, d.tur, d.mevzuat_no, d.ad, m.madde_no, g.sira,
                  g.degistiren_no, g.degistiren_madde, g.ham
           FROM mevzuat_degisiklik g
           JOIN mevzuat_dokuman d ON d.mevzuat_id = g.mevzuat_id
           LEFT JOIN mevzuat_madde m ON m.mevzuat_id = g.mevzuat_id AND m.sira = g.sira
           WHERE g.ham LIKE '%Bilgi Sistemine%'
           ORDER BY g.mevzuat_id, g.sira"""
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        tarih = bekleyen_yururluk_tarihi(r[8])
        if not tarih:
            continue
        if yalniz_gelmis and date.fromisoformat(tarih) > bugun:
            continue
        out.append({
            "mevzuat_id": r[0], "tur": r[1], "mevzuat_no": r[2], "ad": r[3],
            "madde_no": r[4], "sira": r[5], "degistiren_no": r[6],
            "degistiren_madde": r[7], "yururluk_tarihi": tarih,
        })
    return out


def _surum_uyarisi(db: sqlite3.Connection, mevzuat_id: str) -> dict[str, Any]:
    """Belge bir sürüm serisinin ESKİ üyesiyse güncel sürüme yönlendir.

    Eski numara ile çağrı ÇALIŞMAYA DEVAM eder (kullanıcı bilerek yıl seçmiş
    olabilir); yalnızca ``guncel_surum`` uyarısı eklenir.
    """
    row = db.execute(
        "SELECT grup_anahtari, COALESCE(guncel, 1) FROM mevzuat_dokuman"
        " WHERE mevzuat_id = ?",
        (mevzuat_id,),
    ).fetchone()
    if not row or not row[0]:
        return {}
    grup, guncel = row[0], int(row[1] or 0)
    uyeler = db.execute(
        "SELECT mevzuat_no, rg_tarihi, ad, COALESCE(guncel, 1) FROM mevzuat_dokuman"
        " WHERE grup_anahtari = ?",
        (grup,),
    ).fetchall()
    eski = sorted(
        (u for u in uyeler if not int(u[3] or 0)),
        key=lambda u: (_rg_date(u[1]) or date.min),
        reverse=True,
    )
    out: dict[str, Any] = {
        "grup_anahtari": grup,
        "guncel": bool(guncel),
        "eski_surum_sayisi": len(eski),
        "eski_surumler": [
            {"mevzuat_no": u[0], "rg_tarihi": u[1]} for u in eski[:10]
        ],
    }
    if not guncel:
        yeni = next((u for u in uyeler if int(u[3] or 0)), None)
        if yeni is not None:
            out["guncel_surum"] = {
                "mevzuat_no": yeni[0], "rg_tarihi": yeni[1], "ad": yeni[2],
            }
    return out


# Aynı numara farklı türlerde tekrar ediyor (4.11.2026: 161 numara; 7589 hem
# kanun hem bir üniversite yönetmeliği). Eskiden iki belgenin maddeleri tek
# listede karışıyordu; artık tek belge seçilir, öncelik bu sıradadır ve
# konsolide metin (mevzuat.gov.tr) Resmi Gazete ilk yayımının önündedir.
_TUR_ONCELIK_SQL = (
    "CASE tur WHEN 'KANUN' THEN 0 WHEN 'KHK' THEN 1 WHEN 'CBK' THEN 2 "
    "WHEN 'TUZUK' THEN 3 ELSE 4 END"
)

_RG_METIN_NOTU = (
    "Bu metin Resmi Gazete'deki ilk yayımdır, konsolide değildir: kanunun "
    "sonradan değişen hükümleri işlenmemiştir. Kanunun başka kanunlarda "
    "değiştirdiği maddelerin güncel hali için o kanunlara bakın "
    "(mevzuat_degisiklik_haritasi)."
)


def aday_belgeler(
    db: sqlite3.Connection, mevzuat_no: str, tur: str | None = None
) -> list[dict[str, Any]]:
    """Bu numarayı taşıyan belgeler, öncelik sırasıyla."""
    sql = (
        "SELECT mevzuat_id, tur, ad, kaynak, kaynak_url, rg_tarihi, rg_sayisi"
        " FROM mevzuat_dokuman WHERE mevzuat_no = ?"
    )
    params: list[Any] = [str(mevzuat_no).strip()]
    if tur:
        sql += " AND upper(tur) = ?"
        params.append(str(tur).strip().upper())
    sql += f" ORDER BY {_TUR_ONCELIK_SQL}, (kaynak = 'resmigazete'), mevzuat_id"
    alanlar = ("mevzuat_id", "tur", "mevzuat_adi", "kaynak", "kaynak_url",
               "rg_tarihi", "rg_sayisi")
    return [dict(zip(alanlar, r)) for r in db.execute(sql, params).fetchall()]


def get_madde(
    db: sqlite3.Connection,
    mevzuat_no: str,
    madde_no: str,
    tur: str | None = None,
) -> dict[str, Any]:
    """Tek bir maddenin tam metni.

    ``madde_no`` "12", "12/A", "Geçici 1", "geçici 1" hepsi aynı maddeye
    çözülür; karşılaştırma ``legislation._norm_article_no`` ile yapılır, yani
    araç yüzeyindeki numaralandırmayla birebir aynı. Numara birden çok
    belgede geçiyorsa ``tur`` verilmedikçe öncelikli belge (kanun) seçilir,
    diğerleri ``ayni_numarali_diger`` alanında listelenir.
    """
    ensure_schema(db)
    belgeler = aday_belgeler(db, mevzuat_no, tur)
    if not belgeler:
        ek = f" ({str(tur).upper()} türünde)" if tur else ""
        return {
            "ok": False,
            "errorCode": "NOT_FOUND",
            "message": (
                f"{mevzuat_no} sayılı mevzuat{ek} yerel korpusta yok. Korpus yalnızca "
                "çekilmiş mevzuatı içerir; çekmek için scripts/mevzuat_pull.py, "
                "canlı sorgu için search_legislation/get_legislation kullanın."
            ),
        }
    secilen, diger = belgeler[0], belgeler[1:]
    rows = db.execute(
        """SELECT d.mevzuat_id, d.mevzuat_no, d.tur, d.ad, d.kaynak_url,
                  m.madde_no, m.sira, m.baslik, m.metin, m.degisiklik_notu,
                  m.ust_baslik
           FROM mevzuat_madde m
           JOIN mevzuat_dokuman d ON d.mevzuat_id = m.mevzuat_id
           WHERE d.mevzuat_id = ?
           ORDER BY m.sira""",
        (secilen["mevzuat_id"],),
    ).fetchall()
    diger_ozet = [
        {"mevzuat_id": b["mevzuat_id"], "tur": b["tur"], "mevzuat_adi": b["mevzuat_adi"]}
        for b in diger
    ]
    if not rows:
        return {
            "ok": False,
            "errorCode": "NOT_FOUND",
            "message": f"{mevzuat_no} sayılı mevzuatın ({secilen['mevzuat_id']}) maddesi yok.",
            "ayni_numarali_diger": diger_ozet,
        }

    target = _norm_article_no(str(madde_no))
    for r in rows:
        if _norm_article_no(str(r[5])) == target:
            cevap = {
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
            cevap.update(_surum_uyarisi(db, r[0]))
            if secilen["kaynak"] == "resmigazete":
                cevap["metin_turu"] = "resmi_gazete_ilk_yayim"
                cevap["metin_notu"] = _RG_METIN_NOTU
            if diger_ozet:
                cevap["ayni_numarali_diger"] = diger_ozet
                cevap["ayni_numarali_not"] = (
                    "Bu numara başka mevzuatta da var; onu görmek için tur "
                    "parametresini verin (ör. tur='YONETMELIK')."
                )
            uyarilar = yururluk_uyarilari(cevap["degisiklikler"])
            if uyarilar:
                cevap["yururluk_uyarilari"] = uyarilar
                eski = [u for u in uyarilar if u["durum"] == "yururlukte_islenmedi"]
                if eski:
                    # Uyarı metinden ÖNCE görünsün: okuyan model "metin"i
                    # alıp geçmesin diye en üste konur.
                    cevap = {
                        "ok": True,
                        "metin_eski": True,
                        "uyari": " ".join(u["mesaj"] for u in eski),
                        **{k: v for k, v in cevap.items() if k != "ok"},
                    }
            return cevap
    return {
        "ok": False,
        "errorCode": "NOT_FOUND",
        "message": (
            f"{mevzuat_no} sayılı mevzuatta '{madde_no}' maddesi bulunamadı "
            f"({len(rows)} madde kayıtlı)."
        ),
        "mevzuat_adi": rows[0][3],
        "mevcut_madde_sayisi": len(rows),
        **({"ayni_numarali_diger": diger_ozet} if diger_ozet else {}),
    }


# ── Değişiklik kanunu haritası ──────────────────────────────────────────────

_YERINE_ISLENMIS_RE = re.compile(r"ilgili\s+olup,?\s+yerine\s+i[şs]lenmi[şs]tir", re.IGNORECASE)
_YURURLUK_YURUTME_RE = re.compile(
    r"y[üu]r[üu]rl[üu][ğg]e\s+girer|h[üu]k[üu]mlerini\s+.{0,40}y[üu]r[üu]t[üu]r",
    re.IGNORECASE,
)


def _ozet(metin: str, n: int = 220) -> str:
    duz = re.sub(r"\s+", " ", metin or "").strip()
    return duz if len(duz) <= n else duz[: n - 3].rstrip() + "..."


def _madde_durumu(hamlar: list[str], bugun: date) -> tuple[str, str | None]:
    tarihler = [t for t in (bekleyen_yururluk_tarihi(h) for h in hamlar) if t]
    if not tarihler:
        return "islendi", None
    gelmis = [t for t in tarihler if date.fromisoformat(t) <= bugun]
    if gelmis:
        return "yururlukte_islenmedi", min(gelmis)
    return "ileride_yururluge_girecek", min(tarihler)


def degisiklik_haritasi(
    db: sqlite3.Connection,
    kanun_no: str,
    rg_db: sqlite3.Connection | None = None,
    bugun: date | None = None,
) -> dict[str, Any]:
    """Bir değişiklik kanununun hangi mevzuatın hangi maddelerini değiştirdiği.

    Kaynaklar: (1) temel kanunlardaki değişiklik kayıtları
    (``mevzuat_degisiklik.degistiren_no``, "(Değişik: 16/7/2026-7589/13 md.)"
    ve dipnotlardan), (2) kanunun kendi belgesi (geçici maddeleri, kendi
    hükümleri), (3) varsa Resmi Gazete dizinindeki künyesi.
    """
    ensure_schema(db)
    bugun = bugun or date.today()
    no = str(kanun_no).strip()
    rows = db.execute(
        """SELECT g.mevzuat_id, d.tur, d.mevzuat_no, d.ad, m.madde_no, g.sira,
                  g.kapsam, g.tur, g.degistiren_madde, g.ham
           FROM mevzuat_degisiklik g
           JOIN mevzuat_dokuman d ON d.mevzuat_id = g.mevzuat_id
           LEFT JOIN mevzuat_madde m ON m.mevzuat_id = g.mevzuat_id AND m.sira = g.sira
           WHERE g.degistiren_no = ?
           ORDER BY d.mevzuat_no, g.sira""",
        (no,),
    ).fetchall()

    hedefler: dict[str, dict[str, Any]] = {}
    maddeler: dict[tuple[str, int], dict[str, Any]] = {}
    degistiren: set[str] = set()
    for mid, tur, mno, ad, madde_no, sira, kapsam, gtur, dmadde, ham in rows:
        hedef = hedefler.setdefault(mid, {
            "mevzuat_id": mid, "tur": tur, "mevzuat_no": mno,
            "mevzuat_adi": ad, "maddeler": [],
        })
        anahtar = (mid, sira)
        if anahtar not in maddeler:
            maddeler[anahtar] = {"madde_no": madde_no, "islemler": [],
                                 "degistiren_maddeler": [], "_ham": []}
            hedef["maddeler"].append(maddeler[anahtar])
        kayit = maddeler[anahtar]
        islem = " ".join(x for x in (gtur, kapsam) if x)
        if islem and islem not in kayit["islemler"]:
            kayit["islemler"].append(islem)
        if dmadde:
            degistiren.add(str(dmadde))
            if dmadde not in kayit["degistiren_maddeler"]:
                kayit["degistiren_maddeler"].append(dmadde)
        kayit["_ham"].append(ham or "")
    sayac = {"islendi": 0, "yururlukte_islenmedi": 0, "ileride_yururluge_girecek": 0}
    for kayit in maddeler.values():
        durum, tarih = _madde_durumu(kayit.pop("_ham"), bugun)
        kayit["durum"] = durum
        if tarih:
            kayit["yururluk_tarihi"] = tarih
        sayac[durum] += 1

    # Kanunun kendi belgesi: konsolide (mevzuat.gov.tr) varsa o, yoksa RG metni.
    kanun_belgesi = next(iter(aday_belgeler(db, no, "KANUN")), None)
    kendi: list[dict[str, Any]] = []
    izsiz: list[dict[str, Any]] = []
    if kanun_belgesi:
        km = db.execute(
            "SELECT madde_no, metin FROM mevzuat_madde WHERE mevzuat_id = ? ORDER BY sira",
            (kanun_belgesi["mevzuat_id"],),
        ).fetchall()
        for madde_no, metin in km:
            mn = str(madde_no)
            gecici = bool(re.match(r"Ge[çc]ici\b", mn, re.IGNORECASE))
            yerine = bool(_YERINE_ISLENMIS_RE.search(metin or ""))
            yururluk = bool(_YURURLUK_YURUTME_RE.search(metin or ""))
            if gecici or (not yerine and mn not in degistiren):
                kendi.append({
                    "madde_no": mn,
                    "tur": "gecici" if gecici else ("yururluk_yurutme" if yururluk else "metin"),
                    "ozet": _ozet(metin),
                })
            if mn.isdigit() and mn not in degistiren and not yururluk and not gecici:
                izsiz.append({"madde_no": mn, "ozet": _ozet(metin, 160)})

    rg: dict[str, Any] | None = None
    if rg_db is not None:
        try:
            r = rg_db.execute(
                "SELECT item_id, tarih, sayi_no, baslik, url FROM rg_ogeler"
                " WHERE numara = ? AND upper(kategori) IN ('KANUN', 'KANUNLAR')"
                " ORDER BY tarih LIMIT 1",
                (no,),
            ).fetchone()
        except sqlite3.Error:
            r = None
        if r:
            rg = {"item_id": r[0], "tarih": r[1], "sayi": r[2], "baslik": r[3], "url": r[4]}

    if not rows and not kanun_belgesi and not rg:
        return {
            "ok": False,
            "errorCode": "NOT_FOUND",
            "message": (
                f"{no} sayılı kanuna ait değişiklik kaydı, kanun metni ya da "
                "Resmi Gazete künyesi yerel korpusta yok."
            ),
        }

    uyarilar = []
    if izsiz:
        uyarilar.append(
            "korpusta_izi_olmayan_maddeler: bu maddelerin hedefindeki mevzuat korpusta "
            "yok ya da değişiklik notu ayrıştırılamadı. 'Değişiklik yok' DEMEK DEĞİLDİR; "
            "madde metnine bakın."
        )
    if sayac["yururlukte_islenmedi"]:
        uyarilar.append(
            "Bazı maddelerde yürürlüğe girmiş değişiklik metne işlenmemiş: o maddelerin "
            "korpustaki metni eskidir (mevzuat_madde_getir uyari alanı)."
        )
    if kanun_belgesi and kanun_belgesi["kaynak"] == "resmigazete":
        uyarilar.append(_RG_METIN_NOTU)

    return {
        "ok": True,
        "kanun_no": no,
        "kanun": (
            {k: kanun_belgesi[k] for k in ("mevzuat_id", "mevzuat_adi", "kaynak",
                                           "rg_tarihi", "rg_sayisi", "kaynak_url")}
            if kanun_belgesi else None
        ),
        "resmi_gazete": rg,
        "ozet": {
            "etkilenen_mevzuat": len(hedefler),
            "etkilenen_madde": len(maddeler),
            **sayac,
        },
        "etkilenen": list(hedefler.values()),
        "kanunun_kendi_hukumleri": kendi,
        "korpusta_izi_olmayan_maddeler": izsiz,
        "uyarilar": uyarilar,
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
