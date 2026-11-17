"""Yeniden sıralayıcı servisi: sorgu + pasajlar -> puanlar (bge-reranker-v2-m3, GPU).

Dayanak sunucusundan ayrı süreçte çalışır: torch ile faiss aynı süreçte çöküyor.
Parçalama ve metin seçimi Dayanak tarafında; servis yalnız puanlar.

  POST /rerank  {"query": "...", "passages": ["...", ...]}  ->  {"scores": [...], "ms": ...}
  GET  /health                                             ->  {"ok": true, "model": ..., "dtype": ..., "vram_mb": ...}

Ortam: DAYANAK_RERANK_HOST (127.0.0.1), DAYANAK_RERANK_PORT (8791),
DAYANAK_RERANK_MODEL (BAAI/bge-reranker-v2-m3), DAYANAK_RERANK_BATCH (32),
DAYANAK_RERANK_MAX_PASSAGES (600, tek istekte en çok pasaj).
Ölçüm ve kapı: docs/arama-kiyas-asama1.md (git dışı) ve eval/yerel/asama1.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from sentence_transformers import CrossEncoder

MODEL = os.environ.get("DAYANAK_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
BATCH = int(os.environ.get("DAYANAK_RERANK_BATCH", "32"))
MAX_PASSAGES = int(os.environ.get("DAYANAK_RERANK_MAX_PASSAGES", "600"))
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32

model = CrossEncoder(MODEL, device=DEVICE, max_length=512, model_kwargs={"dtype": DTYPE})
LOCK = threading.Lock()  # tek GPU: istekler sırayla


def vram_mb() -> int:
    return int(torch.cuda.memory_allocated() / 2**20) if DEVICE == "cuda" else 0


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            return self._send(404, {"ok": False})
        self._send(200, {"ok": True, "model": MODEL, "device": DEVICE,
                         "dtype": str(next(model.model.parameters()).dtype), "vram_mb": vram_mb()})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/rerank":
            return self._send(404, {"ok": False})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            query, passages = str(req["query"]), [str(p) for p in req["passages"]]
        except Exception as exc:  # bozuk istek
            return self._send(400, {"ok": False, "error": str(exc)[:200]})
        if len(passages) > MAX_PASSAGES:
            return self._send(413, {"ok": False, "error": f"en çok {MAX_PASSAGES} pasaj"})
        t = time.time()
        with LOCK:
            scores = model.predict([(query, p) for p in passages], batch_size=BATCH,
                                   show_progress_bar=False) if passages else []
            if DEVICE == "cuda":
                torch.cuda.empty_cache()  # boşta yalnız model kalsın (~1,1 GB); kart oyunla paylaşılıyor
        self._send(200, {"ok": True, "scores": [float(s) for s in scores],
                         "ms": round((time.time() - t) * 1000)})

    def log_message(self, *args) -> None:  # sorgu metni loga yazılmaz
        pass


if __name__ == "__main__":
    host = os.environ.get("DAYANAK_RERANK_HOST", "127.0.0.1")
    port = int(os.environ.get("DAYANAK_RERANK_PORT", "8791"))
    print(f"rerank servisi {host}:{port} {MODEL} {DEVICE} {DTYPE} vram {vram_mb()} MB", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
