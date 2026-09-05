"""Mevzuat maddelerini gömme, 1. aşama (torch/CUDA venv'i: D:\\emsal-bench\\venv).

Faz 2c: ``mevzuat_korpus_ara`` yalnız BM25 (kelimeler AND) çalışıyor; "tahliye
taahhüdü" TBK m.352'yi bulamıyor çünkü ifade madde metninde geçmiyor.  Bu betik
``mevzuat_madde`` tablosundaki her maddeyi (mevzuat adı + kenar başlıkları +
metin, bkz. ``madde_metni``) parçalayıp
multilingual-e5-small ile fp16 gömer ve 2. aşamanın (faiss venv'i,
``emsal_mcp.legislation_semantic.build_index``) okuyacağı bir sidecar yazar::

    <vec_dir>\\<ad>.vectors.npy    float16 (N, 384)
    <vec_dir>\\<ad>.keys.parquet   mevzuat_id, sira, chunk_index, metin_hash
    <vec_dir>\\<ad>.manifest.json  sayım + model bilgisi

ARTIMLI: ``mevzuat_madde_vektor(mevzuat_id, sira, metin_hash, sidecar, satir)``
tablosunda zaten kayıtlı (mevzuat_id, sira, metin_hash) üçlüleri atlanır.  Metin
değişirse hash değişir, madde yeniden gömülür (eski satır UPSERT ile güncellenir;
eski vektör indekste ölü kalır, tam yeniden kurulumda düşer).  Böylece gecelik
mevzuat çekimi bittikten sonra aynı betik yalnız YENİ maddeleri gömer.

torch ile faiss AYNI SÜREÇTE çöküyor: bu betik faiss'e dokunmaz, indeks kurulumu
ayrı süreçte (bkz. ``scripts/mevzuat_semantic.cmd``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, r"D:\Emsal-mcp\src")
from emsal_mcp.chunking import chunk_text  # noqa: E402  (bağımsız modül, torch venv'inde de çalışır)

MODEL = "intfloat/multilingual-e5-small"
_VARSAYILAN_DB = r"D:\emsal-data\cache.sqlite3"
_VARSAYILAN_VEC = r"D:\emsal-data\mevzuat-vec"

_VEKTOR_TABLE = """\
CREATE TABLE IF NOT EXISTS mevzuat_madde_vektor (
    mevzuat_id TEXT NOT NULL,
    sira INTEGER NOT NULL,
    metin_hash TEXT NOT NULL,
    sidecar TEXT,
    satir INTEGER,
    PRIMARY KEY (mevzuat_id, sira)
);"""


def madde_metni(
    baslik: str | None,
    metin: str | None,
    mevzuat_adi: str | None = None,
    ust_baslik: str | None = None,
) -> str:
    """Gömme birimi: BAĞLAM BAŞLIĞI + madde metni.

    Madde metni tek başına bağlamsızdır: TBK m.352 "kiralananı belli bir
    tarihte boşaltmayı yazılı olarak üstlendiği hâlde" der, ne "kira" ne
    "tahliye" ne de "Borçlar Kanunu" geçer.  Ölçüm (5 Eyl 2026, 15 sorgu):
    yalnız başlık+metin gömülünce "tahliye taahhüdü" sorgusunda m.352
    50.416 parça içinde 20.051. sıraya düşüyordu.  Mevzuat adı ve kenar
    başlığı hiyerarşisi öne eklenince madde kendi konusunu taşır.
    """
    parcalar = [x.strip() for x in (mevzuat_adi, ust_baslik, baslik) if x and x.strip()]
    m = (metin or "").strip()
    return (" > ".join(parcalar) + "\n\n" + m).strip() if parcalar else m


def metin_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db",
                    default=os.environ.get("EMSAL_CACHE_PATH", _VARSAYILAN_DB))
    ap.add_argument("--vec-dir",
                    default=os.environ.get("EMSAL_MEVZUAT_VEC_DIR", _VARSAYILAN_VEC))
    ap.add_argument("--name", default=time.strftime("mevzuat-%Y%m%d-%H%M"))
    ap.add_argument("--provider", default="fastembed-multilingual-e5")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--model-cache", default=r"D:\emsal-bench\models")
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--full", action="store_true", help="manifest'i yok say, hepsini yeniden göm")
    args = ap.parse_args()

    vec_dir = Path(args.vec_dir)
    vec_dir.mkdir(parents=True, exist_ok=True)
    out_v = vec_dir / f"{args.name}.vectors.npy"
    if out_v.exists():
        print(f"{out_v} zaten var; --name ile farklı ad ver")
        sys.exit(2)

    # Okuma ro: gecelik çekim (EmsalMevzuatPull) aynı tablolara YAZIYOR olabilir.
    ro = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=120)
    ro.row_factory = sqlite3.Row
    q = ("SELECT m.mevzuat_id, m.sira, m.baslik, m.metin, m.ust_baslik, d.ad "
         "FROM mevzuat_madde m LEFT JOIN mevzuat_dokuman d "
         "ON d.mevzuat_id = m.mevzuat_id ORDER BY m.mevzuat_id, m.sira")
    if args.limit:
        q += f" LIMIT {int(args.limit)}"
    rows = ro.execute(q).fetchall()
    print(f"korpusta madde: {len(rows)}", flush=True)

    # --- artımlı: zaten gömülü (mevzuat_id, sira, hash) üçlülerini atla -------
    gomulu: dict[tuple[str, int], str] = {}
    if not args.full:
        try:
            for r in ro.execute("SELECT mevzuat_id, sira, metin_hash FROM mevzuat_madde_vektor"):
                gomulu[(r[0], int(r[1]))] = r[2]
        except sqlite3.OperationalError:
            pass  # tablo henüz yok — ilk koşu
    ro.close()

    hedef = []
    for r in rows:
        text = madde_metni(r["baslik"], r["metin"], r["ad"], r["ust_baslik"])
        if len(text) < 20:
            continue
        h = metin_hash(text)
        if gomulu.get((r["mevzuat_id"], int(r["sira"]))) == h:
            continue
        hedef.append((r["mevzuat_id"], int(r["sira"]), h, text))
    del rows, gomulu
    print(f"gömülecek madde: {len(hedef)}", flush=True)
    if not hedef:
        print("yeni madde yok")
        sys.exit(3)

    import torch
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL, device=args.device, cache_folder=args.model_cache,
                                model_kwargs={"torch_dtype": torch.float16})
    model.max_seq_length = 512

    mids: list[str] = []
    siras: list[int] = []
    cix: list[int] = []
    hashes: list[str] = []
    vec_parts: list[np.ndarray] = []
    pending: list[str] = []
    kayit: list[tuple[str, int, str, str, int]] = []
    t0 = time.time()

    def flush() -> None:
        if pending:
            v = model.encode(pending, batch_size=args.batch, normalize_embeddings=True,
                             show_progress_bar=False, convert_to_numpy=True)
            vec_parts.append(np.asarray(v, dtype=np.float16))
            pending.clear()

    for mid, sira, h, text in hedef:
        satir = len(mids)  # bu maddenin İLK parçasının sidecar satır numarası
        for i, ch in enumerate(chunk_text(text)):
            pending.append("passage: " + ch)
            mids.append(mid)
            siras.append(sira)
            cix.append(i)
            hashes.append(h)
        kayit.append((mid, sira, h, args.name, satir))
        if len(pending) >= 8192:
            flush()
            print(f"  {len(mids)} parça, {len(kayit)} madde, "
                  f"{len(mids)/max(time.time()-t0,1e-9):.0f} parça/sn", flush=True)
    flush()
    del hedef
    if not mids:
        print("gömülecek parça yok")
        sys.exit(3)
    vecs = np.concatenate(vec_parts)
    sure = time.time() - t0
    print(f"parça: {len(mids)} ({len(kayit)} madde), gömme {sure:.0f} s "
          f"({len(mids)/max(sure,1e-9):.0f} parça/sn)", flush=True)

    tmp = vec_dir / f"{args.name}.vectors.tmp.npy"
    np.save(tmp, vecs)
    os.replace(tmp, out_v)
    pq.write_table(pa.table({
        "mevzuat_id": pa.array(mids, pa.string()),
        "sira": pa.array(siras, pa.int32()),
        "chunk_index": pa.array(cix, pa.int16()),
        "metin_hash": pa.array(hashes, pa.string()),
    }), vec_dir / f"{args.name}.keys.parquet", compression="zstd")
    (vec_dir / f"{args.name}.manifest.json").write_text(json.dumps(
        {"maddeler": len(kayit), "parcalar": len(mids), "provider": args.provider,
         "model": MODEL, "sure_sn": round(sure, 1),
         "at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False), encoding="utf-8")
    print(f"yazıldı: {out_v} ({vecs.nbytes/2**20:.1f} MB)")

    # --- manifest tablosu: tek kısa yazma işlemi (canlı DB, WAL) -------------
    rw = sqlite3.connect(args.db, timeout=180)
    rw.execute("PRAGMA busy_timeout=180000")
    rw.execute(_VEKTOR_TABLE)
    rw.executemany(
        "INSERT INTO mevzuat_madde_vektor(mevzuat_id, sira, metin_hash, sidecar, satir) "
        "VALUES (?,?,?,?,?) ON CONFLICT(mevzuat_id, sira) DO UPDATE SET "
        "metin_hash=excluded.metin_hash, sidecar=excluded.sidecar, satir=excluded.satir",
        kayit,
    )
    rw.commit()
    rw.close()
    print(f"mevzuat_madde_vektor: {len(kayit)} satır güncellendi")


if __name__ == "__main__":
    main()
