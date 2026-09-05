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
    # "zamanaşımı" tek başına eşleşir; olmayan kelimeyle AND edilince eşleşmez.
    assert lc.search_madde(db, "alacak zamanaşımına")["total_matches"] == 1
    assert lc.search_madde(db, "alacak kadastro")["total_matches"] == 0


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
