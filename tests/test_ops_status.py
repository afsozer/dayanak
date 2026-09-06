"""ops_status: zamanlanmis islerin log dosyalarindan okunan durumu.

Gercek log dizinine dokunmaz; her test kendi sahte dizinini kurar.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from emsal_mcp.ops_status import (
    JOBS,
    collect_scheduled_jobs,
    get_log_dir,
    problem_jobs,
)


def _write(path: Path, text: str, age_hours: float = 0.0) -> Path:
    path.write_text(text, encoding="utf-8")
    if age_hours:
        ts = datetime.now(timezone.utc).timestamp() - age_hours * 3600
        os.utime(path, (ts, ts))
    return path


# ── Log dizini cozumleme ─────────────────────────────────────────────────


def test_log_dir_env_wins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EMSAL_CRAWL_LOG_DIR", str(tmp_path / "loglar"))
    assert get_log_dir() == tmp_path / "loglar"


def test_log_dir_defaults_next_to_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("EMSAL_CRAWL_LOG_DIR", raising=False)
    monkeypatch.setenv("EMSAL_CACHE_PATH", str(tmp_path / "cache.sqlite3"))
    assert get_log_dir() == tmp_path / "crawl_logs"


# ── Log yoksa ────────────────────────────────────────────────────────────


def test_missing_log_dir_is_unknown_not_broken(tmp_path: Path) -> None:
    jobs = collect_scheduled_jobs(log_dir=tmp_path / "yok")
    assert set(jobs) == {spec.key for spec in JOBS}
    for key, info in jobs.items():
        assert info["sonuc"] == "bilinmiyor", key
        assert info["sorunlu"] is False, key
        assert info["son_kosu"] is None
        assert "log bulunamadi" in info["not"]
    assert problem_jobs(jobs) == []


# ── Gunluk crawl ─────────────────────────────────────────────────────────


def test_daily_crawl_fresh_bitti_is_ok(tmp_path: Path) -> None:
    _write(
        tmp_path / "crawl_20260906_0430.log",
        "04:30:01 basladi; ay=3\n04:31:09 crawl bitti: toplam yeni 0 karar\n04:31:09 BITTI\n",
        age_hours=2,
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["crawl_daily"]
    assert job["sonuc"] == "ok"
    assert job["isaret"].endswith("BITTI")
    assert job["gecikmis"] is False
    assert job["sorunlu"] is False
    assert 1.5 < job["yas_saat"] < 2.5
    assert job["log"].endswith("crawl_20260906_0430.log")


def test_daily_crawl_stale_is_degraded(tmp_path: Path) -> None:
    _write(tmp_path / "crawl_20260901_0430.log", "04:31:09 BITTI\n", age_hours=48)
    job = collect_scheduled_jobs(log_dir=tmp_path)["crawl_daily"]
    assert job["sonuc"] == "ok"
    assert job["gecikmis"] is True
    assert job["sorunlu"] is True
    assert "crawl_daily" in problem_jobs(collect_scheduled_jobs(log_dir=tmp_path))


def test_daily_crawl_without_bitti_is_half(tmp_path: Path) -> None:
    _write(tmp_path / "crawl_20260906_0430.log", "04:30:01 basladi; ay=3\n")
    job = collect_scheduled_jobs(log_dir=tmp_path)["crawl_daily"]
    assert job["sonuc"] == "yarim"
    assert job["sorunlu"] is False  # yasi taze; yarim kalmis olabilir, hata degil


def test_newest_log_wins(tmp_path: Path) -> None:
    _write(tmp_path / "crawl_20260901_0430.log", "BITTI\n", age_hours=100)
    _write(tmp_path / "crawl_20260906_0430.log", "BITTI\n", age_hours=1)
    job = collect_scheduled_jobs(log_dir=tmp_path)["crawl_daily"]
    assert job["log"].endswith("crawl_20260906_0430.log")
    assert job["gecikmis"] is False


# ── Haftalik mevzuat ─────────────────────────────────────────────────────


def test_weekly_exit_zero_is_ok(tmp_path: Path) -> None:
    _write(
        tmp_path / "mevzuat_weekly.log",
        "Paz 06.09.2026 03:00:01,10 haftalik deneme 1 basladi\n"
        "Paz 06.09.2026 03:12:44,02 WEEKLY-EXIT 0 \n",
        age_hours=20,
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["mevzuat_weekly"]
    assert job["sonuc"] == "ok"
    assert job["rc"] == 0
    assert job["sorunlu"] is False
    assert job["isaret_zamani"].startswith("2026-09-06T03:12:44")


def test_weekly_nonzero_exit_is_error(tmp_path: Path) -> None:
    _write(tmp_path / "mevzuat_weekly.log", "Paz 06.09.2026 03:12:44,02 WEEKLY-EXIT 3\n")
    jobs = collect_scheduled_jobs(log_dir=tmp_path)
    job = jobs["mevzuat_weekly"]
    assert job["sonuc"] == "hata"
    assert job["rc"] == 3
    assert job["sorunlu"] is True
    assert "mevzuat_weekly" in problem_jobs(jobs)


def test_weekly_stale_is_degraded(tmp_path: Path) -> None:
    _write(tmp_path / "mevzuat_weekly.log", "WEEKLY-EXIT 0\n", age_hours=9 * 24)
    job = collect_scheduled_jobs(log_dir=tmp_path)["mevzuat_weekly"]
    assert job["rc"] == 0
    assert job["gecikmis"] is True
    assert job["sorunlu"] is True


# ── Aylik birlestirme ────────────────────────────────────────────────────


def test_monthly_error_marker_beats_trailing_bitti(tmp_path: Path) -> None:
    _write(
        tmp_path / "monthly_20260901.log",
        "Cmt 05.09.2026 20:48:34,58 GOMME HATASI \n"
        "Cmt 05.09.2026 20:48:34,58 BITTI \n",
        age_hours=24,
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["monthly_merge"]
    assert job["sonuc"] == "hata"
    assert "GOMME HATASI" in job["isaret"]
    assert job["sorunlu"] is True


def test_monthly_empty_delta_is_ok(tmp_path: Path) -> None:
    _write(
        tmp_path / "monthly_20260901.log",
        "01.09.2026 02:00:00,00 basladi delta-20260901\n"
        "01.09.2026 02:00:04,00 delta bos, is yok\n"
        "01.09.2026 02:00:04,00 BITTI\n",
        age_hours=24,
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["monthly_merge"]
    assert job["sonuc"] == "ok"
    assert job["sorunlu"] is False


def test_monthly_stale_beyond_35_days(tmp_path: Path) -> None:
    _write(tmp_path / "monthly_20260701.log", "BITTI\n", age_hours=40 * 24)
    job = collect_scheduled_jobs(log_dir=tmp_path)["monthly_merge"]
    assert job["gecikmis"] is True
    assert job["sorunlu"] is True


# ── Mevzuat semantik indeksi ─────────────────────────────────────────────


def test_semantic_marker_file_is_not_the_run_log(tmp_path: Path) -> None:
    _write(tmp_path / "mevzuat_semantic_20260906-1952.log", "BITTI\n", age_hours=3)
    _write(
        tmp_path / "mevzuat_semantic_marker.log",
        "Paz 06.09.2026 19:52:43,01 SEMANTIC-EXIT 0 \n",
        age_hours=3,
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["mevzuat_semantic"]
    assert job["log"].endswith("mevzuat_semantic_20260906-1952.log")
    assert job["sonuc"] == "ok"
    assert job["marker_rc"] == 0
    assert job["sorunlu"] is False


def test_semantic_index_error_marker(tmp_path: Path) -> None:
    _write(
        tmp_path / "mevzuat_semantic_20260906-1952.log",
        "basladi\nINDEKS HATASI\nBITTI\n",
        age_hours=3,
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["mevzuat_semantic"]
    assert job["sonuc"] == "hata"
    assert job["sorunlu"] is True


def test_semantic_marker_nonzero_rc_overrides_ok(tmp_path: Path) -> None:
    _write(tmp_path / "mevzuat_semantic_20260906-1952.log", "BITTI\n", age_hours=3)
    _write(
        tmp_path / "mevzuat_semantic_marker.log",
        "Paz 06.09.2026 19:52:43,01 SEMANTIC-EXIT 1\n",
        age_hours=3,
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["mevzuat_semantic"]
    assert job["sonuc"] == "hata"
    assert job["rc"] == 1
    assert job["sorunlu"] is True


# ── Bozuk girdi ──────────────────────────────────────────────────────────


def test_unreadable_bytes_do_not_raise(tmp_path: Path) -> None:
    # cmd betiklerinin ANSI ciktisi: gecersiz UTF-8 baytlari (BOM degil)
    (tmp_path / "crawl_20260906_0430.log").write_bytes(b"\x81\x9d bozuk\nBITTI\n")
    job = collect_scheduled_jobs(log_dir=tmp_path)["crawl_daily"]
    assert job["sonuc"] == "ok"


def test_utf16_powershell_log_is_read(tmp_path: Path) -> None:
    """crawl_*.log dosyalarini PowerShell Tee-Object UTF-16LE yaziyor."""
    (tmp_path / "crawl_20260906_0430.log").write_bytes(
        "04:30:01 basladi\n04:31:09 BITTI\n".encode("utf-16-le")
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["crawl_daily"]
    assert job["sonuc"] == "ok"
    assert job["isaret"].endswith("BITTI")


def test_utf16_with_bom_is_read(tmp_path: Path) -> None:
    (tmp_path / "crawl_20260906_0430.log").write_bytes(
        b"\xff\xfe" + "04:31:09 BITTI\n".encode("utf-16-le")
    )
    job = collect_scheduled_jobs(log_dir=tmp_path)["crawl_daily"]
    assert job["sonuc"] == "ok"


def test_now_parameter_controls_age(tmp_path: Path) -> None:
    _write(tmp_path / "crawl_20260906_0430.log", "BITTI\n")
    future = datetime.now(timezone.utc) + timedelta(hours=40)
    job = collect_scheduled_jobs(log_dir=tmp_path, now=future)["crawl_daily"]
    assert job["yas_saat"] > 36
    assert job["sorunlu"] is True


@pytest.mark.parametrize("spec", JOBS, ids=lambda s: s.key)
def test_every_job_declares_a_threshold_and_task(spec) -> None:
    assert spec.max_age_hours > 0
    assert spec.task
    assert spec.patterns
