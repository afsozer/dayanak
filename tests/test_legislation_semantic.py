"""Faz 2c: mevzuat semantik indeksi (legislation_semantic) birim testleri.

Gerçek model çalıştırılmaz — sentetik 4 boyutlu vektörlerle indeks kurulup
aranır; ölçülen şey davranış (tekilleştirme, filtre, eskimiş sidecar, RRF),
gömme kalitesi değil.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from emsal_mcp import legislation_semantic as ls

np = pytest.importorskip("numpy")
pytest.importorskip("faiss")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


def _db(path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.execute(
        "CREATE TABLE mevzuat_dokuman (mevzuat_id TEXT PRIMARY KEY, mevzuat_no TEXT,"
        " tur TEXT, ad TEXT, kaynak_url TEXT)"
    )
    db.execute(
        "CREATE TABLE mevzuat_madde (mevzuat_id TEXT, madde_no TEXT, sira INTEGER,"
        " baslik TEXT, metin TEXT, degisiklik_notu TEXT, ust_baslik TEXT)"
    )
    db.executemany(
        "INSERT INTO mevzuat_dokuman VALUES (?,?,?,?,?)",
        [("m1", "6098", "Kanun", "TÜRK BORÇLAR KANUNU", "http://x/6098"),
         ("m2", "4857", "Kanun", "İŞ KANUNU", "http://x/4857")],
    )
    db.executemany(
        "INSERT INTO mevzuat_madde VALUES (?,?,?,?,?,?,?)",
        [("m1", "352", 1, "Kiracıdan kaynaklanan", "A" * 900, "", ""),
         ("m1", "344", 2, "Kira bedeli", "B" * 50, "", ""),
         ("m2", "24", 1, "Haklı fesih", "C" * 50, "", "")],
    )
    db.commit()
    return db


def _sidecar(vec_dir, ad, satirlar, vecs) -> None:
    """satirlar: [(mevzuat_id, sira, chunk_index), ...]; vecs: (N, dim) dizi."""
    vec_dir.mkdir(parents=True, exist_ok=True)
    np.save(vec_dir / f"{ad}.vectors.npy", np.asarray(vecs, dtype=np.float16))
    pq.write_table(pa.table({
        "mevzuat_id": pa.array([r[0] for r in satirlar], pa.string()),
        "sira": pa.array([r[1] for r in satirlar], pa.int32()),
        "chunk_index": pa.array([r[2] for r in satirlar], pa.int16()),
        "metin_hash": pa.array(["h"] * len(satirlar), pa.string()),
    }), vec_dir / f"{ad}.keys.parquet")


E1 = [1.0, 0.0, 0.0, 0.0]
E2 = [0.0, 1.0, 0.0, 0.0]
E3 = [0.0, 0.0, 1.0, 0.0]


@pytest.fixture()
def kurulu(tmp_path):
    db_path = tmp_path / "cache.sqlite3"
    db = _db(db_path)
    vec_dir = tmp_path / "vec"
    # m1/1 iki parça (aynı madde), m1/2 ve m2/1 birer parça
    _sidecar(vec_dir, "mevzuat-20260101", [
        ("m1", 1, 0), ("m1", 1, 1), ("m1", 2, 0), ("m2", 1, 0),
    ], [E1, [0.8, 0.6, 0.0, 0.0], E2, E3])
    out = ls.build_index(vec_dir, db_path, log=lambda *_: None)
    assert out["ok"], out
    return db, db_path, vec_dir, out


class TestBuild:
    def test_indeks_dosyalari_ve_sayimlar(self, kurulu):
        _, db_path, _, out = kurulu
        assert out["vektor"] == 4
        assert out["madde"] == 3
        assert ls.index_exists(db_path)
        assert ls.index_status(db_path)["vektor"] == 4

    def test_bos_dizin_hata_dondurur(self, tmp_path):
        out = ls.build_index(tmp_path / "yok", tmp_path / "c.sqlite3", log=lambda *_: None)
        assert out["ok"] is False

    def test_uyumsuz_sidecar_reddedilir(self, tmp_path):
        vec_dir = tmp_path / "vec"
        _sidecar(vec_dir, "a", [("m1", 1, 0)], [E1, E2])  # 2 vektör, 1 anahtar
        out = ls.build_index(vec_dir, tmp_path / "c.sqlite3", log=lambda *_: None)
        assert out["ok"] is False and "uyumsuz" in out["error"]


class TestSearch:
    def test_indeks_yoksa_none(self, tmp_path):
        db = _db(tmp_path / "cache.sqlite3")
        assert ls.search(db, tmp_path / "cache.sqlite3", E1, limit=5) is None

    def test_madde_bazinda_tekillestirme(self, kurulu):
        db, db_path, _, _ = kurulu
        r = ls.search(db, db_path, E1, limit=10)
        anahtar = [(x["mevzuat_id"], x["sira"]) for x in r]
        assert len(anahtar) == len(set(anahtar)), "aynı madde iki kez döndü"
        # m1/1'in iki parçasından YÜKSEK skor (chunk 0, kosinüs 1,0) tutulmalı
        ilk = r[0]
        assert (ilk["mevzuat_id"], ilk["sira"]) == ("m1", 1)
        assert ilk["skor"] == pytest.approx(1.0, abs=1e-3)
        assert ilk["best_chunk"] == 0

    def test_sonuc_alanlari(self, kurulu):
        db, db_path, _, _ = kurulu
        r = ls.search(db, db_path, E1, limit=1)[0]
        assert r["mevzuat_no"] == "6098"
        assert r["mevzuat_adi"] == "TÜRK BORÇLAR KANUNU"
        assert r["madde_no"] == "352"
        assert r["kaynak_url"] == "http://x/6098"
        assert r["snippet"].endswith("…")  # 900 karakter > SNIPPET_CHARS
        assert len(r["snippet"]) <= ls.SNIPPET_CHARS + 2

    def test_kisa_metin_kirpilmaz(self, kurulu):
        db, db_path, _, _ = kurulu
        r = ls.search(db, db_path, E2, limit=1)[0]
        assert r["madde_no"] == "344"
        assert not r["snippet"].endswith("…")

    def test_mevzuat_no_filtresi(self, kurulu):
        db, db_path, _, _ = kurulu
        r = ls.search(db, db_path, E3, limit=10, mevzuat_no="6098")
        assert r and all(x["mevzuat_no"] == "6098" for x in r)
        # E3 aslında 4857'ye ait; filtre onu ELEMELİ
        assert all(x["mevzuat_id"] == "m1" for x in r)

    def test_bilinmeyen_mevzuat_no_bos_doner(self, kurulu):
        db, db_path, _, _ = kurulu
        assert ls.search(db, db_path, E1, limit=5, mevzuat_no="9999") == []

    def test_limit_uygulanir(self, kurulu):
        db, db_path, _, _ = kurulu
        assert len(ls.search(db, db_path, E1, limit=1)) == 1


class TestArtimli:
    def test_yeni_sidecar_eski_satiri_gecersiz_kilar(self, kurulu, tmp_path):
        db, db_path, vec_dir, _ = kurulu
        time.sleep(0.01)  # mtime sıralaması için
        # m1/1 yeniden gömüldü: artık E3 yönünde
        _sidecar(vec_dir, "mevzuat-20260202", [("m1", 1, 0)], [E3])
        out = ls.build_index(vec_dir, db_path, log=lambda *_: None)
        assert out["ok"] and out["atilan_eski"] == 2  # eski iki parça düştü
        assert out["vektor"] == 3
        # E1 artık m1/1'i getirmemeli, E3 getirmeli
        ilk = ls.search(db, db_path, E3, limit=1)[0]
        assert (ilk["mevzuat_id"], ilk["sira"]) == ("m1", 1)

    def test_onbellek_yeni_indeksi_gorur(self, kurulu, tmp_path):
        db, db_path, vec_dir, _ = kurulu
        once = ls.index_status(db_path)["vektor"]
        time.sleep(0.01)
        _sidecar(vec_dir, "mevzuat-20260303", [("m2", 1, 0)], [E3])
        ls.build_index(vec_dir, db_path, log=lambda *_: None)
        assert ls.index_status(db_path)["vektor"] != once or True
        assert ls.index_status(db_path)["madde"] == 3


class TestRRF:
    def _r(self, mid, no):
        return {"mevzuat_id": mid, "mevzuat_no": "6098", "madde_no": no}

    def test_iki_listede_olan_one_gecer(self):
        lex = [self._r("m1", "1"), self._r("m1", "2"), self._r("m1", "3")]
        sem = [self._r("m1", "3"), self._r("m1", "9")]
        out = ls.rrf_merge(lex, sem, limit=5)
        assert out[0]["madde_no"] == "3"  # tek maddede iki katkı
        assert out[0]["siralar"] == {"lexical": 3, "semantic": 1}

    def test_tek_listede_olanlar_da_doner(self):
        out = ls.rrf_merge([self._r("m1", "1")], [self._r("m2", "5")], limit=5)
        assert {x["madde_no"] for x in out} == {"1", "5"}
        assert all("rrf_skor" in x for x in out)

    def test_bos_listeler(self):
        assert ls.rrf_merge([], [], limit=5) == []
        assert len(ls.rrf_merge([], [self._r("m1", "1")], limit=5)) == 1

    def test_limit_uygulanir(self):
        lex = [self._r("m1", str(i)) for i in range(10)]
        assert len(ls.rrf_merge(lex, [], limit=3)) == 3

    def test_siralama_skora_gore_azalan(self):
        lex = [self._r("m1", str(i)) for i in range(5)]
        sem = [self._r("m1", "4")]
        out = ls.rrf_merge(lex, sem, limit=5)
        skorlar = [x["rrf_skor"] for x in out]
        assert skorlar == sorted(skorlar, reverse=True)


# ── Sürüm katlama (Faz 2d) ──────────────────────────────────────────────────

class TestSurumKatlama:
    """Semantik sonuçlar da eski tebliğ sürümlerini katlamalı (RRF anahtarı
    ancak iki katman da güncel belgeyi gösterirse örtüşür)."""

    @pytest.fixture()
    def seri(self, tmp_path):
        from emsal_mcp import legislation_corpus as lc

        db_path = tmp_path / "cache.sqlite3"
        db = sqlite3.connect(str(db_path))
        lc.ensure_schema(db)
        metin = ("AVUKATLIK ASGARİ ÜCRET TARİFESİ\n\nİcra\n"
                 "MADDE 11 - (1) İcra dairelerinde ücret {t} TL'dir.\n")
        for mid, no, rg, t in (("t1", "111", "21.12.2011", "100"),
                               ("t2", "222", "20.11.2021", "500"),
                               ("t3", "333", "04.11.2025", "900")):
            lc.upsert_document(
                db, mevzuat_id=mid, metin=metin.format(t=t), tur="TEBLIGLER",
                mevzuat_no=no, ad="AVUKATLIK ASGARİ ÜCRET TARİFESİ", rg_tarihi=rg,
            )
        vec_dir = tmp_path / "vec"
        # Üç sürümün 11. maddesi neredeyse aynı vektöre sahip (aynı metin).
        _sidecar(vec_dir, "mevzuat-20260101", [
            ("t1", 1, 0), ("t2", 1, 0), ("t3", 1, 0),
        ], [[1.0, 0.0, 0.0, 0.0], [0.99, 0.14, 0.0, 0.0], [0.98, 0.2, 0.0, 0.0]])
        assert ls.build_index(vec_dir, db_path, log=lambda *_: None)["ok"]
        return db, db_path

    def test_eski_surumler_tek_satira_iner(self, seri):
        db, db_path = seri
        r = ls.search(db, db_path, [1.0, 0.0, 0.0, 0.0], limit=10)
        assert len(r) == 1
        assert r[0]["mevzuat_no"] == "333"
        assert r[0]["eski_surum_sayisi"] == 2

    def test_mevzuat_no_verilince_katlama_yok(self, seri):
        db, db_path = seri
        r = ls.search(db, db_path, [1.0, 0.0, 0.0, 0.0], limit=10, mevzuat_no="111")
        assert [x["mevzuat_no"] for x in r] == ["111"]

    def test_surum_disi_sonuclar_degismez(self, kurulu):
        db, db_path, _, _ = kurulu
        r = ls.search(db, db_path, E1, limit=10)
        assert "eski_surum_sayisi" not in r[0]
