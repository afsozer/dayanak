"""Yeniden sıralayıcı servisinin istemcisi (servis: ``scripts/rerank_servis.py``, ayrı süreç, GPU).

``hybrid_search_rrf`` ``semantic_query`` verildiğinde RRF'nin ilk 20'sini buraya gönderir.
Her kararın metni parçalanır (chunking v2), sorguyla sözcük örtüşmesi en yüksek ``max_parca``
parça servise gider, karar puanı = parçalarının en yükseği. Servis yoksa, yavaşsa ya da hata
verirse ``None`` döner ve çağıran RRF sırasını korur.

Ortam: DAYANAK_RERANK_URL (ör. http://127.0.0.1:8791; boşsa kapalı),
DAYANAK_RERANK_TIMEOUT (sn, 8), DAYANAK_RERANK_MAX_PARCA (karar başına parça, 3).
Servis bir kez cevap vermezse ``BEKLEME`` saniye boyunca denenmez: kart oyunla
paylaşılıyor, her arama zaman aşımını beklemesin.
Ölçüm (17 Kas 2026, 155 sorgu, tam korpus): canlı yol nDCG@10 0,840 -> 0,905.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import unicodedata
import urllib.request
from typing import Any

from .chunking import chunk_text

BEKLEME = 60.0
_son_hata = 0.0


def ayarlar() -> tuple[str, float, int]:
    return (
        os.environ.get("DAYANAK_RERANK_URL", "").strip().rstrip("/"),
        float(os.environ.get("DAYANAK_RERANK_TIMEOUT", "8")),
        int(os.environ.get("DAYANAK_RERANK_MAX_PARCA", "3")),
    )


def _katla(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s.lower().replace("ı", "i").replace("İ", "i"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return {w for w in re.findall(r"\w+", s) if len(w) > 2}


def _metin(db: sqlite3.Connection, document_id: str, source: str) -> str:
    try:
        r = db.execute(
            "SELECT full_text, markdown FROM documents_v2 WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    if not r:
        return ""
    return r[0] if r[0] and len(r[0]) >= 50 else (r[1] or "")


def parcalar(metin: str, sorgu_kelime: set[str], max_parca: int) -> list[str]:
    """Kararın sorguyla en çok sözcük paylaşan ``max_parca`` parçası (0 = hepsi)."""
    ch = chunk_text(metin) if metin else []
    if max_parca <= 0 or len(ch) <= max_parca:
        return ch
    sira = sorted(range(len(ch)), key=lambda i: (-len(sorgu_kelime & _katla(ch[i])), i))
    return [ch[i] for i in sorted(sira[:max_parca])]


def yeniden_sirala(
    db: sqlite3.Connection,
    sorgu: str,
    anahtar: str,
    sonuclar: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Sonuçları servis puanına göre sıralar; (liste, None) ya da (None, uyarı)."""
    global _son_hata
    url, timeout, max_parca = ayarlar()
    if not url or not sonuclar:
        return None, None
    if time.monotonic() - _son_hata < BEKLEME:
        return None, "Yeniden sıralayıcı az önce cevap vermedi, bir süre denenmiyor; RRF sırası korundu."
    kelime = _katla(sorgu + " " + anahtar)
    sahip: list[int] = []
    pasaj: list[str] = []
    for i, r in enumerate(sonuclar):
        for p in parcalar(_metin(db, r.get("document_id", ""), r.get("source", "")), kelime, max_parca) or [""]:
            sahip.append(i)
            pasaj.append(p)
    try:
        req = urllib.request.Request(
            url + "/rerank",
            data=json.dumps({"query": sorgu, "passages": pasaj}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as yanit:
            puan = json.loads(yanit.read())["scores"]
        if len(puan) != len(pasaj):
            raise ValueError("puan sayısı pasaj sayısıyla uyuşmuyor")
    except Exception as exc:  # servis kapalı, yavaş ya da bozuk: RRF sırası kalır
        _son_hata = time.monotonic()
        return None, f"Yeniden sıralayıcı kullanılamadı ({type(exc).__name__}); RRF sırası korundu."
    en_iyi: dict[int, float] = {}
    for i, s in zip(sahip, puan):
        en_iyi[i] = max(en_iyi.get(i, float("-inf")), float(s))
    sira = sorted(range(len(sonuclar)), key=lambda i: -en_iyi.get(i, float("-inf")))
    return [{**sonuclar[i], "rerank_score": round(en_iyi.get(i, 0.0), 4)} for i in sira], None
