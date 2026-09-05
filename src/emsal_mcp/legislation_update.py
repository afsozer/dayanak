"""Mevzuat korpusunun haftalık güncellenmesi (Faz 2b).

Neden ayrı modül: ``legislation_corpus`` korpusun şemasını ve madde ayrımını
tutuyor; burada tutulan şey "ne değişti" sorusu — kaynak tarafındaki değişim
sinyalleri, eski metnin arşivi ve koşu günlüğü. İkisini ayırmak, korpus
ayrıştırıcısı geliştikçe güncelleme mantığının rahatsız edilmemesini sağlıyor.

ÖLÇÜLMÜŞ KAYNAK DAVRANIŞI (05.09.2026, canlı):

* mevzuat.gov.tr ``MevzuatDatatable`` satırında **güncelleme tarihi yok**.
  Alanlar (``mevzuatNo``, ``mevAdi``, ``kabulTarih``, ``resmiGazeteTarihi``,
  ``resmiGazeteSayisi``, ``mevzuatTertip``, ``mukerrer``, …) mevzuatın İLK
  yayımına ait; bir kanun 40 kez değişse de bu satır sabit kalır. Yani
  listelemeye bakarak "bu metin değişmiş mi" sorusu CEVAPLANAMAZ.
* Bedesten (``/mevzuat/searchDocuments``) satırı ``kayitTarihi`` veriyor ve bu
  alan UYAP'ın konsolide metni en son ne zaman yeniden yüklediğini gösteriyor
  (ör. 05.09.2026'da CEZA MUHAKEMESİ KANUNU → 2026-09-03T11:00). Varsayılan
  sıralama zaten ``kayitTarihi`` azalan. ``guncellemeTarihi`` alanı her satırda
  ``null`` — kullanılamaz. ``sortFields`` enum'u ``GUNCELLEME_TARIHI`` kabul
  ETMİYOR; geçerli değer ``KAYIT_TARIHI``.

Bundan çıkan strateji: değişim sinyali **Bedesten ``kayitTarihi``**. Tür başına
KAYIT_TARIHI azalan listelenir, eşik tarihin altına inince durulur — tür başına
1-2 istek. Sonra yalnız (a) korpusta hiç olmayan, (b) taze kayıt listesinde
görünen, (c) RG tarih/sayısı DB'dekinden farklı olan mevzuatın tam metni
çekilir.

KURU KOŞU ÖLÇÜMÜ (05.09.2026, üretim korpusu 1 012 belge, KANUN+KHK+CBK):
1 007 "değişmemiş" (hiç ağa çıkılmadı), 2 "kayıt tarihi", 3 "rg değişti" →
1 012 yerine 5 belge indirilir. Maliyet: 12 listeleme isteği 88 s + Bedesten
0,6 s + 5 metin ≈ 1,5 dk; aynı işin tam çekimi ~7,6 dk (13 bin belgelik hedef
korpusta ~1,6 saat).

``rg_degisti`` yanlış pozitif verebilir: korpustaki bazı eski satırların
``rg_sayisi`` sütunu boş (``meta_json``da dolu). Bu satır bir kez çekilir,
sütun dolar ve sinyal kendiliğinden susar — 1 012 belgede 3 satır.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

# ── Şema ────────────────────────────────────────────────────────────────────

_GECMIS_TABLE = """\
CREATE TABLE IF NOT EXISTS mevzuat_dokuman_gecmis (
    mevzuat_id TEXT NOT NULL,
    metin TEXT,
    metin_hash TEXT,
    guncelleme_tarihi TEXT,
    arsivlenme_zamani TEXT NOT NULL
);"""

_GECMIS_INDEX = (
    "CREATE INDEX IF NOT EXISTS mevzuat_dokuman_gecmis_id "
    "ON mevzuat_dokuman_gecmis(mevzuat_id, arsivlenme_zamani);"
)

_LOG_TABLE = """\
CREATE TABLE IF NOT EXISTS mevzuat_guncelleme_log (
    kosu_zamani TEXT NOT NULL,
    tur TEXT,
    listelenen INTEGER,
    degisen INTEGER,
    yeni INTEGER,
    hata INTEGER,
    sure_s REAL
);"""

_LOG_INDEX = (
    "CREATE INDEX IF NOT EXISTS mevzuat_guncelleme_log_zaman "
    "ON mevzuat_guncelleme_log(kosu_zamani);"
)


def ensure_update_schema(db: sqlite3.Connection) -> None:
    """Arşiv ve koşu günlüğü tablolarını kur (idempotent).

    ``legislation_corpus.ensure_schema`` gibi yalnız CREATE IF NOT EXISTS
    yapar; canlı 72 GB'lık cache üzerinde tam tablo taraması yapmaz.
    """
    db.execute(_GECMIS_TABLE)
    db.execute(_GECMIS_INDEX)
    db.execute(_LOG_TABLE)
    db.execute(_LOG_INDEX)
    db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def arsivle(db: sqlite3.Connection, mevzuat_id: str) -> bool:
    """Bir mevzuatın MEVCUT metnini geçmiş tablosuna kopyala.

    Üzerine yazmadan ÖNCE çağrılır. Kayıt yoksa ya da metni boşsa hiçbir şey
    yazmaz ve False döner (ilk çekimde arşivlenecek eski metin yoktur).
    """
    row = db.execute(
        "SELECT metin, metin_hash, guncelleme_tarihi FROM mevzuat_dokuman "
        "WHERE mevzuat_id = ?",
        (mevzuat_id,),
    ).fetchone()
    if not row or not (row[0] or ""):
        return False
    db.execute(
        "INSERT INTO mevzuat_dokuman_gecmis "
        "(mevzuat_id, metin, metin_hash, guncelleme_tarihi, arsivlenme_zamani) "
        "VALUES (?,?,?,?,?)",
        (mevzuat_id, row[0], row[1], row[2], _now()),
    )
    db.commit()
    return True


def kosu_yaz(
    db: sqlite3.Connection,
    *,
    tur: str,
    listelenen: int,
    degisen: int,
    yeni: int,
    hata: int,
    sure_s: float,
    kosu_zamani: str | None = None,
) -> str:
    """Bir türün koşu özetini günlüğe yaz; koşu zaman damgasını döndür."""
    ts = kosu_zamani or _now()
    db.execute(
        "INSERT INTO mevzuat_guncelleme_log "
        "(kosu_zamani, tur, listelenen, degisen, yeni, hata, sure_s) "
        "VALUES (?,?,?,?,?,?,?)",
        (ts, tur, listelenen, degisen, yeni, hata, round(float(sure_s), 2)),
    )
    db.commit()
    return ts


def son_kosular(db: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    """En yeni koşu satırları (tür bazında)."""
    try:
        rows = db.execute(
            "SELECT kosu_zamani, tur, listelenen, degisen, yeni, hata, sure_s "
            "FROM mevzuat_guncelleme_log ORDER BY kosu_zamani DESC, rowid DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "kosu_zamani": r[0], "tur": r[1], "listelenen": r[2],
            "degisen": r[3], "yeni": r[4], "hata": r[5], "sure_s": r[6],
        }
        for r in rows
    ]


def son_basarili_kosu(db: sqlite3.Connection) -> str | None:
    """En son koşunun zaman damgası (eşik tarihi için)."""
    try:
        row = db.execute(
            "SELECT MAX(kosu_zamani) FROM mevzuat_guncelleme_log"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row and row[0] else None


# ── Değişti mi? ─────────────────────────────────────────────────────────────


def db_ozet(db: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Korpustaki her mevzuatın karşılaştırma alanları.

    Tek sorgu, metin OKUNMAZ (metin sütunu 300 KB'a kadar çıkıyor; 13 bin
    satırda bu gereksiz GB'lardır).
    """
    out: dict[str, dict[str, str]] = {}
    for mid, tur, no, rg_t, rg_s, h in db.execute(
        "SELECT mevzuat_id, tur, mevzuat_no, rg_tarihi, rg_sayisi, metin_hash "
        "FROM mevzuat_dokuman"
    ):
        out[mid] = {
            "tur": tur or "", "mevzuat_no": str(no or ""),
            "rg_tarihi": rg_t or "", "rg_sayisi": rg_s or "",
            "metin_hash": h or "",
        }
    return out


def cekilsin_mi(
    mevzuat_id: str,
    *,
    tur: str,
    mevzuat_no: str,
    rg_tarihi: str,
    rg_sayisi: str,
    ozet: dict[str, dict[str, str]],
    taze: set[tuple[str, str]],
) -> tuple[bool, str]:
    """``--only-changed`` kararı: bu kaydın TAM METNİ çekilsin mi?

    Dönüş ``(çekilsin, sebep)``. Sebepler: ``yeni`` (korpusta yok),
    ``kayit_tarihi`` (Bedesten yeniden yüklemiş), ``rg_degisti`` (listelemedeki
    RG tarih/sayısı DB'dekinden farklı), ``degismemis`` (atla).
    """
    mevcut = ozet.get(mevzuat_id)
    if mevcut is None:
        return True, "yeni"
    if (tur or "", str(mevzuat_no or "")) in taze:
        return True, "kayit_tarihi"
    if (rg_tarihi or "") != mevcut["rg_tarihi"] or (rg_sayisi or "") != mevcut["rg_sayisi"]:
        return True, "rg_degisti"
    return False, "degismemis"


# mevzuat.gov.tr tür adı → Bedesten ``mevzuatTurList`` değeri. mevzuat_pull'un
# BEDESTEN_TUR sözlüğüyle aynı; burada tekrarlanıyor çünkü bu modül scripts/
# altına bağımlı olamaz (MCP sunucusu da import ediyor).
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


async def taze_kayitlar(
    bd_client: Any,
    turler: list[str],
    esik_iso: str,
    *,
    sayfa: int = 20,
    en_fazla_sayfa: int = 25,
) -> tuple[set[tuple[str, str]], list[dict[str, Any]]]:
    """Bedesten'de ``kayitTarihi >= esik`` olan mevzuatı topla.

    Tür başına KAYIT_TARIHI azalan listeler, eşiğin altına inen ilk satırda
    durur — yani hafta içinde 3 kanun değiştiyse tek istek yeter.

    ÖLÇÜM: Bedesten ``pageSize`` en fazla 20 ("Kayıt sayısı 20'den fazla
    olamaz"); daha büyüğü ADALET_EMPTY_EXCEPTION ile döner.

    Dönüş: ``({(tur, mevzuat_no), …}, [detay satırları])``.
    """
    taze: set[tuple[str, str]] = set()
    detay: list[dict[str, Any]] = []
    for tur in turler:
        bd_tur = BEDESTEN_TUR.get(tur)
        if not bd_tur:
            continue
        for sayfa_no in range(1, en_fazla_sayfa + 1):
            hits = await bd_client.search(
                "", limit=sayfa, page=sayfa_no, sort_by="kayit_tarihi",
                sort_direction="desc", mevzuat_tur_list=[bd_tur],
            )
            if not hits:
                break
            bitti = False
            for h in hits:
                meta = h.metadata or {}
                kt = str(meta.get("kayitTarihi") or "")
                if kt and kt < esik_iso:
                    bitti = True
                    break
                no = str(meta.get("mevzuatNo") or h.karar_no or "")
                if not no:
                    continue
                taze.add((tur, no))
                detay.append({
                    "tur": tur, "mevzuat_no": no,
                    "ad": h.title, "kayit_tarihi": kt,
                })
            if bitti or len(hits) < sayfa:
                break
    return taze, detay


# ── Resmî Gazete deltası ────────────────────────────────────────────────────

_TR_MAP = str.maketrans({
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "I": "i", "İ": "i",
    "î": "i", "Î": "i", "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u",
    "Ü": "u", "û": "u", "Û": "u", "â": "a", "Â": "a", "’": "'", "‘": "'",
})


def normalize_ad(text: str) -> str:
    """Mevzuat adını karşılaştırılabilir biçime indirge.

    Türkçe büyük/küçük harf tuzağından (I/İ) kaçınmak için önce harfler ASCII
    karşılıklarına çevrilir, sonra küçültülür; noktalama atılır, boşluk tekilleşir.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", str(text)).translate(_TR_MAP).lower()
    t = re.sub(r"[^0-9a-z]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# "… Değişiklik Yapılmasına Dair …" kalıbının başladığı yer. "Yapılması
# Hakkında" ve "Yapılmasına İlişkin" varyantları da aynı işi görüyor.
# Not: kalıbın başında SADECE boşluk aranıyor. "\w{0,4}" gibi bir esneklik
# eklemek "Kanununda"nın son ekini yutar ve önek "…Kanun" olarak kesilir.
_DEGISIKLIK_RE = re.compile(r"\s+De[ğg]i[şs]iklik\s+Yap[ıi]lmas[ıi]")

# Yürürlükten kaldırma / iptal kalıbı: "… Yönetmeliğinin Yürürlükten
# Kaldırılmasına Dair Yönetmelik".
_KALDIRMA_RE = re.compile(r"\s+Y[üu]r[üu]rl[üu]kten\s+Kald[ıi]r[ıi]lmas[ıi]")

# "5271 Sayılı Ceza Muhakemesi Kanunu…" → hedef numarası.
_SAYILI_RE = re.compile(r"\b(\d{3,6})\s+[Ss]ay[ıi]l[ıi]\b")

# Hedef adının sonundaki bulunma hâli ekini yalın hâle çevir. Sıra önemli:
# uzun ek önce denenir. Değer None ise hedef çoğuldur ("Bazı Kanunlarda"),
# tek bir mevzuata bağlanamaz.
_EK_TABLOSU: list[tuple[str, str | None]] = [
    ("Kanun Hükmünde Kararnamesinde", "Kanun Hükmünde Kararnamesi"),
    ("Kanun Hükmünde Kararnamelerde", None),
    ("Kanun Hükmünde Kararnamede", "Kanun Hükmünde Kararname"),
    ("Kararnamesinde", "Kararnamesi"),
    ("Kararnamelerinde", None),
    ("Kararnamede", "Kararname"),
    ("Kanununda", "Kanunu"),
    ("Kanunlarda", None),
    ("Kanunda", "Kanun"),
    ("Yönetmeliğinde", "Yönetmeliği"),
    ("Yönetmeliklerinde", None),
    ("Yönetmeliklerde", None),
    ("Tebliğinde", "Tebliği"),
    ("Tebliğlerinde", None),
    ("Tebliğde", "Tebliğ"),
    ("Tüzüğünde", "Tüzüğü"),
    ("Kararında", "Kararı"),
    ("Kararlarında", None),
    ("Kararda", "Karar"),
    ("Esaslarında", "Esasları"),
    ("Yönergesinde", "Yönergesi"),
    ("Genelgesinde", "Genelgesi"),
    ("Tarifesinde", "Tarifesi"),
    ("Talimatında", "Talimatı"),
    ("Statüsünde", "Statüsü"),
    ("Protokolünde", "Protokolü"),
    ("Listesinde", "Listesi"),
    ("Planında", "Planı"),
    ("Programında", "Programı"),
    ("Şartlarında", "Şartları"),
    ("Esaslarda", "Esaslar"),
    ("Şartlarda", "Şartlar"),
    ("Cetvelinde", "Cetveli"),
    ("Sözleşmesinde", "Sözleşmesi"),
    # Yalın adın bulunma hâli ("… Hakkında Yönetmelikte Değişiklik")
    ("Yönetmelikte", "Yönetmelik"),
    ("Tüzükte", "Tüzük"),
    ("Yönergede", "Yönerge"),
    # İyelik hâli ("… Yönetmeliğinin Yürürlükten Kaldırılması"). Uzun biçim
    # ("Kanununun" = Kanunu+nun) kısa biçimden ("Kanunun" = Kanun+un) önce
    # denenmeli.
    ("Kanununun", "Kanunu"),
    ("Kanunun", "Kanun"),
    ("Yönetmeliğinin", "Yönetmeliği"),
    ("Yönetmeliğin", "Yönetmelik"),
    ("Tebliğinin", "Tebliği"),
    ("Tebliğin", "Tebliğ"),
    ("Kararnamesinin", "Kararnamesi"),
    ("Kararının", "Kararı"),
    ("Tüzüğünün", "Tüzüğü"),
    ("Esaslarının", "Esasları"),
]


def hedef_mevzuat(baslik: str) -> dict[str, Any]:
    """RG kaleminin başlığından hedef mevzuatı çıkar.

    Örnek: ``"Ceza Muhakemesi Kanununda Değişiklik Yapılmasına Dair Kanun"``
    → ``{"hedef_ad": "Ceza Muhakemesi Kanunu", "hedef_no": None,
    "degisiklik": True, "tip": "degisiklik"}``.

    ``hedef_ad`` None ise başlık ya yeni bir mevzuat ("… Hakkında Kanun") ya da
    çoğul bir değişikliktir ("Bazı Kanunlarda Değişiklik…"); ikisinde de tek bir
    korpus kaydına bağlanamaz.
    """
    ham = re.sub(r"\s+", " ", (baslik or "").replace("\xa0", " ")).strip()
    # Sondaki "(Karar Sayısı: 11732)" / "(Sıra No: 595)" kuyruğu hedefe ait
    # değil, değiştiren belgeye ait.
    govde = re.sub(r"\s*\((?:Karar Say[ıi]s[ıi]|S[ıi]ra No|No)\s*:[^)]*\)\s*$", "", ham)

    no_match = _SAYILI_RE.search(govde)
    hedef_no = no_match.group(1) if no_match else None

    tip = ""
    m = _DEGISIKLIK_RE.search(govde)
    if m:
        tip = "degisiklik"
    else:
        m = _KALDIRMA_RE.search(govde)
        if m:
            tip = "kaldirma"
    if not m:
        return {"hedef_ad": None, "hedef_no": hedef_no, "degisiklik": False, "tip": "yeni"}

    onek = govde[: m.start()].strip()
    # "X Kanunu ile/ve Bazı Kanunlarda Değişiklik…" → hedef X'tir; "Bazı"dan
    # sonrası zaten çoğul.
    ayir = re.search(r"\s+(?:ile|ve)\s+Baz[ıi]\s+", onek)
    if ayir:
        onek = onek[: ayir.start()].strip()
        return {"hedef_ad": _temizle_onek(onek), "hedef_no": hedef_no,
                "degisiklik": True, "tip": tip}

    hedef = _yalinlastir(onek)
    return {"hedef_ad": hedef, "hedef_no": hedef_no, "degisiklik": True, "tip": tip}


def _temizle_onek(onek: str) -> str | None:
    onek = re.sub(r"^\d{3,6}\s+[Ss]ay[ıi]l[ıi]\s+", "", onek).strip()
    return onek or None


def _yalinlastir(onek: str) -> str | None:
    """Önekin sonundaki bulunma/iyelik ekini yalın hâle çevir."""
    onek = onek.strip()
    if not onek:
        return None
    for ek, yalin in _EK_TABLOSU:
        if onek.endswith(ek):
            if yalin is None:
                return None
            govde = onek[: -len(ek)].rstrip()
            aday = f"{govde} {yalin}".strip()
            return _temizle_onek(aday)
    # "(Sıra No: 538)’nde" gibi apostroflu ek: parantez kuyruğu hedefe ait.
    kirpik = re.sub(r"(?:’|')\s*\w{1,4}$", "", onek).strip()
    if kirpik and kirpik != onek:
        return _temizle_onek(kirpik)
    return None


_RG_KATEGORI_ANAHTAR = (
    "KANUN", "YÖNETMELİK", "TEBLİĞ", "KARARNAME", "CUMHURBAŞKANI KARAR", "TÜZÜK",
)


def mevzuat_kalemi_mi(kategori: str | None, bolum: str | None) -> bool:
    """RG fihrist kalemi mevzuat mı (ilan/yargı kararı/atama değil)?"""
    metin = f"{kategori or ''} {bolum or ''}".upper()
    return any(a in metin for a in _RG_KATEGORI_ANAHTAR)


def _ad_indeksi(db: sqlite3.Connection) -> dict[str, tuple[str, str, str]]:
    """normalize edilmiş ad → (mevzuat_id, ad, tur)."""
    idx: dict[str, tuple[str, str, str]] = {}
    for mid, ad, tur in db.execute("SELECT mevzuat_id, ad, tur FROM mevzuat_dokuman"):
        n = normalize_ad(ad or "")
        if n and n not in idx:
            idx[n] = (mid, ad or "", tur or "")
    return idx


def _no_indeksi(db: sqlite3.Connection) -> dict[str, tuple[str, str, str]]:
    idx: dict[str, tuple[str, str, str]] = {}
    for mid, ad, tur, no in db.execute(
        "SELECT mevzuat_id, ad, tur, mevzuat_no FROM mevzuat_dokuman"
    ):
        key = str(no or "")
        if key and key not in idx:
            idx[key] = (mid, ad or "", tur or "")
    return idx


def eslestir(
    hedef_ad: str | None,
    hedef_no: str | None,
    ad_idx: dict[str, tuple[str, str, str]],
    no_idx: dict[str, tuple[str, str, str]],
) -> dict[str, Any] | None:
    """Hedef adı/numarasını korpustaki bir kayda bağla.

    Sıra: tam normalize ad → adın sonek/önek kapsaması → mevzuat numarası.
    Numara eşleşmesi en zayıfı (aynı numara farklı türlerde tekrar ediyor), o
    yüzden en sona bırakıldı ve ``yontem`` alanında raporlanıyor.
    """
    n = normalize_ad(hedef_ad or "")
    if n:
        hit = ad_idx.get(n)
        if hit:
            return {"mevzuat_id": hit[0], "ad": hit[1], "tur": hit[2], "yontem": "ad"}
        # Korpustaki ad daha uzun olabilir ("… HAKKINDA KANUN" vs "… Kanunu").
        if len(n) >= 15:
            for key, hit in ad_idx.items():
                if key.startswith(n) or n.startswith(key):
                    return {"mevzuat_id": hit[0], "ad": hit[1], "tur": hit[2],
                            "yontem": "ad_kapsama"}
    if hedef_no:
        hit = no_idx.get(str(hedef_no))
        if hit:
            return {"mevzuat_id": hit[0], "ad": hit[1], "tur": hit[2], "yontem": "no"}
    return None


async def rg_degisiklikleri(
    db: sqlite3.Connection,
    gun_sayisi: int = 7,
    *,
    rg_client: Any = None,
    bitis: date | None = None,
) -> dict[str, Any]:
    """Son N günün Resmî Gazete fihristinden mevzuat deltasını çıkar.

    Fihristte tarih aralığı yok; gün gün dolaşılır (ölçüm: ~2,4 s/gün, tatil
    günleri 404 ile hızlı döner). Her mevzuat kalemi için başlıktan hedef
    çıkarılır ve korpusla eşleştirilir; eşleşenler "yeniden çek" listesidir.
    """
    if rg_client is None:
        from .sources.resmigazete import ResmiGazeteClient

        rg_client = ResmiGazeteClient()
    son = bitis or date.today()
    ad_idx = _ad_indeksi(db)
    no_idx = _no_indeksi(db)

    kalemler: list[dict[str, Any]] = []
    gunler: list[dict[str, Any]] = []
    for i in range(max(1, int(gun_sayisi))):
        g = son - timedelta(days=i)
        try:
            sp = await rg_client.search_page("", limit=500, date=g.isoformat())
        except Exception as exc:  # ağ hatası bir günü düşürsün, koşuyu değil
            gunler.append({"tarih": g.isoformat(), "hata": f"{type(exc).__name__}: {exc}"})
            continue
        mevzuat_sayisi = 0
        for r in sp.results:
            meta = r.metadata or {}
            if not mevzuat_kalemi_mi(meta.get("kategori"), meta.get("bolum")):
                continue
            mevzuat_sayisi += 1
            hedef = hedef_mevzuat(r.title)
            es = eslestir(hedef["hedef_ad"], hedef["hedef_no"], ad_idx, no_idx) \
                if hedef["degisiklik"] else None
            kalemler.append({
                "rg_tarihi": g.isoformat(),
                "kategori": meta.get("kategori"),
                "baslik": r.title,
                "kaynak_url": r.source_url,
                "tip": hedef["tip"],
                "hedef_ad": hedef["hedef_ad"],
                "hedef_no": hedef["hedef_no"],
                "eslesme": es,
            })
        gunler.append({"tarih": g.isoformat(), "kalem": len(sp.results),
                       "mevzuat_kalemi": mevzuat_sayisi})

    degisiklik = [k for k in kalemler if k["tip"] in ("degisiklik", "kaldirma")]
    eslesen = [k for k in degisiklik if k["eslesme"]]
    yeniden_cek = sorted({k["eslesme"]["mevzuat_id"] for k in eslesen})
    return {
        "ok": True,
        "gun_sayisi": int(gun_sayisi),
        "bitis": son.isoformat(),
        "gunler": gunler,
        "mevzuat_kalemi": len(kalemler),
        "degisiklik_kalemi": len(degisiklik),
        "eslesen": len(eslesen),
        "eslesme_orani": round(len(eslesen) / len(degisiklik), 3) if degisiklik else 0.0,
        "yeniden_cek": yeniden_cek,
        "kalemler": kalemler,
    }


async def degisiklik_raporu(
    db: sqlite3.Connection,
    gun_sayisi: int = 7,
    *,
    rg_client: Any = None,
) -> dict[str, Any]:
    """MCP aracının gövdesi: RG deltası + son güncelleme koşusu özeti."""
    rapor = await rg_degisiklikleri(db, gun_sayisi, rg_client=rg_client)
    kosular = son_kosular(db, limit=20)
    rapor["son_kosular"] = kosular
    rapor["son_kosu_zamani"] = kosular[0]["kosu_zamani"] if kosular else None
    if not kosular:
        rapor["uyari"] = (
            "Henüz haftalık güncelleme koşusu kaydı yok; RG kalemleri korpusa "
            "işlenmemiş olabilir (EmsalMevzuatWeekly görevi çalışmamış)."
        )
    return rapor
