"""emsal_mcp.legislation_semantic — mevzuat maddeleri için semantik indeks (Faz 2c).

Neden var
---------
``legislation_corpus.search_madde`` FTS5/BM25, yani kelimeler AND: "tahliye
taahhüdü" TBK m.352'yi bulamıyor (madde metninde bu ifade geçmiyor, "yazılı
olarak kiralananı belli bir tarihte boşaltmayı üstlendiği hâlde" geçiyor),
"idari para cezasına itiraz süresi" Kabahatler Kanunu m.27'yi kaçırıyor.  Bu
modül aynı maddeleri yoğun vektörle aratır ve ikisini RRF ile birleştirir.

İçtihat tarafındaki ``bulk_index`` ile aynı iki aşamalı kalıp: gömme torch
venv'inde ayrı süreçte (``scripts/embed_mevzuat_madde.py``), indeks kurulumu
burada faiss venv'inde.  Fark: madde sayısı küçük (37 bin madde ≈ 45 bin parça,
gecelik çekimle birkaç yüz bine çıkar), o yüzden IVF-PQ + refine gereksiz —
``IndexFlatIP`` ile TAM arama yapılır, gecikme milisaniye mertebesinde ve
recall 1,0'dır.

Dosyalar (cache.sqlite3'ün yanında)::

    mevzuat-<provider>.faiss        IndexFlatIP (float32, N×384)
    mevzuat-<provider>.keys.npz     mev_idx int32, sira int32, chunk_index int16
    mevzuat-<provider>.meta.json    mevzuat_id sözlüğü, sayımlar, kaynak sidecar'lar

Parça → madde tekilleştirmesi ``search`` içinde: aynı maddenin birden çok
parçası dönerse en yüksek skor tutulur.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_PROVIDER = "fastembed-multilingual-e5"

#: Sorgu tarafı önek — gömme betiği "passage: " kullanıyor; e5 ailesinde
#: asimetrik arama için sorgu "query: " ile öneklenir.  Sunucudaki fastembed
#: sağlayıcısı ``embed_query`` içinde bu öneki kendisi ekler.
QUERY_PREFIX = "query: "

#: Metin özeti uzunluğu (sonuçta maddenin ilk N karakteri gösterilir).
SNIPPET_CHARS = 400


def _stem(db_path: Path, provider_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", provider_id)
    return Path(db_path).parent / f"mevzuat-{safe}"


def index_paths(db_path: Path, provider_id: str = DEFAULT_PROVIDER) -> dict[str, Path]:
    s = _stem(Path(db_path), provider_id)
    return {
        "index": s.with_suffix(".faiss"),
        "keys": s.with_suffix(".keys.npz"),
        "meta": s.with_suffix(".meta.json"),
    }


def index_exists(db_path: Path, provider_id: str = DEFAULT_PROVIDER) -> bool:
    p = index_paths(db_path, provider_id)
    return all(x.exists() for x in p.values())


# ---------------------------------------------------------------------------
# Kurulum
# ---------------------------------------------------------------------------

def _iter_sidecars(vec_dir: Path) -> list[tuple[Path, Path]]:
    """Sidecar çiftleri, ESKİDEN YENİYE (mtime) sıralı.

    Sıra önemli: aynı maddenin birden çok sidecar'daki satırlarından SONUNCUSU
    kazanır.  Ada göre sıralama tuzaklı ("mevzuat-20260905-b" ada göre
    "mevzuat-20260905"ten ÖNCE gelir, '-' < '.'), o yüzden dosya zamanı.
    """
    out: list[tuple[Path, Path]] = []
    for v in glob.glob(str(Path(vec_dir) / "*.vectors.npy")):
        k = Path(v[: -len(".vectors.npy")] + ".keys.parquet")
        if k.exists():
            out.append((Path(v), k))
    out.sort(key=lambda vk: (vk[0].stat().st_mtime, vk[0].name))
    return out


def build_index(
    vec_dir: Path,
    db_path: Path,
    provider_id: str = DEFAULT_PROVIDER,
    *,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """``vec_dir`` içindeki tüm sidecar'lardan tam (flat) indeksi yeniden kur.

    Artımlı gömme birden çok sidecar bırakır; aynı maddenin (mevzuat_id, sira)
    birden fazla sidecar'da bulunması metnin değiştiği anlamına gelir — EN YENİ
    sidecar (dosya zamanına göre) kazanır, eskiler indekse alınmaz.

    Flat indeks kurulumu tamamen G/Ç sınırlı: yeniden kurmak saniyeler sürer,
    o yüzden "append" karmaşıklığına gerek yok.
    """
    import faiss
    import numpy as np
    import pyarrow.parquet as pq

    files = _iter_sidecars(Path(vec_dir))
    if not files:
        return {"ok": False, "error": f"{vec_dir} içinde *.vectors.npy yok"}

    t0 = time.time()
    mid_all: list[Any] = []
    sira_all: list[Any] = []
    cix_all: list[Any] = []
    file_ix: list[Any] = []
    shapes = []
    for fi, (v, k) in enumerate(files):
        tbl = pq.read_table(k, columns=["mevzuat_id", "sira", "chunk_index"])
        n = tbl.num_rows
        vshape = np.load(v, mmap_mode="r").shape
        if vshape[0] != n:
            return {"ok": False, "error": f"{v.name}: {vshape[0]} vektör, {n} anahtar — uyumsuz"}
        shapes.append(vshape)
        mid_all.append(np.asarray(tbl.column("mevzuat_id").to_pylist(), dtype=object))
        sira_all.append(tbl.column("sira").to_numpy().astype(np.int32))
        cix_all.append(tbl.column("chunk_index").to_numpy().astype(np.int16))
        file_ix.append(np.full(n, fi, dtype=np.int32))
    mids = np.concatenate(mid_all)
    siras = np.concatenate(sira_all)
    cixs = np.concatenate(cix_all)
    fixs = np.concatenate(file_ix)
    dim = shapes[0][1]
    total = len(mids)
    log(f"{len(files)} sidecar, {total:,} parça, dim={dim}")

    # --- eskimiş sidecar satırlarını ele ------------------------------------
    uniq_ids, mev_idx = np.unique(mids, return_inverse=True)
    mev_idx = mev_idx.astype(np.int64)
    madde_key = mev_idx * 1_000_000 + siras.astype(np.int64)
    son: dict[int, int] = {}
    for kk, ff in zip(madde_key.tolist(), fixs.tolist()):
        if son.get(kk, -1) < ff:
            son[kk] = ff
    keep = np.fromiter(
        (son[kk] == ff for kk, ff in zip(madde_key.tolist(), fixs.tolist())),
        dtype=bool, count=total,
    )
    atilan = int(total - keep.sum())
    if atilan:
        log(f"eskimiş sidecar satırı atlandı: {atilan:,}")

    # --- vektörler ----------------------------------------------------------
    index = faiss.IndexFlatIP(dim)
    off = 0
    for (v, _), s in zip(files, shapes):
        blok = np.asarray(np.load(v, mmap_mode="r"), dtype=np.float32)
        m = keep[off : off + s[0]]
        off += s[0]
        blok = blok[m]
        if not len(blok):
            continue
        faiss.normalize_L2(blok)
        index.add(blok)
        del blok
    log(f"indeks: {index.ntotal:,} vektör, {time.time()-t0:.1f} s")

    p = index_paths(Path(db_path), provider_id)
    tmp = p["index"].with_suffix(".faiss.tmp")
    faiss.write_index(index, str(tmp))
    os.replace(tmp, p["index"])
    np.savez(
        p["keys"],
        mev_idx=mev_idx[keep].astype(np.int32),
        sira=siras[keep],
        chunk_index=cixs[keep],
    )
    p["meta"].write_text(json.dumps({
        "provider": provider_id,
        "dim": int(dim),
        "vektor": int(index.ntotal),
        "madde": int(len(son)),
        "mevzuat_ids": [str(x) for x in uniq_ids],
        "sidecars": [v.name for v, _ in files],
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False), encoding="utf-8")
    _CACHE.clear()
    return {
        "ok": True,
        "vektor": int(index.ntotal),
        "madde": int(len(son)),
        "sidecar": len(files),
        "atilan_eski": atilan,
        "sure_sn": round(time.time() - t0, 1),
        "index": str(p["index"]),
        "boyut_mb": round(p["index"].stat().st_size / 2**20, 1),
    }


# ---------------------------------------------------------------------------
# Süreç içi önbellek
# ---------------------------------------------------------------------------

class _Loaded:
    __slots__ = ("index", "mev_idx", "sira", "chunk_index", "meta", "mtime", "ids")

    # faiss/numpy nesneleri lazy import edildigi icin Any; alanlar _load'da dolar.
    index: Any
    mev_idx: Any
    sira: Any
    chunk_index: Any
    meta: dict[str, Any]
    mtime: float
    ids: Any


_CACHE: dict[str, _Loaded] = {}


def _load(db_path: Path, provider_id: str) -> _Loaded | None:
    import faiss
    import numpy as np

    p = index_paths(Path(db_path), provider_id)
    if not all(x.exists() for x in p.values()):
        return None
    key = str(p["index"])
    mtime = p["index"].stat().st_mtime
    hit = _CACHE.get(key)
    if hit is not None and hit.mtime == mtime:
        return hit
    L = _Loaded()
    L.mtime = mtime
    L.index = faiss.read_index(str(p["index"]))
    with np.load(p["keys"]) as z:
        L.mev_idx = z["mev_idx"]
        L.sira = z["sira"]
        L.chunk_index = z["chunk_index"]
    L.meta = json.loads(p["meta"].read_text(encoding="utf-8"))
    L.ids = L.meta.get("mevzuat_ids", [])
    _CACHE[key] = L
    return L


def index_status(db_path: Path, provider_id: str = DEFAULT_PROVIDER) -> dict[str, Any]:
    """İndeks var mı, kaç vektör, ne zaman kuruldu."""
    L = _load(Path(db_path), provider_id)
    if L is None:
        return {"ok": False, "var": False, "provider": provider_id}
    return {
        "ok": True, "var": True, "provider": provider_id,
        "vektor": int(L.index.ntotal), "madde": L.meta.get("madde"),
        "built_at": L.meta.get("built_at"), "sidecar": len(L.meta.get("sidecars", [])),
    }


# ---------------------------------------------------------------------------
# Arama
# ---------------------------------------------------------------------------

def _mevzuat_id_filter(db: Any, mevzuat_no: str) -> set[str]:
    rows = db.execute(
        "SELECT mevzuat_id FROM mevzuat_dokuman WHERE mevzuat_no = ?",
        (str(mevzuat_no).strip(),),
    ).fetchall()
    return {r[0] for r in rows}


def search(
    db: Any,
    db_path: Path,
    q_vec: list[float],
    *,
    limit: int = 20,
    mevzuat_no: str | None = None,
    provider_id: str = DEFAULT_PROVIDER,
) -> list[dict[str, Any]] | None:
    """Semantik madde araması; madde bazında tekilleştirilmiş, skora göre sıralı.

    İndeks yoksa ``None`` döner (çağıran sözlüksel aramaya düşer).
    """
    import numpy as np

    L = _load(Path(db_path), provider_id)
    if L is None:
        return None
    limit = max(1, int(limit))

    q = np.asarray([q_vec], dtype=np.float32)
    nrm = float(np.linalg.norm(q))
    if nrm > 0:
        q = q / nrm

    sel_pos = None
    if mevzuat_no is not None and str(mevzuat_no).strip():
        hedef = _mevzuat_id_filter(db, mevzuat_no)
        if not hedef:
            return []
        wanted = np.array(
            [i for i, mid in enumerate(L.ids) if mid in hedef], dtype=np.int64
        )
        if not len(wanted):
            return []
        sel_pos = np.nonzero(np.isin(L.mev_idx, wanted))[0]
        if not len(sel_pos):
            return []

    if sel_pos is not None:
        # Alt küme küçük: doğrudan alt matriste tam arama (faiss IDSelector'a
        # sürüm bağımlılığı yok, sonuç birebir aynı).
        sub = np.vstack([L.index.reconstruct(int(i)) for i in sel_pos])
        scores = (sub @ q[0]).astype(np.float32)
        k = min(limit * 20, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        ids = sel_pos[top]
        sc = scores[top]
    else:
        k = min(max(limit * 20, 200), L.index.ntotal)
        sc_arr, id_arr = L.index.search(q, k)
        ids = id_arr[0]
        sc = sc_arr[0]
        m = ids >= 0
        ids, sc = ids[m], sc[m]

    # --- parça → madde tekilleştirme ---------------------------------------
    best: dict[tuple[str, int], tuple[float, int]] = {}
    for s, i in zip(sc.tolist(), ids.tolist()):
        key = (L.ids[int(L.mev_idx[i])], int(L.sira[i]))
        cur = best.get(key)
        if cur is None or s > cur[0]:
            best[key] = (float(s), int(L.chunk_index[i]))
    if not best:
        return []
    # Katlama payı: aynı tebliğin 20 yılı üst sıraları doldurabiliyor
    # (bkz. legislation_corpus.surum_katla). Katlama sonrası limit'e inilir.
    ic_limit = limit if mevzuat_no else min(max(limit * 3, limit + 40), 300)
    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:ic_limit]

    out: list[dict[str, Any]] = []
    for (mid, sira), (score, cix) in ranked:
        row = db.execute(
            """SELECT d.mevzuat_no, d.tur, d.ad, d.kaynak_url,
                      m.madde_no, m.baslik, m.metin, m.degisiklik_notu
               FROM mevzuat_madde m JOIN mevzuat_dokuman d
                 ON d.mevzuat_id = m.mevzuat_id
               WHERE m.mevzuat_id = ? AND m.sira = ?""",
            (mid, sira),
        ).fetchone()
        if row is None:
            continue  # madde silinmiş (indeks eskimiş) — sessizce atla
        metin = (row[6] or "").strip()
        out.append({
            "mevzuat_id": mid,
            "mevzuat_no": row[0],
            "tur": row[1],
            "mevzuat_adi": row[2],
            "kaynak_url": row[3],
            "madde_no": row[4],
            "sira": sira,
            "baslik": row[5],
            "degisiklik_notu": row[7],
            "snippet": metin[:SNIPPET_CHARS] + (" …" if len(metin) > SNIPPET_CHARS else ""),
            "skor": round(float(score), 4),
            "best_chunk": cix,
        })
    if mevzuat_no:
        # Kullanıcı tek mevzuat seçti (yılı bilerek seçmiş olabilir) — katlama yok.
        return out[:limit]
    from .legislation_corpus import surum_katla

    return surum_katla(db, out, limit=limit)


# ---------------------------------------------------------------------------
# Melez (RRF)
# ---------------------------------------------------------------------------

RRF_K = 60


def rrf_merge(
    lexical: list[dict[str, Any]],
    semantic: list[dict[str, Any]],
    *,
    limit: int = 20,
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    """İki sıralamayı Reciprocal Rank Fusion ile birleştir.

    Skorlar karşılaştırılabilir değil (BM25 negatif ve ölçeksiz, kosinüs
    0-1), o yüzden yalnız SIRALAR kullanılır: ``skor = Σ 1/(k + sıra)``.
    Anahtar (mevzuat_id, madde_no) — aynı madde iki listede de varsa iki
    katkı alır, bu da RRF'nin istenen davranışıdır.
    """
    puan: dict[tuple[Any, Any], float] = {}
    kayit: dict[tuple[Any, Any], dict[str, Any]] = {}
    siralar: dict[tuple[Any, Any], dict[str, int]] = {}
    for ad, liste in (("lexical", lexical), ("semantic", semantic)):
        for i, r in enumerate(liste or []):
            key = (r.get("mevzuat_id"), r.get("madde_no"))
            puan[key] = puan.get(key, 0.0) + 1.0 / (k + i + 1)
            siralar.setdefault(key, {})[ad] = i + 1
            # Semantik kayıt tam metin özeti taşır; sözlüksel snippet eşleşen
            # yeri gösterir. İkisi de varsa sözlükselin snippet'i korunur.
            if key not in kayit:
                kayit[key] = dict(r)
            elif ad == "lexical":
                merged = dict(r)
                merged.setdefault("best_chunk", kayit[key].get("best_chunk"))
                kayit[key] = merged
    out: list[dict[str, Any]] = []
    for key in sorted(puan, key=lambda x: puan[x], reverse=True)[: max(1, int(limit))]:
        r = dict(kayit[key])
        r["rrf_skor"] = round(puan[key], 6)
        r["siralar"] = siralar[key]
        out.append(r)
    return out


def embed_query(text: str, provider_id: str = DEFAULT_PROVIDER) -> list[float] | None:
    """Sorgu vektörü (fastembed ONNX; faiss ile aynı süreçte sorun yok).

    Sağlayıcı yoksa/yüklenemiyorsa None — çağıran sözlüksel aramaya düşer.
    """
    from .embeddings import get_embedding_provider

    prov = get_embedding_provider(provider_id, strict=True)
    if prov is None:
        return None
    try:
        return list(prov.embed_query(text))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — sağlayıcı hatası aramayı düşürmemeli
        return None
