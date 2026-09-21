"""Yeniden gömme, 3. aşama: YENİ (hazırlık) indeksi geçişten ÖNCE doğrula.

Canlı indekse dokunmadan, hazırlık dizinindeki ``bulk-*.{faiss,keys.npz,meta.json}``
üzerinde şunları ölçer:

  * vektör sayısı canlı indeksin en çok %1 altında mı,
  * ``chunking_version`` beklenen sürüm mü (varsayılan 2),
  * meta.files'taki her sidecar yeni vektör dizininde var mı (refine şart),
  * örnek Türkçe sorgular sonuç döndürüyor mu, skorlar makul mü, alıntı geliyor mu.

Çıkış: 0 sağlıklı, 1 doğrulama başarısız.  ``scripts/reembed_switch.cmd``
bunu koşmadan indeksi TAKAS ETMEZ.

    .venv\\Scripts\\python.exe -X utf8 scripts\\reembed_check.py ^
        --new-dir <veri-dizini>\\staging --new-vec <bench-dizini>\\vec2 ^
        --live-dir <veri-dizini>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import _yollar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

QUERIES = [
    "kira sözleşmesinin feshi ve tahliye",
    "işçinin haklı nedenle iş akdini feshi kıdem tazminatı",
    "trafik kazası maddi manevi tazminat kusur oranı",
    "vergi ziyaı cezası tebligat usulsüzlüğü",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new-dir", required=True, help="yeni bulk-*.faiss'in bulunduğu dizin")
    ap.add_argument("--new-vec", required=True, help="yeni sidecar dizini (vec2)")
    ap.add_argument("--live-dir", default=str(_yollar.DATA_DIR))
    ap.add_argument("--db", default=str(_yollar.CACHE_PATH))
    ap.add_argument("--provider", default="fastembed-multilingual-e5")
    ap.add_argument("--expect-chunking-version", type=int, default=2)
    ap.add_argument("--min-ratio", type=float, default=0.99)
    args = ap.parse_args()

    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", args.provider)
    new_meta_p = Path(args.new_dir) / f"bulk-{safe}.meta.json"
    live_meta_p = Path(args.live_dir) / f"bulk-{safe}.meta.json"
    fails: list[str] = []

    if not new_meta_p.exists():
        print(f"HATA: yeni indeks meta yok: {new_meta_p}")
        return 1
    new_meta = json.loads(new_meta_p.read_text(encoding="utf-8"))
    live_meta = json.loads(live_meta_p.read_text(encoding="utf-8")) if live_meta_p.exists() else {}

    new_n, live_n = int(new_meta["count"]), int(live_meta.get("count", 0))
    ratio = new_n / live_n if live_n else float("inf")
    print(f"vektör: yeni {new_n:,} / canlı {live_n:,} (oran {ratio:.4f})")
    # Vektör sayısı parçalama sürümüyle meşru olarak değişir (v2 ~%5 az parça);
    # asıl güvence kapsanan tekil karar sayısıdır.
    import numpy as _np
    def _docs(path):
        with _np.load(path, allow_pickle=False) as z:
            return int(_np.unique(z["doc_num"]).shape[0])
    live_docs = _docs(str(live_meta_p.with_name(f"bulk-{safe}.keys.npz"))) if live_n else 0
    new_docs = _docs(str(new_meta_p.with_name(f"bulk-{safe}.keys.npz")))
    print(f"tekil karar: yeni {new_docs:,} / canlı {live_docs:,}")
    if live_docs and new_docs < live_docs * args.min_ratio:
        fails.append(f"tekil karar sayısı canlıdan %{100*(1-new_docs/live_docs):.2f} düşük (sınır %{100*(1-args.min_ratio):.0f})")

    ver = int(new_meta.get("chunking_version", 1))
    print(f"chunking_version: {ver}")
    if ver != args.expect_chunking_version:
        fails.append(f"chunking_version {ver}, beklenen {args.expect_chunking_version}")

    missing = [f for f in new_meta.get("files", []) if not (Path(args.new_vec) / f).exists()]
    print(f"sidecar: {len(new_meta.get('files', []))} dosya, eksik {len(missing)}")
    if missing:
        fails.append(f"vektör dosyaları eksik (refine kapanır): {missing[:3]}")

    # --- örnek sorgular: yeni indeks + yeni sidecar'lar ------------------------
    os.environ["EMSAL_BULK_VEC_DIR"] = args.new_vec
    from emsal_mcp import bulk_index
    from emsal_mcp.embeddings import get_embedding_provider

    prov = get_embedding_provider(args.provider)
    if prov is None:
        fails.append(f"gömme sağlayıcısı yok: {args.provider}")
    else:
        db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=120)
        db.row_factory = sqlite3.Row
        fake_db_path = Path(args.new_dir) / "cache.sqlite3"  # yalnız dosya adlarını türetmek için
        for q in QUERIES:
            vec = prov.embed_query(q) if hasattr(prov, "embed_query") else prov.embed_text(q)
            res = bulk_index.bulk_search(db, fake_db_path, args.provider, list(vec), limit=5)
            if not res:
                fails.append(f"sorgu sonuçsuz: {q!r}")
                continue
            top = res[0]
            snip = "snippet" in top and len(top["snippet"]) > 40
            print(f"  {q[:38]:40s} n={len(res)} skor={top['score']:.3f} "
                  f"doc={top['document_id']}/{top['source']} alıntı={'var' if snip else 'YOK'}")
            if top["score"] < 0.75:
                fails.append(f"düşük skor {top['score']:.3f}: {q!r}")
            if not snip:
                fails.append(f"alıntı üretilmedi: {q!r}")
        db.close()

    if fails:
        print("\nDOĞRULAMA BAŞARISIZ:")
        for f in fails:
            print(" -", f)
        return 1
    print("\nDOĞRULAMA TAMAM: indeks geçişe hazır")
    return 0


if __name__ == "__main__":
    sys.exit(main())
