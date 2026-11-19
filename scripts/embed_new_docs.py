"""Yeni (crawl'dan gelen) kararları yoğun (dense) delta indeksine gömer.

`semantic update-indexes` TF-IDF adımını da çalıştırır; 11 M kararlık korpusta
`search_vectors` boş olduğu için o adım tüm korpusu hesaplamaya kalkar. Bu betik
yalnız dense kısmını yapar: embedding_vectors'ta olmayan ve `--since`'ten sonra
alınmış kararları belge başına tek vektör olarak gömer: e5-small CPU'da (ONNX),
bge-m3 GPU'da (torch venv'inde ayrı süreç, `gom_gpu.py`; CPU'da karar başına ~8 sn).
Ardından `dayanak semantic build-matrix` çağrılmalı (delta matrisi).

Kullanım: python scripts/embed_new_docs.py --since 2026-09-05T00:00:00 [--limit 20000]
          python scripts/embed_new_docs.py --ids eksik.json   ([[document_id, source], ...])
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import _yollar  # noqa: E402

GPU_SAGLAYICI = {"onnx-bge-m3"}  # CPU'da pratik değil; torch venv'i yoksa CPU'ya düşer
GPU_BLOK = 2000


def _torch_py() -> str | None:
    p = os.environ.get("DAYANAK_TORCH_PY") or str(_yollar.BENCH_DIR / "venv" / "Scripts" / "python.exe")
    return p if Path(p).is_file() else None


def _gpu_gom(py: str, provider: str, texts: list[str]) -> list[list[float]]:
    import numpy as np
    with tempfile.TemporaryDirectory() as d:
        girdi, cikti = Path(d) / "metin.json", Path(d) / "v.npy"
        girdi.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        subprocess.run([py, "-X", "utf8", str(Path(__file__).with_name("gom_gpu.py")),
                        "--provider", provider, str(girdi), str(cikti)], check=True)
        return np.load(cikti).tolist()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="ISO zaman (retrieved_at >= since)")
    ap.add_argument("--ids", help="JSON dosyası: [[document_id, source], ...] (--since yerine)")
    ap.add_argument("--cpu", action="store_true", help="GPU sağlayıcısını da CPU'da göm")
    ap.add_argument("--provider", default=os.environ.get("DAYANAK_EMBEDDING_PROVIDER", "fastembed-multilingual-e5"))
    ap.add_argument("--limit", type=int, default=50_000)
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()
    if bool(args.since) == bool(args.ids):
        sys.exit("--since ya da --ids (biri)")

    from dayanak.cache import Cache
    from dayanak.embeddings import get_embedding_provider, pack_vector
    from dayanak import semantic

    c = Cache()
    db = c.db
    semantic._ensure_embedding_vectors(db)
    prov = get_embedding_provider(args.provider)
    if prov is None or prov.id == "local-hash-v1":
        sys.exit(f"sağlayıcı yok: {args.provider}")
    t0 = time.time()
    metinli = ("((dv.full_text IS NOT NULL AND dv.full_text != '') "
               "OR (dv.markdown IS NOT NULL AND dv.markdown != ''))")
    secim = ("SELECT dv.document_id, dv.source, dv.full_text, dv.markdown, dv.content_hash "
             "FROM documents_v2 dv LEFT JOIN embedding_vectors ev "
             "ON ev.document_id = dv.document_id AND ev.source = dv.source AND ev.provider_id = ? ")
    if args.ids:
        rows = []
        for d, s in json.loads(Path(args.ids).read_text(encoding="utf-8"))[: args.limit]:
            r = db.execute(secim + f"WHERE dv.document_id = ? AND dv.source = ? AND ev.document_id IS NULL AND {metinli}",
                           (prov.id, d, s)).fetchone()
            if r:
                rows.append(r)
    else:
        rows = db.execute(secim + f"WHERE dv.retrieved_at >= ? AND ev.document_id IS NULL AND {metinli} LIMIT ?",
                          (prov.id, args.since, args.limit)).fetchall()
    print(f"gömülecek: {len(rows)} karar (tarama {time.time()-t0:.0f} s)", flush=True)
    py = _torch_py() if prov.id in GPU_SAGLAYICI and not args.cpu else None
    if prov.id in GPU_SAGLAYICI and not args.cpu and py is None:
        print("torch venv'i yok, CPU'da gömülüyor (yavaş)", flush=True)
    adim = GPU_BLOK if py else args.batch
    done = 0
    for i in range(0, len(rows), adim):
        batch = rows[i:i + adim]
        texts = [(r["full_text"] or r["markdown"] or "") for r in batch]
        if py:
            vecs = _gpu_gom(py, prov.id, texts)
        elif hasattr(prov, "embed_documents_batch"):
            vecs = prov.embed_documents_batch(texts)
        else:
            vecs = [prov.embed_document(t) if hasattr(prov, "embed_document") else prov.embed_text(t) for t in texts]
        for r, vec in zip(batch, vecs):
            db.execute(
                "INSERT OR REPLACE INTO embedding_vectors "
                "(document_id, source, provider_id, dim, vector, norm, content_hash) VALUES (?,?,?,?,?,?,?)",
                (r["document_id"], r["source"], prov.id, prov.dimensions, pack_vector(vec),
                 math.sqrt(sum(v * v for v in vec)), r["content_hash"]),
            )
        db.commit()
        done += len(batch)
        if py or done % 320 == 0 or done == len(rows):
            print(f"  {done}/{len(rows)} {done/(time.time()-t0):.1f} belge/sn", flush=True)
    c.close()
    print(f"bitti: {done} vektör, {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main()
