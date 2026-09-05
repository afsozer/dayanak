"""Mevzuat semantik indeksi, 2. aşama (faiss venv'i: D:\\Emsal-mcp\\.venv).

``scripts/embed_mevzuat_madde.py``ın yazdığı sidecar'lardan
``mevzuat-<provider>.faiss`` (IndexFlatIP) indeksini yeniden kurar.  torch ile
faiss aynı süreçte çöktüğü için gömme ve kurulum ayrı süreçlerde; ikisini
ardışık koşturan sarmalayıcı ``scripts/mevzuat_semantic.cmd``.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from emsal_mcp.legislation_semantic import DEFAULT_PROVIDER, build_index

_VARSAYILAN_DB = r"D:\emsal-data\cache.sqlite3"
_VARSAYILAN_VEC = r"D:\emsal-data\mevzuat-vec"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db",
                    default=os.environ.get("EMSAL_CACHE_PATH", _VARSAYILAN_DB))
    ap.add_argument("--vec-dir",
                    default=os.environ.get("EMSAL_MEVZUAT_VEC_DIR", _VARSAYILAN_VEC))
    ap.add_argument("--provider", default=DEFAULT_PROVIDER)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    out = build_index(Path(args.vec_dir), Path(args.db), args.provider)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        for k, v in out.items():
            print(f"{k}: {v}")
    raise SystemExit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
