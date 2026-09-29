"""Resmi Gazete BASLIK dizini — tarihler arasi anahtar kelime aramasi.

Neden var: ``sources/resmigazete.py`` her cagrida TEK gunun fihristini cekip
yerelde suzuyor; "avukatlik asgari ucret tarifesi hangi yil yayimlandi" gibi
tarih araligi sorulari cevapsiz kaliyordu.  Bu modul her gunun fihristini
(``/eskiler/YYYY/MM/YYYYMMDD.htm`` ve mukerrer sayilar ``...m1.htm``) bir kez
cekip ayri bir SQLite dosyasina (``resmigazete.sqlite3``) yazar ve basliklari
FTS5 ile aratir.  YALNIZ baslik dizini: ogelerin tam metni dizine alinmaz.

Tasarim notlari (olculdu, 29 Eyl 2026):

* Arsiv 2000-06-27'de baslar (2000-06-26 ve oncesi 404).
* Mukerrer sayilar ana gunun fihristinde DEGIL, ayri sayfada: ``YYYYMMDDm1.htm``
  (``m2`` ... 404'e kadar).  Ogeleri ``YYYYMMDDm1-N`` kimligiyle.
* Sunucu ``curl/*`` User-Agent'ina cevap vermeden asili birakiyor; adapterin
  User-Agent'i (EmsalMcp/...) sorunsuz.
* ``base.client()`` host basina 8 istek/31 sn siniri koyuyor (karar kaynaklari
  icin); geri doldurma icin fazla yavas.  Burada kendi nazik hiz sinirimiz var
  (``delay``), throttle kancalari yok.
* Ayri SQLite: 72 GB'lik korpus cache'ine dokunmaz, tek dosya kopyalayip silinerek
  yeniden kurulabilir.  Yol: ``EMSAL_RG_DB_PATH`` > cache dosyasinin yani.
"""
from __future__ import annotations

import asyncio
import html as _html
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

from .sources.resmigazete import (
    ResmiGazeteClient,
    _fold,
    _iso_from_day,
    parse_issue_header,
)

# Arsivin en eski erisilebilir gunu (olculdu).
ARCHIVE_START = _date(2000, 6, 27)
BASE = "https://www.resmigazete.gov.tr"
# Bir gunde en fazla bu kadar mukerrer sayfa denenir (gercekte 1-3).
MAX_MUKERRER = 8

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS rg_ogeler (
    item_id TEXT PRIMARY KEY,
    tarih TEXT NOT NULL,
    sayi_no TEXT,
    mukerrer INTEGER NOT NULL DEFAULT 0,
    sayfa TEXT NOT NULL,
    bolum TEXT,
    kategori TEXT,
    numara TEXT,
    baslik TEXT NOT NULL,
    baslik_fold TEXT NOT NULL,
    url TEXT,
    ext TEXT,
    cekilme_zamani TEXT
);
CREATE INDEX IF NOT EXISTS rg_ogeler_tarih ON rg_ogeler(tarih);
CREATE INDEX IF NOT EXISTS rg_ogeler_sayfa ON rg_ogeler(sayfa);

CREATE TABLE IF NOT EXISTS rg_gunler (
    sayfa TEXT PRIMARY KEY,          -- 20230309 ya da 20230309m1
    tarih TEXT NOT NULL,             -- ISO gun
    durum TEXT NOT NULL,             -- ok | 404 | hata
    oge_sayisi INTEGER NOT NULL DEFAULT 0,
    sayi_no TEXT,
    hata TEXT,
    cekilme_zamani TEXT
);
CREATE INDEX IF NOT EXISTS rg_gunler_tarih ON rg_gunler(tarih);

CREATE VIRTUAL TABLE IF NOT EXISTS rg_fts USING fts5(
    baslik, kategori,
    tokenize='unicode61 remove_diacritics 2'
);
"""
# rg_fts.rowid = rg_ogeler.rowid (satir ekleme/silme birlikte yapilir).


def default_db_path() -> Path:
    env = os.environ.get("EMSAL_RG_DB_PATH", "").strip()
    if env:
        return Path(env)
    from .config import config
    return Path(config.cache_path).parent / "resmigazete.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: str | Path | None = None, create: bool = True) -> sqlite3.Connection:
    p = Path(path) if path else default_db_path()
    if create:
        p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(_SCHEMA)
    return db


def open_readonly(path: str | Path | None = None) -> sqlite3.Connection | None:
    """Dizin dosyasi yoksa None (dosya YARATILMAZ); varsa salt-okunur baglanti."""
    p = Path(path) if path else default_db_path()
    if not p.is_file():
        return None
    try:
        db = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("SELECT 1 FROM rg_ogeler LIMIT 1")
        return db
    except sqlite3.Error:
        return None


# ── Yazma ───────────────────────────────────────────────────────────────────


def store_issue(
    db: sqlite3.Connection,
    sayfa: str,
    items: list[dict[str, Any]],
    *,
    sayi_no: str | None = None,
    mukerrer: bool = False,
) -> int:
    """Bir fihristin ogelerini yaz (varsa o sayfanin eskilerini degistir).

    ``sayfa``: '20230309' ya da '20230309m1'.  Donus: yazilan oge sayisi.
    """
    day = sayfa[:8]
    tarih = _iso_from_day(day)
    now = _now()
    # Yeniden cekimde eski satirlar (FTS dahil) silinir; sayfa tek atomik birim.
    old = [r[0] for r in db.execute("SELECT rowid FROM rg_ogeler WHERE sayfa=?", (sayfa,))]
    for rid in old:
        db.execute("DELETE FROM rg_fts WHERE rowid=?", (rid,))
    db.execute("DELETE FROM rg_ogeler WHERE sayfa=?", (sayfa,))
    n = 0
    for it in items:
        item_id = it["id"]
        ext = it.get("ext") or "htm"
        baslik = it["title"]
        kategori = it.get("category") or it.get("section")
        cur = db.execute(
            "INSERT OR REPLACE INTO rg_ogeler(item_id,tarih,sayi_no,mukerrer,sayfa,bolum,"
            "kategori,numara,baslik,baslik_fold,url,ext,cekilme_zamani) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, tarih, sayi_no, 1 if mukerrer else 0, sayfa, it.get("section"),
             it.get("category"), it.get("number"), baslik, _fold(baslik),
             it.get("url") or f"{BASE}/eskiler/{day[0:4]}/{day[4:6]}/{item_id}.{ext}", ext, now),
        )
        db.execute(
            "INSERT INTO rg_fts(rowid,baslik,kategori) VALUES(?,?,?)",
            (cur.lastrowid, _fold(baslik), _fold(kategori or "")),
        )
        n += 1
    return n


def mark_day(db: sqlite3.Connection, sayfa: str, durum: str, oge_sayisi: int = 0,
             sayi_no: str | None = None, hata: str | None = None) -> None:
    db.execute(
        "INSERT OR REPLACE INTO rg_gunler(sayfa,tarih,durum,oge_sayisi,sayi_no,hata,cekilme_zamani) "
        "VALUES(?,?,?,?,?,?,?)",
        (sayfa, _iso_from_day(sayfa[:8]), durum, oge_sayisi, sayi_no, hata, _now()),
    )


# ── Arama ───────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def build_match(query: str) -> str | None:
    """Serbest sorgudan FTS5 MATCH ifadesi: tirnakli obekler aynen, digerleri
    ONEK eslesmesi (yazilan sozcuk + ``*``: ``tarife`` -> ``tarifesi``) ve hepsi
    VE ile.  Aksan/buyuk-kucuk harf duyarsiz (``_fold``); FTS operatorleri
    ve ozel karakterler temizlenir."""
    if not query or not query.strip():
        return None
    parts: list[str] = []
    for phrase in re.findall(r'"([^"]+)"', query):
        toks = _TOKEN_RE.findall(_fold(phrase))
        if toks:
            parts.append('"' + " ".join(toks) + '"')
    rest = re.sub(r'"[^"]*"', " ", query)
    for tok in _TOKEN_RE.findall(_fold(rest)):
        if tok in ("and", "or", "not", "near"):
            continue
        parts.append(f'"{tok}"*')
    return " AND ".join(parts) if parts else None


def search_index(
    db: sqlite3.Connection,
    query: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str | None = None,
    limit: int = 10,
    page: int = 1,
) -> tuple[int, list[sqlite3.Row]]:
    """Baslik FTS aramasi. ``date_*`` ISO (YYYY-MM-DD, dahil). Donus (toplam, satirlar)."""
    match = build_match(query)
    if match is None and not (date_from or date_to):
        return 0, []               # ne sorgu ne tarih: tum arsivi dokme
    where: list[str] = []
    args: list[Any] = []
    if match is not None:
        where.append("rg_fts MATCH ?")
        args.append(match)
    if date_from:
        where.append("o.tarih >= ?")
        args.append(date_from)
    if date_to:
        where.append("o.tarih <= ?")
        args.append(date_to)
    cond = " AND ".join(where)
    if match is not None:
        base = "FROM rg_fts JOIN rg_ogeler o ON o.rowid = rg_fts.rowid WHERE " + cond
    else:
        base = "FROM rg_ogeler o WHERE " + cond
    total = db.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
    if sort_by == "date" or match is None:
        order = "o.tarih DESC, o.item_id DESC"
    else:
        order = "bm25(rg_fts), o.tarih DESC, o.item_id"
    limit = max(1, int(limit))
    offset = (max(1, int(page)) - 1) * limit
    rows = db.execute(
        f"SELECT o.* {base} ORDER BY {order} LIMIT ? OFFSET ?", [*args, limit, offset]
    ).fetchall()
    return total, list(rows)


def index_status(db: sqlite3.Connection | None) -> dict[str, Any]:
    """Saglik/ops icin ozet. Dizin yoksa ``mevcut=False``."""
    if db is None:
        return {"mevcut": False, "oge_sayisi": 0}
    q = lambda s: db.execute(s).fetchone()  # noqa: E731
    n = q("SELECT COUNT(*) FROM rg_ogeler")[0]
    mn, mx = q("SELECT MIN(tarih), MAX(tarih) FROM rg_ogeler")
    gunler = {r[0]: r[1] for r in db.execute("SELECT durum, COUNT(*) FROM rg_gunler GROUP BY durum")}
    last = q("SELECT MAX(cekilme_zamani) FROM rg_gunler")[0]
    return {
        "mevcut": n > 0,
        "oge_sayisi": n,
        "en_eski_oge_tarihi": mn,
        "en_yeni_oge_tarihi": mx,
        "gun_durumlari": gunler,
        "son_cekilme": last,
    }


def index_status_safe(path: str | Path | None = None) -> dict[str, Any]:
    db = open_readonly(path)
    try:
        return index_status(db)
    except sqlite3.Error as exc:
        return {"mevcut": False, "oge_sayisi": 0, "hata": str(exc)}
    finally:
        if db is not None:
            db.close()


# ── Ayristirma ──────────────────────────────────────────────────────────────

_LEGACY_ANCHOR_RE = re.compile(r"^#(\d+)$")
_OLD_HEADER_RE = re.compile(r"Say\w*\s*:\s*(\d{4,6})", re.I)
# Eski sayfalar iso-8859-1 / windows-1256 diye beyan ediyor ama Turkce icerik;
# 1254 hepsinin Turkce icin ust kumesi.
_FORCE_1254 = {"iso-8859-1", "latin-1", "latin1", "iso-8859-9", "windows-1252",
               "windows-1256", "iso-8859-15", "us-ascii", "ascii"}


def decode_page(content: bytes) -> str:
    m = re.search(rb"charset=[\"']?([\w-]+)", content[:4096], re.I)
    cs = m.group(1).decode("ascii", "ignore").lower() if m else "windows-1254"
    if cs in _FORCE_1254:
        cs = "windows-1254"
    try:
        return content.decode(cs, errors="replace")
    except LookupError:
        return content.decode("windows-1254", errors="replace")


def _header(html: str) -> tuple[str | None, bool]:
    sayi, muk = parse_issue_header(html)
    if sayi:
        return sayi, muk
    flat = re.sub(r"<[^>]+>", " ", html[:20000])
    flat = re.sub(r"\s+", " ", _html.unescape(flat))
    m = _OLD_HEADER_RE.search(flat)
    return (m.group(1) if m else None), False


def _parse_legacy(html: str, day: str) -> list[dict[str, Any]]:
    """2000-2003 civari tek sayfalik fihrist: ogeler ayri dosya degil, sayfa
    ici ``#N`` baglantilari.  Kimlik ``YYYYMMDD-N``, url sayfa#N."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    section = category = None
    items: list[dict[str, Any]] = []
    page_url = f"{BASE}/eskiler/{day[0:4]}/{day[4:6]}/{day}.htm"
    for para in soup.find_all("p"):
        anchors = [a for a in para.find_all("a", href=True) if _LEGACY_ANCHOR_RE.match(a["href"].strip())]
        text = re.sub(r"\s+", " ", para.get_text("").replace("\xa0", " ")).strip()
        if not anchors:
            if text and len(text) <= 100:
                if "bolumu" in _fold(text):
                    section, category = text, None
                elif para.find_parent(["u", "b"]) is not None or para.find("u") is not None:
                    category = text
            continue
        for a in anchors:
            n = _LEGACY_ANCHOR_RE.match(a["href"].strip()).group(1)  # type: ignore[union-attr]
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True).replace("\xa0", " "))
            title = re.sub(r"^[\s–—-]+", "", title).strip()
            if not title:
                continue
            items.append({"id": f"{day}-{n}", "ext": "htm", "number": None, "title": title,
                          "section": section, "category": category, "url": f"{page_url}#{n}"})
    return items


def parse_issue(html: str, day: str) -> list[dict[str, Any]]:
    items = ResmiGazeteClient()._parse_index(html, day)
    if not items:
        items = _parse_legacy(html, day)
    return items


# ── Cekme ───────────────────────────────────────────────────────────────────


class _Pacer:
    """Istek baslangiclari arasinda en az ``delay`` sn birakir (eszamanlilik
    gecikmeyi kisamaz, yalniz bekleme surelerini orter)."""

    def __init__(self, delay: float) -> None:
        self.delay = max(0.0, delay)
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
                now = time.monotonic()
            self._next = now + self.delay


@dataclass
class FetchResult:
    status: str                 # ok | 404 | hata
    html: str | None = None
    error: str | None = None


class IndexFetcher:
    """Fihrist sayfalarini nazikce ceker: 429/5xx/zaman asiminda ustel geri cekilme."""

    def __init__(self, delay: float = 0.7, retries: int = 5, backoff: float = 5.0,
                 timeout: float = 30.0, http: httpx.AsyncClient | None = None) -> None:
        self.pacer = _Pacer(delay)
        self.retries = retries
        self.backoff = backoff
        self._own = http is None
        if http is None:
            from .sources.base import _ssl_context
            from . import __version__
            kw: dict[str, Any] = {}
            ctx = _ssl_context()
            if ctx is not None:
                kw["verify"] = ctx
            http = httpx.AsyncClient(
                timeout=timeout, follow_redirects=True,
                headers={"User-Agent": f"EmsalMcp/{__version__} (+https://github.com/afsozer/emsal-mcp)"},
                **kw,
            )
        self.http = http
        self.requests = 0
        self.rate_limited = 0

    async def aclose(self) -> None:
        if self._own:
            await self.http.aclose()

    async def get_index(self, sayfa: str) -> FetchResult:
        url = f"{BASE}/eskiler/{sayfa[0:4]}/{sayfa[4:6]}/{sayfa}.htm"
        err = ""
        for attempt in range(self.retries + 1):
            await self.pacer.wait()
            self.requests += 1
            try:
                resp = await self.http.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                err = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    return FetchResult("ok", html=decode_page(resp.content))
                if resp.status_code == 404:
                    return FetchResult("404")
                err = f"HTTP {resp.status_code}"
                if resp.status_code == 429:
                    self.rate_limited += 1
                elif resp.status_code < 500:
                    return FetchResult("hata", error=err)   # 403 vb.: tekrar denemek anlamsiz
            if attempt < self.retries:
                await asyncio.sleep(self.backoff * (2 ** attempt))
        return FetchResult("hata", error=err or "bilinmeyen hata")


async def fetch_day(fetcher: IndexFetcher, db: sqlite3.Connection, day: str) -> dict[str, Any]:
    """Bir gunu (ana sayi + mukerrerler) cekip yaz.  ``day``: 'YYYYMMDD'.

    Donus: {"ogeler": n, "durumlar": {sayfa: durum}}.  Gecici bir hata ana
    sayfayi 'hata' olarak isaretler (sonraki kosuda yeniden denenir); 404 kesin
    sayilir (yalniz `update` yakin gunleri yeniden dener).
    """
    total = 0
    durumlar: dict[str, str] = {}
    sayfalar = [day] + [f"{day}m{k}" for k in range(1, MAX_MUKERRER + 1)]
    for sayfa in sayfalar:
        res = await fetcher.get_index(sayfa)
        durumlar[sayfa] = res.status
        if res.status == "404":
            mark_day(db, sayfa, "404")
            db.commit()
            if sayfa != day:
                break              # m(k) yoksa m(k+1) de yok
            continue               # ana sayfa 404 ise de m1 denenir (nadir)
        if res.status == "hata":
            mark_day(db, sayfa, "hata", hata=res.error)
            db.commit()
            break
        sayi_no, muk = _header(res.html or "")
        items = parse_issue(res.html or "", day)
        n = store_issue(db, sayfa, items, sayi_no=sayi_no, mukerrer=(sayfa != day) or muk)
        mark_day(db, sayfa, "ok", n, sayi_no)
        db.commit()
        total += n
        if not items:
            durumlar[sayfa] = "ok-bos"   # sayfa var ama ayristirilamadi: raporda gorunsun
    return {"ogeler": total, "durumlar": durumlar}


def _days(d_from: _date, d_to: _date) -> Iterable[_date]:
    d = d_from
    while d <= d_to:
        yield d
        d += timedelta(days=1)


def pending_days(db: sqlite3.Connection, d_from: _date, d_to: _date,
                 refresh_from: _date | None = None) -> list[str]:
    """Araliktaki, tekrar sorulmasi gereken gunler (YYYYMMDD).

    Ana sayfasi 'ok' ya da '404' olan gun bitmis sayilir (m-sayfalari da o
    turda denendi).  'hata' ve hic denenmemis gunler kalir.  ``refresh_from``
    ve sonrasindaki gunler (yakin gecmis + bugun) her seferinde yeniden cekilir:
    yayimlanmamis 404'ler ve sonradan eklenen mukerrerler icin.
    """
    done = {
        r[0] for r in db.execute(
            "SELECT sayfa FROM rg_gunler WHERE durum IN ('ok','404') AND length(sayfa)=8 "
            "AND tarih BETWEEN ? AND ?", (d_from.isoformat(), d_to.isoformat()))
    }
    out = []
    for d in _days(d_from, d_to):
        s = d.strftime("%Y%m%d")
        if refresh_from is not None and d >= refresh_from:
            out.append(s)
        elif s not in done:
            out.append(s)
    return out


async def backfill(
    db: sqlite3.Connection,
    d_from: _date,
    d_to: _date,
    *,
    fetcher: IndexFetcher | None = None,
    delay: float = 0.7,
    concurrency: int = 1,
    refresh_from: _date | None = None,
    progress: Callable[[str], None] | None = None,
    progress_every: int = 50,
) -> dict[str, Any]:
    """[d_from, d_to] araligini doldur; kaldigi yerden devam eder."""
    d_from = max(d_from, ARCHIVE_START)
    own = fetcher is None
    fetcher = fetcher or IndexFetcher(delay=delay)
    days = pending_days(db, d_from, d_to, refresh_from)
    t0 = time.monotonic()
    stats = {"istenen_gun": (d_to - d_from).days + 1 if d_to >= d_from else 0,
             "islenen_gun": 0, "atlanan_gun": 0, "oge": 0, "gun_404": 0, "gun_hata": 0,
             "mukerrer_sayfa": 0}
    stats["atlanan_gun"] = max(0, stats["istenen_gun"] - len(days))
    sem = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()

    async def one(day: str) -> None:
        async with sem:
            r = await fetch_day(fetcher, db, day)
        async with lock:
            stats["islenen_gun"] += 1
            stats["oge"] += r["ogeler"]
            main = r["durumlar"].get(day)
            if main == "404":
                stats["gun_404"] += 1
            elif main == "hata":
                stats["gun_hata"] += 1
            stats["mukerrer_sayfa"] += sum(
                1 for k, v in r["durumlar"].items() if k != day and v.startswith("ok"))
            if progress and stats["islenen_gun"] % progress_every == 0:
                progress(f"{stats['islenen_gun']}/{len(days)} gun, {stats['oge']} oge, "
                         f"{time.monotonic() - t0:.0f}s, son={day}")

    try:
        if concurrency <= 1:
            for day in days:
                await one(day)
        else:
            await asyncio.gather(*(one(d) for d in days))
    finally:
        stats["sure_sn"] = round(time.monotonic() - t0, 1)
        stats["istek"] = fetcher.requests
        stats["429"] = fetcher.rate_limited
        if own:
            await fetcher.aclose()
    return stats


def last_ok_day(db: sqlite3.Connection) -> _date | None:
    row = db.execute("SELECT MAX(tarih) FROM rg_gunler WHERE durum='ok'").fetchone()
    return _date.fromisoformat(row[0]) if row and row[0] else None
