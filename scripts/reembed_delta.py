"""Yeniden gömme, 2. aşama: parquet DIŞINDAKİ kararları vec2'ye göm (torch/CUDA venv'i).

Toplu indeks iki tür sidecar'dan oluşur: HF parquet dosyaları
(``embed_parquet_worker.py``) ve delta sidecar'ları (``embed_delta_chunks.py``
— uyap_arsiv, crawl'dan gelen bedesten kararları, mevzuat).  Parçalama
düzeltmesinden sonra ikincisi de yeniden gömülmeli, yoksa yeni indekste
o kararların ``chunk_index`` değerleri eski (hatalı) parçalamaya göre kalır.

Gömülecek kümenin kaynağı iki yerdir:
  1. ESKİ vektör dizinindeki ``*.manifest.json`` dosyalarının ``docs`` listesi
     (indekste olan, delta tablosundan silinmiş kararlar),
  2. şu an ``embedding_vectors`` tablosunda duran kararlar (henüz indekse
     girmemiş crawl deltası) — bunlar delta olarak kalmaya devam eder,
     yeniden gömülmeleri zarar vermez, indekste de bulunmuş olurlar.

Çıktı ``embed_delta_chunks.py`` ile aynı biçimdedir (``source`` sütunlu
keys.parquet + manifest), böylece ``bulk_index.build_bulk_index`` doğrudan
okuyabilir.

    D:\\emsal-bench\\venv\\Scripts\\python.exe -X utf8 scripts\\reembed_delta.py ^
        --old-vec D:\\emsal-bench\\vec --out D:\\emsal-bench\\vec2 --name delta-reembed-20260907
"""
from __future__ import annotations

import argparse
import glob
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
from emsal_mcp.chunking import CHUNKING_VERSION, chunk_text  # noqa: E402

MODEL = "intfloat/multilingual-e5-small"
MAX_TEXT = 2_000_000  # tek belge bunu aşarsa atlanır (bozuk metin; MemoryError)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("EMSAL_CACHE_PATH", r"D:\emsal-data\cache.sqlite3"))
    ap.add_argument("--old-vec", default=r"D:\emsal-bench\vec", help="manifest'lerin okunacağı ESKİ dizin")
    ap.add_argument("--out", default=r"D:\emsal-bench\vec2")
    ap.add_argument("--provider", default="fastembed-multilingual-e5")
    ap.add_argument("--name", default=time.strftime("delta-reembed-%Y%m%d"))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--model-cache", default=r"D:\emsal-bench\models")
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_v = out_dir / f"{args.name}.vectors.npy"
    if out_v.exists():
        print(f"{out_v} zaten var, atlandı (resumable)")
        return

    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mf in sorted(glob.glob(str(Path(args.old_vec) / "*.manifest.json"))):
        m = json.loads(Path(mf).read_text(encoding="utf-8"))
        n0 = len(keys)
        for did, src in m.get("docs", []):
            if (did, src) not in seen:
                seen.add((did, src))
                keys.append((did, src))
        print(f"{Path(mf).name}: +{len(keys)-n0} karar", flush=True)

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=300)
    db.row_factory = sqlite3.Row
    n0 = len(keys)
    for r in db.execute("SELECT DISTINCT document_id, source FROM embedding_vectors WHERE provider_id=?",
                        (args.provider,)):
        k = (r["document_id"], r["source"])
        if k not in seen:
            seen.add(k)
            keys.append(k)
    print(f"embedding_vectors deltası: +{len(keys)-n0} karar; toplam {len(keys)} karar", flush=True)
    if args.limit:
        keys = keys[: args.limit]
    if not keys:
        print("gömülecek karar yok")
        sys.exit(3)

    import torch
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL, device=args.device, cache_folder=args.model_cache,
                                model_kwargs={"torch_dtype": torch.float16})
    model.max_seq_length = 512

    ids: list[str] = []
    srcs: list[str] = []
    cix: list[int] = []
    tlen: list[int] = []
    manifest: list[list[str]] = []
    vec_parts: list[np.ndarray] = []
    pending: list[str] = []
    t0 = time.time()
    skipped = missing = 0

    def flush() -> None:
        if pending:
            v = model.encode(pending, batch_size=args.batch, normalize_embeddings=True,
                             show_progress_bar=False, convert_to_numpy=True)
            vec_parts.append(np.asarray(v, dtype=np.float16))
            pending.clear()

    sel = ("SELECT full_text, markdown FROM documents_v2 WHERE document_id=? AND source=?")
    for did, src in keys:
        row = db.execute(sel, (did, src)).fetchone()
        if row is None:
            missing += 1
            continue
        text = row["full_text"] or row["markdown"] or ""
        if len(text) < 50:
            continue
        if len(text) > MAX_TEXT:
            skipped += 1
            continue
        manifest.append([did, src])
        for i, ch in enumerate(chunk_text(text)):
            pending.append("passage: " + ch)
            ids.append(did)
            srcs.append(src)
            cix.append(i)
            tlen.append(len(text))
        if len(pending) >= 8192:
            flush()
            el = max(time.time() - t0, 1e-9)
            print(f"  {len(manifest):,} karar, {len(ids):,} parça, {len(ids)/el:.0f} parça/sn", flush=True)
    flush()
    if not ids:
        print("gömülecek parça yok")
        sys.exit(3)

    vecs = np.concatenate(vec_parts)
    print(f"parça: {len(ids):,} ({len(manifest):,} karar, {skipped} çok uzun, {missing} bulunamadı), "
          f"{time.time()-t0:.0f} s", flush=True)

    tmp = out_dir / f"{args.name}.vectors.tmp.npy"
    np.save(tmp, vecs)
    os.replace(tmp, out_v)
    pq.write_table(pa.table({
        "document_id": pa.array(ids, pa.string()), "source": pa.array(srcs, pa.string()),
        "chunk_index": pa.array(cix, pa.int16()), "text_len": pa.array(tlen, pa.int32()),
    }), out_dir / f"{args.name}.keys.parquet", compression="zstd")
    (out_dir / f"{args.name}.manifest.json").write_text(json.dumps(
        {"docs": manifest, "chunks": len(ids), "provider": args.provider, "model": MODEL,
         "chunking_version": CHUNKING_VERSION, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "note": "parçalama düzeltmesi sonrası yeniden gömme"}, ensure_ascii=False), encoding="utf-8")
    print(f"yazıldı: {out_v} ({vecs.nbytes/2**20:.0f} MB)")


if __name__ == "__main__":
    main()
