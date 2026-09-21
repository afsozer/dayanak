"""Betiklerin ortak yol varsayılanları — makineye özel değer repoya girmez.

Öncelik: ortam değişkeni > scripts/yerel-ayar.cmd içindeki ``set AD=deger``
satırları > ``~/.emsal_mcp`` altından türetilen varsayılan. Böylece betik
``emsal-env.cmd`` çağrılmadan elle çalıştırıldığında da aynı yolları bulur.
Şablon: scripts/yerel-ayar.ornek.cmd.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

_SET = re.compile(r"^\s*set\s+([A-Za-z_][A-Za-z0-9_]*)=(.*?)\s*$", re.IGNORECASE)


def _yerel_ayar_yukle() -> None:
    dosya = Path(__file__).resolve().parent / "yerel-ayar.cmd"
    if not dosya.is_file():
        return
    for satir in dosya.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SET.match(satir)
        if m and m.group(2) and not os.environ.get(m.group(1)):
            os.environ[m.group(1)] = m.group(2)


_yerel_ayar_yukle()


def _env_yol(ad: str, varsayilan: Path) -> Path:
    deger = os.environ.get(ad, "").strip()
    return Path(deger) if deger else varsayilan


DATA_DIR = _env_yol("EMSAL_DATA_DIR", Path.home() / ".emsal_mcp")
BENCH_DIR = _env_yol("EMSAL_BENCH_DIR", DATA_DIR / "bench")
HF_DIR = _env_yol("EMSAL_HF_DIR", DATA_DIR / "hf-datasets" / "turkish-court-decisions")
LOG_DIR = _env_yol("EMSAL_LOG_DIR", DATA_DIR / "crawl_logs")
CACHE_PATH = _env_yol("EMSAL_CACHE_PATH", DATA_DIR / "cache.sqlite3")
VEC_DIR = _env_yol("EMSAL_BULK_VEC_DIR", BENCH_DIR / "vec")
VEC2_DIR = BENCH_DIR / "vec2"
VEC_OLD_DIR = BENCH_DIR / "vec_v1"
STAGE_DIR = DATA_DIR / "staging"
MEVZUAT_VEC_DIR = DATA_DIR / "mevzuat-vec"
TORCH_MODEL_CACHE = BENCH_DIR / "models"
YEDEK_DIR = BENCH_DIR / "yedek"
