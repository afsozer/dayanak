"""HF parquet karar dosyalarını parçalayıp multilingual-e5-small ile gömer; vektörleri
dosya başına sidecar olarak yazar (SQLite'a dokunmaz — birleştirme ayrı adım).

Her girdi parquet dosyası için çıktı dizinine:
    <ad>.vectors.npy   float16 (N, 384), L2-normalize edilmiş
    <ad>.keys.parquet  document_id (string), chunk_index (int16), text_len (int32)
    <ad>.done.json     sayılar + süre
Tamamlanmış dosyalar (done.json varsa) atlanır → kaldığı yerden devam eder.

Parçalama emsal_mcp.chunking.chunk_text ile (1600/200, CHUNKING_VERSION) — Mac ve laptop
aynı kodu koşar. done.json'a yazılan ``chunking_version`` sidecar'ın hangi parçalayıcıyla
üretildiğini söyler; bulk_index bunu meta'ya taşır ve karışık sürümlü dizini reddeder.
Metin filtresi import_hf_parquet.py ile aynı: len(text) >= 50.

Kullanım (laptop, CUDA):
    python embed_parquet_worker.py \
        --files "D:/hf-datasets/turkish-court-decisions/data/yargitay/*.parquet" \
        --out D:/emsal-bench/vec --device cuda
Kullanım (Mac, MPS):
    python scripts/embed_parquet_worker.py \
        --files "~/Developer/emsal-mcp-data/hf/emsal/*.parquet" \
        --out ~/Developer/emsal-mcp-data/vec --device mps
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
for cand in (HERE.parent / "src", HERE):
    if (cand / "emsal_mcp" / "chunking.py").exists() or (cand / "chunking.py").exists():
        sys.path.insert(0, str(cand))
try:
    from emsal_mcp.chunking import CHUNKING_VERSION, chunk_text
except ImportError:
    from chunking import CHUNKING_VERSION, chunk_text  # laptop kopyası: chunking.py betiğin yanında

MODEL = "intfloat/multilingual-e5-small"
DIM = 384
MAX_ROWS = 0


def load_model(device: str, cache_dir: str):
    import torch
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(MODEL, device=device, cache_folder=cache_dir,
                            model_kwargs={"torch_dtype": torch.float16})
    m.max_seq_length = 512
    return m


def process_file(path: str, out_dir: Path, model, batch: int, block: int, log) -> dict:
    stem = Path(path).stem
    src = Path(path).parent.name
    name = f"{src}-{stem}"
    done = out_dir / f"{name}.done.json"
    if done.exists():
        log(f"{name}: zaten bitmiş, atlandı")
        return json.loads(done.read_text())

    t0 = time.time()
    pf = pq.ParquetFile(path)
    n_rows = pf.metadata.num_rows
    ids: list[str] = []
    cidx: list[int] = []
    tlen: list[int] = []
    vec_parts: list[np.ndarray] = []
    pending_txt: list[str] = []
    pending_keys: list[tuple[str, int, int]] = []
    seen = 0

    def flush():
        if not pending_txt:
            return
        v = model.encode(pending_txt, batch_size=batch, normalize_embeddings=True,
                         show_progress_bar=False, convert_to_numpy=True)
        vec_parts.append(np.asarray(v, dtype=np.float16))
        for d, c, ln in pending_keys:
            ids.append(d)
            cidx.append(c)
            tlen.append(ln)
        pending_txt.clear()
        pending_keys.clear()

    for rg in range(pf.num_row_groups):
        tbl = pf.read_row_group(rg, columns=["document_id", "text"])
        for did, text in zip(tbl["document_id"].to_pylist(), tbl["text"].to_pylist()):
            if MAX_ROWS and seen >= MAX_ROWS:
                break
            seen += 1
            if not did or not text or len(text) < 50:
                continue
            for i, ch in enumerate(chunk_text(text)):
                pending_txt.append("passage: " + ch)
                pending_keys.append((did, i, len(text)))
            if len(pending_txt) >= block:
                flush()
                el = time.time() - t0
                nvec = sum(len(p) for p in vec_parts)
                log(f"{name}: satır {seen:,}/{n_rows:,} parça {nvec:,} {nvec/el:,.0f} parça/sn")
    flush()

    vectors = np.concatenate(vec_parts) if vec_parts else np.zeros((0, DIM), np.float16)
    tmp_v = out_dir / f"{name}.vectors.tmp.npy"  # np.save '.npy' ile bitmeyen ada uzantı ekler
    np.save(tmp_v, vectors)
    os.replace(tmp_v, out_dir / f"{name}.vectors.npy")
    keys = pa.table({
        "document_id": pa.array(ids, pa.string()),
        "chunk_index": pa.array(cidx, pa.int16()),
        "text_len": pa.array(tlen, pa.int32()),
    })
    tmp_k = out_dir / f"{name}.keys.parquet.tmp"
    pq.write_table(keys, tmp_k, compression="zstd")
    os.replace(tmp_k, out_dir / f"{name}.keys.parquet")
    el = time.time() - t0
    info = {"file": path, "source": src, "rows": seen, "chunks": int(len(ids)),
            "seconds": round(el, 1), "chunks_per_sec": round(len(ids) / max(el, 1e-9), 1),
            "model": MODEL, "dtype": "float16", "dim": DIM, "chunk_size": 1600, "overlap": 200,
            "chunking_version": CHUNKING_VERSION}
    done.write_text(json.dumps(info, ensure_ascii=False, indent=1))
    log(f"{name}: BİTTİ {len(ids):,} parça {el/60:.1f} dk ({info['chunks_per_sec']} parça/sn)")
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", required=True, action="append", help="glob (tekrarlanabilir)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--model-cache", default=None)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--block", type=int, default=8192,
                    help="encode çağrısı başına parça (uzunluk sıralaması bu blok içinde)")
    ap.add_argument("--max-rows", type=int, default=0,
                    help="duman testi: dosya başına en çok bu kadar satır")
    args = ap.parse_args()
    global MAX_ROWS
    MAX_ROWS = args.max_rows

    out_dir = Path(os.path.expanduser(args.out))
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted({f for g in args.files for f in glob.glob(os.path.expanduser(g))})
    if not files:
        sys.exit("dosya bulunamadı")
    logf = open(out_dir / "worker.log", "a", encoding="utf-8")

    def log(msg: str) -> None:
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    log(f"başladı: {len(files)} dosya, device={args.device}, batch={args.batch}")
    model = load_model(args.device, args.model_cache or str(out_dir / "models"))
    total = 0
    t0 = time.time()
    for f in files:
        info = process_file(f, out_dir, model, args.batch, args.block, log)
        total += info["chunks"]
    log(f"TÜMÜ BİTTİ: {total:,} parça, {(time.time()-t0)/3600:.2f} saat")


if __name__ == "__main__":
    main()
