"""Faz 2b — haftalık güncelleme: başlık ayrıştırma, only-changed, arşiv.

Ağa çıkmaz. RG deltası sahte bir istemciyle sürülür; canlı ölçüm ayrı
(``tests/test_mevzuat_live_smoke.py`` tarzı) işlerin konusudur.
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from emsal_mcp import legislation_corpus as lc
from emsal_mcp import legislation_update as lu
from emsal_mcp.models import ContentStatus, SearchPage, SearchResult


@pytest.fixture()
def db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    lc.ensure_schema(con)
    lu.ensure_update_schema(con)
    yield con
    con.close()


def _ekle(db, mevzuat_id, ad, tur="KANUN", no="", rg_t="", rg_s="", metin="Madde 1 – Test."):
    lc.upsert_document(
        db, mevzuat_id=mevzuat_id, metin=metin, kaynak="mevzuatgov", tur=tur,
        mevzuat_no=no, ad=ad, rg_tarihi=rg_t, rg_sayisi=rg_s,
    )


# ── Başlıktan hedef mevzuat çıkarma ─────────────────────────────────────────

@pytest.mark.parametrize(
    "baslik,beklenen_ad,beklenen_tip",
    [
        ("Ceza Muhakemesi Kanununda Değişiklik Yapılmasına Dair Kanun",
         "Ceza Muhakemesi Kanunu", "degisiklik"),
        ("Türk Ceza Kanunu ile Bazı Kanunlarda Değişiklik Yapılmasına Dair Kanun",
         "Türk Ceza Kanunu", "degisiklik"),
        ("Sosyal Güvenlik Kurumu Sağlık Uygulama Tebliğinde Değişiklik Yapılmasına Dair Tebliğ",
         "Sosyal Güvenlik Kurumu Sağlık Uygulama Tebliği", "degisiklik"),
        ("Millî Eğitim Bakanlığı Okul Öncesi Eğitim ve İlköğretim Kurumları "
         "Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik",
         "Millî Eğitim Bakanlığı Okul Öncesi Eğitim ve İlköğretim Kurumları Yönetmeliği",
         "degisiklik"),
        ("İthalat Rejimi Kararında Değişiklik Yapılmasına İlişkin Karar (Karar Sayısı: 11644)",
         "İthalat Rejimi Kararı", "degisiklik"),
        ("Ödeme Hizmetleri ve Elektronik Para İhracı Hakkında Yönetmelikte "
         "Değişiklik Yapılmasına Dair Yönetmelik",
         "Ödeme Hizmetleri ve Elektronik Para İhracı Hakkında Yönetmelik", "degisiklik"),
        ("Vergi Usul Kanunu Genel Tebliği (Sıra No: 538)’nde Değişiklik "
         "Yapılmasına Dair Tebliğ (Sıra No: 595)",
         "Vergi Usul Kanunu Genel Tebliği (Sıra No: 538)", "degisiklik"),
        ("Yatırım Projelerinin Stratejik Öncelik ve Teknik Değerlendirmesine Dair "
         "Tebliğde Değişiklik Yapılması Hakkında Tebliğ",
         "Yatırım Projelerinin Stratejik Öncelik ve Teknik Değerlendirmesine Dair Tebliğ",
         "degisiklik"),
        ("Doktora Öğrencilerine Burs Verilmesine İlişkin Yönetmeliğin "
         "Yürürlükten Kaldırılmasına Dair Yönetmelik",
         "Doktora Öğrencilerine Burs Verilmesine İlişkin Yönetmelik", "kaldirma"),
        ("Danıştay Kanununda Değişiklik Yapılmasına Dair Kanun",
         "Danıştay Kanunu", "degisiklik"),
        # "ve Bazı" da "ile Bazı" gibi: hedef, ilk adı geçen mevzuattır.
        ("Yükseköğretim Kanunu ve Bazı Kanunlarda Değişiklik Yapılmasına Dair Kanun",
         "Yükseköğretim Kanunu", "degisiklik"),
        ("Zorunlu Deprem Sigortası Genel Şartlarında Değişiklik Yapılmasına Dair "
         "Genel Şartlar",
         "Zorunlu Deprem Sigortası Genel Şartları", "degisiklik"),
        ("İstatistik Pozisyonlarına Bölünmüş Türk Gümrük Tarife Cetvelinde "
         "Değişiklik Yapılmasına İlişkin Karar (Karar Sayısı: 11234)",
         "İstatistik Pozisyonlarına Bölünmüş Türk Gümrük Tarife Cetveli",
         "degisiklik"),
        ("Sözleşmeli Personel Çalıştırılmasına İlişkin Esaslarda Değişiklik "
         "Yapılmasına Dair Esaslar (Karar Sayısı: 11560)",
         "Sözleşmeli Personel Çalıştırılmasına İlişkin Esaslar", "degisiklik"),
        # Çoğul hedef: tek bir mevzuata bağlanamaz.
        ("Bazı Kanunlarda Değişiklik Yapılmasına Dair Kanun", None, "degisiklik"),
        # Değişiklik değil, yeni mevzuat.
        ("Beşeri Tıbbi Ürünlerin Fiyatlandırılması Hakkında Tebliğ", None, "yeni"),
        ("Konkordato Gider Avansı Tarifesi", None, "yeni"),
    ],
)
def test_hedef_mevzuat(baslik, beklenen_ad, beklenen_tip):
    h = lu.hedef_mevzuat(baslik)
    assert h["tip"] == beklenen_tip
    assert h["hedef_ad"] == beklenen_ad


def test_hedef_mevzuat_sayili_numarayi_yakalar():
    h = lu.hedef_mevzuat(
        "375 Sayılı Kanun Hükmünde Kararnamede Değişiklik Yapılmasına Dair Kanun"
    )
    assert h["hedef_no"] == "375"
    assert h["degisiklik"] is True


def test_normalize_ad_turkce_buyuk_kucuk_tuzagi():
    # DB'deki ad BÜYÜK harfli, RG başlığı başlık düzeninde: I/İ tuzağına
    # düşmeden aynı anahtara inmeliler.
    assert lu.normalize_ad("İŞ KANUNU") == lu.normalize_ad("İş Kanunu")
    assert lu.normalize_ad("TÜRK BORÇLAR KANUNU") == lu.normalize_ad("Türk Borçlar Kanunu")
    assert lu.normalize_ad("Vergi Usul Kanunu Genel Tebliği (Sıra No: 538)") == \
        "vergi usul kanunu genel tebligi sira no 538"


# ── Eşleştirme ──────────────────────────────────────────────────────────────

def test_eslestir_ad_ve_no(db):
    _ekle(db, "1.5.4857", "İŞ KANUNU", no="4857")
    _ekle(db, "1.4.213", "VERGİ USUL KANUNU", no="213")
    ad_idx = lu._ad_indeksi(db)
    no_idx = lu._no_indeksi(db)

    hit = lu.eslestir("İş Kanunu", None, ad_idx, no_idx)
    assert hit and hit["mevzuat_id"] == "1.5.4857" and hit["yontem"] == "ad"

    # Ad tutmuyor ama numara tutuyor.
    hit = lu.eslestir("Bilinmeyen Bir Kanun", "213", ad_idx, no_idx)
    assert hit and hit["mevzuat_id"] == "1.4.213" and hit["yontem"] == "no"

    assert lu.eslestir("Hiç Olmayan Yönetmelik", None, ad_idx, no_idx) is None
    assert lu.eslestir(None, None, ad_idx, no_idx) is None


def test_eslestir_kapsama(db):
    _ekle(db, "1.4.213", "VERGİ USUL KANUNU", no="213")
    ad_idx = lu._ad_indeksi(db)
    no_idx = lu._no_indeksi(db)
    hit = lu.eslestir("Vergi Usul Kanunu Genel Tebliği (Sıra No: 538)", None, ad_idx, no_idx)
    assert hit and hit["yontem"] == "ad_kapsama"


def test_mevzuat_kalemi_mi():
    assert lu.mevzuat_kalemi_mi("YÖNETMELİKLER", "YÜRÜTME VE İDARE BÖLÜMÜ")
    assert lu.mevzuat_kalemi_mi("KANUN", None)
    assert lu.mevzuat_kalemi_mi("TEBLİĞLER", None)
    assert not lu.mevzuat_kalemi_mi("YARGITAY KARARI", "İLÂN BÖLÜMÜ")
    assert not lu.mevzuat_kalemi_mi("ATAMA KARARLARI", None)


# ── only-changed karar mantığı ──────────────────────────────────────────────

def test_cekilsin_mi(db):
    _ekle(db, "1.5.4857", "İŞ KANUNU", no="4857", rg_t="10.06.2003", rg_s="25134")
    ozet = lu.db_ozet(db)

    # Korpusta yok → yeni.
    cek, sebep = lu.cekilsin_mi(
        "1.5.9999", tur="KANUN", mevzuat_no="9999", rg_tarihi="", rg_sayisi="",
        ozet=ozet, taze=set())
    assert cek and sebep == "yeni"

    # Aynı RG, taze listesinde yok → atla (metin İNDİRİLMEZ).
    cek, sebep = lu.cekilsin_mi(
        "1.5.4857", tur="KANUN", mevzuat_no="4857", rg_tarihi="10.06.2003",
        rg_sayisi="25134", ozet=ozet, taze=set())
    assert not cek and sebep == "degismemis"

    # Bedesten yeniden yüklemiş → çek.
    cek, sebep = lu.cekilsin_mi(
        "1.5.4857", tur="KANUN", mevzuat_no="4857", rg_tarihi="10.06.2003",
        rg_sayisi="25134", ozet=ozet, taze={("KANUN", "4857")})
    assert cek and sebep == "kayit_tarihi"

    # RG sayısı değişmiş → çek.
    cek, sebep = lu.cekilsin_mi(
        "1.5.4857", tur="KANUN", mevzuat_no="4857", rg_tarihi="10.06.2003",
        rg_sayisi="25135", ozet=ozet, taze=set())
    assert cek and sebep == "rg_degisti"


def test_db_ozet_metni_okumaz(db):
    _ekle(db, "1.5.4857", "İŞ KANUNU", no="4857", metin="Madde 1 – Uzun metin.")
    ozet = lu.db_ozet(db)
    assert set(ozet["1.5.4857"]) == {"tur", "mevzuat_no", "rg_tarihi", "rg_sayisi", "metin_hash"}
    assert ozet["1.5.4857"]["metin_hash"]


# ── Arşivleme ───────────────────────────────────────────────────────────────

def test_arsivle_eski_metni_saklar(db):
    _ekle(db, "1.5.4857", "İŞ KANUNU", no="4857", metin="Madde 1 – Eski hâli.")
    assert lu.arsivle(db, "1.5.4857") is True
    # Şimdi üzerine yaz.
    _ekle(db, "1.5.4857", "İŞ KANUNU", no="4857", metin="Madde 1 – Yeni hâli.")

    rows = db.execute(
        "SELECT metin, metin_hash, arsivlenme_zamani FROM mevzuat_dokuman_gecmis "
        "WHERE mevzuat_id = ?", ("1.5.4857",)
    ).fetchall()
    assert len(rows) == 1
    assert "Eski hâli" in rows[0][0]
    assert rows[0][1] and rows[0][2]
    # Canlı satır yeni metni taşıyor.
    guncel = db.execute(
        "SELECT metin FROM mevzuat_dokuman WHERE mevzuat_id = ?", ("1.5.4857",)
    ).fetchone()[0]
    assert "Yeni hâli" in guncel


def test_arsivle_olmayan_kayitta_yazmaz(db):
    assert lu.arsivle(db, "yok.yok.yok") is False
    assert db.execute("SELECT COUNT(*) FROM mevzuat_dokuman_gecmis").fetchone()[0] == 0


def test_ensure_update_schema_idempotent(db):
    lu.ensure_update_schema(db)
    lu.ensure_update_schema(db)
    tablolar = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"mevzuat_dokuman_gecmis", "mevzuat_guncelleme_log"} <= tablolar


# ── Koşu günlüğü ────────────────────────────────────────────────────────────

def test_kosu_gunlugu(db):
    ts = lu.kosu_yaz(db, tur="KANUN", listelenen=916, degisen=2, yeni=1, hata=0,
                     sure_s=61.5)
    lu.kosu_yaz(db, tur="KHK", listelenen=63, degisen=0, yeni=0, hata=0,
                sure_s=3.2, kosu_zamani=ts)
    kosular = lu.son_kosular(db)
    assert len(kosular) == 2
    assert {k["tur"] for k in kosular} == {"KANUN", "KHK"}
    assert lu.son_basarili_kosu(db) == ts


def test_son_kosular_tablo_yokken_bos_doner():
    con = sqlite3.connect(":memory:")
    try:
        assert lu.son_kosular(con) == []
        assert lu.son_basarili_kosu(con) is None
    finally:
        con.close()


# ── RG deltası (sahte istemci) ──────────────────────────────────────────────

class _SahteRG:
    """``ResmiGazeteClient.search_page`` sözleşmesinin küçük bir taklidi."""

    def __init__(self, gunler: dict[str, list[tuple[str, str]]]):
        self.gunler = gunler
        self.istekler: list[str] = []

    async def search_page(self, query="", limit=10, page=1, **filters):
        gun = str(filters.get("date"))
        self.istekler.append(gun)
        kalemler = self.gunler.get(gun, [])
        results = [
            SearchResult(
                source="resmigazete", document_id=f"{gun}-{i}", title=baslik,
                court=kategori, source_url=f"https://ornek/{gun}-{i}.htm",
                content_status=ContentStatus.METADATA_ONLY,
                metadata={"kategori": kategori, "bolum": "YÜRÜTME VE İDARE BÖLÜMÜ"},
            )
            for i, (kategori, baslik) in enumerate(kalemler, 1)
        ]
        return SearchPage(results=results, total=len(results), page=1,
                          page_size=limit, total_pages=1 if results else 0)


def test_rg_degisiklikleri_eslesenleri_yeniden_cek_listesine_koyar(db):
    from datetime import date

    _ekle(db, "1.5.4857", "İŞ KANUNU", no="4857")
    _ekle(db, "1.5.5271", "CEZA MUHAKEMESİ KANUNU", no="5271")
    bitis = date(2026, 9, 5)
    rg = _SahteRG({
        "2026-09-05": [
            ("KANUN", "İş Kanununda Değişiklik Yapılmasına Dair Kanun"),
            ("YARGITAY KARARI", "Yargıtay 5. Hukuk Dairesine Ait Karar"),
        ],
        "2026-09-04": [
            ("KANUN", "Ceza Muhakemesi Kanununda Değişiklik Yapılmasına Dair Kanun"),
            ("TEBLİĞLER", "Konkordato Gider Avansı Tarifesi"),
            ("YÖNETMELİK", "Hiç Bilinmeyen Yönetmelikte Değişiklik Yapılmasına Dair Yönetmelik"),
        ],
    })
    r = asyncio.run(lu.rg_degisiklikleri(db, 2, rg_client=rg, bitis=bitis))

    assert rg.istekler == ["2026-09-05", "2026-09-04"]
    # Yargıtay kararı mevzuat kalemi değil.
    assert r["mevzuat_kalemi"] == 4
    assert r["degisiklik_kalemi"] == 3
    assert r["eslesen"] == 2
    assert r["yeniden_cek"] == ["1.5.4857", "1.5.5271"]
    assert 0 < r["eslesme_orani"] <= 1


def test_degisiklik_raporu_kosu_yoksa_uyarir(db):
    rg = _SahteRG({"2026-09-05": []})
    r = asyncio.run(lu.degisiklik_raporu(db, 1, rg_client=rg))
    assert r["ok"] is True
    assert r["son_kosu_zamani"] is None
    assert "uyari" in r

    lu.kosu_yaz(db, tur="KANUN", listelenen=1, degisen=0, yeni=0, hata=0, sure_s=1.0)
    r2 = asyncio.run(lu.degisiklik_raporu(db, 1, rg_client=rg))
    assert r2["son_kosu_zamani"]
    assert "uyari" not in r2
