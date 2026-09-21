"""Zamanlanmis islerin (Windows Gorev Zamanlayici) son kosu durumu.

Neden schtasks degil: MCP sunucusu korpus makinesinde *Limited* butunlukte kosuyor;
``schtasks /query`` orada bazen calisir bazen yetki hatasi verir ve her
cagrida yeni bir surec baslatir (yavas).  Isler zaten her kosuda kendi log
dosyasina bir bitis isareti yaziyor; bu modul o isareti ve dosyanin son
yazilma zamanini okur.  Disariya surec baslatmaz, sadece dosya okur.

Log dizini: ``EMSAL_CRAWL_LOG_DIR`` (varsayilan: cache dosyasinin yanindaki
``crawl_logs``).  Dosya yoksa is "bilinmiyor" olarak raporlanir; bu tek
basina "bozuk" sayilmaz, cunku is henuz hic kosmamis olabilir.

Kullanan: ``server.health_check`` -> ``scheduled_jobs``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Log kuyrugundan en fazla bu kadar bayt okunur (isaret satirlari sondadir).
_TAIL_BYTES = 64 * 1024

# "Paz 06.09.2026 19:52:43,01" / "06.09.2026 19:52:43"
_TR_TS_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})")


@dataclass(frozen=True)
class JobSpec:
    """Bir zamanlanmis isin log imzasi."""

    key: str
    task: str                       # schtasks gorev adi (yalniz bilgi amacli)
    patterns: tuple[str, ...]       # log dosyasi glob'lari (oncelik sirasiyla)
    max_age_hours: float            # bu yasi asarsa "gecikmis"
    aciklama: str
    ok_markers: tuple[str, ...] = ()
    error_markers: tuple[str, ...] = ()
    exit_re: str | None = None      # ornek: r"WEEKLY-EXIT\s+(-?\d+)"
    exclude: tuple[str, ...] = ()   # glob'a takilan ama istenmeyen adlar
    marker_file: str | None = None  # rc'yi ayri dosyaya yazan isler icin
    marker_exit_re: str | None = None


JOBS: tuple[JobSpec, ...] = (
    JobSpec(
        key="crawl_daily",
        task="EmsalCrawlDaily",
        patterns=("crawl_*.log",),
        max_age_hours=36.0,
        aciklama="Gunluk artimli karar crawl'i (scripts/crawl_incremental.ps1)",
        ok_markers=("BITTI", "zaten calisiyor"),
        error_markers=(),
    ),
    JobSpec(
        key="mevzuat_weekly",
        task="EmsalMevzuatWeekly",
        patterns=("mevzuat_weekly.log",),
        max_age_hours=8 * 24.0,
        aciklama="Haftalik mevzuat guncellemesi (scripts/mevzuat_weekly.cmd)",
        exit_re=r"WEEKLY-EXIT\s+(-?\d+)",
    ),
    JobSpec(
        key="monthly_merge",
        task="EmsalMonthlyMerge",
        patterns=("monthly_*.log",),
        max_age_hours=35 * 24.0,
        aciklama="Aylik delta->toplu FAISS birlestirmesi (scripts/monthly_merge.cmd)",
        ok_markers=("BITTI", "delta bos"),
        error_markers=("GOMME HATASI", "APPEND HATASI"),
    ),
    JobSpec(
        key="mevzuat_semantic",
        task="EmsalMevzuatWeekly (art-islem) / mevzuat_semantic.cmd",
        patterns=("mevzuat_semantic_*.log",),
        exclude=("mevzuat_semantic_marker.log",),
        max_age_hours=8 * 24.0,
        aciklama="Mevzuat maddelerinin semantik indeksi (scripts/mevzuat_semantic.cmd)",
        ok_markers=("BITTI", "yeni madde yok"),
        error_markers=("GOMME HATASI", "INDEKS HATASI"),
        marker_file="mevzuat_semantic_marker.log",
        marker_exit_re=r"SEMANTIC-EXIT\s+(-?\d+)",
    ),
)


def get_log_dir() -> Path:
    """Zamanlanmis is loglarinin bulundugu dizin.

    ``EMSAL_CRAWL_LOG_DIR`` verilmisse o; degilse cache dosyasinin yanindaki
    ``crawl_logs``.
    """
    env = os.environ.get("EMSAL_CRAWL_LOG_DIR", "").strip()
    if env:
        return Path(env)
    cache = os.environ.get("EMSAL_CACHE_PATH", "").strip()
    if cache:
        return Path(cache).parent / "crawl_logs"
    try:
        from .config import config as _cfg

        return Path(_cfg.cache_path).parent / "crawl_logs"
    except Exception:  # pragma: no cover - config her zaman yuklenir
        return Path.home() / ".emsal_mcp" / "crawl_logs"


def _tail_text(path: Path, limit: int = _TAIL_BYTES) -> str:
    """Dosyanin son ``limit`` baytini metin olarak dondur (bozuk bayt yutulur).

    PowerShell'in ``Tee-Object``/``>`` cikti dosyalari UTF-16LE olabiliyor
    (olculdu: ``crawl_*.log``), cmd betiklerinin ``>>`` ciktilari ise ANSI/
    UTF-8.  Ikisi de okunur: NUL yogunlugu UTF-16 isaretidir.
    """
    try:
        size = path.stat().st_size
        offset = max(0, size - limit)
        with path.open("rb") as fh:
            if offset:
                fh.seek(offset)
            raw = fh.read()
    except OSError:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") and offset == 0:
        return raw.decode("utf-16", errors="replace")
    if raw.count(0) > len(raw) // 4:
        # UTF-16LE: cift bayt hizasina getir (dosya basindan sayarak).
        if offset % 2:
            raw = raw[1:]
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _newest(paths: list[Path]) -> Path | None:
    best: Path | None = None
    best_m = -1.0
    for p in paths:
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > best_m:
            best, best_m = p, m
    return best


def _find_log(spec: JobSpec, log_dir: Path) -> Path | None:
    for pattern in spec.patterns:
        try:
            hits = [
                p for p in log_dir.glob(pattern)
                if p.is_file() and p.name not in spec.exclude
            ]
        except OSError:
            hits = []
        newest = _newest(hits)
        if newest is not None:
            return newest
    return None


def _parse_tr_timestamp(line: str) -> str | None:
    """Windows ``%date% %time%`` damgasini ISO'ya cevir (yerel saat, tz yok)."""
    m = _TR_TS_RE.search(line)
    if not m:
        return None
    d, mo, y, hh, mm, ss = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, hh, mm, ss).isoformat()
    except ValueError:
        return None


def _classify(spec: JobSpec, text: str) -> tuple[str, str | None, int | None]:
    """(sonuc, isaret_satiri, rc) dondur."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # 1) Acik cikis kodu yazan isler
    if spec.exit_re:
        rx = re.compile(spec.exit_re)
        for ln in reversed(lines):
            m = rx.search(ln)
            if m:
                rc = int(m.group(1))
                return ("ok" if rc == 0 else "hata"), ln, rc
        return "yarim", (lines[-1] if lines else None), None

    # 2) Hata isaretleri (kosu icinde bir yerde gectiyse bitis satiri yaniltir)
    for ln in reversed(lines):
        for marker in spec.error_markers:
            if marker in ln:
                return "hata", ln, None

    # 3) Basari isaretleri
    for ln in reversed(lines):
        for marker in spec.ok_markers:
            if marker in ln:
                return "ok", ln, None

    return "yarim", (lines[-1] if lines else None), None


def read_job_status(spec: JobSpec, log_dir: Path | None = None,
                    now: datetime | None = None) -> dict[str, Any]:
    """Tek bir isin durumunu dondur.  Hicbir zaman istisna atmaz."""
    log_dir = log_dir if log_dir is not None else get_log_dir()
    now = now or datetime.now(timezone.utc)
    out: dict[str, Any] = {
        "gorev": spec.task,
        "aciklama": spec.aciklama,
        "beklenen_azami_saat": spec.max_age_hours,
        "son_kosu": None,
        "yas_saat": None,
        "sonuc": "bilinmiyor",
        "rc": None,
        "log": None,
        "isaret": None,
        "sorunlu": False,
    }

    path = _find_log(spec, log_dir)
    if path is None:
        out["not"] = f"log bulunamadi ({log_dir})"
        return out

    out["log"] = str(path)
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        mtime = None
    if mtime is not None:
        out["son_kosu"] = mtime.isoformat()
        out["yas_saat"] = round((now - mtime).total_seconds() / 3600.0, 2)

    text = _tail_text(path)
    sonuc, isaret, rc = _classify(spec, text)
    out["sonuc"] = sonuc
    out["isaret"] = isaret
    out["rc"] = rc
    if isaret:
        ts = _parse_tr_timestamp(isaret)
        if ts:
            out["isaret_zamani"] = ts

    # Ayri marker dosyasina yazilan cikis kodu (mevzuat_semantic)
    if spec.marker_file and spec.marker_exit_re:
        mpath = log_dir / spec.marker_file
        if mpath.is_file():
            rx = re.compile(spec.marker_exit_re)
            for ln in reversed(
                [x.strip() for x in _tail_text(mpath).splitlines() if x.strip()]
            ):
                m = rx.search(ln)
                if m:
                    mrc = int(m.group(1))
                    out["marker_rc"] = mrc
                    out["marker_isaret"] = ln
                    if mrc == 3 and "SEMANTIC-EXIT" in ln:
                        # mevzuat_semantic.cmd: 3 = yeni madde yok, indeks korundu
                        out["not"] = "yeni madde yok, indeks korundu (rc 3)"
                    elif mrc != 0:
                        out["sonuc"] = "hata"
                        out["rc"] = mrc
                    break

    gecikmis = (
        out["yas_saat"] is not None and out["yas_saat"] > spec.max_age_hours
    )
    out["gecikmis"] = gecikmis
    out["sorunlu"] = bool(gecikmis or out["sonuc"] == "hata")
    return out


def collect_scheduled_jobs(log_dir: Path | None = None,
                           now: datetime | None = None) -> dict[str, Any]:
    """Tum zamanlanmis islerin durumu: ``{is_adi: {...}}``."""
    log_dir = log_dir if log_dir is not None else get_log_dir()
    return {spec.key: read_job_status(spec, log_dir, now) for spec in JOBS}


def problem_jobs(jobs: dict[str, Any]) -> list[str]:
    """Gecikmis ya da hatali biten islerin adlari."""
    return sorted(k for k, v in jobs.items() if isinstance(v, dict) and v.get("sorunlu"))
