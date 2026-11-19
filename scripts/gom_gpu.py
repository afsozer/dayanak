"""Belge başına tek vektör, GPU'da (torch/CUDA venv'i: <bench-dizini>/venv).

`embed_new_docs.py` bge-m3 gibi CPU'da yavaş sağlayıcılarda gömmeyi buraya devreder;
torch ve faiss aynı süreçte çöktüğü için ayrı süreç (bkz. monthly_merge.cmd).
Model, önek ve token sınırı toplu indeksle aynı (embed_delta_chunks.MODELLER).

    python gom_gpu.py --provider onnx-bge-m3 <metinler.json> <cikti.npy>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

import _yollar
from embed_delta_chunks import MODELLER


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("girdi")
    ap.add_argument("cikti")
    a = ap.parse_args()
    if a.provider not in MODELLER:
        sys.exit(f"bilinmeyen sağlayıcı: {a.provider}")
    model_adi, onek, max_token = MODELLER[a.provider]
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # model <bench>/models önbelleğinde; gece ağa çıkmasın
    import torch
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model_adi, device=a.device, cache_folder=str(_yollar.TORCH_MODEL_CACHE),
                            model_kwargs={"torch_dtype": torch.float16})
    m.max_seq_length = max_token
    metin = json.loads(Path(a.girdi).read_text(encoding="utf-8"))
    v = m.encode([onek + t for t in metin], batch_size=a.batch, normalize_embeddings=True,
                 convert_to_numpy=True, show_progress_bar=False)
    np.save(a.cikti, v.astype(np.float32))


if __name__ == "__main__":
    main()
