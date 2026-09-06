"""Yerel mevzuat korpusu (Faz 1) testleri — şema, madde ayrımı, FTS, get_madde.

Tamamen hermetik: ağ yok, geçici SQLite dosyası kullanılır.
"""
from __future__ import annotations

import sqlite3

import pytest

from emsal_mcp import legislation_corpus as lc

pytestmark = [pytest.mark.unit]


SAMPLE = """DENEME KANUNU

Kanun Numarası : 9999

BİRİNCİ KISIM
Genel Hükümler

BİRİNCİ BÖLÜM
Amaç ve kapsam

Amaç
MADDE 1 - (1) Bu Kanunun amacı deneme yapmaktır.

Kapsam
MADDE 2 - (Değişik: 1/1/2020-7000/3 md.) (1) Bu Kanun herkesi kapsar. [1]

Zamanaşımı
MADDE 3/A - (1) Alacak on yılda zamanaşımına uğrar.

Ek
MADDE 1 - (Ek: 2/2/2021-7100/5 md.) (1) Ek hüküm.

Geçici
MADDE 1 - (1) Yürürlükten önceki işler eski hükme tabidir.
"""


@pytest.fixture()
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "test-korpus.sqlite3")
    lc.ensure_schema(conn)
    yield conn
    conn.close()


# ── Şema ────────────────────────────────────────────────────────────────────

def test_ensure_schema_is_idempotent(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.sqlite3")
    assert lc.ensure_schema(conn) is False  # ilk kurulum
    assert lc.ensure_schema(conn) is True   # ikinci çağrı: zaten vardı
    names = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','trigger')"
        )
    }
    assert {"mevzuat_dokuman", "mevzuat_madde", "mevzuat_madde_fts"} <= names
    assert {"mevzuat_madde_ai", "mevzuat_madde_ad", "mevzuat_madde_au"} <= names
    conn.close()


# ── Madde ayrımı ────────────────────────────────────────────────────────────

def test_split_articles_numbers_and_qualifiers():
    arts = lc.split_articles(SAMPLE)
    assert [a["madde_no"] for a in arts] == ["1", "2", "3/A", "Ek 1", "Geçici 1"]
    assert [a["sira"] for a in arts] == [1, 2, 3, 4, 5]


def test_split_articles_extracts_heading():
    arts = {a["madde_no"]: a for a in lc.split_articles(SAMPLE)}
    assert arts["1"]["baslik"].endswith("Amaç")
    assert "Zamanaşımı" in arts["3/A"]["baslik"]


def test_split_articles_collects_change_notes_raw():
    arts = {a["madde_no"]: a for a in lc.split_articles(SAMPLE)}
    note = arts["2"]["degisiklik_notu"]
    assert "(Değişik: 1/1/2020-7000/3 md.)" in note
    assert "[1]" in note                     # dipnot numarası da toplanır
    assert "(Ek: 2/2/2021-7100/5 md.)" in arts["Ek 1"]["degisiklik_notu"]
    assert arts["1"]["degisiklik_notu"] == ""


# ── Yazma ───────────────────────────────────────────────────────────────────

def _write(db, **kw):
    args = dict(
        mevzuat_id="1.5.9999", metin=SAMPLE, kaynak="mevzuatgov", tur="KANUN",
        mevzuat_no="9999", tertip="5", ad="DENEME KANUNU",
        rg_tarihi="01.01.2020", guncelleme_tarihi="01.01.2020",
        kaynak_url="https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=9999",
    )
    args.update(kw)
    return lc.upsert_document(db, **args)


def test_upsert_inserts_then_skips_unchanged(db):
    first = _write(db)
    assert first == {"status": "inserted", "madde_sayisi": 5}
    again = _write(db)
    assert again["status"] == "skipped"
    assert db.execute("SELECT COUNT(*) FROM mevzuat_madde").fetchone()[0] == 5


def test_upsert_updates_when_text_changes(db):
    _write(db)
    changed = SAMPLE.replace("deneme yapmaktır", "başka bir şey yapmaktır")
    res = _write(db, metin=changed)
    assert res["status"] == "updated"
    # Eski maddeler silinip yenileri yazılır — kopya kalmaz.
    assert db.execute("SELECT COUNT(*) FROM mevzuat_madde").fetchone()[0] == 5
    row = db.execute(
        "SELECT madde_sayisi, metin_hash FROM mevzuat_dokuman WHERE mevzuat_id='1.5.9999'"
    ).fetchone()
    assert row[0] == 5 and row[1] == lc._hash(changed)


# ── Arama ───────────────────────────────────────────────────────────────────

def test_search_madde_finds_article(db):
    _write(db)
    out = lc.search_madde(db, "zamanaşımına uğrar")
    assert out["ok"] is True
    assert out["total_matches"] >= 1
    hit = out["results"][0]
    assert hit["madde_no"] == "3/A"
    assert hit["mevzuat_no"] == "9999"
    assert hit["mevzuat_adi"] == "DENEME KANUNU"
    assert hit["kaynak_url"].startswith("https://www.mevzuat.gov.tr/")
    assert "zaman" in hit["snippet"].lower()


def test_search_madde_words_are_anded(db):
    _write(db)
    # "zamanaşımı" tek başına eşleşir; kelimeler önce AND'lenir.
    out = lc.search_madde(db, "alacak zamanaşımına")
    assert out["total_matches"] == 1
    assert " AND " in out["fts_query"]
    assert "lexical_fallback" not in out


def test_search_madde_or_fallback(db):
    """AND boş dönerse aynı kelimelerle OR'a düşülür (Faz 2d)."""
    _write(db)
    out = lc.search_madde(db, "alacak kadastro")
    assert out["ok"] is True
    assert out["lexical_fallback"] == "or"
    assert out["fts_query"] == '"alacak" OR "kadastro"'
    assert out["total_matches"] == 1          # "alacak" geçen madde
    assert out["results"][0]["madde_no"] == "3/A"
    # Tek kelimede düşüş YOK (AND/OR farkı yok, işaret kirletmesin).
    assert "lexical_fallback" not in lc.search_madde(db, "kadastro")


def test_search_madde_or_fallback_kelimeleri_hic_yoksa_bos(db):
    _write(db)
    out = lc.search_madde(db, "kadastro tapu")
    assert out["ok"] is True and out["total_matches"] == 0


def test_search_madde_filters_by_mevzuat_no(db):
    _write(db)
    _write(db, mevzuat_id="1.5.8888", mevzuat_no="8888", ad="İKİNCİ DENEME KANUNU")
    assert lc.search_madde(db, "zamanaşımına")["total_matches"] == 2
    tek = lc.search_madde(db, "zamanaşımına", mevzuat_no="8888")
    assert tek["total_matches"] == 1
    assert tek["results"][0]["mevzuat_no"] == "8888"


def test_search_madde_rejects_empty_query(db):
    out = lc.search_madde(db, "   ...  ")
    assert out["ok"] is False and out["errorCode"] == "INVALID_INPUT"


def test_search_madde_survives_fts_metacharacters(db):
    """Kullanıcı sorgusu FTS5 sözdizimine sızmamalı (aksi hâlde OperationalError)."""
    _write(db)
    out = lc.search_madde(db, 'zamanaşımı AND "kapsam* (')
    assert out["ok"] is True


def test_deleting_document_rows_keeps_fts_in_sync(db):
    _write(db)
    db.execute("DELETE FROM mevzuat_madde WHERE mevzuat_id='1.5.9999'")
    db.commit()
    assert lc.search_madde(db, "zamanaşımına")["total_matches"] == 0


# ── Tek madde ───────────────────────────────────────────────────────────────

def test_get_madde_returns_full_text(db):
    _write(db)
    out = lc.get_madde(db, "9999", "3/A")
    assert out["ok"] is True
    assert "on yılda zamanaşımına uğrar" in out["metin"]
    assert out["mevzuat_adi"] == "DENEME KANUNU"
    assert out["kaynak_url"]


def test_get_madde_normalizes_article_number(db):
    _write(db)
    assert lc.get_madde(db, "9999", "3 / a")["ok"] is True
    assert lc.get_madde(db, "9999", "geçici 1")["madde_no"] == "Geçici 1"
    # Nitelikli madde, aynı numaralı asıl maddeyle karışmaz.
    assert lc.get_madde(db, "9999", "1")["metin"].startswith("MADDE 1 -")


def test_get_madde_missing_law_and_missing_article(db):
    _write(db)
    yok = lc.get_madde(db, "1234", "1")
    assert yok["ok"] is False and yok["errorCode"] == "NOT_FOUND"
    yok_madde = lc.get_madde(db, "9999", "99")
    assert yok_madde["ok"] is False and yok_madde["errorCode"] == "NOT_FOUND"
    assert yok_madde["mevcut_madde_sayisi"] == 5


def test_corpus_stats(db):
    _write(db)
    stats = lc.corpus_stats(db)
    assert stats == {"belge_sayisi": 1, "madde_sayisi": 5, "turler": {"KANUN": 1}}


# ── Faz 2a: değişiklik ayrıştırması ─────────────────────────────────────────

def _tek(chunk: str) -> dict:
    kayitlar = lc.parse_paren(chunk)
    assert len(kayitlar) == 1, kayitlar
    return kayitlar[0]


def test_parse_paren_basit_degisik():
    k = _tek("(Değişik: 23/1/2008-5728/47 md.)")
    assert (k["tur"], k["kapsam"]) == ("degisik", "madde")
    assert (k["tarih"], k["degistiren_no"], k["degistiren_madde"]) == (
        "2008-01-23", "5728", "47")


def test_parse_paren_mulga_bosluklu_tire():
    k = _tek("(Mülga: 1/4/1965 - 557/8 md.)")
    assert k["tur"] == "mulga" and k["tarih"] == "1965-04-01"
    assert k["degistiren_no"] == "557"


def test_parse_paren_uzun_tire_ve_ek_fikra():
    k = _tek("(Ek fıkra: 2/3/2005 – 5311/5 md.)")
    assert (k["tur"], k["kapsam"]) == ("ek", "fıkra")
    assert k["degistiren_no"] == "5311"


def test_parse_paren_sirali_fikra_kapsami():
    k = _tek("(Değişik birinci fıkra: 17/7/2003-4949/16 md.)")
    assert (k["tur"], k["kapsam"]) == ("degisik", "fıkra")
    assert k["degistiren_madde"] == "16"
    # Sıra bilgisi ("birinci") ham alanda korunur.
    assert "birinci fıkra" in k["ham"]


@pytest.mark.parametrize("chunk,no", [
    ("(Değişik:11/10/2011-KHK-663/58 md.)", "KHK-663"),
    ("(Mülga: 2/7/2018 - KHK/703/119 md.)", "KHK-703"),
    ("(Değişik:9/8/1993 – KHK – 499/17 md.)", "KHK-499"),
    ("(Değişik birinci fıkra: 23/12/1988 – KHK 351/7 md.)", "KHK-351"),
])
def test_parse_paren_khk_bicimleri(chunk, no):
    assert _tek(chunk)["degistiren_no"] == no


@pytest.mark.parametrize("chunk,no,md", [
    ("(Ek: 24/1/2013-6411/ 1 md.)", "6411", "1"),          # boşluklu madde no
    ("(Mülga: 22/5/2003/4857/120 md.)", "4857", "120"),      # tarih-ayraç "/"
    ("(Değişik: 20/3/1981–2430/7 md.)", "2430", "7"),        # ayraçsız uzun tire
    ("(Mülga: 15/5/1974- 1803/8 md.)", "1803", "8"),
])
def test_parse_paren_ayrac_varyantlari(chunk, no, md):
    k = _tek(chunk)
    assert (k["degistiren_no"], k["degistiren_madde"]) == (no, md)


def test_parse_paren_iki_nokta_olmadan():
    k = _tek("(Değişik 6/6/1985-3222/17 md.)")
    assert k["tur"] == "degisik" and k["degistiren_no"] == "3222"


def test_parse_paren_coklu_degisiklik():
    ks = lc.parse_paren(
        "(Ek: 17/7/2003-4949/50 md.; Mülga: 28/2/2018-7101/65 md.)")
    assert [k["tur"] for k in ks] == ["ek", "mulga"]
    assert [k["tarih"] for k in ks] == ["2003-07-17", "2018-02-28"]
    assert [k["degistiren_no"] for k in ks] == ["4949", "7101"]


def test_parse_paren_khk_aynen_kabul():
    ks = lc.parse_paren(
        "(Mülga: 24/6/1995-KHK-560/21 md.; Aynen kabul: 27/5/2004-5179/37 md.)")
    assert [k["tur"] for k in ks] == ["mulga", "aynen_kabul"]
    assert ks[0]["degistiren_no"] == "KHK-560"
    assert ks[1]["degistiren_no"] == "5179"


def test_parse_paren_degistirilerek_kabul():
    ks = lc.parse_paren(
        "(Ek: 2/1/2017-KHK-681/30 md.; Değiştirilerek kabul: 1/2/2018-7073/30 md.)")
    assert [k["tur"] for k in ks] == ["ek", "degistirilerek_kabul"]


def test_parse_paren_yeniden_duzenleme():
    k = _tek("(Yeniden Düzenleme:19/2/2025-7542/1 md.)")
    assert k["tur"] == "yeniden_duzenleme" and k["tarih"] == "2025-02-19"


def test_parse_paren_cumle_kapsami():
    k = _tek("(Ek cümle: 17/7/2003-4949/33 md.)")
    assert k["kapsam"] == "cümle" and k["tur"] == "ek"


def test_parse_paren_aym_iptali():
    k = _tek(
        "(İptal fıkra:Anayasa Mahkemesinin 14/3/2024 tarihli ve "
        "E.: 2023/140, K.: 2024/81 sayılı Kararı ile)")
    assert (k["tur"], k["kapsam"]) == ("iptal", "fıkra")
    assert (k["aym_esas"], k["aym_karar"]) == ("2023/140", "2024/81")
    assert k["tarih"] == "2024-03-14"
    assert k["degistiren_no"] == ""


def test_parse_paren_aym_kunyesindeki_noktali_virgul_bolmez():
    """AYM künyesi ";" içerir; parantez ondan bölünmemeli."""
    ks = lc.parse_paren(
        "(İptal sekizinci fıkra: Anayasa Mahkemesinin 25/12/2024 tarihli ve "
        "E.:2022/6; K.:2024/225 sayılı Kararı ile)")
    assert len(ks) == 1
    assert (ks[0]["aym_esas"], ks[0]["aym_karar"]) == ("2022/6", "2024/225")


def test_parse_paren_aym_kesme_isaretli():
    k = _tek(
        "(İptal birinci fıkra: Anayasa Mahkemesi’nin 28/2/2008 tarihli ve "
        "E.: 2006/71, K.: 2008/69 sayılı Kararı ile.)")
    assert k["aym_esas"] == "2006/71" and k["tarih"] == "2008-02-28"


@pytest.mark.parametrize("chunk", [
    "(ek gösterge dahil)",
    "(Ekim ayı dahil)",
    "(Ek Madde 1, Ek Madde 2, Ek Madde 3)",
    "(1) Bu Kanunun amacı budur.",
])
def test_parse_paren_degisiklik_olmayan_parantezleri_eler(chunk):
    assert lc.parse_paren(chunk) == []


# ── Faz 2a: dipnot gövdeleri ────────────────────────────────────────────────

FOOTNOTE_DOC = (
    "MADDE 1 - Bir hüküm. [1]\n"
    "MADDE 2 - Başka hüküm. [2]\n"
    "[1]\n"
    "2/3/2024 tarihli ve 7499 sayılı Kanunun 37 nci maddesiyle bu fıkrada yer\r\n"
    "alan “on gündür.” ibaresi “iki haftadır.” şeklinde değiştirilmiştir.\n"
    "[2]\n"
    "Bu madde başlığı “Temyiz:“ iken, 2/3/2005 tarihli ve 5311 sayılı Kanunun\r\n"
    "25 inci maddesiyle metne işlendiği şekilde değiştirilmiştir.\n"
)


def test_parse_footnotes_govdeleri_numarayla_esler():
    fn = lc.parse_footnotes(FOOTNOTE_DOC)
    assert set(fn) == {1, 2}
    assert fn[1].startswith("2/3/2024 tarihli ve 7499")
    assert "Temyiz" in fn[2]
    # Yumuşak satır kaydırması boşluğa dönüşür.
    assert "\r" not in fn[1] and "\n" not in fn[1]


def test_parse_dipnot_kanun_kunyesi():
    k = lc.parse_dipnot(1, lc.parse_footnotes(FOOTNOTE_DOC)[1])
    assert (k["tur"], k["kapsam"]) == ("degisik", "fıkra")
    assert (k["tarih"], k["degistiren_no"], k["degistiren_madde"]) == (
        "2024-03-02", "7499", "37")
    assert k["dipnot_no"] == 1


def test_parse_dipnot_madde_basligi_kapsami():
    k = lc.parse_dipnot(2, lc.parse_footnotes(FOOTNOTE_DOC)[2])
    assert k["kapsam"] == "başlık" and k["degistiren_no"] == "5311"


def test_parse_dipnot_tarih_ve_yazimi():
    """Kaynakta "tarihli ve" kadar sık "tarih ve" geçiyor."""
    k = lc.parse_dipnot(3, "22/7/1998 tarih ve 4369 sayılı Kanunun 81 inci "
                           "maddesiyle bu bentte yer alan ibare değiştirilmiştir.")
    assert (k["tarih"], k["degistiren_no"], k["degistiren_madde"]) == (
        "1998-07-22", "4369", "81")
    assert k["kapsam"] == "bent"


def test_parse_dipnot_khk():
    k = lc.parse_dipnot(4, "2/7/2018 tarihli 703 sayılı KHK’nin 68 inci "
                           "maddesiyle, bu fıkrada yer alan “Bakanlar Kurulunca” "
                           "ibaresi “Cumhurbaşkanınca” şeklinde değiştirilmiştir.")
    assert k["degistiren_no"] == "KHK-703" and k["degistiren_madde"] == "68"


def test_parse_dipnot_aym_iptali():
    k = lc.parse_dipnot(5, "Anayasa Mahkemesinin 8/11/2023 tarihli ve "
                           "E.: 2020/75; K.: 2023/188 sayılı Kararı ile bu fıkra "
                           "iptal edilmiştir.")
    assert k["tur"] == "iptal"
    assert (k["aym_esas"], k["aym_karar"]) == ("2020/75", "2023/188")


def test_parse_dipnot_yapilandirilamayan_ham_kalir():
    k = lc.parse_dipnot(6, "Bu hükmün uygulanmasında ek 2 nci maddeye bakınız.")
    assert k["tarih"] == "" and k["degistiren_no"] == ""
    assert k["ham"].startswith("Bu hükmün")


def test_parse_dipnot_bakanlar_kurulu_karari_kanun_sayilmaz():
    """"97/9218 sayılı Bakanlar Kurulu Kararı" kanun numarası değildir."""
    k = lc.parse_dipnot(7, "2/1/1997 tarihli ve 97/9218 sayılı Bakanlar Kurulu "
                           "Kararı ile ölçüler tespit edilmiştir.")
    assert k["degistiren_no"] == ""


def test_parse_degisiklik_parantez_ve_dipnotu_birlestirir():
    dipnotlar = lc.parse_footnotes(FOOTNOTE_DOC)
    kayitlar = lc.parse_degisiklik(
        "(Değişik: 23/1/2008-5728/47 md.) Bir hüküm. [1]", dipnotlar)
    assert len(kayitlar) == 2
    assert kayitlar[0]["degistiren_no"] == "5728" and kayitlar[0]["dipnot_no"] is None
    assert kayitlar[1]["dipnot_no"] == 1


# ── Faz 2a: madde başlığı sezgiseli ─────────────────────────────────────────

# Kaynak biçimi birebir: "\r\n" yumuşak kaydırma, çıplak "\n" blok sınırı.
HIYERARSIK = (
    "F. Konut ve çatılı işyeri kiralarında sözleşmenin sona\r\nermesi\n"
    "I. Bildirim yoluyla\n"
    "1. Genel olarak\n"
    "MADDE 347-\nKonut ve çatılı işyeri kiralarında kiracı, belirli\r\n"
    "süreli sözleşmelerin süresinin bitiminden en az onbeş gün önce\r\n"
    "bildirimde bulunmadıkça, sözleşme uzatılmış sayılır.\n"
)


def test_baslik_hiyerarsik_kenar_basligi():
    art = lc.split_articles(HIYERARSIK)[0]
    assert art["baslik"] == "1. Genel olarak"
    assert art["ust_baslik"] == (
        "F. Konut ve çatılı işyeri kiralarında sözleşmenin sona ermesi"
        " > I. Bildirim yoluyla"
    )


def test_baslik_iki_nokta_ile_biten_eski_usul():
    """İİK 68 tipi: madde başlığı ":" ile biter — Faz 1'de boş kalıyordu."""
    metin = (
        "b) İtirazın kesin\r\nolarak kaldırılması:\n"
        "[28]\n"
        "Madde\r\n68 – Talebine itiraz edilen alacaklı bir belgeye dayanıyorsa\r\n"
        "itirazın kaldırılmasını isteyebilir.\n"
    )
    art = lc.split_articles(metin)[0]
    assert art["madde_no"] == "68"
    assert art["baslik"] == "b) İtirazın kesin olarak kaldırılması:"


def test_baslik_ciplak_satir_sonuyla_bolunmus_basligi_birlestirir():
    """6100 m.170: başlık nadiren çıplak "\\n" ile de bölünüyor."""
    metin = (
        "İsticvap olunacak\nkişilerin belirlenmesi\n"
        "MADDE 170-\n(1) Taraflardan her biri isticvap olunabilir.\n"
    )
    art = lc.split_articles(metin)[0]
    assert art["baslik"] == "İsticvap olunacak kişilerin belirlenmesi"
    assert art["ust_baslik"] == ""


def test_baslik_onceki_maddenin_cumlesini_almaz():
    metin = (
        "MADDE 1 -\nBu Kanunun amacı budur.\n"
        "MADDE 2 -\nİkinci hükmün metni.\n"
    )
    arts = lc.split_articles(metin)
    assert arts[1]["baslik"] == "" and arts[1]["ust_baslik"] == ""


def test_baslik_kapanis_parantezli_cumleyi_baslik_saymaz():
    """492 m.14: "(… karar verilir.)" paragrafı üst başlık sanılıyordu."""
    metin = (
        "(Yukarıdaki işlemlerin harçlarının karşı taraftan tahsiline karar "
        "verilir.)\n"
        "Harçtan muaf olanlar:\n"
        "MADDE 14 -\nAşağıdaki kişiler harçtan muaftır.\n"
    )
    art = lc.split_articles(metin)[0]
    assert art["baslik"] == "Harçtan muaf olanlar:"
    assert art["ust_baslik"] == ""


def test_sonraki_maddenin_basligi_onceki_govdeye_yapismaz():
    arts = lc.split_articles(HIYERARSIK + "Sonraki başlık\nMADDE 348-\nİkinci.\n")
    assert not arts[0]["metin"].rstrip().endswith("Sonraki başlık")
    assert arts[1]["baslik"] == "Sonraki başlık"


# ── Faz 2a: şema ve okuma yüzeyi ────────────────────────────────────────────

def test_ensure_schema_degisiklik_tablosunu_ve_ust_baslik_sutununu_ekler(tmp_path):
    conn = sqlite3.connect(tmp_path / "y.sqlite3")
    lc.ensure_schema(conn)
    lc.ensure_schema(conn)  # idempotent: ikinci ALTER hata vermemeli
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mevzuat_madde)")}
    assert "ust_baslik" in cols
    dcols = [r[1] for r in conn.execute("PRAGMA table_info(mevzuat_degisiklik)")]
    assert dcols == [
        "mevzuat_id", "sira", "kapsam", "tur", "tarih", "degistiren_no",
        "degistiren_madde", "rg_tarihi", "rg_sayisi", "aym_esas", "aym_karar",
        "ham", "dipnot_no",
    ]
    conn.close()


def test_ensure_schema_faz1_tablosuna_sutunu_sonradan_ekler(tmp_path):
    """Faz 1'de yazılmış tablo düşürülmeden yükseltilmeli."""
    conn = sqlite3.connect(tmp_path / "z.sqlite3")
    conn.execute(lc._MADDE_TABLE)
    conn.execute(
        "INSERT INTO mevzuat_madde (mevzuat_id, madde_no, sira, baslik, metin,"
        " degisiklik_notu) VALUES ('x', '1', 1, 'Amaç', 'metin', '')")
    conn.commit()
    lc.ensure_schema(conn)
    row = conn.execute(
        "SELECT baslik, ust_baslik FROM mevzuat_madde WHERE mevzuat_id='x'"
    ).fetchone()
    assert row == ("Amaç", None)
    conn.close()


def test_upsert_degisiklik_satirlarini_yazar(db):
    _write(db)
    rows = db.execute(
        "SELECT sira, tur, tarih, degistiren_no FROM mevzuat_degisiklik"
        " ORDER BY sira").fetchall()
    assert ("degisik", "2020-01-01", "7000") in [(r[1], r[2], r[3]) for r in rows]
    assert ("ek", "2021-02-02", "7100") in [(r[1], r[2], r[3]) for r in rows]
    # Yeniden yazımda kopya birikmemeli.
    _write(db, metin=SAMPLE.replace("deneme yapmaktır", "başka iş yapmaktır"))
    assert db.execute(
        "SELECT COUNT(*) FROM mevzuat_degisiklik").fetchone()[0] == len(rows)


def test_get_madde_degisiklikleri_ve_ust_basligi_dondurur(db):
    _write(db)
    out = lc.get_madde(db, "9999", "2")
    assert out["ok"] is True
    assert "ust_baslik" in out
    degs = out["degisiklikler"]
    assert degs and degs[0]["tur"] == "degisik"
    assert degs[0]["degistiren_no"] == "7000"
    # Boş alanlar çıktıyı şişirmez.
    assert "aym_esas" not in degs[0]


# ── Faz 3: belge boyu başlık hiyerarşisi ────────────────────────────────────
#
# Fikstürler gerçek metinlerden birebir alındı (mevzuat.gov.tr konsolide metin,
# "\r\n" yumuşak kaydırma / çıplak "\n" blok sınırı korunarak).

# 6098 m.350-352: yapısal başlık ve kenar başlığı zincirinin ÜST halkaları
# m.352'nin çok yukarısında; Faz 2a yalnız yerel pencereye baktığı için
# m.352'nin ust_baslik'i boş kalıyordu.
TBK_KIRA = (
    "İKİNCİ KISIM\nÖzel Borç İlişkileri\n"
    "DÖRDÜNCÜ BÖLÜM\nKira Sözleşmesi\n"
    "İKİNCİ AYIRIM\nKonut ve Çatılı İşyeri Kiraları\n"
    "F. Konut ve çatılı işyeri kiralarında sözleşmenin sona\r\nermesi\n"
    "II. Dava yoluyla\n"
    "1. Kiraya verenden kaynaklanan sebeplerle\n"
    "a. Gereksinim, yeniden inşa ve imar\n"
    "MADDE 350-\nKiraya veren, kira sözleşmesini belirli hâllerde sona\r\n"
    "erdirebilir.\n"
    "b. Yeni malikin gereksinimi\n"
    "MADDE 351-\nKiralananı sonradan edinen kişi, sözleşmeyi altı ay sonra\r\n"
    "açacağı bir davayla sona erdirebilir.\n"
    "2. Kiracıdan kaynaklanan sebeplerle\n"
    "MADDE 352-\nKiracı, kiralananı belli bir tarihte boşaltmayı yazılı olarak\r\n"
    "üstlendiği hâlde boşaltmamışsa tahliye edilebilir.\n"
)


def test_hiyerarsi_yapisal_baslik_maddeler_boyunca_tasinir():
    arts = {a["madde_no"]: a for a in lc.split_articles(TBK_KIRA)}
    assert arts["350"]["ust_baslik"] == (
        "İKİNCİ KISIM — Özel Borç İlişkileri"
        " > DÖRDÜNCÜ BÖLÜM — Kira Sözleşmesi"
        " > İKİNCİ AYIRIM — Konut ve Çatılı İşyeri Kiraları"
        " | F. Konut ve çatılı işyeri kiralarında sözleşmenin sona ermesi"
        " > II. Dava yoluyla > 1. Kiraya verenden kaynaklanan sebeplerle"
    )


def test_hiyerarsi_uzaktaki_ust_halkalar_kaybolmaz():
    """TBK 352: üstünde tek blok var, zincirin gerisi iki madde yukarıda."""
    art = {a["madde_no"]: a for a in lc.split_articles(TBK_KIRA)}["352"]
    assert art["baslik"] == "2. Kiracıdan kaynaklanan sebeplerle"
    assert art["ust_baslik"] == (
        "İKİNCİ KISIM — Özel Borç İlişkileri"
        " > DÖRDÜNCÜ BÖLÜM — Kira Sözleşmesi"
        " > İKİNCİ AYIRIM — Konut ve Çatılı İşyeri Kiraları"
        " | F. Konut ve çatılı işyeri kiralarında sözleşmenin sona ermesi"
        " > II. Dava yoluyla"
    )


def test_hiyerarsi_ayni_seviyedeki_kardes_baslik_oncekini_dusurur():
    """"2. Kiracıdan…" aynı seviyedeki "1. Kiraya verenden…"i değiştirir."""
    arts = {a["madde_no"]: a for a in lc.split_articles(TBK_KIRA)}
    assert "1. Kiraya verenden" not in arts["352"]["ust_baslik"]
    assert "a. Gereksinim" not in arts["352"]["ust_baslik"]


# 4721: KİTAP seviyesi ve büyük harfli yapısal adlar.
TMK_TAPU = (
    "DÖRDÜNCÜ KİTAP\nEŞYA HUKUKU\n"
    "ÜÇÜNCÜ KISIM\nZİLYETLİK VE TAPU SİCİLİ\n"
    "İKİNCİ BÖLÜM\nTAPU SİCİLİ\n"
    "E. Terkin ve değiştirme\nI. Yolsuz tescilde\n"
    "MADDE 1025-\nBir aynî hak yolsuz olarak tescil edilmiş ise, düzeltme\r\n"
    "istenebilir.\n"
)


def test_hiyerarsi_kitap_seviyesi():
    art = lc.split_articles(TMK_TAPU)[0]
    assert art["baslik"] == "I. Yolsuz tescilde"
    assert art["ust_baslik"] == (
        "DÖRDÜNCÜ KİTAP — EŞYA HUKUKU > ÜÇÜNCÜ KISIM — ZİLYETLİK VE TAPU SİCİLİ"
        " > İKİNCİ BÖLÜM — TAPU SİCİLİ | E. Terkin ve değiştirme"
    )


# Yönetmelik/tebliğ kalıbı: bölümün İLK maddesinden sonrakiler bağlamı yerel
# pencerede göremiyordu (Faz 2a'da yönetmeliklerde doluluk %20'de kalmıştı).
YONETMELIK = (
    "BİRİNCİ BÖLÜM\nAmaç, Kapsam, Dayanak ve Tanımlar\n"
    "Amaç\nMADDE 1 –\n(1) Bu Yönetmeliğin amacı usul ve esasları belirlemektir.\n"
    "Kapsam\nMADDE 2 –\n(1) Bu Yönetmelik tüm birimleri kapsar.\n"
    "İKİNCİ BÖLÜM\nGörev ve Yetkiler\n"
    "Kurulun görevleri\nMADDE 3 –\n(1) Kurul şu görevleri yerine getirir.\n"
)


def test_hiyerarsi_yonetmelik_bolum_ikinci_maddede_de_dolu():
    arts = {a["madde_no"]: a for a in lc.split_articles(YONETMELIK)}
    assert arts["1"]["ust_baslik"] == "BİRİNCİ BÖLÜM — Amaç, Kapsam, Dayanak ve Tanımlar"
    assert arts["2"]["baslik"] == "Kapsam"
    assert arts["2"]["ust_baslik"] == "BİRİNCİ BÖLÜM — Amaç, Kapsam, Dayanak ve Tanımlar"
    assert arts["3"]["ust_baslik"] == "İKİNCİ BÖLÜM — Görev ve Yetkiler"


def test_hiyerarsi_bolum_adi_madde_basligina_karismaz():
    arts = {a["madde_no"]: a for a in lc.split_articles(YONETMELIK)}
    assert arts["1"]["baslik"] == "Amaç"
    assert arts["3"]["baslik"] == "Kurulun görevleri"


def test_hiyerarsi_madde_govdesindeki_bolum_kelimesi_yapisal_sayilmaz():
    """Yanlış pozitif: gövde içinde geçen "bölüm"/"kısım" kelimeleri."""
    metin = (
        "BİRİNCİ BÖLÜM\nGenel Esaslar\n"
        "Amaç\nMADDE 1 –\n(1) Bu Yönetmeliğin birinci bölüm hükümleri, ikinci\r\n"
        "kısım ile birlikte uygulanır.\n"
        "Kapsam\nMADDE 2 –\n(1) İkinci bölüm ayrıca değerlendirilir.\n"
    )
    arts = {a["madde_no"]: a for a in lc.split_articles(metin)}
    assert arts["2"]["ust_baslik"] == "BİRİNCİ BÖLÜM — Genel Esaslar"


def test_hiyerarsi_gecici_madde_bayat_kenar_basligini_almaz():
    metin = TBK_KIRA + (
        "DOKUZUNCU BÖLÜM\nSon Hükümler\n"
        "GEÇİCİ MADDE 1-\nBu Kanunun yürürlüğünden önceki ilişkilere uygulanır.\n"
    )
    art = next(a for a in lc.split_articles(metin) if a["madde_no"] == "Geçici 1")
    assert art["ust_baslik"] == (
        "İKİNCİ KISIM — Özel Borç İlişkileri > DOKUZUNCU BÖLÜM — Son Hükümler"
    )
    assert "Dava yoluyla" not in art["ust_baslik"]


def test_hiyerarsi_kanun_kunyesi_ust_basliga_yapismaz():
    """4857 m.1'in üst başlığına "Yayımlandığı Düstur : Tertip: 5" giriyordu."""
    metin = (
        "İŞ KANUNU\n"
        "Kanun Numarası\xa0 : 4857\n"
        "Yayımlandığı\r\nDüstur\xa0 : Tertip : 5\xa0 Cilt : 42\n"
        "BİRİNCİ BÖLÜM\nGenel Hükümler\n"
        "Amaç ve kapsam\nMADDE 1 -\nBu Kanunun amacı düzenlemektir.\n"
    )
    art = lc.split_articles(metin)[0]
    assert art["baslik"] == "Amaç ve kapsam"
    assert "Düstur" not in art["ust_baslik"]
    assert art["ust_baslik"] == "BİRİNCİ BÖLÜM — Genel Hükümler"


@pytest.mark.parametrize("blok,seviye", [
    ("A. Sözleşmenin kurulması", 1),
    ("II. Dava yoluyla", 2),
    ("1. Genel olarak", 3),
    ("a. Hazır olanlar arasında", 4),
    ("Amaç ve kapsam", lc._LEVEL_NONE),
])
def test_enum_seviye(blok, seviye):
    assert lc._enum_level(blok) == seviye


# ── Sürüm grupları (Faz 2d) ─────────────────────────────────────────────────

TARIFE = """AVUKATLIK ASGARİ ÜCRET TARİFESİ

Amaç
MADDE 1 - (1) Bu Tarifenin amacı ücreti belirlemektir.

İcra ve iflas müdürlüklerindeki hukuki yardım
MADDE 11 - (1) İcra dairelerinde takip edilen işlerde ücret {yil} yılında
{tutar} TL'dir.
"""


def _tarife(db, mevzuat_id, no, rg, tutar, ad="AVUKATLIK ASGARİ ÜCRET TARİFESİ"):
    return lc.upsert_document(
        db,
        mevzuat_id=mevzuat_id,
        metin=TARIFE.format(yil=rg[-4:], tutar=tutar),
        kaynak="mevzuatgov",
        tur="TEBLIGLER",
        mevzuat_no=no,
        ad=ad,
        rg_tarihi=rg,
        kaynak_url=f"https://www.mevzuat.gov.tr/{no}",
    )


def _seri(db):
    _tarife(db, "9.5.111", "111", "21.12.2011", "100")
    _tarife(db, "9.5.222", "222", "20.11.2021", "500")
    _tarife(db, "9.5.333", "333", "04.11.2025", "900")


def test_ad_anahtari_normalize_eder():
    a = lc.ad_anahtari("TEBLIGLER", "  Avukatlık   Asgari Ücret Tarifesi ")
    b = lc.ad_anahtari("tebligler", "AVUKATLIK ASGARİ ÜCRET TARİFESİ")
    assert a == b
    # Tür ayırıcı: aynı ad farklı türde aynı gruba düşmez.
    assert lc.ad_anahtari("KANUN", "X") != lc.ad_anahtari("YONETMELIK", "X")


def test_grup_en_yeni_rg_tarihini_guncel_isaretler(db):
    _seri(db)
    rows = dict(db.execute(
        "SELECT mevzuat_no, guncel FROM mevzuat_dokuman WHERE grup_anahtari IS NOT NULL"
    ).fetchall())
    assert rows == {"111": 0, "222": 0, "333": 1}


def test_yeni_surum_gelince_guncel_bayragi_kayar(db):
    _seri(db)
    _tarife(db, "9.5.444", "444", "10.11.2026", "1500")
    rows = dict(db.execute(
        "SELECT mevzuat_no, guncel FROM mevzuat_dokuman WHERE grup_anahtari IS NOT NULL"
    ).fetchall())
    assert rows == {"111": 0, "222": 0, "333": 0, "444": 1}


def test_kanun_turu_asla_katlanmaz(db):
    """İŞ KANUNU 1475 ve 4857 aynı adı taşır; 1475 m.14 hâlâ yürürlükte."""
    for mid, no, rg in (("1.5.1475", "1475", "01.09.1971"),
                        ("1.5.4857", "4857", "10.06.2003")):
        lc.upsert_document(
            db, mevzuat_id=mid, metin="İŞ KANUNU\n\nKıdem\nMADDE 14 - (1) Kıdem tazminatı.\n",
            tur="KANUN", mevzuat_no=no, ad="İŞ KANUNU", rg_tarihi=rg,
        )
    assert db.execute(
        "SELECT COUNT(*) FROM mevzuat_dokuman WHERE grup_anahtari IS NOT NULL"
    ).fetchone()[0] == 0
    out = lc.search_madde(db, "kıdem tazminatı")
    assert out["total_matches"] == 2


def test_sik_yayimlanan_ayni_ad_seri_sayilmaz(db):
    """51 ayrı "ULUSAL MESLEK STANDARTLARINA DAİR TEBLİĞ" örneği: medyan aralık kısa."""
    for i, rg in enumerate(("05.11.2009", "03.02.2010", "12.05.2010", "05.07.2010")):
        _tarife(db, f"9.5.90{i}", f"90{i}", rg, "1",
                ad="ULUSAL MESLEK STANDARTLARINA DAİR TEBLİĞ")
    assert db.execute(
        "SELECT COUNT(*) FROM mevzuat_dokuman WHERE grup_anahtari IS NOT NULL"
    ).fetchone()[0] == 0


def test_arama_eski_surumleri_katlar(db):
    _seri(db)
    out = lc.search_madde(db, "icra dairelerinde takip")
    assert out["total_matches"] == 1
    hit = out["results"][0]
    assert hit["mevzuat_no"] == "333"          # en yeni sürüm
    assert hit["guncel"] is True
    assert hit["eski_surum_sayisi"] == 2
    assert {e["mevzuat_no"] for e in hit["eski_surumler"]} == {"111", "222"}
    assert "900" in hit["snippet"]             # snippet güncel metinden


def test_katlama_madde_yoksa_eski_surumu_dusurmez(db):
    """Güncel sürümde olmayan madde SESSİZCE KAYBOLMAZ, uyarıyla gelir."""
    _seri(db)
    lc.upsert_document(
        db, mevzuat_id="9.5.555", metin=TARIFE.format(yil="2015", tutar="200")
        + "\nKaldırılan\nMADDE 20 - (1) Kadastro işlerinde ayrı ücret.\n",
        tur="TEBLIGLER", mevzuat_no="555", ad="AVUKATLIK ASGARİ ÜCRET TARİFESİ",
        rg_tarihi="31.12.2014",
    )
    out = lc.search_madde(db, "kadastro işlerinde")
    assert out["total_matches"] == 1
    hit = out["results"][0]
    assert hit["mevzuat_no"] == "555" and hit["guncel"] is False
    assert hit["guncel_surum"]["mevzuat_no"] == "333"


def test_get_madde_eski_surumde_guncel_surume_yonlendirir(db):
    _seri(db)
    eski = lc.get_madde(db, "111", "11")
    assert eski["ok"] is True
    assert eski["mevzuat_no"] == "111"          # istenen sürüm yine gelir
    assert eski["guncel"] is False
    assert eski["guncel_surum"] == {
        "mevzuat_no": "333", "rg_tarihi": "04.11.2025",
        "ad": "AVUKATLIK ASGARİ ÜCRET TARİFESİ",
    }
    yeni = lc.get_madde(db, "333", "11")
    assert yeni["guncel"] is True and yeni["eski_surum_sayisi"] == 2
    assert "guncel_surum" not in yeni


def test_gruplari_yenile_kuru_kosum_yazmaz(db):
    _seri(db)
    db.execute("UPDATE mevzuat_dokuman SET grup_anahtari = NULL, guncel = NULL")
    db.commit()
    rapor = lc.gruplari_yenile(db, uygula=False)
    assert rapor["seri_grup"] == 1 and rapor["katlanan_eski_surum"] == 2
    assert rapor["uygulandi"] is False
    assert db.execute(
        "SELECT COUNT(*) FROM mevzuat_dokuman WHERE grup_anahtari IS NOT NULL"
    ).fetchone()[0] == 0
    lc.gruplari_yenile(db, uygula=True)
    assert db.execute(
        "SELECT COUNT(*) FROM mevzuat_dokuman WHERE guncel = 1"
    ).fetchone()[0] == 1
