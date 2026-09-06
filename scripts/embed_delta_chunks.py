"""Aylık birleştirme, 1. aşama (torch/CUDA venv'i: D:\emsal-bench\venv).

Günlük crawl'ın delta tablosunda (embedding_vectors, belge başına tek vektör)
biriken kararları toplu indeksle aynı yöntemle — parçalı, multilingual-e5-small
fp16 — gömer ve toplu indekse eklenecek bir sidecar yazar:

    <vec_dir>\delta-YYYYMMDD.vectors.npy    float16 (N, 384)
    <vec_dir>\delta-YYYYMMDD.keys.parquet   document_id, source, chunk_index, text_len
    <vec_dir>\delta-YYYYMMDD.manifest.json  gömülen (document_id, source) listesi

2. aşama (faiss venv'i): `emsal-mcp semantic bulk-append <vec_dir> delta-YYYYMMDD`,
sonra manifest'teki kararların delta satırları silinir (scripts/monthly_merge.cmd).
"""
from __future__ import annotations

import argparse
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
from emsal_mcp.chunking import CHUNKING_VERSION, chunk_text  # noqa: E402  (bağımsız modül, torch venv'inde de çalışır)

MODEL = "intfloat/multilingual-e5-small"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("EMSAL_CACHE_PATH", r"D:\emsal-data\cache.sqlite3"))
    ap.add_argument("--vec-dir", default=os.environ.get("EMSAL_BULK_VEC_DIR", r"D:\emsal-bench\vec"))
    ap.add_argument("--provider", default="fastembed-multilingual-e5")
    ap.add_argument("--name", default=time.strftime("delta-%Y%m%d"))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--model-cache", default=r"D:\emsal-bench\models")
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    vec_dir = Path(args.vec_dir)
    out_v = vec_dir / f"{args.name}.vectors.npy"
    if out_v.exists():
        print(f"{out_v} zaten var; --name ile farklı ad ver"); sys.exit(2)

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    # embedding_vectors parça başına satır tutabilir (chunk_index PK'da); belge
    # başına TEK satır al, yoksa aynı karar chunk sayısı kadar gömülür.
    q = ("SELECT d.document_id, d.source, d.full_text, d.markdown FROM documents_v2 d "
         "WHERE (d.document_id, d.source) IN (SELECT DISTINCT document_id, source "
         "FROM embedding_vectors WHERE provider_id = ?) ORDER BY d.rowid")
    if args.limit:
        q += f" LIMIT {int(args.limit)}"
    rows = db.execute(q, (args.provider,)).fetchall()
    print(f"delta karar: {len(rows)}", flush=True)

    # Toplu indekste ZATEN olan kararları atla (desktop'tan gelen eski delta
    # vektörlerinin çoğu HF korpusundaki kararlara ait; kopya eklemek israf).
    # Anahtar kodlaması bulk_index ile aynı: sayısal id → int, diğerleri → uuid listesi.
    import json as _json
    import re as _re
    safe = _re.sub(r"[^A-Za-z0-9_.-]", "_", args.provider)
    stem = Path(args.db).parent / f"bulk-{safe}"
    keys_p, meta_p = stem.with_suffix(".keys.npz"), stem.with_suffix(".meta.json")
    in_index: set[tuple[int, int]] = set()
    sources = ["bedesten", "aym"]
    # Delta sidecar MEVCUT indekse eklenir; parçalama sürümü indeksinkiyle
    # aynı olmalı, yoksa chunk_index değerleri (dolayısıyla alıntılar) kayar.
    chunk_ver = CHUNKING_VERSION
    if keys_p.exists() and meta_p.exists():
        meta = _json.loads(meta_p.read_text(encoding="utf-8"))
        chunk_ver = int(meta.get("chunking_version", 1))
        sources = meta.get("sources", sources)
        uuid_pos = {u: i for i, u in enumerate(meta.get("uuids", []))}
        with np.load(keys_p) as kz:
            dn = kz["doc_num"]; sid = kz["source_id"]
        pairs = np.unique(np.stack([dn, sid.astype(np.int64)], axis=1), axis=0)
        in_index = {(int(a), int(b)) for a, b in pairs}
        del dn, sid, pairs
        def _key(did: str, src: str) -> tuple[int, int] | None:
            if src not in sources:
                return None
            if did.isdigit() and len(did) < 19:
                n = int(did)
            else:
                j = uuid_pos.get(did)
                if j is None:
                    return None
                n = -(j + 1)
            return (n, sources.index(src))
        before = len(rows)
        rows = [r for r in rows if _key(r["document_id"], r["source"]) not in in_index]
        print(f"indekste zaten olan atlandı: {before - len(rows)}, gömülecek karar: {len(rows)}", flush=True)
        del in_index
    if not rows:
        sys.exit(3)

    import torch
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL, device=args.device, cache_folder=args.model_cache,
                                model_kwargs={"torch_dtype": torch.float16})
    model.max_seq_length = 512

    # Akışlı: metinler tek tek okunur, parçalar 8k'lık bloklarla gömülür; tek
    # belge 2 MB'ı aşarsa atlanır (bozuk/çöp metin, MemoryError'a yol açıyordu).
    MAX_TEXT = 2_000_000
    ids, srcs, cix, tlen, manifest = [], [], [], [], []
    vec_parts: list[np.ndarray] = []
    pending: list[str] = []
    t0 = time.time()

    def flush() -> None:
        if pending:
            v = model.encode(pending, batch_size=args.batch, normalize_embeddings=True,
                             show_progress_bar=False, convert_to_numpy=True)
            vec_parts.append(np.asarray(v, dtype=np.float16))
            pending.clear()

    skipped = 0
    for r in rows:
        text = r["full_text"] or r["markdown"] or ""
        if len(text) < 50:
            continue
        if len(text) > MAX_TEXT:
            skipped += 1
            continue
        manifest.append([r["document_id"], r["source"]])
        for i, ch in enumerate(chunk_text(text, version=chunk_ver)):
            pending.append("passage: " + ch)
            ids.append(r["document_id"]); srcs.append(r["source"]); cix.append(i); tlen.append(len(text))
        if len(pending) >= 8192:
            flush()
            print(f"  {len(ids)} parça, {len(manifest)} karar, {len(ids)/max(time.time()-t0,1e-9):.0f} parça/sn", flush=True)
    flush()
    del rows
    if not ids:
        print("gömülecek parça yok"); sys.exit(3)
    vecs = np.concatenate(vec_parts)
    print(f"parça: {len(ids)} ({len(manifest)} karar, {skipped} çok uzun atlandı), gömme {time.time()-t0:.0f} s", flush=True)

    tmp = vec_dir / f"{args.name}.vectors.tmp.npy"
    np.save(tmp, vecs); os.replace(tmp, out_v)
    pq.write_table(pa.table({
        "document_id": pa.array(ids, pa.string()), "source": pa.array(srcs, pa.string()),
        "chunk_index": pa.array(cix, pa.int16()), "text_len": pa.array(tlen, pa.int32()),
    }), vec_dir / f"{args.name}.keys.parquet", compression="zstd")
    (vec_dir / f"{args.name}.manifest.json").write_text(json.dumps(
        {"docs": manifest, "chunks": len(ids), "provider": args.provider, "model": MODEL,
         "chunking_version": chunk_ver,
         "at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False), encoding="utf-8")
    print(f"yazıldı: {out_v} ({vecs.nbytes/2**20:.0f} MB)")


if __name__ == "__main__":
    main()
