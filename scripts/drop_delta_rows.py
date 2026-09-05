"""Aylık birleştirme, 3. aşama: toplu indekse eklenen kararların delta vektörlerini sil, delta matrisini yenile."""
import json, sqlite3, sys, os, subprocess
from pathlib import Path
name = sys.argv[1]
vec_dir = Path(os.environ.get("EMSAL_BULK_VEC_DIR", r"D:\emsal-bench\vec"))
m = json.loads((vec_dir / f"{name}.manifest.json").read_text(encoding="utf-8"))
db = sqlite3.connect(os.environ.get("EMSAL_CACHE_PATH", r"D:\emsal-data\cache.sqlite3"), timeout=600)
db.execute("PRAGMA busy_timeout=600000")
n = 0
for did, src in m["docs"]:
    n += db.execute("DELETE FROM embedding_vectors WHERE document_id=? AND source=? AND provider_id=?",
                    (did, src, m["provider"])).rowcount
db.commit()
left = db.execute("SELECT COUNT(*) FROM embedding_vectors WHERE provider_id=?", (m["provider"],)).fetchone()[0]
print(f"delta satırı silindi: {n}, kalan delta: {left}")
db.close()
