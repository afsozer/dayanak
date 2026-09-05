"""bulk_index — FAISS IVF-PQ toplu indeks: kurulum, arama, belge tekilleştirme, refine."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

faiss = pytest.importorskip("faiss")

from emsal_mcp import bulk_index  # noqa: E402

DIM = 384


def _write_sidecar(vec_dir: Path, name: str, vectors: np.ndarray, doc_ids: list[str],
                   chunk_ix: list[int]) -> None:
    np.save(vec_dir / f"{name}.vectors.npy", vectors.astype(np.float16))
    pq.write_table(pa.table({
        "document_id": pa.array(doc_ids, pa.string()),
        "chunk_index": pa.array(chunk_ix, pa.int16()),
        "text_len": pa.array([1000] * len(doc_ids), pa.int32()),
    }), vec_dir / f"{name}.keys.parquet")


@pytest.fixture
def corpus(tmp_path: Path):
    """2 dosya: bedesten (sayısal id, belge başına 3 parça) + aym (uuid id)."""
    rng = np.random.default_rng(1)
    vec_dir = tmp_path / "vec"
    vec_dir.mkdir()
    db_path = tmp_path / "cache.sqlite3"

    n_docs = 400
    ids, cix, vecs = [], [], []
    for d in range(n_docs):
        base = rng.normal(size=DIM)
        for c in range(3):
            v = base + 0.05 * rng.normal(size=DIM)
            ids.append(str(100000 + d))
            cix.append(c)
            vecs.append(v / np.linalg.norm(v))
    _write_sidecar(vec_dir, "yargitay-train-00000", np.array(vecs), ids, cix)

    a_ids, a_cix, a_vecs = [], [], []
    for d in range(50):
        v = rng.normal(size=DIM)
        a_ids.append(f"uuid-{d:04d}")
        a_cix.append(0)
        a_vecs.append(v / np.linalg.norm(v))
    _write_sidecar(vec_dir, "aym_bb-train-00000", np.array(a_vecs), a_ids, a_cix)

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE documents_v2 (document_id TEXT, source TEXT, title TEXT, "
               "content_status TEXT, full_text TEXT, PRIMARY KEY (document_id, source))")
    body = "\n\n".join(f"Paragraf {k} " + ("hukuki metin " * 120) for k in range(4))
    db.executemany("INSERT INTO documents_v2 VALUES (?,?,?,?,?)",
                   [(i, "bedesten", f"Yargıtay {i}", "html_markdown", body) for i in set(ids)]
                   + [(i, "aym", f"AYM {i}", "html_markdown", None) for i in a_ids])
    db.commit()
    return {"vec_dir": vec_dir, "db_path": db_path, "db": db,
            "vecs": np.array(vecs), "ids": ids, "a_vecs": np.array(a_vecs), "a_ids": a_ids}


def _build(corpus, **kw):
    r = bulk_index.build_bulk_index(
        corpus["vec_dir"], corpus["db_path"], "testprov",
        nlist=8, pq_m=16, train_sample=2000, log=lambda m: None, **kw,
    )
    assert r["ok"], r
    return r


class TestBuild:
    def test_writes_index_keys_meta(self, corpus):
        r = _build(corpus)
        p = bulk_index.bulk_paths(corpus["db_path"], "testprov")
        assert p["index"].exists() and p["keys"].exists() and p["meta"].exists()
        assert r["count"] == 1250
        meta = json.loads(p["meta"].read_text(encoding="utf-8"))
        assert meta["sources"] == bulk_index.SOURCES
        assert len(meta["uuids"]) == 50  # sayısal olmayan kimlikler ayrı listede
        keys = np.load(p["keys"])
        assert (keys["doc_num"] < 0).sum() == 50
        assert set(keys["source_id"].tolist()) == {0, 1}

    def test_source_for_file(self):
        assert bulk_index.source_for_file("aym_bb-train-00000.vectors.npy") == "aym"
        assert bulk_index.source_for_file("aym_norm-x.vectors.npy") == "aym"
        assert bulk_index.source_for_file("yargitay-x.vectors.npy") == "bedesten"
        assert bulk_index.source_for_file("emsal-x.vectors.npy") == "bedesten"

    def test_status(self, corpus):
        assert bulk_index.bulk_index_status(corpus["db_path"], "testprov") == {"exists": False}
        _build(corpus)
        st = bulk_index.bulk_index_status(corpus["db_path"], "testprov")
        assert st["exists"] and st["count"] == 1250 and "uuids" not in st


class TestSearch:
    def test_missing_index_returns_none(self, corpus):
        assert bulk_index.bulk_search(
            corpus["db"], corpus["db_path"], "testprov", [0.0] * DIM, limit=5,
        ) is None

    def test_dedupes_chunks_per_document(self, corpus, monkeypatch):
        _build(corpus)
        monkeypatch.setenv("EMSAL_BULK_VEC_DIR", str(corpus["vec_dir"]))
        bulk_index._CACHE.clear()
        # 7. belgenin 1. parçasını sorgu olarak kullan → aynı belgenin 3 parçası tek satır olmalı
        q = corpus["vecs"][7 * 3 + 1].tolist()
        out = bulk_index.bulk_search(corpus["db"], corpus["db_path"], "testprov", q, limit=10)
        assert out is not None and out
        keys = [(r["document_id"], r["source"]) for r in out]
        assert len(keys) == len(set(keys)), "aynı belge birden çok kez döndü"
        assert out[0]["document_id"] == corpus["ids"][7 * 3]
        assert out[0]["source"] == "bedesten"
        assert out[0]["title"] == f"Yargıtay {corpus['ids'][7 * 3]}"
        assert out[0]["best_chunk"] in (0, 1, 2)
        assert out[0]["score"] > 0.99  # refine: tam fp16 iç çarpım, PQ yaklaşıklığı değil
        assert out[0]["snippet"].startswith("Paragraf") and "related_quotes" not in out[0]
        assert "snippet" not in out[-1] or len(out) <= 20  # yalnız ilk snippet_n belge
        assert out == sorted(out, key=lambda r: r["score"], reverse=True)

    def test_uuid_ids_and_source_mapping(self, corpus, monkeypatch):
        _build(corpus)
        monkeypatch.setenv("EMSAL_BULK_VEC_DIR", str(corpus["vec_dir"]))
        bulk_index._CACHE.clear()
        q = corpus["a_vecs"][3].tolist()
        out = bulk_index.bulk_search(corpus["db"], corpus["db_path"], "testprov", q, limit=3)
        assert out[0]["document_id"] == "uuid-0003"
        assert out[0]["source"] == "aym"
        assert out[0]["title"] == "AYM uuid-0003"

    def test_without_vector_files_falls_back_to_pq_scores(self, corpus, monkeypatch):
        _build(corpus)
        monkeypatch.setenv("EMSAL_BULK_VEC_DIR", str(corpus["db_path"].parent / "yok"))
        bulk_index._CACHE.clear()
        L = bulk_index._load(corpus["db_path"], "testprov")
        assert L is not None and not L.mats and "refine kapalı" in L.refine_warning
        q = corpus["vecs"][0].tolist()
        out = bulk_index.bulk_search(corpus["db"], corpus["db_path"], "testprov", q, limit=5)
        assert out and out[0]["document_id"] == corpus["ids"][0]

    def test_filters_applied(self, corpus, monkeypatch):
        _build(corpus)
        monkeypatch.setenv("EMSAL_BULK_VEC_DIR", str(corpus["vec_dir"]))
        bulk_index._CACHE.clear()
        q = corpus["vecs"][0].tolist()
        out = bulk_index.bulk_search(
            corpus["db"], corpus["db_path"], "testprov", q, limit=5, filters={"source": "aym"},
        )
        assert out is not None
        assert all(r["source"] == "aym" for r in out)


class TestAppend:
    def test_append_sidecar_extends_index_and_keys(self, corpus, monkeypatch):
        _build(corpus)
        monkeypatch.setenv("EMSAL_BULK_VEC_DIR", str(corpus["vec_dir"]))
        rng = np.random.default_rng(7)
        # karışık kaynaklı delta: 3 yeni bedesten belgesi (2 parça) + 1 aym (uuid)
        vecs, ids, srcs, cix = [], [], [], []
        for d in range(3):
            base = rng.normal(size=DIM)
            for c in range(2):
                v = base + 0.05 * rng.normal(size=DIM)
                vecs.append(v / np.linalg.norm(v)); ids.append(str(900000 + d)); srcs.append("bedesten"); cix.append(c)
        v = rng.normal(size=DIM); vecs.append(v / np.linalg.norm(v)); ids.append("uuid-new"); srcs.append("aym"); cix.append(0)
        np.save(corpus["vec_dir"] / "delta-1.vectors.npy", np.array(vecs).astype(np.float16))
        pq.write_table(pa.table({
            "document_id": pa.array(ids, pa.string()), "source": pa.array(srcs, pa.string()),
            "chunk_index": pa.array(cix, pa.int16()), "text_len": pa.array([500] * len(ids), pa.int32()),
        }), corpus["vec_dir"] / "delta-1.keys.parquet")
        corpus["db"].executemany("INSERT INTO documents_v2 VALUES (?,?,?,?,?)",
                                 [(str(900000 + d), "bedesten", f"Yeni {d}", "html_markdown", None) for d in range(3)]
                                 + [("uuid-new", "aym", "AYM yeni", "html_markdown", None)])
        corpus["db"].commit()
        r = bulk_index.append_sidecar(corpus["vec_dir"], corpus["db_path"], "testprov", "delta-1", log=lambda m: None)
        assert r["ok"] and r["added"] == 7 and r["count"] == 1250 + 7
        st = bulk_index.bulk_index_status(corpus["db_path"], "testprov")
        assert st["count"] == 1257 and st["files"][-1] == "delta-1.vectors.npy"
        bulk_index._CACHE.clear()
        out = bulk_index.bulk_search(corpus["db"], corpus["db_path"], "testprov", vecs[0].tolist(), limit=3)
        assert out[0]["document_id"] == "900000" and out[0]["source"] == "bedesten"
        out = bulk_index.bulk_search(corpus["db"], corpus["db_path"], "testprov", vecs[-1].tolist(), limit=3)
        assert out[0]["document_id"] == "uuid-new" and out[0]["source"] == "aym" and out[0]["title"] == "AYM yeni"
        # tekrar ekleme atlanır
        r2 = bulk_index.append_sidecar(corpus["vec_dir"], corpus["db_path"], "testprov", "delta-1", log=lambda m: None)
        assert r2["ok"] and r2.get("skipped")
