"""Yeni (crawl'dan gelen) kararları yoğun (dense) delta indeksine gömer.

`semantic update-indexes` TF-IDF adımını da çalıştırır; 11 M kararlık korpusta
`search_vectors` boş olduğu için o adım tüm korpusu hesaplamaya kalkar. Bu betik
yalnız dense kısmını yapar: embedding_vectors'ta olmayan ve `--since`'ten sonra
alınmış kararları fastembed (ONNX, CPU) ile belge başına tek vektör olarak
gömer. Ardından `emsal-mcp semantic build-matrix` çağrılmalı (delta matrisi).

Kullanım: python scripts/embed_new_docs.py --since 2026-09-05T00:00:00 [--limit 20000]
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="ISO zaman (retrieved_at >= since)")
    ap.add_argument("--provider", default=os.environ.get("EMSAL_EMBEDDING_PROVIDER", "fastembed-multilingual-e5"))
    ap.add_argument("--limit", type=int, default=50_000)
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()

    from emsal_mcp.cache import Cache
    from emsal_mcp.embeddings import get_embedding_provider, pack_vector
    from emsal_mcp import semantic

    c = Cache()
    db = c.db
    semantic._ensure_embedding_vectors(db)
    prov = get_embedding_provider(args.provider)
    if prov is None or prov.id == "local-hash-v1":
        sys.exit(f"sağlayıcı yok: {args.provider}")
    t0 = time.time()
    rows = db.execute(
        """
        SELECT dv.document_id, dv.source, dv.full_text, dv.markdown, dv.content_hash
        FROM documents_v2 dv
        LEFT JOIN embedding_vectors ev
          ON ev.document_id = dv.document_id AND ev.source = dv.source AND ev.provider_id = ?
        WHERE dv.retrieved_at >= ? AND ev.document_id IS NULL
          AND ((dv.full_text IS NOT NULL AND dv.full_text != '')
            OR (dv.markdown IS NOT NULL AND dv.markdown != ''))
        LIMIT ?
        """,
        (prov.id, args.since, args.limit),
    ).fetchall()
    print(f"gömülecek: {len(rows)} karar (tarama {time.time()-t0:.0f} s)", flush=True)
    done = 0
    for i in range(0, len(rows), args.batch):
        batch = rows[i:i + args.batch]
        texts = [(r["full_text"] or r["markdown"] or "") for r in batch]
        if hasattr(prov, "embed_documents_batch"):
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
        if done % 320 == 0 or done == len(rows):
            print(f"  {done}/{len(rows)} {done/(time.time()-t0):.1f} belge/sn", flush=True)
    c.close()
    print(f"bitti: {done} vektör, {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main()
