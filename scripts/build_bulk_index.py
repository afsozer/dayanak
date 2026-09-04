"""embed_parquet_worker.py çıktısından FAISS IVF-PQ toplu indeks kur.

    python scripts/build_bulk_index.py --vec ~/Developer/emsal-mcp-data/vec \
        --cache ~/Developer/emsal-mcp-data/cache.sqlite3 [--max-files 3] [--nlist 16384] [--pq-m 64]

Çıktı cache.sqlite3'ün yanına: bulk-fastembed-multilingual-e5.{faiss,keys.npz,meta.json}
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from emsal_mcp.bulk_index import build_bulk_index  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vec", required=True)
    default_cache = os.environ.get("EMSAL_CACHE_PATH") or str(
        Path.home() / ".emsal-mcp" / "cache.sqlite3"
    )
    ap.add_argument("--cache", default=default_cache)
    ap.add_argument("--provider", default="fastembed-multilingual-e5")
    ap.add_argument("--nlist", type=int, default=16384)
    ap.add_argument("--pq-m", type=int, default=64)
    ap.add_argument("--train-sample", type=int, default=1_000_000)
    ap.add_argument("--max-files", type=int, default=0)
    args = ap.parse_args()

    def log(m: str) -> None:
        print(time.strftime("%H:%M:%S ") + m, flush=True)

    r = build_bulk_index(Path(os.path.expanduser(args.vec)), Path(os.path.expanduser(args.cache)),
                         args.provider, nlist=args.nlist, pq_m=args.pq_m,
                         train_sample=args.train_sample, max_files=args.max_files, log=log)
    print(r)


if __name__ == "__main__":
    main()
