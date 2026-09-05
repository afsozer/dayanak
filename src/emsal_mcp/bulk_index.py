"""emsal_mcp.bulk_index — milyonlarca parça vektörü için FAISS IVF-PQ toplu indeks.

Neden var
---------
``semantic.embedding_search`` her sorguda sidecar matrisin tamamını tarar
(float32, N×384).  1,3 M vektörde 2 GB ve ~40 ms; 11 M kararın parçalı
gömülmesiyle (~22 M vektör) matris 34 GB olur ve 16 GB RAM'li sunucuda her
sorgu diski baştan sona okur.  Bu modül aynı vektörleri IVF-PQ ile 64 bayt/
vektöre sıkıştırır (~1,4 GB), sorgu ~10 ms, RAM'de kalır.

Kaynak veri ``scripts/embed_parquet_worker.py`` çıktısıdır (dosya başına
``*.vectors.npy`` float16 + ``*.keys.parquet``).  İndeks SQLite'a dokunmaz;
``documents_v2`` yalnız başlık/metadata birleştirmek için okunur.

Dosyalar (cache.sqlite3'ün yanında)::

    bulk-<provider>.faiss       IVF-PQ indeks
    bulk-<provider>.keys.npz    doc_num int64, chunk_index int16, source_id int8
    bulk-<provider>.meta.json   sayılar, parametreler, uuid listesi (sayısal
                                olmayan document_id'ler; AYM)

Parça → belge tekilleştirmesi burada yapılır: aynı belgenin birden çok
parçası dönerse en yüksek skor tutulur.  Çıktı biçimi ``_score_vectors_mmap``
ile aynıdır, ``hybrid_search`` farkı görmez.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

SOURCES = ["bedesten", "aym"]  # source_id int8 → ad; yeni kaynak SONA eklenir
_DEFAULT_NLIST = 16384
_DEFAULT_PQ_M = 64
_DEFAULT_NPROBE = 128
_TRAIN_SAMPLE = 1_000_000
#: PQ yalnız aday bulur; adaylar diskteki fp16 vektörlerle yeniden puanlanır
#: ("refine").  Ölçüm (3,3 M vektör, 15 sorgu, tam aramaya göre recall@10):
#: PQ64 tek başına 0,29-0,31; PQ64 + refine k=500 0,81, k=2000 0,85 (nprobe 48)
#: / 0,87 (nprobe 128), k=5000 0,87.  Gecikme Mac'te 6-7 ms.
_REFINE_K = 2000


def _stem(db_path: Path, provider_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", provider_id)
    return db_path.parent / f"bulk-{safe}"


def bulk_paths(db_path: Path, provider_id: str) -> dict[str, Path]:
    s = _stem(db_path, provider_id)
    return {
        "index": s.with_suffix(".faiss"),
        "keys": s.with_suffix(".keys.npz"),
        "meta": s.with_suffix(".meta.json"),
    }


def bulk_index_exists(db_path: Path, provider_id: str) -> bool:
    p = bulk_paths(db_path, provider_id)
    return p["index"].exists() and p["keys"].exists() and p["meta"].exists()


# ---------------------------------------------------------------------------
# Kurulum
# ---------------------------------------------------------------------------

def source_for_file(name: str) -> str:
    """embed_parquet_worker dosya adından kaynak: aym_* → aym, diğerleri bedesten
    (HF yargitay/emsal/danistay kimlikleri Bedesten kimlikleriyle aynı)."""
    return "aym" if name.startswith("aym_") else "bedesten"


def _iter_vec_files(vec_dir: Path) -> list[tuple[Path, Path]]:
    out = []
    for v in sorted(glob.glob(str(vec_dir / "*.vectors.npy"))):
        k = Path(v[: -len(".vectors.npy")] + ".keys.parquet")
        if k.exists():
            out.append((Path(v), k))
    return out


def build_bulk_index(
    vec_dir: Path,
    db_path: Path,
    provider_id: str,
    *,
    nlist: int = _DEFAULT_NLIST,
    pq_m: int = _DEFAULT_PQ_M,
    train_sample: int = _TRAIN_SAMPLE,
    max_files: int = 0,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    import faiss
    import numpy as np
    import pyarrow.parquet as pq

    files = _iter_vec_files(Path(vec_dir))
    if max_files:
        files = files[:max_files]
    if not files:
        return {"ok": False, "error": f"{vec_dir} içinde *.vectors.npy yok"}

    t0 = time.time()
    shapes = [np.load(v, mmap_mode="r").shape for v, _ in files]
    total = sum(s[0] for s in shapes)
    dim = shapes[0][1]
    log(f"{len(files)} dosya, {total:,} vektör, dim={dim}")

    # --- eğitim örneği: her dosyadan orantılı rastgele satır -----------------
    rng = np.random.default_rng(0)
    take = min(train_sample, total)
    parts = []
    for (v, _), s in zip(files, shapes):
        n = max(1, int(round(take * s[0] / total)))
        m = np.load(v, mmap_mode="r")
        idx = np.sort(rng.choice(s[0], size=min(n, s[0]), replace=False))
        parts.append(np.asarray(m[idx], dtype=np.float32))
    train = np.concatenate(parts)
    del parts
    log(f"eğitim örneği {train.shape[0]:,} ({time.time()-t0:.0f} s)")

    quant = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFPQ(quant, dim, nlist, pq_m, 8, faiss.METRIC_INNER_PRODUCT)
    index.train(train)
    del train
    log(f"IVF{nlist},PQ{pq_m} eğitildi ({time.time()-t0:.0f} s)")

    # --- ekleme + anahtarlar ---------------------------------------------------
    doc_num = np.empty(total, dtype=np.int64)
    chunk_ix = np.empty(total, dtype=np.int16)
    src_id = np.empty(total, dtype=np.int8)
    uuids: list[str] = []
    uuid_pos: dict[str, int] = {}
    pos = 0
    for fi, ((v, k), s) in enumerate(zip(files, shapes)):
        keys = pq.read_table(k)
        ids = keys["document_id"].to_pylist()
        n = len(ids)
        assert n == s[0], f"{v.name}: {n} anahtar / {s[0]} vektör"
        if "source" in keys.column_names:  # delta sidecar: satır başına kaynak
            sids = np.array([SOURCES.index(x) for x in keys["source"].to_pylist()], dtype=np.int8)
        else:
            sids = np.full(n, SOURCES.index(source_for_file(v.name)), dtype=np.int8)
        nums = np.empty(n, dtype=np.int64)
        for i, d in enumerate(ids):
            if d.isdigit() and len(d) < 19:
                nums[i] = int(d)
            else:
                j = uuid_pos.get(d)
                if j is None:
                    j = len(uuids)
                    uuids.append(d)
                    uuid_pos[d] = j
                nums[i] = -(j + 1)
        doc_num[pos:pos + n] = nums
        chunk_ix[pos:pos + n] = keys["chunk_index"].to_numpy()
        src_id[pos:pos + n] = sids
        m = np.load(v, mmap_mode="r")
        step = 500_000
        for a in range(0, n, step):
            index.add(np.asarray(m[a:a + step], dtype=np.float32))
        pos += n
        log(f"[{fi+1}/{len(files)}] {v.name}: +{n:,} → {pos:,} ({time.time()-t0:.0f} s)")

    paths = bulk_paths(Path(db_path), provider_id)
    tmp = paths["index"].with_suffix(".faiss.tmp")
    faiss.write_index(index, str(tmp))
    os.replace(tmp, paths["index"])
    np.savez(paths["keys"], doc_num=doc_num, chunk_index=chunk_ix, source_id=src_id)
    meta = {
        "provider": provider_id, "count": int(total), "dim": int(dim),
        "nlist": nlist, "pq_m": pq_m, "nprobe": _DEFAULT_NPROBE,
        "sources": SOURCES, "uuids": uuids,
        "files": [v.name for v, _ in files],
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(time.time() - t0, 1),
        "model": "intfloat/multilingual-e5-small", "chunk_size": 1600, "overlap": 200,
    }
    paths["meta"].write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    log(f"yazıldı: {paths['index']} ({paths['index'].stat().st_size/2**20:.0f} MB), "
        f"{total:,} vektör, {time.time()-t0:.0f} s")
    return {"ok": True, **{k: v for k, v in meta.items() if k != "uuids"}}



def _encode_doc_ids(ids: list[str], uuids: list[str]) -> "np.ndarray":
    """document_id -> int64: sayısal kimlik olduğu gibi, diğerleri -(uuid_idx+1).
    `uuids` yerinde genişletilir."""
    import numpy as np
    pos = {u: i for i, u in enumerate(uuids)}
    out = np.empty(len(ids), dtype=np.int64)
    for i, d in enumerate(ids):
        if d.isdigit() and len(d) < 19:
            out[i] = int(d)
        else:
            j = pos.get(d)
            if j is None:
                j = len(uuids)
                uuids.append(d)
                pos[d] = j
            out[i] = -(j + 1)
    return out


def append_sidecar(
    vec_dir: Path,
    db_path: Path,
    provider_id: str,
    name: str,
    *,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Mevcut toplu indekse yeni bir sidecar (``<name>.vectors.npy`` +
    ``<name>.keys.parquet``) ekle: FAISS add, anahtar dizileri ve meta.files
    genişler. Tam yeniden kurulum gerekmez (IVF merkezleri sabit kalır).
    Aylık birleştirme bunu kullanır (scripts/monthly_merge.cmd)."""
    import faiss
    import numpy as np
    import pyarrow.parquet as pq

    vec_dir = Path(vec_dir)
    v = vec_dir / f"{name}.vectors.npy"
    k = vec_dir / f"{name}.keys.parquet"
    if not (v.exists() and k.exists()):
        return {"ok": False, "error": f"{name}: vectors/keys yok ({vec_dir})"}
    paths = bulk_paths(Path(db_path), provider_id)
    if not bulk_index_exists(Path(db_path), provider_id):
        return {"ok": False, "error": "toplu indeks yok; önce bulk-build"}
    meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    if v.name in meta.get("files", []):
        return {"ok": True, "skipped": True, "reason": f"{v.name} zaten indekste"}

    t0 = time.time()
    mat = np.load(v, mmap_mode="r")
    keys = pq.read_table(k)
    n = mat.shape[0]
    if n != keys.num_rows:
        return {"ok": False, "error": f"{name}: {keys.num_rows} anahtar / {n} vektör"}
    if n == 0:
        return {"ok": True, "skipped": True, "reason": "boş sidecar"}

    index = faiss.read_index(str(paths["index"]))
    if mat.shape[1] != index.d:
        return {"ok": False, "error": f"dim uyuşmuyor {mat.shape[1]} != {index.d}"}
    for a in range(0, n, 500_000):
        index.add(np.asarray(mat[a:a + 500_000], dtype=np.float32))
    log(f"{name}: +{n:,} vektör eklendi → {index.ntotal:,} ({time.time()-t0:.0f} s)")

    with np.load(paths["keys"]) as old_npz:  # Windows: dosya açıkken os.replace başarısız olur
        old = {k: old_npz[k] for k in ("doc_num", "chunk_index", "source_id")}
    uuids: list[str] = list(meta.get("uuids", []))
    nums = _encode_doc_ids(keys["document_id"].to_pylist(), uuids)
    # Kaynak listesi meta'da yaşar ve genişleyebilir (uyap_arsiv, mevzuat, ...);
    # yeni kaynak SONA eklenir, eski source_id değerleri değişmez (int8, ≤127).
    sources: list[str] = list(meta.get("sources", SOURCES))
    src_col = keys["source"].to_pylist() if "source" in keys.column_names \
        else [source_for_file(v.name)] * n
    for x in src_col:
        if x not in sources:
            sources.append(x)
    if len(sources) > 127:
        return {"ok": False, "error": "kaynak sayısı int8 sınırını aştı"}
    sid_of = {x: i for i, x in enumerate(sources)}
    sids = np.array([sid_of[x] for x in src_col], dtype=np.int8)
    doc_num = np.concatenate([old["doc_num"], nums])
    chunk_ix = np.concatenate([old["chunk_index"], keys["chunk_index"].to_numpy().astype(np.int16)])
    src_id = np.concatenate([old["source_id"], sids])
    assert len(doc_num) == index.ntotal, (len(doc_num), index.ntotal)

    # Yazım sırası: index (tmp+replace) → keys → meta. Sunucu dosyaları mtime ile
    # yeniden yükler; sidecar .npy'ler değiştirilmez, yalnız yenisi eklenir.
    tmp = paths["index"].with_suffix(".faiss.tmp")
    faiss.write_index(index, str(tmp))
    os.replace(tmp, paths["index"])
    tmpk = paths["keys"].with_suffix(".npz.tmp.npz")
    np.savez(tmpk, doc_num=doc_num, chunk_index=chunk_ix, source_id=src_id)
    os.replace(tmpk, paths["keys"])
    meta["files"] = list(meta.get("files", [])) + [v.name]
    meta["count"] = int(index.ntotal)
    meta["uuids"] = uuids
    meta["sources"] = sources
    meta.setdefault("appends", []).append({
        "file": v.name, "chunks": int(n), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    tmpm = paths["meta"].with_suffix(".json.tmp")
    tmpm.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(tmpm, paths["meta"])
    _CACHE.clear()
    log(f"{name}: indeks {index.ntotal:,} vektör, {len(meta['files'])} dosya, {time.time()-t0:.0f} s")
    return {"ok": True, "added": int(n), "count": int(index.ntotal), "files": len(meta["files"]),
            "elapsed_s": round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------
# Arama
# ---------------------------------------------------------------------------

class _Loaded:
    __slots__ = ("index", "doc_num", "chunk_index", "source_id", "meta", "mtime",
                 "mats", "offsets", "refine_warning")


_CACHE: dict[str, _Loaded] = {}


def vec_dir_for(db_path: Path) -> Path:
    """fp16 vektör dosyalarının yeri: EMSAL_BULK_VEC_DIR ya da cache'in yanındaki vec/."""
    env = os.environ.get("EMSAL_BULK_VEC_DIR", "").strip()
    return Path(os.path.expanduser(env)) if env else db_path.parent / "vec"


def _load(db_path: Path, provider_id: str) -> _Loaded | None:
    import faiss
    import numpy as np

    p = bulk_paths(db_path, provider_id)
    if not (p["index"].exists() and p["keys"].exists() and p["meta"].exists()):
        return None
    key = str(p["index"])
    mtime = p["index"].stat().st_mtime
    hit = _CACHE.get(key)
    if hit is not None and hit.mtime == mtime:
        return hit
    L = _Loaded()
    L.index = faiss.read_index(key)
    with np.load(p["keys"]) as keys:
        L.doc_num = keys["doc_num"]
        L.chunk_index = keys["chunk_index"]
        L.source_id = keys["source_id"]
    L.meta = json.loads(p["meta"].read_text(encoding="utf-8"))
    L.index.nprobe = int(os.environ.get("EMSAL_BULK_NPROBE", L.meta.get("nprobe", _DEFAULT_NPROBE)))
    L.mtime = mtime
    # refine için fp16 memmap'ler (indeksle aynı dosya sırası); yoksa PQ skoru kalır
    L.mats, L.offsets, L.refine_warning = [], None, None
    vdir = vec_dir_for(db_path)
    try:
        mats = [np.load(vdir / name, mmap_mode="r") for name in L.meta["files"]]
        if sum(m.shape[0] for m in mats) != L.index.ntotal:
            raise ValueError("vektör dosyaları indeksle uyuşmuyor (satır sayısı)")
        L.mats = mats
        L.offsets = np.cumsum([0] + [m.shape[0] for m in mats])
    except Exception as exc:
        L.refine_warning = f"refine kapalı ({vdir}): {exc}"
    _CACHE[key] = L
    return L


def _refine(L: _Loaded, q: Any, ids: Any) -> Any:
    """Adayları diskteki fp16 vektörlerle tam iç çarpımla yeniden puanla."""
    import numpy as np
    order = np.argsort(ids)  # sıralı okuma: disk için daha iyi
    sids = ids[order]
    fi = np.searchsorted(L.offsets, sids, side="right") - 1
    V = np.empty((len(sids), q.shape[0]), dtype=np.float32)
    for k, (f, g) in enumerate(zip(fi, sids)):
        V[k] = L.mats[int(f)][int(g) - int(L.offsets[f])]
    s = np.empty(len(ids), dtype=np.float32)
    s[order] = V @ q
    return s


def _doc_id(L: _Loaded, i: int) -> str:
    n = int(L.doc_num[i])
    return str(n) if n >= 0 else L.meta["uuids"][-n - 1]


def _best_chunk_text(text: str, chunk_index: int, max_chars: int = 600) -> str:
    """Belgeyi indekslemede kullanilan ayni parcalayiciyla bol, en iyi parcayi dondur."""
    try:
        from .chunking import chunk_text
        chunks = chunk_text(text)
        if not chunks:
            return ""
        c = chunks[min(max(int(chunk_index), 0), len(chunks) - 1)]
        c = " ".join(c.split())
        # Ortusme parcalari, onceki parcanin kuyrugunu basa ekliyor ve ayni metin
        # hemen ardindan yeniden geliyor ("... takdirde k" + "... takdirde kiraci").
        # Ilk 100 karakter ileride tekrar ediyorsa basi at.
        head = c[:100]
        if len(head) == 100:
            again = c.find(head, 1)
            if 0 < again <= 400:
                c = c[again:]
        # Kelime ortasindan baslayan kesit: ilk bosluga kadar at.
        if c and not c[0].isupper() and " " in c[:40]:
            c = c[c.index(" ") + 1:]
        return c[:max_chars] + ("…" if len(c) > max_chars else "")
    except Exception:
        return ""


def bulk_search(
    db: Any,
    db_path: Path,
    provider_id: str,
    q_vec: list[float],
    *,
    limit: int,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    """Toplu indekste ara; belge bazında tekilleştirilmiş, skora göre sıralı liste.
    İndeks yoksa None (çağıran mevcut yola düşer)."""
    import numpy as np

    L = _load(db_path, provider_id)
    if L is None:
        return None
    q = np.asarray([q_vec], dtype=np.float32)
    nrm = float(np.linalg.norm(q))
    if nrm > 0:
        q = q / nrm
    k = min(max(limit * 20, _REFINE_K if L.mats else 200), L.index.ntotal)
    scores, ids = L.index.search(q, k)
    ids = ids[0]
    scores = scores[0]
    keep = ids >= 0
    ids, scores = ids[keep], scores[keep]
    if L.mats and len(ids):
        scores = _refine(L, q[0], ids)

    best: dict[tuple[str, str], tuple[float, int]] = {}
    for s, i in zip(scores, ids):
        if s <= 0:
            continue
        key = (_doc_id(L, int(i)), L.meta["sources"][int(L.source_id[i])])
        cur = best.get(key)
        if cur is None or s > cur[0]:
            best[key] = (float(s), int(L.chunk_index[i]))
    if not best:
        return []

    # Baslik/durum sorgusu belge basina bir PK aramasi: 2.000 aday icin 67 GB
    # DB'de soguk rastgele okuma ~5 s olculdu (5 Eyl 2026). Once skora gore
    # sirala, yalniz ilk N belge icin metadata cek; filtre varsa N genis tutulur
    # (filtre metadata uzerinden calisir, sonradan elenecek).
    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
    top_n = max(limit * 40, 1000) if filters else max(limit * 10, 200)
    # En iyi parcanin metni alinti olur: kullanici sonucun NEDEN eslestigini
    # gorur (sozluksel aramadaki snippet'in karsiligi). Yalniz ilk `snippet_n`
    # belge icin full_text okunur (belge basina bir PK okumasi + parcalama).
    snippet_n = max(limit * 2, 10)
    out: list[dict[str, Any]] = []
    for rank, ((doc_id, source), (score, cix)) in enumerate(ranked[:top_n]):
        cols = "title, content_status, full_text" if rank < snippet_n else \
            "title, content_status, NULL AS full_text"
        try:
            row = db.execute(
                f"SELECT {cols} FROM documents_v2 WHERE document_id=? AND source=?",
                (doc_id, source),
            ).fetchone()
        except sqlite3.OperationalError:  # full_text sutunu olmayan sema (test)
            row = db.execute(
                "SELECT title, content_status, NULL AS full_text FROM documents_v2 "
                "WHERE document_id=? AND source=?",
                (doc_id, source),
            ).fetchone()
        entry: dict[str, Any] = {
            "document_id": doc_id, "source": source,
            "title": (row["title"] if row else "") or "",
            "score": round(min(score, 1.0), 6),
            "content_status": (row["content_status"] if row else None) or "unknown",
            "best_chunk": cix,
        }
        text = row["full_text"] if row else None
        if text:
            snippet = _best_chunk_text(text, cix)
            if snippet:
                entry["snippet"] = snippet  # related_quotes'u sunucu bundan uretir
        out.append(entry)
    if filters:
        from .semantic import _apply_filters
        out = _apply_filters(out, filters)
    return out


def bulk_index_status(db_path: Path, provider_id: str) -> dict[str, Any]:
    p = bulk_paths(db_path, provider_id)
    if not p["meta"].exists():
        return {"exists": False}
    meta = json.loads(p["meta"].read_text(encoding="utf-8"))
    meta.pop("uuids", None)
    meta["exists"] = True
    meta["size_mb"] = round(p["index"].stat().st_size / 2**20, 1) if p["index"].exists() else None
    return meta
