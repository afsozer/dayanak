"""Desktop dışa aktarımını (D:\emsal-export.sqlite3) laptop korpusuna birleştir: ON CONFLICT DO NOTHING."""
import sqlite3, time, sys
DB = r"D:\emsal-data\cache.sqlite3"; EXP = r"D:\emsal-data\emsal-export.sqlite3"
c = sqlite3.connect(DB, timeout=600); c.execute("PRAGMA busy_timeout=600000"); c.execute("PRAGMA journal_mode=WAL")
c.execute(f"ATTACH DATABASE '{EXP}' AS x")
before = c.execute("SELECT COUNT(*) FROM documents_v2_fts_docsize").fetchone()[0]
cols = [r[1] for r in c.execute("PRAGMA table_info(documents_v2)")]
xcols = {r[1] for r in c.execute("PRAGMA table_info(x.documents_v2)")}
common = [k for k in cols if k in xcols]; cl = ", ".join(common)
t0 = time.time()
c.execute(f"INSERT INTO documents_v2({cl}) SELECT {cl} FROM x.documents_v2 WHERE 1 ON CONFLICT(document_id, source) DO NOTHING")
c.commit()
after = c.execute("SELECT COUNT(*) FROM documents_v2_fts_docsize").fetchone()[0]
print(f"documents_v2: +{after-before} (dışa aktarımdaki {c.execute('SELECT COUNT(*) FROM x.documents_v2').fetchone()[0]}), {time.time()-t0:.0f}s")
ev_cols = [r[1] for r in c.execute("PRAGMA table_info(embedding_vectors)")]
xev = {r[1] for r in c.execute("PRAGMA table_info(x.embedding_vectors)")}
ec = ", ".join(k for k in ev_cols if k in xev)
n0 = c.execute("SELECT COUNT(*) FROM embedding_vectors").fetchone()[0]
c.execute(f"INSERT OR IGNORE INTO embedding_vectors({ec}) SELECT {ec} FROM x.embedding_vectors")
c.commit()
print("embedding_vectors:", c.execute("SELECT COUNT(*) FROM embedding_vectors").fetchone()[0] - n0, "eklendi")
print("kaynak dağılımı:", c.execute("SELECT source, COUNT(*) FROM documents_v2 GROUP BY 1").fetchall())
c.execute("DETACH DATABASE x"); c.close()
