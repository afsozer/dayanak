"""Faz 2c kalite ölçümü: 15 hukuki sorgu × 3 mod (lexical / semantic / hybrid).

Ölçüt: beklenen (mevzuat_no, madde_no) ilk 5 sonuçta var mı; ayrıca sorgu
gecikmesi (sorgu gömme dahil, sıcak indeks).
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import _yollar

from emsal_mcp import legislation_semantic as ls
from emsal_mcp.legislation import _norm_article_no
from emsal_mcp.legislation_corpus import search_madde

SORGULAR = [
    ("tahliye taahhüdü", "6098", ["352"]),
    ("idari para cezasına itiraz süresi", "5326", ["27"]),
    ("işçinin haklı nedenle derhal fesih hakkı", "4857", ["24"]),
    ("kira bedelinin tespiti", "6098", ["344", "345"]),
    ("boşanmada ziynet eşyası", "4721", None),
    ("zamanaşımı def'i", "6098", [str(i) for i in range(146, 162)]),
    ("tapu iptali ve tescil", "4721", ["1025"]),
    ("haksız fiil sorumluluğu", "6098", ["49"]),
    ("kamulaştırma bedelinin tespiti", "2942", ["10"]),
    ("adli kontrol", "5271", ["109"]),
    ("tutuklama nedenleri", "5271", ["100"]),
    ("ihtiyati tedbir şartları", "6100", ["389"]),
    ("icra inkar tazminatı", "2004", ["67"]),
    ("istihkak davası", "2004", ["96", "97", "98", "99"]),
    ("vergi ziyaı", "213", ["341"]),
]

TOP = 5


def _hit(results, no, maddeler) -> str:
    if maddeler is None:
        return "-"
    hedef = {_norm_article_no(m) for m in maddeler}
    for i, r in enumerate(results[:TOP]):
        if str(r.get("mevzuat_no")) == no and _norm_article_no(str(r.get("madde_no"))) in hedef:
            return f"{i+1}"
    return "yok"


def main() -> None:
    db_path = Path(str(_yollar.CACHE_PATH))
    # search_madde ensure_schema (DDL) calistiriyor: rw baglanti gerekiyor.
    db = sqlite3.connect(str(db_path), timeout=180)
    db.execute("PRAGMA busy_timeout=180000")
    db.row_factory = sqlite3.Row

    st = ls.index_status(db_path)
    print("indeks:", st)
    # ısıtma (model + indeks yükleme gecikmeyi kirletmesin)
    ls.embed_query("ısınma")
    ls.search(db, db_path, ls.embed_query("ısınma"), limit=5)

    sonuc = []
    sureler = {"lexical": [], "semantic": [], "hybrid": []}
    for q, no, maddeler in SORGULAR:
        satir = {"sorgu": q, "bekl": f"{no} m.{','.join(maddeler) if maddeler else '?'}"}

        t = time.perf_counter()
        lex = search_madde(db, q, limit=20)
        sureler["lexical"].append((time.perf_counter() - t) * 1000)
        lexr = lex.get("results", [])
        satir["lexical"] = _hit(lexr, no, maddeler)

        t = time.perf_counter()
        qv = ls.embed_query(q)
        semr = ls.search(db, db_path, qv, limit=20) or []
        sureler["semantic"].append((time.perf_counter() - t) * 1000)
        satir["semantic"] = _hit(semr, no, maddeler)

        t = time.perf_counter()
        qv2 = ls.embed_query(q)
        s2 = ls.search(db, db_path, qv2, limit=20) or []
        l2 = search_madde(db, q, limit=20).get("results", [])
        hyb = ls.rrf_merge(l2, s2, limit=20)
        sureler["hybrid"].append((time.perf_counter() - t) * 1000)
        satir["hybrid"] = _hit(hyb, no, maddeler)

        if len(sys.argv) > 1 and sys.argv[1] == "-v":
            print("\n###", q)
            for ad, rs in (("LEX", lexr), ("SEM", semr), ("HYB", hyb)):
                print(" ", ad, [f"{r.get('mevzuat_no')}/{r.get('madde_no')}" for r in rs[:TOP]])
        sonuc.append(satir)

    print()
    print(f"{'sorgu':40s} {'beklenen':22s} {'lex':>5s} {'sem':>5s} {'hyb':>5s}")
    say = {"lexical": 0, "semantic": 0, "hybrid": 0}
    olcum = 0
    for s in sonuc:
        print(f"{s['sorgu'][:40]:40s} {s['bekl'][:22]:22s} "
              f"{s['lexical']:>5s} {s['semantic']:>5s} {s['hybrid']:>5s}")
        if s["lexical"] == "-":
            continue
        olcum += 1
        for m in say:
            if s[m] not in ("yok", "-"):
                say[m] += 1
    print(f"\nilk {TOP}'te bulunan / {olcum} ölçülebilir sorgu: "
          + ", ".join(f"{m}={say[m]}" for m in ("lexical", "semantic", "hybrid")))
    for m, v in sureler.items():
        v = sorted(v)
        print(f"gecikme {m}: medyan {v[len(v)//2]:.0f} ms, p90 {v[int(len(v)*0.9)]:.0f} ms")


if __name__ == "__main__":
    main()
