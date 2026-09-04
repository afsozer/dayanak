"""Emsal kütüphane paneli — yerel web arayüzü.

Tarayıcıdan açılan tek sayfalık bir gösterge paneli: crawl çalışıyor mu, hangi
yıl/sayfada, ne hızla ilerliyor, kütüphanede ne var. Ek bağımlılık yok
(standart kütüphane); hedef ölçümü için emsal_mcp içe aktarılır ama zorunlu
değildir.

    .venv\\Scripts\\python.exe scripts\\panel.py
    → http://127.0.0.1:8799

NEDEN AYRI BİR SAYAÇ VERİTABANI: cache.sqlite3 21 GB. "2023 yılında kaç karar
var" sorgusu tam tablo taraması gerektirdiği için tek başına ~60 saniye sürüyor
(ölçüldü). Panel bunu her istekte yapamaz. Bu yüzden sayımlar
~/.emsal-mcp/panel_stats.sqlite3 içinde tutulur ve arka planda yalnızca YENİ
satırlar (rowid > son_görülen) taranarak güncellenir. documents_v2 upsert
kullandığı için (ON CONFLICT DO UPDATE) rowid'ler kararlı; yine de güncellenen
ya da silinen satırların yaratabileceği kaymayı temizlemek için günde bir kez
tam sayım yapılır.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "crawl_logs"
STATUS_FILE = LOG_DIR / "crawl_status.json"
STATE_FILE = LOG_DIR / "crawl_state.json"
TARGET_FILE = LOG_DIR / "hedefler.json"
MASTER_PS1 = ROOT / "crawl_master.ps1"

EMSAL_HOME = Path.home() / ".emsal-mcp"
CACHE_DB = EMSAL_HOME / "cache.sqlite3"
RATE_FILE = EMSAL_HOME / ".rate_limit.json"
STATS_DB = EMSAL_HOME / "panel_stats.sqlite3"

RATE_HOST = "bedesten.adalet.gov.tr"
REFRESH_SECONDS = 60
FULL_REBUILD_SECONDS = 24 * 3600
SAMPLE_KEEP_DAYS = 60
TASK_NAME = "EmsalCrawlMaster"

# Panelin ilerleme çubuğu çizeceği görevler — crawl_master.ps1 ile aynı sıra.
TASKS = [
    ("YARGITAYKARARI", "2023"),
    ("YARGITAYKARARI", "2022"),
    ("YARGITAYKARARI", "2021"),
    ("YARGITAYKARARI", "2024"),
    ("YARGITAYKARARI", "2025"),
]

# item_type → documents_v2.court değeri (yıl sayımlarını eşlemek için)
COURT_OF_TYPE = {
    "YARGITAYKARARI": "Yargıtay Kararı",
    "ISTINAFHUKUK": "İstinaf Hukuk Mahkemesi Kararı",
    "DANISTAYKARAR": "Danıştay Kararı",
}


# ─────────────────────────── yardımcılar ────────────────────────────────────

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def process_alive(pid: int) -> bool:
    """PID yaşıyor mu (Windows).

    os.kill(pid, 0) KULLANILMAZ: Windows'ta CPython bunu TerminateProcess'e
    çevirir, yani süreci öldürür. OpenProcess + GetExitCodeProcess güvenli yol.
    """
    if not pid or pid <= 0:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def year_of(decision_date: str | None) -> str | None:
    """'25.02.2026' → '2026'. Bozuk/eksik tarihte None."""
    if not decision_date or len(decision_date) < 4:
        return None
    y = decision_date[-4:]
    return y if y.isdigit() else None


# ─────────────────────────── sayım deposu ───────────────────────────────────

class StatsStore:
    """documents_v2 sayımlarının artımlı olarak tutulduğu küçük yan veritabanı."""

    def __init__(self) -> None:
        STATS_DB.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        db = sqlite3.connect(STATS_DB, check_same_thread=False)
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS court_counts (court TEXT PRIMARY KEY, n INTEGER);
            CREATE TABLE IF NOT EXISTS year_counts (
                court TEXT, year TEXT, n INTEGER, PRIMARY KEY (court, year));
            CREATE TABLE IF NOT EXISTS status_counts (status TEXT PRIMARY KEY, n INTEGER);
            CREATE TABLE IF NOT EXISTS source_counts (source TEXT PRIMARY KEY, n INTEGER);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS samples (ts INTEGER PRIMARY KEY, total INTEGER);
            """
        )
        db.commit()
        self.db = db

    # -- meta --
    def get_meta(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    # -- güncelleme --
    def update(self, full: bool = False) -> dict:
        """Cache'ten yeni satırları oku, sayaçları güncelle. Snapshot döndür."""
        if not CACHE_DB.exists():
            return {"hata": "cache.sqlite3 bulunamadı"}

        started = time.time()
        src = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True, timeout=120)
        try:
            src.execute("PRAGMA query_only=1")
            total = src.execute("SELECT count(*) FROM documents_v2").fetchone()[0]

            with self.lock:
                last_rowid = int(self.get_meta("last_rowid", "0") or 0)
                if full:
                    last_rowid = 0
                    for t in ("court_counts", "year_counts", "status_counts", "source_counts"):
                        self.db.execute(f"DELETE FROM {t}")

                courts: Counter = Counter()
                years: Counter = Counter()
                statuses: Counter = Counter()
                sources: Counter = Counter()
                seen = 0
                max_rowid = last_rowid

                cur = src.execute(
                    "SELECT rowid, court, decision_date, content_status, source "
                    "FROM documents_v2 WHERE rowid > ? ORDER BY rowid",
                    (last_rowid,),
                )
                for rid, court, ddate, cstatus, source in cur:
                    seen += 1
                    max_rowid = max(max_rowid, rid)
                    c = court or "(bilinmiyor)"
                    courts[c] += 1
                    statuses[cstatus or "(bilinmiyor)"] += 1
                    sources[source or "(bilinmiyor)"] += 1
                    y = year_of(ddate)
                    if y:
                        years[(c, y)] += 1

                for c, n in courts.items():
                    self.db.execute(
                        "INSERT INTO court_counts(court,n) VALUES(?,?) "
                        "ON CONFLICT(court) DO UPDATE SET n=n+excluded.n", (c, n))
                for (c, y), n in years.items():
                    self.db.execute(
                        "INSERT INTO year_counts(court,year,n) VALUES(?,?,?) "
                        "ON CONFLICT(court,year) DO UPDATE SET n=n+excluded.n", (c, y, n))
                for s, n in statuses.items():
                    self.db.execute(
                        "INSERT INTO status_counts(status,n) VALUES(?,?) "
                        "ON CONFLICT(status) DO UPDATE SET n=n+excluded.n", (s, n))
                for s, n in sources.items():
                    self.db.execute(
                        "INSERT INTO source_counts(source,n) VALUES(?,?) "
                        "ON CONFLICT(source) DO UPDATE SET n=n+excluded.n", (s, n))

                self.set_meta("last_rowid", max_rowid)
                self.set_meta("total", total)
                self.set_meta("updated_at", now_iso())
                if full:
                    self.set_meta("full_rebuild_at", now_iso())
                elif not self.get_meta("full_rebuild_at"):
                    self.set_meta("full_rebuild_at", now_iso())

                ts = int(time.time())
                self.db.execute(
                    "INSERT INTO samples(ts,total) VALUES(?,?) "
                    "ON CONFLICT(ts) DO UPDATE SET total=excluded.total", (ts, total))
                self.db.execute(
                    "DELETE FROM samples WHERE ts < ?", (ts - SAMPLE_KEEP_DAYS * 86400,))
                self.db.commit()

            return {
                "toplam": total,
                "yeni_satir": seen,
                "sure_sn": round(time.time() - started, 1),
                "tam_sayim": full,
            }
        finally:
            src.close()

    # -- okuma --
    def snapshot(self) -> dict:
        with self.lock:
            courts = self.db.execute(
                "SELECT court, n FROM court_counts ORDER BY n DESC").fetchall()
            years = self.db.execute(
                "SELECT court, year, n FROM year_counts").fetchall()
            statuses = self.db.execute(
                "SELECT status, n FROM status_counts ORDER BY n DESC").fetchall()
            sources = self.db.execute(
                "SELECT source, n FROM source_counts ORDER BY n DESC").fetchall()
            total = int(self.get_meta("total", "0") or 0)
            updated = self.get_meta("updated_at")
            full_at = self.get_meta("full_rebuild_at")

        yil_map: dict[str, dict[str, int]] = {}
        for court, year, n in years:
            # 1900-2100 dışı tarihler UYAP verisindeki bozuk kayıtlar — gösterme
            if not (1900 <= int(year) <= 2100):
                continue
            yil_map.setdefault(court, {})[year] = n

        return {
            "toplam": total,
            "mahkemeler": [{"ad": c, "n": n} for c, n in courts],
            "yillar": yil_map,
            "icerik_durumu": [{"ad": s, "n": n} for s, n in statuses],
            "kaynaklar": [{"ad": s, "n": n} for s, n in sources],
            "guncellendi": updated,
            "tam_sayim": full_at,
            "db_boyut_gb": round(CACHE_DB.stat().st_size / 1024**3, 2) if CACHE_DB.exists() else 0,
        }

    def hiz(self) -> dict:
        """Örneklerden saatlik hız ve toplam artış."""
        now = int(time.time())
        with self.lock:
            rows = self.db.execute(
                "SELECT ts, total FROM samples ORDER BY ts").fetchall()
        if len(rows) < 2:
            return {"son_1_saat": None, "son_24_saat": None, "ortalama_saatlik": None,
                    "olcum_suresi_saat": 0}

        son_ts, son_total = rows[-1]

        def delta(pencere: int):
            hedef = now - pencere
            adaylar = [r for r in rows if r[0] <= hedef]
            if not adaylar:
                return None
            t0, v0 = adaylar[-1]
            gecen = son_ts - t0
            if gecen < pencere * 0.5:   # yeterince geriye giden örnek yok
                return None
            return {"belge": son_total - v0, "saat": round(gecen / 3600, 1),
                    "saatlik": round((son_total - v0) / (gecen / 3600))}

        ilk_ts, ilk_v = rows[0]
        toplam_saat = (son_ts - ilk_ts) / 3600
        return {
            "son_1_saat": delta(3600),
            "son_24_saat": delta(86400),
            "ortalama_saatlik": round((son_total - ilk_v) / toplam_saat) if toplam_saat > 0.5 else None,
            "olcum_suresi_saat": round(toplam_saat, 1),
        }


# ─────────────────────────── crawl durumu ───────────────────────────────────

def rate_limit_durumu() -> dict:
    data = read_json(RATE_FILE) or {}
    st = data.get(RATE_HOST) or {}
    times = [float(t) for t in st.get("times", [])]
    cooldown = float(st.get("cooldown_until", 0) or 0)
    now = time.time()
    return {
        "son_istek_sn_once": round(now - max(times)) if times else None,
        "pencerede_istek": sum(1 for t in times if now - t < 31),
        "cooldown_kaldi_sn": max(0, round(cooldown - now)),
        "cooldown_yasandi": cooldown > 0,
    }


LOG_SATIR = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ")


def son_log_satirlari(item_type: str, year: str, adet: int = 12) -> list[str]:
    path = LOG_DIR / f"crawl_{item_type}_{year}.txt"
    if not path.exists():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            boyut = fh.tell()
            fh.seek(max(0, boyut - 120_000))
            ham = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    satirlar = [s.rstrip() for s in ham.splitlines() if LOG_SATIR.match(s)]
    return satirlar[-adet:]


def crawl_durumu() -> dict:
    status = read_json(STATUS_FILE) or {}
    state = read_json(STATE_FILE) or {}
    pid = int(status.get("pid") or 0)
    calisiyor = process_alive(pid)
    rate = rate_limit_durumu()

    phase = status.get("phase") or "bilinmiyor"
    if not calisiyor:
        durum = "bitti" if phase == "bitti" else "durdu"
    elif phase == "bekleme":
        durum = "bekliyor"
    else:
        durum = "calisiyor"

    item_type = status.get("item_type") or (TASKS[0][0])
    year = str(status.get("year") or TASKS[0][1])

    return {
        "durum": durum,
        "calisiyor": calisiyor,
        "pid": pid,
        "item_type": item_type,
        "yil": year,
        "sayfa": status.get("page") or state.get("page") or 1,
        "gorev_no": (status.get("task_index") or 0) + 1,
        "gorev_toplam": status.get("task_total") or len(TASKS),
        "tamamlanan": status.get("completed") or state.get("completed") or [],
        "son_stored": status.get("last_stored"),
        "son_stopped": status.get("last_stopped"),
        "son_hata": status.get("last_error") or "",
        "bekleme_sebebi": status.get("wait_reason") or "",
        "bekleme_bitis": status.get("wait_until") or "",
        "oturum_stored": status.get("session_stored"),
        "retries_429": status.get("retries_429"),
        "rate_limit_max": status.get("rate_limit_max"),
        "baslangic": status.get("started_at"),
        "guncelleme": status.get("updated_at"),
        "cagri_basladi": status.get("call_started"),
        "docs_per_call": status.get("docs_per_call"),
        "rate": rate,
        "log": son_log_satirlari(item_type, year),
    }


# ─────────────────────────── hedefler ───────────────────────────────────────

def hedefleri_oku() -> dict:
    return read_json(TARGET_FILE) or {}


def hedef_olc(item_type: str, year: str) -> dict:
    """Bedesten'e TEK arama isteği atıp o yılın gerçek karar sayısını öğrenir.

    Aynı rate limiter dosyasını kullandığı için crawl ile çakışmaz; istek
    sırası paylaşılan pencereye göre beklemeye alınır.
    """
    import asyncio

    src_dir = str(ROOT / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    os.environ.setdefault("EMSAL_RATE_LIMIT_MAX", "12")
    from emsal_mcp.sources.registry import get_source  # noqa: E402

    async def _run():
        client = get_source("bedesten")
        # search() yalnız sonuç listesi döndürür; toplam sayı search_page()'te.
        return await client.search_page(
            "karar", limit=1, page=1, item_type=item_type, sort_direction="desc",
            start_date=f"{year}-01-01T00:00:00.000Z",
            end_date=f"{year}-12-31T23:59:59.999Z",
        )

    res = asyncio.run(_run())
    total = getattr(res, "total", None)
    if not isinstance(total, int):
        raise RuntimeError("Bedesten total döndürmedi")

    hedefler = hedefleri_oku()
    hedefler[f"{item_type} {year}"] = {"toplam": total, "olculdu": now_iso()}
    write_json(TARGET_FILE, hedefler)
    return {"item_type": item_type, "yil": year, "toplam": total}


# ─────────────────────────── toplu durum ────────────────────────────────────

def gorev_ilerlemesi(stats: dict, hedefler: dict, aktif: dict) -> list[dict]:
    out = []
    for i, (item_type, year) in enumerate(TASKS):
        court = COURT_OF_TYPE.get(item_type, item_type)
        mevcut = (stats.get("yillar", {}).get(court, {}) or {}).get(year)
        hedef = (hedefler.get(f"{item_type} {year}") or {}).get("toplam")
        tamamlandi = f"{item_type} {year}" in (aktif.get("tamamlanan") or [])
        out.append({
            "item_type": item_type, "yil": year, "court": court,
            "mevcut": mevcut or 0, "hedef": hedef,
            "yuzde": round(100 * (mevcut or 0) / hedef, 1) if hedef else None,
            "aktif": (aktif.get("gorev_no") == i + 1) and aktif.get("calisiyor"),
            "tamamlandi": tamamlandi,
        })
    return out


def tam_durum(store: StatsStore) -> dict:
    stats = store.snapshot()
    crawl = crawl_durumu()
    hedefler = hedefleri_oku()
    gorevler = gorev_ilerlemesi(stats, hedefler, crawl)
    hiz = store.hiz()

    kalan = sum(max(0, (g["hedef"] or 0) - g["mevcut"]) for g in gorevler if g["hedef"])
    bilinmeyen = [f'{g["item_type"]} {g["yil"]}' for g in gorevler if not g["hedef"]]
    saatlik = None
    for anahtar in ("son_24_saat", "son_1_saat"):
        d = hiz.get(anahtar)
        if d and d.get("saatlik", 0) > 0:
            saatlik = d["saatlik"]
            break
    if saatlik is None and hiz.get("ortalama_saatlik"):
        saatlik = hiz["ortalama_saatlik"]

    tahmin = None
    if kalan and saatlik and saatlik > 0:
        gun = kalan / saatlik / 24
        tahmin = {
            "kalan_belge": kalan,
            "saatlik": saatlik,
            "gun": round(gun, 1),
            "hedefi_bilinmeyen": bilinmeyen,
        }

    return {
        "zaman": now_iso(),
        "crawl": crawl,
        "kutuphane": stats,
        "gorevler": gorevler,
        "hiz": hiz,
        "tahmin": tahmin,
    }


# ─────────────────────────── arka plan iş parçacığı ─────────────────────────

class Refresher(threading.Thread):
    daemon = True

    def __init__(self, store: StatsStore) -> None:
        super().__init__(name="refresher")
        self.store = store
        self.son_hata = ""
        self.zorla_tam = False

    def run(self) -> None:
        while True:
            try:
                full = self.zorla_tam or not self.store.get_meta("full_rebuild_at")
                if not full:
                    try:
                        onceki = datetime.fromisoformat(self.store.get_meta("full_rebuild_at"))
                        yas = (datetime.now(timezone.utc) - onceki.astimezone(timezone.utc))
                        full = yas.total_seconds() > FULL_REBUILD_SECONDS
                    except Exception:
                        full = True
                self.zorla_tam = False
                self.store.update(full=full)
                self.son_hata = ""
                self._eksik_hedef_olc()
            except Exception as exc:  # panel asla ölmesin
                self.son_hata = f"{type(exc).__name__}: {exc}"
            time.sleep(REFRESH_SECONDS)

    def _eksik_hedef_olc(self) -> None:
        """Döngü başına en fazla bir yılın hedefini ölç (UYAP'ı yormamak için)."""
        if rate_limit_durumu()["cooldown_kaldi_sn"] > 0:
            return
        hedefler = hedefleri_oku()
        for item_type, year in TASKS:
            if f"{item_type} {year}" not in hedefler:
                try:
                    hedef_olc(item_type, year)
                except Exception as exc:
                    self.son_hata = f"hedef ölçülemedi ({item_type} {year}): {exc}"
                return


# ─────────────────────────── crawl kontrolü ─────────────────────────────────

def crawl_baslat() -> dict:
    """Zamanlanmış görevi çalıştırır; yoksa script'i doğrudan başlatır."""
    r = subprocess.run(["schtasks", "/run", "/tn", TASK_NAME],
                       capture_output=True, text=True, shell=False)
    if r.returncode == 0:
        return {"ok": True, "yol": "zamanlanmis_gorev"}
    p = subprocess.Popen(
        ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(MASTER_PS1)],
        cwd=str(ROOT), creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    return {"ok": True, "yol": "dogrudan", "pid": p.pid,
            "not": r.stderr.strip()[:200]}


def crawl_durdur() -> dict:
    """Crawl'i durdurur.

    Önce zamanlanmış görevi düzgün biçimde sonlandırır: süreci doğrudan
    öldürmek görevi "başarısız" saydırır ve Task Scheduler 5 dk sonra yeniden
    başlatır. Artakalan süreçler yine de temizlenir.
    """
    r = subprocess.run(["schtasks", "/end", "/tn", TASK_NAME],
                       capture_output=True, text=True)
    status = read_json(STATUS_FILE) or {}
    pid = int(status.get("pid") or 0)
    if pid and process_alive(pid):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, text=True)
    subprocess.run(["taskkill", "/F", "/IM", "emsal-mcp.exe"],
                   capture_output=True, text=True)
    return {"ok": True, "pid": pid, "gorev_sonlandirildi": r.returncode == 0,
            "not": "Durduruldu. Kalıcı kapatmak için: "
                   "scripts\\kur-otomatik-baslatma.ps1 -Kaldir"}


# ─────────────────────────── HTTP ───────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "EmsalPanel"
    store: StatsStore
    refresher: Refresher

    def log_message(self, fmt, *args):  # konsolu kirletme
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        yol = parsed.path
        if yol == "/":
            return self._html(SAYFA)
        if yol == "/api/durum":
            veri = tam_durum(self.store)
            veri["panel"] = {"son_hata": self.refresher.son_hata}
            return self._json(veri)
        if yol == "/api/saglik":
            return self._json({"ok": True, "zaman": now_iso()})
        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        yol = parsed.path
        try:
            if yol == "/api/baslat":
                return self._json(crawl_baslat())
            if yol == "/api/durdur":
                return self._json(crawl_durdur())
            if yol == "/api/tam-sayim":
                self.refresher.zorla_tam = True
                return self._json({"ok": True, "not": "Tam sayım sıraya alındı (~1-2 dk)."})
            if yol == "/api/hedef-olc":
                q = urllib.parse.parse_qs(parsed.query)
                it = (q.get("type") or [TASKS[0][0]])[0]
                yil = (q.get("yil") or [TASKS[0][1]])[0]
                return self._json(hedef_olc(it, yil))
        except Exception as exc:
            return self._json({"ok": False, "hata": f"{type(exc).__name__}: {exc}"}, 500)
        self.send_error(404)


SAYFA = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Emsal Kütüphane Paneli</title>
<style>
  :root{
    --bg:#0f1115; --kart:#171a21; --cizgi:#262b36; --metin:#e6e9ef;
    --soluk:#8b93a7; --yesil:#3fb950; --sari:#d29922; --kirmizi:#f85149;
    --mavi:#4c8dff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--metin);
       font:15px/1.5 "Segoe UI",system-ui,sans-serif}
  header{display:flex;align-items:center;gap:16px;padding:18px 24px;
         border-bottom:1px solid var(--cizgi);position:sticky;top:0;
         background:rgba(15,17,21,.94);backdrop-filter:blur(6px);z-index:5}
  h1{font-size:17px;margin:0;font-weight:600;letter-spacing:.2px}
  .pill{padding:4px 12px;border-radius:999px;font-size:13px;font-weight:600}
  .pill.calisiyor{background:rgba(63,185,80,.15);color:var(--yesil)}
  .pill.bekliyor{background:rgba(210,153,34,.15);color:var(--sari)}
  .pill.durdu{background:rgba(248,81,73,.15);color:var(--kirmizi)}
  .pill.bitti{background:rgba(76,141,255,.15);color:var(--mavi)}
  .sag{margin-left:auto;display:flex;gap:8px;align-items:center}
  button{background:#222835;color:var(--metin);border:1px solid var(--cizgi);
         padding:6px 14px;border-radius:7px;cursor:pointer;font-size:13px}
  button:hover{background:#2b3243;border-color:#3d4557}
  button.tehlike{color:var(--kirmizi)}
  main{padding:22px;display:grid;gap:18px;
       grid-template-columns:repeat(auto-fit,minmax(370px,1fr));max-width:1500px}
  .kart{background:var(--kart);border:1px solid var(--cizgi);border-radius:12px;
        padding:18px 20px}
  .kart h2{font-size:12px;text-transform:uppercase;letter-spacing:.9px;
           color:var(--soluk);margin:0 0 14px;font-weight:600}
  .genis{grid-column:1/-1}
  .buyuk{font-size:38px;font-weight:650;letter-spacing:-1px;line-height:1.1}
  .alt{color:var(--soluk);font-size:13px}
  table{width:100%;border-collapse:collapse;font-size:14px}
  td{padding:5px 0;vertical-align:top}
  td.e{color:var(--soluk);white-space:nowrap;padding-right:14px;width:1%}
  td.s{text-align:right;font-variant-numeric:tabular-nums}
  .cubuk{height:7px;background:#20242e;border-radius:99px;overflow:hidden;margin-top:6px}
  .cubuk > i{display:block;height:100%;background:linear-gradient(90deg,#4c8dff,#3fb950)}
  .gorev{padding:11px 0;border-bottom:1px solid var(--cizgi)}
  .gorev:last-child{border-bottom:0}
  .gorev .ust{display:flex;justify-content:space-between;font-size:14px;gap:10px}
  .rozet{font-size:11px;padding:2px 8px;border-radius:99px;background:#232936;
         color:var(--soluk)}
  .rozet.aktif{background:rgba(63,185,80,.15);color:var(--yesil)}
  .rozet.bitti{background:rgba(76,141,255,.15);color:var(--mavi)}
  pre{background:#10131a;border:1px solid var(--cizgi);border-radius:8px;
      padding:12px;overflow-x:auto;font-size:12.5px;color:#b9c2d4;margin:0;
      max-height:270px;overflow-y:auto}
  .nokta{display:inline-block;width:8px;height:8px;border-radius:99px;margin-right:7px}
  .yesil{background:var(--yesil)} .sari{background:var(--sari)}
  .kirmizi{background:var(--kirmizi)} .mavi{background:var(--mavi)}
  .hata{color:var(--kirmizi);font-size:13px;margin-top:8px}
  .iki{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:600px){.iki{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1>Emsal Kütüphane Paneli</h1>
  <span id="pill" class="pill durdu">yükleniyor</span>
  <span class="alt" id="ozet"></span>
  <div class="sag">
    <span class="alt" id="zaman"></span>
    <button onclick="cagir('/api/baslat')">Başlat</button>
    <button class="tehlike" onclick="if(confirm('Crawl durdurulsun mu?'))cagir('/api/durdur')">Durdur</button>
    <button onclick="cagir('/api/tam-sayim')">Tam sayım</button>
  </div>
</header>

<main>
  <div class="kart">
    <h2>Crawl</h2>
    <div id="crawl"></div>
  </div>

  <div class="kart">
    <h2>Hız ve tahmin</h2>
    <div id="hiz"></div>
  </div>

  <div class="kart">
    <h2>Kütüphane</h2>
    <div id="kutuphane"></div>
  </div>

  <div class="kart">
    <h2>Yıl hedefleri</h2>
    <div id="gorevler"></div>
  </div>

  <div class="kart genis">
    <h2>Yargıtay / İstinaf yıl dağılımı</h2>
    <div class="iki">
      <div id="yilYargitay"></div>
      <div id="yilIstinaf"></div>
    </div>
  </div>

  <div class="kart genis">
    <h2>Son crawl kaydı</h2>
    <pre id="log"></pre>
  </div>
</main>

<script>
const sayi = n => (n===null||n===undefined) ? "—" : n.toLocaleString("tr-TR");
const el = id => document.getElementById(id);

async function cagir(yol){
  try{
    const r = await fetch(yol,{method:"POST"});
    const j = await r.json();
    if(j.hata) alert("Hata: "+j.hata);
    else if(j.not) alert(j.not);
    yenile();
  }catch(e){ alert("İstek başarısız: "+e); }
}

function tablo(satirlar){
  return "<table>"+satirlar.map(([a,b])=>
    `<tr><td class="e">${a}</td><td class="s">${b}</td></tr>`).join("")+"</table>";
}

function crawlKarti(c){
  const r = c.rate || {};
  const nokta = {calisiyor:"yesil",bekliyor:"sari",durdu:"kirmizi",bitti:"mavi"}[c.durum];
  const canli = r.son_istek_sn_once===null ? "—"
    : (r.son_istek_sn_once < 90 ? `${r.son_istek_sn_once} sn önce` :
       `${Math.round(r.son_istek_sn_once/60)} dk önce`);
  let s = [
    ["Görev", `${c.item_type} ${c.yil} &nbsp;<span class="alt">(${c.gorev_no}/${c.gorev_toplam})</span>`],
    ["Sayfa", sayi(c.sayfa)],
    ["Son UYAP isteği", `<span class="nokta ${r.son_istek_sn_once!==null&&r.son_istek_sn_once<90?"yesil":"kirmizi"}"></span>${canli}`],
    ["İstek penceresi", `${r.pencerede_istek ?? "—"} / ${c.rate_limit_max ?? "12"} (31 sn)`],
    ["429 bekleme", r.cooldown_kaldi_sn ? `${r.cooldown_kaldi_sn} sn` : "yok"],
    ["429 yeniden deneme", `${sayi(c.retries_429)} <span class="alt">(bu oturum)</span>`],
    ["Süren çağrı", c.cagri_basladi
        ? `${Math.round((Date.now()-new Date(c.cagri_basladi))/60000)} dk · en fazla ${sayi(c.docs_per_call)} belge`
        : "—"],
    ["Biten son çağrı", `+${sayi(c.son_stored)} belge · ${c.son_stopped||"—"}`],
    ["Bu oturumda", `+${sayi(c.oturum_stored)} belge`],
    ["PID", c.pid ? c.pid : "—"],
  ];
  if(c.bekleme_sebebi) s.push(["Bekleme", c.bekleme_sebebi]);
  let h = `<div class="buyuk"><span class="nokta ${nokta}"></span>${
      {calisiyor:"Çalışıyor",bekliyor:"Bekliyor",durdu:"Durdu",bitti:"Tamamlandı"}[c.durum]
    }</div><div class="alt" style="margin-bottom:12px">Son durum güncellemesi: ${
      c.guncelleme ? new Date(c.guncelleme).toLocaleString("tr-TR") : "—"}</div>`;
  h += tablo(s);
  if(c.son_hata) h += `<div class="hata">⚠ ${c.son_hata}</div>`;
  if(!c.calisiyor && c.durum==="durdu")
    h += `<div class="hata">Crawl çalışmıyor — "Başlat" ile sürdürebilirsin.</div>`;
  return h;
}

function hizKarti(d){
  const f = x => x ? `${sayi(x.saatlik)}/saat <span class="alt">(${sayi(x.belge)} belge / ${x.saat} sa)</span>` : "—";
  let s = [
    ["Son 1 saat", f(d.hiz.son_1_saat)],
    ["Son 24 saat", f(d.hiz.son_24_saat)],
    ["Ortalama", d.hiz.ortalama_saatlik ? `${sayi(d.hiz.ortalama_saatlik)}/saat` : "—"],
    ["Ölçüm süresi", `${d.hiz.olcum_suresi_saat} saat`],
  ];
  let h = tablo(s);
  if(d.tahmin){
    h += `<div style="margin-top:14px" class="buyuk">${d.tahmin.gun} gün</div>
          <div class="alt">kalan ${sayi(d.tahmin.kalan_belge)} belge · ${sayi(d.tahmin.saatlik)}/saat varsayımıyla</div>`;
    if(d.tahmin.hedefi_bilinmeyen.length)
      h += `<div class="alt" style="margin-top:6px">Hedefi ölçülmemiş: ${d.tahmin.hedefi_bilinmeyen.join(", ")} — dahil değil.</div>`;
  }else{
    h += `<div class="alt" style="margin-top:12px">Tahmin için yeterli ölçüm yok (panel yeni başladı).</div>`;
  }
  return h;
}

function kutuphaneKarti(k){
  let h = `<div class="buyuk">${sayi(k.toplam)}</div>
           <div class="alt" style="margin-bottom:14px">karar · ${k.db_boyut_gb} GB</div>`;
  h += tablo(k.mahkemeler.slice(0,7).map(m=>[m.ad, sayi(m.n)]));
  h += `<div class="alt" style="margin-top:12px">Kaynak: ` +
       k.kaynaklar.slice(0,4).map(s=>`${s.ad} ${sayi(s.n)}`).join(" · ") + `</div>`;
  h += `<div class="alt">Tam metinli: ` +
       (k.icerik_durumu.find(i=>i.ad==="html_markdown")?.n ?? 0).toLocaleString("tr-TR") + `</div>`;
  h += `<div class="alt" style="margin-top:8px">Sayaç: ${
        k.guncellendi ? new Date(k.guncellendi).toLocaleTimeString("tr-TR") : "—"} ·
        tam sayım: ${k.tam_sayim ? new Date(k.tam_sayim).toLocaleString("tr-TR") : "—"}</div>`;
  return h;
}

function gorevlerKarti(gs){
  return gs.map(g=>{
    const rozet = g.aktif ? '<span class="rozet aktif">aktif</span>'
                : g.tamamlandi ? '<span class="rozet bitti">bitti</span>'
                : '<span class="rozet">sırada</span>';
    const sag = g.hedef ? `${sayi(g.mevcut)} / ${sayi(g.hedef)} · %${g.yuzde}`
                        : `${sayi(g.mevcut)} <span class="alt">(hedef ölçülüyor…)</span>`;
    const cubuk = g.hedef ? `<div class="cubuk"><i style="width:${Math.min(100,g.yuzde)}%"></i></div>` : "";
    return `<div class="gorev"><div class="ust"><span>${g.item_type} ${g.yil} ${rozet}</span>
            <span>${sag}</span></div>${cubuk}</div>`;
  }).join("");
}

function yilTablosu(yillar, court, baslik){
  const m = yillar[court] || {};
  const anahtarlar = Object.keys(m).sort().reverse().slice(0,12);
  if(!anahtarlar.length) return `<div class="alt">${baslik}: veri yok</div>`;
  const enb = Math.max(...anahtarlar.map(y=>m[y]));
  return `<div class="alt" style="margin-bottom:8px">${baslik}</div>` +
    anahtarlar.map(y=>`<div style="margin-bottom:7px">
      <div class="ust" style="display:flex;justify-content:space-between;font-size:13.5px">
        <span>${y}</span><span>${sayi(m[y])}</span></div>
      <div class="cubuk"><i style="width:${Math.round(100*m[y]/enb)}%"></i></div></div>`).join("");
}

async function yenile(){
  try{
    const d = await (await fetch("/api/durum")).json();
    const c = d.crawl;
    const pill = el("pill");
    pill.className = "pill "+c.durum;
    pill.textContent = {calisiyor:"ÇALIŞIYOR",bekliyor:"BEKLİYOR",durdu:"DURDU",bitti:"TAMAMLANDI"}[c.durum];
    el("ozet").textContent = `${c.item_type} ${c.yil} · sayfa ${c.sayfa}`;
    el("zaman").textContent = new Date(d.zaman).toLocaleTimeString("tr-TR");
    el("crawl").innerHTML = crawlKarti(c);
    el("hiz").innerHTML = hizKarti(d);
    el("kutuphane").innerHTML = kutuphaneKarti(d.kutuphane);
    el("gorevler").innerHTML = gorevlerKarti(d.gorevler);
    el("yilYargitay").innerHTML = yilTablosu(d.kutuphane.yillar,"Yargıtay Kararı","Yargıtay Kararı");
    el("yilIstinaf").innerHTML = yilTablosu(d.kutuphane.yillar,"İstinaf Hukuk Mahkemesi Kararı","İstinaf Hukuk Mahkemesi Kararı");
    el("log").textContent = (c.log||[]).join("\n") || "(kayıt yok)";
    document.title = `${{calisiyor:"●",bekliyor:"◐",durdu:"○",bitti:"✓"}[c.durum]} ${sayi(d.kutuphane.toplam)} — Emsal`;
  }catch(e){
    el("pill").className = "pill durdu";
    el("pill").textContent = "PANEL ERİŞİLEMİYOR";
  }
}
yenile();
setInterval(yenile, 5000);
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Emsal kütüphane paneli")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    store = StatsStore()
    refresher = Refresher(store)
    refresher.start()

    Handler.store = store
    Handler.refresher = refresher
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Emsal paneli: http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
