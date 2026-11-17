"""Arama kıyası (aşama 0): BM25, canlı dense, RRF ve tam (PQ'suz) dense aynı sorgularla.

İki iş:

  kos  (sunucuda)  sorgular.json -> kosu.json + havuz.json
       DB yalnız okunur (mode=ro); Cache.search_local çağrılmaz, bu yüzden
       search_history'e satır yazılmaz (önce/sonra sayısı loglanır).
  olc  (her yerde) kosu.json + puanlar.json -> metrik tablosu (stdout, JSON)

Kullanım (korpusun olduğu makinede, ortam dayanak-env.cmd'den):
  python arama_kiyas.py kos --sorgular sorgular.json --cikti <çıktı dizini>
  python arama_kiyas.py olc --dizin eval/yerel
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

N = 50          # her yoldan alınan sonuç
HAVUZ_N = 20    # hakemliğe giren derinlik
RRF_K = 60


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ── kos ──────────────────────────────────────────────────────────────────────

def kos(args):
    import sqlite3
    import types

    import numpy as np

    from dayanak import bulk_index, semantic
    from dayanak.cache import _fts5_match_expr
    from dayanak.embeddings import get_embedding_provider

    if os.name == "nt":  # koşu boyunca uyku/ekran kapanması yok; süreç bitince kalkar
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)

    db_path = Path(os.environ["DAYANAK_CACHE_PATH"])
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    gecmis0 = db.execute("SELECT COUNT(*), MAX(id) FROM search_history").fetchone()
    log("search_history önce:", tuple(gecmis0))

    out_dir = Path(args.cikti)
    sorgular = json.loads(Path(args.sorgular).read_text(encoding="utf-8"))
    prov = get_embedding_provider()
    cache = types.SimpleNamespace(db=db, path=db_path, close=lambda: None)
    sonuc: dict[str, dict] = {}

    # 1-3: BM25, canlı dense, RRF
    for q in sorgular:
        excl = set(q.get("exclude", []))
        r: dict = {"sure": {}}
        t = time.time()
        bm = []
        expr = _fts5_match_expr(q["kw"])
        if expr:
            try:
                rows = db.execute(
                    "SELECT d.document_id, d.source, snippet(documents_v2_fts, 3, '', '', '…', 48) AS s "
                    "FROM documents_v2_fts f JOIN documents_v2 d ON d.rowid = f.rowid "
                    "WHERE documents_v2_fts MATCH ? ORDER BY bm25(documents_v2_fts) LIMIT ?",
                    (expr, N + len(excl))).fetchall()
                bm = [{"id": x["document_id"], "src": x["source"], "snip": x["s"]}
                      for x in rows if x["document_id"] not in excl][:N]
            except sqlite3.OperationalError as e:  # canlı yol burada LIKE'a düşer (70 GB tarama); biz düşmüyoruz
                r["bm25_hata"] = str(e)
        r["bm25"] = bm
        r["sure"]["bm25"] = round(time.time() - t, 2)

        t = time.time()
        dr = semantic.embedding_search(query=q["query"], limit=N + len(excl), provider=prov.id, cache=cache)
        r["dense_yontem"] = dr.get("method")
        r["dense"] = [{"id": x["document_id"], "src": x["source"], "skor": x["score"],
                       "snip": x.get("snippet", "")}
                      for x in dr.get("results", []) if x["document_id"] not in excl][:N]
        r["sure"]["dense"] = round(time.time() - t, 2)

        fused = semantic._rrf_fusion(
            [{"document_id": x["id"], "source": x["src"]} for x in bm], [],
            [{"document_id": x["id"], "source": x["src"]} for x in r["dense"]], N)
        r["rrf"] = [{"id": x["document_id"], "src": x["source"]} for x in fused]
        sonuc[q["id"]] = r
        log(q["id"], "bm25", len(bm), "dense", len(r["dense"]), r["sure"])

    # 4: tam dense, PQ'suz kaba kuvvet (aynı sidecar'lar, dosya dosya)
    L = bulk_index._load(db_path, prov.id)
    if L is None or not L.mats:
        raise SystemExit("toplu indeks ya da vektör dosyaları yok")
    qv = [prov.embed_query(q["query"]) for q in sorgular]
    Q = np.asarray(qv, dtype=np.float32)
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    n, K, STEP = len(sorgular), 3000, 250_000
    best_s = np.full((n, K), -np.inf, dtype=np.float32)
    best_i = np.zeros((n, K), dtype=np.int64)
    t0 = time.time()
    for f, m in enumerate(L.mats):
        base = int(L.offsets[f])
        for a in range(0, m.shape[0], STEP):
            S = Q @ np.asarray(m[a:a + STEP], dtype=np.float32).T
            k = min(K, S.shape[1])
            idx = np.argpartition(-S, k - 1, axis=1)[:, :k]
            cs = np.take_along_axis(S, idx, 1)
            allS = np.concatenate([best_s, cs], 1)
            allI = np.concatenate([best_i, idx + base + a], 1)
            sel = np.argpartition(-allS, K - 1, axis=1)[:, :K]
            best_s = np.take_along_axis(allS, sel, 1)
            best_i = np.take_along_axis(allI, sel, 1)
        log(f"tam [{f+1}/{len(L.mats)}] {L.meta['files'][f]} {time.time()-t0:.0f} s")
    chunk_ver = int(L.meta.get("chunking_version", 1))
    for qi, q in enumerate(sorgular):
        excl = set(q.get("exclude", []))
        order = np.argsort(-best_s[qi])
        best: dict[tuple[str, str], tuple[float, int]] = {}
        for j in order:
            i = int(best_i[qi, j]); s = float(best_s[qi, j])
            if s <= 0:
                break
            key = (bulk_index._doc_id(L, i), L.meta["sources"][int(L.source_id[i])])
            if key not in best:
                best[key] = (s, int(L.chunk_index[i]))
        # canlı yolla aynı: indeks sonrası gelen delta matrisi en yüksek skorla birleşir
        qn = math.sqrt(sum(v * v for v in qv[qi]))
        delta = semantic._score_vectors_mmap(db, db_path, prov.id, qv[qi], qn, limit=N + len(excl)) or []
        for x in delta:
            key = (x["document_id"], x["source"])
            if key not in best or x["score"] > best[key][0]:
                best[key] = (float(x["score"]), -1)
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
        tam = []
        for (did, src), (s, cix) in ranked:
            if did in excl:
                continue
            e = {"id": did, "src": src, "skor": round(s, 6), "cix": cix}
            if len(tam) < HAVUZ_N and cix >= 0:
                row = db.execute("SELECT full_text FROM documents_v2 WHERE document_id=? AND source=?",
                                 (did, src)).fetchone()
                if row and row[0]:
                    e["snip"] = bulk_index._best_chunk_text(row[0], cix, chunking_version=chunk_ver)
            tam.append(e)
            if len(tam) >= N:
                break
        sonuc[q["id"]]["tam"] = tam
    log("tam dense bitti", round(time.time() - t0), "s")

    # havuz: dört yolun ilk 20'si, karar başına künye + baş + en iyi pasaj
    havuz = {}
    for q in sorgular:
        r = sonuc[q["id"]]
        docs: dict[str, dict] = {}
        for yol in ("bm25", "dense", "rrf", "tam"):
            for x in r[yol][:HAVUZ_N]:
                d = docs.setdefault(x["id"], {"id": x["id"], "src": x["src"], "pasaj": ""})
                if x.get("snip") and len(x["snip"]) > len(d["pasaj"]):
                    d["pasaj"] = x["snip"]
        for d in docs.values():
            row = db.execute(
                "SELECT court, chamber, decision_date, esas_no, karar_no, substr(full_text, 1, 2500) AS bas "
                "FROM documents_v2 WHERE document_id=? AND source=?", (d["id"], d["src"])).fetchone()
            if row:
                d.update(kunye=f"{row['court']} | {row['chamber']} | {row['decision_date']} | "
                               f"E.{row['esas_no']} K.{row['karar_no']}",
                         bas=" ".join((row["bas"] or "").split())[:900])
        havuz[q["id"]] = list(docs.values())

    gecmis1 = db.execute("SELECT COUNT(*), MAX(id) FROM search_history").fetchone()
    log("search_history sonra:", tuple(gecmis1), "eklenen:", gecmis1[0] - gecmis0[0])
    (out_dir / "kosu.json").write_text(json.dumps(sonuc, ensure_ascii=False), encoding="utf-8")
    (out_dir / "havuz.json").write_text(json.dumps(havuz, ensure_ascii=False), encoding="utf-8")
    log("BITTI")


# ── kos2: düzeltmelerin ölçümü (gerçek hybrid_search_rrf) ────────────────────

def kos2(args):
    """V1-V4 (gerçek hybrid_search_rrf, SKIP_HEAD_CHUNK kapalı/açık, dense_query
    yok/var) ve yalnız dense (anahtar/cümle x kapalı/açık).  DB salt okunur;
    Cache.__init__ (DDL yazar) atlanır, record_search no-op'a çevrilir."""
    import sqlite3
    import statistics

    import numpy as np

    from dayanak import bulk_index, search_analytics, semantic
    from dayanak.cache import Cache, _fts5_match_expr
    from dayanak.embeddings import get_embedding_provider

    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)

    kayit = {"n": 0}

    def _sessiz(**kw):
        kayit["n"] += 1
        return {"ok": True}
    search_analytics.record_search = _sessiz

    db_path = Path(os.environ["DAYANAK_CACHE_PATH"])
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    c = Cache.__new__(Cache)
    c.path, c.db, c._query_profile = db_path, db, {}
    gecmis0 = tuple(db.execute("SELECT COUNT(*), MAX(id) FROM search_history").fetchone())
    log("search_history önce:", gecmis0)

    sorgular = json.loads(Path(args.sorgular).read_text(encoding="utf-8"))
    prov = get_embedding_provider()
    L = bulk_index._load(db_path, prov.id)
    dn_all = np.asarray(L.doc_num)
    ci_all = np.asarray(L.chunk_index)
    cok_parca: dict[str, bool] = {}

    def _cok_parcali(did: str) -> bool | None:
        if did in cok_parca:
            return cok_parca[did]
        if not did.lstrip("-").isdigit():
            return None
        pos = np.nonzero(dn_all == int(did))[0]
        cok_parca[did] = bool(len(pos) and (ci_all[pos] > 0).any())
        return cok_parca[did]

    def _yaz(liste, excl):
        out = []
        for x in liste:
            if x["document_id"] in excl:
                continue
            out.append({"id": x["document_id"], "src": x["source"], "cix": x.get("best_chunk"),
                        "snip": x.get("snippet", "") if ("best_chunk" in x or "rrf_score" not in x) else "",
                        "kunye": {k: x.get(k) for k in ("court", "chamber", "decision_date",
                                                        "esas_no", "karar_no")}})
        return out

    sonuc: dict[str, dict] = {q["id"]: {"sure": {}} for q in sorgular}
    yollar = [  # ad, skip, dense_query cümle mi
        ("v1", False, False), ("v2", True, False), ("v3", False, True), ("v4", True, True)]
    tfidf_sure = []
    semantic.embedding_search(query="ısınma", limit=5, provider=prov.id, cache=c)  # indeks ve model yüklensin
    for ad, skip, cumle in yollar:
        bulk_index.SKIP_HEAD_CHUNK = skip
        for q in sorgular:
            excl = set(q["dislanan"])
            t = time.time()
            r = semantic.hybrid_search_rrf(query=q["kw"], limit=20, cache=c,
                                           dense_query=q["cumle"] if cumle else None)
            sonuc[q["id"]]["sure"][ad] = round(time.time() - t, 3)
            if not r.get("dense_included"):
                sonuc[q["id"]].setdefault("uyari", []).append(f"{ad}: dense yok")
            sonuc[q["id"]][ad] = _yaz(r["results"], excl)
            log(ad, q["id"], len(r["results"]), sonuc[q["id"]]["sure"][ad])
        if ad == "v1":  # bileşen süreleri ve BM25'in RRF'ye giren listesi (limit*2=40)
            for q in sorgular:
                t = time.time()
                bm = semantic._fts5_search(q["kw"], limit=40, cache=c)
                sonuc[q["id"]]["sure"]["bm25_40"] = round(time.time() - t, 3)
                sonuc[q["id"]]["bm25_40"] = [x["document_id"] for x in bm]
                t = time.time()
                semantic._tfidf_search(q["kw"], limit=40, cache=c)
                tfidf_sure.append(time.time() - t)

    for ad, skip, cumle in [("d_kw", False, False), ("d_kw_skip", True, False),
                            ("d_cumle", False, True), ("d_cumle_skip", True, True)]:
        bulk_index.SKIP_HEAD_CHUNK = skip
        for q in sorgular:
            excl = set(q["dislanan"])
            t = time.time()
            r = semantic.embedding_search(query=q["cumle"] if cumle else q["kw"],
                                          limit=20 + len(excl), provider=prov.id, cache=c)
            sonuc[q["id"]]["sure"][ad] = round(time.time() - t, 3)
            sonuc[q["id"]][ad] = _yaz(r.get("results", []), excl)[:20]
            for x in sonuc[q["id"]][ad][:10]:
                if x["cix"] == 0:
                    x["cok_parca"] = _cok_parcali(x["id"])
            log(ad, q["id"], len(sonuc[q["id"]][ad]), sonuc[q["id"]]["sure"][ad])
    bulk_index.SKIP_HEAD_CHUNK = False
    for q in sorgular:  # V1 ikinci kez: sıcak önbellekle gecikme
        t = time.time()
        semantic.hybrid_search_rrf(query=q["kw"], limit=20, cache=c)
        sonuc[q["id"]]["sure"]["v1_sicak"] = round(time.time() - t, 3)

    # hakemlik için: her yolun ilk 10'unda puansız kararların künye, baş ve pasajı
    paket: dict[str, list[dict]] = {}
    for q in sorgular:
        r = sonuc[q["id"]]
        puanli = set(q["puanli"])
        docs: dict[str, dict] = {}
        for ad in ("v1", "v2", "v3", "v4", "d_kw", "d_kw_skip", "d_cumle", "d_cumle_skip"):
            for x in r[ad][:10]:
                if x["id"] in puanli:
                    continue
                d = docs.setdefault(x["id"], {"id": x["id"], "src": x["src"], "pasaj": "", "cix": set()})
                if x["cix"] is not None:
                    d["cix"].add(x["cix"])
                if len(x.get("snip") or "") > len(d["pasaj"]):
                    d["pasaj"] = x["snip"]
        expr = _fts5_match_expr(q["kw"])
        for d in docs.values():
            row = db.execute(
                "SELECT rowid, court, chamber, decision_date, esas_no, karar_no, "
                "substr(full_text, 1, 4000) AS bas FROM documents_v2 WHERE document_id=? AND source=?",
                (d["id"], d["src"])).fetchone()
            if not row:
                continue
            if expr:
                try:
                    s = db.execute("SELECT snippet(documents_v2_fts, 3, '', '', '…', 48) FROM documents_v2_fts "
                                   "WHERE documents_v2_fts MATCH ? AND rowid = ?", (expr, row["rowid"])).fetchone()
                    if s and s[0] and len(s[0]) > len(d["pasaj"]):
                        d["pasaj"] = s[0]
                except sqlite3.OperationalError:
                    pass
            bas = " ".join((row["bas"] or "").split())
            d.update(kunye=f"{row['court']} | {row['chamber']} | {row['decision_date']} | "
                           f"E.{row['esas_no']} K.{row['karar_no']}",
                     bas=bas[:900], ilk_parca=bas[:1900], cix=sorted(d["cix"]))
        paket[q["id"]] = list(docs.values())

    gecmis1 = tuple(db.execute("SELECT COUNT(*), MAX(id) FROM search_history").fetchone())
    log("search_history sonra:", gecmis1, "record_search çağrısı (no-op):", kayit["n"])
    v1 = [r["sure"]["v1"] for r in sonuc.values()]
    v1s = [r["sure"]["v1_sicak"] for r in sonuc.values()]
    ozet = {"search_history": [gecmis0, gecmis1], "record_search_cagri": kayit["n"],
            "v1_medyan": statistics.median(v1), "v1_p90": float(np.percentile(v1, 90)),
            "v1_sicak_medyan": statistics.median(v1s), "v1_sicak_p90": float(np.percentile(v1s, 90)),
            "tfidf_medyan": statistics.median(tfidf_sure), "tfidf_max": max(tfidf_sure)}
    log("özet", ozet)
    out = Path(args.cikti)
    (out / "kosu_v2.json").write_text(json.dumps(sonuc, ensure_ascii=False), encoding="utf-8")
    (out / "paket_ham.json").write_text(json.dumps(paket, ensure_ascii=False), encoding="utf-8")
    (out / "ozet.json").write_text(json.dumps(ozet, ensure_ascii=False), encoding="utf-8")
    log("BITTI")


# ── olc ──────────────────────────────────────────────────────────────────────

def _metrik(ids: list[str], puan: dict[str, int], k: int) -> tuple[float, float]:
    """recall@k (puan>=1) ve kademeli nDCG@k (kazanç = puan 0/1/2)."""
    ilgili = {d for d, p in puan.items() if p >= 1}
    if not ilgili:
        return math.nan, math.nan
    rec = len(set(ids[:k]) & ilgili) / len(ilgili)
    dcg = sum(puan.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ids[:k]))
    ideal = sorted((p for p in puan.values() if p > 0), reverse=True)[:k]
    idcg = sum(p / math.log2(i + 2) for i, p in enumerate(ideal))
    return rec, dcg / idcg


def olc(args):
    d = Path(args.dizin)
    kosu = json.loads((d / "kosu.json").read_text(encoding="utf-8"))
    golden = json.loads((d / "golden_gercek.json").read_text(encoding="utf-8"))
    yollar = ("bm25", "dense", "rrf", "tam")
    satir: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
    for g in golden:
        r = kosu[g["id"]]
        for yol in yollar:
            ids = [x["id"] for x in r[yol]]
            r10, n10 = _metrik(ids, g["puanlar"], 10)
            r50, _ = _metrik(ids, g["puanlar"], 50)
            if math.isnan(r10):
                continue
            for grup in ("toplam", g["kaynak"]):
                satir.setdefault((grup, yol), []).append((r10, n10, r50))
    tablo = {}
    for (grup, yol), v in sorted(satir.items()):
        tablo.setdefault(grup, {})[yol] = {
            "n": len(v),
            "recall@10": round(sum(x[0] for x in v) / len(v), 3),
            "ndcg@10": round(sum(x[1] for x in v) / len(v), 3),
            "recall@50": round(sum(x[2] for x in v) / len(v), 3),
        }
    # indeks (PQ) kaybı: hakemden bağımsız, canlı dense'in tam dense ilk 10'unu yakalama oranı
    ort = []
    for g in golden:
        r = kosu[g["id"]]
        tam10 = {x["id"] for x in r["tam"][:10]}
        if tam10:
            ort.append(len(tam10 & {x["id"] for x in r["dense"][:10]}) / len(tam10))
    tablo["pq_ortusme@10"] = round(sum(ort) / len(ort), 3)
    print(json.dumps(tablo, ensure_ascii=False, indent=1))


def olc2(args):
    """Düzeltmelerin ölçümü: eski ve yeni yollar, birleşik puanlarla (golden_gercek_v2.json).
    Kapsam (ilk 10'un hakemli payı) ilk puan setine göre verilir."""
    import random

    d = Path(args.dizin)
    eski = json.loads((d / "kosu.json").read_text(encoding="utf-8"))
    yeni = json.loads((d / "kosu_v2.json").read_text(encoding="utf-8"))
    g1 = {g["id"]: g for g in json.loads((d / "golden_gercek.json").read_text(encoding="utf-8"))}
    g2 = json.loads((d / "golden_gercek_v2.json").read_text(encoding="utf-8"))
    yollar = {"bm25": ("eski", "bm25"), "rrf_eski": ("eski", "rrf"), "dense_eski": ("eski", "dense"),
              **{y: ("yeni", y) for y in ("v1", "v2", "v3", "v4", "d_kw", "d_kw_skip", "d_cumle", "d_cumle_skip")}}

    def ids(qid, yol):
        k, ad = yollar[yol]
        return [x["id"] for x in (eski if k == "eski" else yeni)[qid][ad]]

    m: dict[str, dict[str, tuple]] = {y: {} for y in yollar}
    kapsam: dict[str, list[float]] = {y: [] for y in yollar}
    for g in g2:
        for y in yollar:
            top = ids(g["id"], y)[:10]
            if top:
                kapsam[y].append(sum(x in g1[g["id"]]["puanlar"] for x in top) / len(top))
            r10, n10 = _metrik(top, g["puanlar"], 10)
            if not math.isnan(r10):
                m[y][g["id"]] = (n10, r10, float(any(g["puanlar"].get(x, 0) == 2 for x in top)))
    gruplar = {"toplam": None, "a": "a", "b": "b", "c": "c", "bc": "bc"}
    kaynak = {g["id"]: g["kaynak"] for g in g2}

    def secim(grup):
        return [q for q in m["bm25"] if grup == "toplam" or kaynak[q] in grup]

    tablo = {"kapsam_ilk10": {y: round(sum(v) / len(v), 3) for y, v in kapsam.items()}}
    for grup in gruplar:
        qs = secim(grup)
        tablo[grup] = {y: {"n": len(qs), **{ad: round(sum(m[y][q][i] for q in qs) / len(qs), 3)
                                            for i, ad in enumerate(("ndcg@10", "recall@10", "isabet@10"))}}
                       for y in yollar}
    rng = random.Random(17)
    farklar = [("v1", "bm25"), ("v1", "rrf_eski"), ("v2", "v1"), ("v3", "v1"), ("v4", "v3"), ("v4", "bm25"),
               ("d_kw_skip", "d_kw"), ("d_cumle_skip", "d_cumle"), ("d_cumle", "d_kw")]
    tablo["bootstrap_ndcg@10"] = {}
    for a, b in farklar:
        for grup in ("toplam", "a", "bc"):
            qs = secim(grup)
            dif = [m[a][q][0] - m[b][q][0] for q in qs]
            ort = sorted(sum(rng.choice(dif) for _ in dif) / len(dif) for _ in range(4000))
            tablo["bootstrap_ndcg@10"][f"{a}-{b} {grup}"] = [round(sum(dif) / len(dif), 3),
                                                            round(ort[100], 3), round(ort[3899], 3)]
    # dense ilk 10'da ilk parça payı: cix==0 (tek parçalı kısa kararlar dahil) ve çok parçalı kararın başlığı
    bas = {}
    for y in ("d_kw", "d_kw_skip", "d_cumle", "d_cumle_skip"):
        for grup in ("a", "bc"):
            xs = [x for q in secim(grup) for x in yeni[q][y][:10]]
            bas[f"{y} {grup}"] = [round(sum(x["cix"] == 0 for x in xs) / len(xs), 3),
                                  round(sum(bool(x.get("cok_parca")) for x in xs) / len(xs), 3)]
    tablo["ilk_parca_payi[cix0, baslik]"] = bas
    # künye: V1'de BM25'in 40'ında olmayan (yalnız dense'in getirdiği) sonuçlar
    alan = ("court", "chamber", "decision_date", "esas_no", "karar_no")
    yd = [x for q in yeni.values() for x in q["v1"][:20] if x["id"] not in set(q["bm25_40"])]
    tablo["kunye_yalniz_dense"] = {"n": len(yd), **{k: round(sum(bool(x["kunye"].get(k)) for x in yd) / len(yd), 3)
                                                    for k in alan}}
    sure = {y: sorted(q["sure"][y] for q in yeni.values()) for y in ("v1", "v1_sicak", "v2", "v3", "v4", "d_kw", "bm25_40")}
    tablo["sure_s[medyan,p90,max]"] = {y: [v[len(v) // 2], v[int(len(v) * 0.9)], v[-1]] for y, v in sure.items()}
    tablo["v1_bm25_kotu"] = sorted(((round(m["v1"][q][0] - m["bm25"][q][0], 3), q) for q in m["v1"]))[:12]
    print(json.dumps(tablo, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="komut", required=True)
    a = s.add_parser("kos"); a.add_argument("--sorgular", required=True); a.add_argument("--cikti", required=True)
    a2 = s.add_parser("kos2"); a2.add_argument("--sorgular", required=True); a2.add_argument("--cikti", required=True)
    b = s.add_parser("olc"); b.add_argument("--dizin", required=True)
    b2 = s.add_parser("olc2"); b2.add_argument("--dizin", required=True)
    args = p.parse_args()
    {"kos": kos, "kos2": kos2, "olc": olc, "olc2": olc2}[args.komut](args)


if __name__ == "__main__":
    sys.exit(main())
