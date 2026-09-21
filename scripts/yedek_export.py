"""Yedek disa aktarimi: (1) mevzuat_* tablolari ayri sqlite'a, (2) parquet disindaki kararlar
(uyap_arsiv + delta manifestindeki + 2026-09-05 sonrasi cekilenler) ayri sqlite'a.
Buyuk documents_v2 uzerinde tam tarama YAPMAZ: rowid/retrieved_at indeksi ve kimlik listesi kullanir."""
import glob, json, os, sqlite3, sys, time

import _yollar
DB = str(_yollar.CACHE_PATH)
VEC = str(_yollar.VEC_DIR)
OUT = sys.argv[1] if len(sys.argv) > 1 else str(_yollar.YEDEK_DIR)
os.makedirs(OUT, exist_ok=True)
t0 = time.time()
src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); src.execute("PRAGMA busy_timeout=600000")

# 1) mevzuat tablolari
mp = os.path.join(OUT, "mevzuat.sqlite3")
if os.path.exists(mp): os.remove(mp)
src.execute(f"ATTACH DATABASE '{mp.replace(chr(92), '/')}' AS y")
tabs = [r[0] for r in src.execute("select name from sqlite_master where type='table' and name like 'mevzuat_%' and name not like '%_fts%'")]
for t in tabs:
    src.execute(f"CREATE TABLE y.{t} AS SELECT * FROM main.{t}")
    print(f"mevzuat: {t} {src.execute(f'select count(*) from y.{t}').fetchone()[0]:,}")
src.commit(); src.execute("DETACH DATABASE y")

# 2) parquet disi kararlar
ids = set()
for mf in glob.glob(os.path.join(VEC, "delta-*.manifest.json")):
    m = json.load(open(mf, encoding="utf-8"))
    docs = m.get("docs", m) if isinstance(m, dict) else m
    if isinstance(docs, dict):
        for k in docs: ids.add(tuple(k.split("|", 1)) if "|" in k else (None, k))
    elif isinstance(docs, list):
        for d in docs:
            if isinstance(d, dict): ids.add((d.get("source"), str(d.get("document_id"))))
            elif isinstance(d, (list, tuple)) and len(d) >= 2: ids.add((d[1], str(d[0])))  # manifest: [document_id, source]
            else: ids.add((None, str(d)))
print("manifest kimlik:", len(ids))
kp = os.path.join(OUT, "karar-delta.sqlite3")
if os.path.exists(kp): os.remove(kp)
src.execute(f"ATTACH DATABASE '{kp.replace(chr(92), '/')}' AS k")
src.execute("CREATE TABLE k.documents_v2 AS SELECT * FROM main.documents_v2 WHERE 0")
src.execute("CREATE TEMP TABLE sel(source TEXT, document_id TEXT, PRIMARY KEY(source, document_id))")
src.executemany("INSERT OR IGNORE INTO sel VALUES(?,?)", [(s, d) for s, d in ids if s])
src.executemany("INSERT OR IGNORE INTO sel SELECT source, document_id FROM main.documents_v2 WHERE document_id=? LIMIT 4", [(d,) for s, d in ids if not s])
# uyap_arsiv (idx_dv2_source) ve 2026-09-05 sonrasi (idx_dv2_retrieved_at) indeksli
src.execute("INSERT OR IGNORE INTO sel SELECT source, document_id FROM main.documents_v2 WHERE source='uyap_arsiv'")
src.execute("INSERT OR IGNORE INTO sel SELECT source, document_id FROM main.documents_v2 WHERE retrieved_at >= '2026-09-05'")
n = src.execute("SELECT count(*) FROM sel").fetchone()[0]
# CROSS JOIN: once kucuk sel taranir, documents_v2 PK (document_id, source) ile tek tek bulunur (11 M satir taranmaz)
src.execute("INSERT INTO k.documents_v2 SELECT d.* FROM sel s CROSS JOIN main.documents_v2 d ON d.document_id=s.document_id AND d.source=s.source")
src.commit()
print(f"karar-delta: {src.execute('select count(*) from k.documents_v2').fetchone()[0]:,} karar (secilen {n:,})")
src.execute("DETACH DATABASE k")
for p in (mp, kp):
    print(f"{os.path.basename(p)}: {os.path.getsize(p)/1e6:.0f} MB")
print(f"sure {time.time()-t0:.0f} s")
