"""Betiklerin ortak yol varsayılanları — makineye özel değer repoya girmez.

Öncelik: ortam değişkeni > scripts/yerel-ayar.cmd içindeki ``set AD=deger``
satırları > ``~/.dayanak`` altından türetilen varsayılan. Böylece betik
``dayanak-env.cmd`` çağrılmadan elle çalıştırıldığında da aynı yolları bulur.
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
        if not m or not m.group(2):
            continue
        ad = _yeni_ad(m.group(1))
        if not os.environ.get(ad):
            os.environ[ad] = m.group(2)


def _yeni_ad(ad: str) -> str:
    """2.0.0 oncesi ``EMSAL_*`` adini ``DAYANAK_*`` karsiligina cevirir."""
    return "DAYANAK_" + ad[len("EMSAL_"):] if ad.startswith("EMSAL_") else ad


for _ad, _deger in list(os.environ.items()):
    if _ad.startswith("EMSAL_"):
        os.environ.setdefault(_yeni_ad(_ad), _deger)

_yerel_ayar_yukle()


def _env_yol(ad: str, varsayilan: Path) -> Path:
    deger = os.environ.get(ad, "").strip()
    return Path(deger) if deger else varsayilan


DATA_DIR = _env_yol("DAYANAK_DATA_DIR", Path.home() / ".dayanak")
BENCH_DIR = _env_yol("DAYANAK_BENCH_DIR", DATA_DIR / "bench")
HF_DIR = _env_yol("DAYANAK_HF_DIR", DATA_DIR / "hf-datasets" / "turkish-court-decisions")
LOG_DIR = _env_yol("DAYANAK_LOG_DIR", DATA_DIR / "crawl_logs")
CACHE_PATH = _env_yol("DAYANAK_CACHE_PATH", DATA_DIR / "cache.sqlite3")
VEC_DIR = _env_yol("DAYANAK_BULK_VEC_DIR", BENCH_DIR / "vec")
VEC2_DIR = BENCH_DIR / "vec2"
VEC_OLD_DIR = BENCH_DIR / "vec_v1"
STAGE_DIR = DATA_DIR / "staging"
MEVZUAT_VEC_DIR = DATA_DIR / "mevzuat-vec"
TORCH_MODEL_CACHE = BENCH_DIR / "models"
YEDEK_DIR = BENCH_DIR / "yedek"
