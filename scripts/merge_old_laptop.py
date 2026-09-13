"""Gocten onceki laptop korpusundaki (~/.emsal-mcp/cache.sqlite3) yeni korpusta olmayan kararlari aktar; retrieved_at=simdi (delta gomme secimi icin)."""
import sqlite3, time, datetime
DB = r"D:\emsal-data\cache.sqlite3"; OLD = r"C:\Users\Sozer\.emsal-mcp\cache.sqlite3"
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
c = sqlite3.connect(DB, timeout=600, uri=False); c.execute("PRAGMA busy_timeout=600000")
oldp = OLD.replace("\\", "/")
c.execute(f"ATTACH DATABASE '{oldp}' AS o")
cols = [r[1] for r in c.execute("PRAGMA main.table_info(documents_v2)")]
ocols = {r[1] for r in c.execute("PRAGMA o.table_info(documents_v2)")}
common = [k for k in cols if k in ocols and k != "retrieved_at"]
sel = ", ".join(f"o.{k}" for k in common) + ", ?"
t0 = time.time()
before = c.execute("SELECT COUNT(*) FROM documents_v2_fts_docsize").fetchone()[0]
c.execute(f"INSERT INTO main.documents_v2({', '.join(common)}, retrieved_at) "
          f"SELECT {sel} FROM o.documents_v2 o WHERE NOT EXISTS (SELECT 1 FROM main.documents_v2 m WHERE m.source=o.source AND m.document_id=o.document_id) "
          f"ON CONFLICT(document_id, source) DO NOTHING", (now,))
c.commit()
after = c.execute("SELECT COUNT(*) FROM documents_v2_fts_docsize").fetchone()[0]
print(f"eklenen: {after-before} ({time.time()-t0:.0f} s), retrieved_at={now}")
c.execute("DETACH DATABASE o"); c.close()
print("SINCE", now)
