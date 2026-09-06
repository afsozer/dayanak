"""Yeniden gömme, 4. aşama: YENİ indekse geçiş (canlı sunucuda ~1-2 dk kesinti).

Sıra:
  1. ``reembed_check.py`` — hazırlık indeksi sağlıklı mı (vektör sayısı, parçalama
     sürümü, sidecar'lar, örnek sorgular).  Başarısızsa HİÇBİR ŞEY değişmez.
  2. ``schtasks /end /tn EmsalMcpHttp`` — sunucu durur (dosyalar serbest kalır).
  3. Canlı ``bulk-*.{faiss,keys.npz,meta.json}`` → ``bulk-v1-yedek\\`` (SİLİNMEZ),
     hazırlık dizinindeki yeni üçlü canlı dizine taşınır.  Taşıma yarıda
     kalırsa yedek geri alınır (rollback) ve sunucu eski indeksle açılır.
  4. Vektör dizinleri takas edilir: ``vec`` → ``vec_v1``, ``vec2`` → ``vec``.
     Böylece ``EMSAL_BULK_VEC_DIR`` (emsal-env.cmd, mcp_http_sunucu.cmd)
     DEĞİŞMEZ; geri dönüş de aynı takasın tersidir.
  5. Yeniden gömülen kararların delta satırları silinir (``drop_delta_rows.py``),
     delta matrisi yenilenir.  Gömme sırasında crawl'ın eklediği YENİ kararlar
     manifest'te olmadığı için delta'da kalır ve aramada görünmeye devam eder.
  6. ``schtasks /run /tn EmsalMcpHttp`` + sağlık kontrolü (406).

    .venv\\Scripts\\python.exe -X utf8 scripts\\reembed_switch.py [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROV_STEM = "bulk-fastembed-multilingual-e5"
PARTS = (".faiss", ".keys.npz", ".meta.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-dir", default=r"D:\emsal-data")
    ap.add_argument("--stage-dir", default=r"D:\emsal-data\staging")
    ap.add_argument("--vec", default=r"D:\emsal-bench\vec")
    ap.add_argument("--vec2", default=r"D:\emsal-bench\vec2")
    ap.add_argument("--vec-old", default=r"D:\emsal-bench\vec_v1")
    ap.add_argument("--log", default=r"D:\emsal-data\crawl_logs\reembed.log")
    ap.add_argument("--task", default="EmsalMcpHttp")
    ap.add_argument("--delta-name", default="", help="boşsa vec2'deki en yeni delta-reembed-*")
    ap.add_argument("--dry-run", action="store_true", help="yalnız doğrulama, geçiş yok")
    args = ap.parse_args()

    logf = open(args.log, "a", encoding="utf-8")

    def log(msg: str) -> None:
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    def run(cmd: list[str], env: dict | None = None) -> int:
        log("$ " + " ".join(cmd))
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env)
        for stream in (p.stdout, p.stderr):
            for ln in (stream or "").splitlines():
                if ln.strip():
                    log("  | " + ln)
        return p.returncode

    py = str(REPO / ".venv" / "Scripts" / "python.exe")
    live, stage = Path(args.live_dir), Path(args.stage_dir)

    log("=== GEÇİŞ: doğrulama ===")
    rc = run([py, "-X", "utf8", str(REPO / "scripts" / "reembed_check.py"),
              "--new-dir", str(stage), "--new-vec", args.vec2, "--live-dir", str(live)])
    if rc != 0:
        log("DOĞRULAMA BAŞARISIZ — geçiş YAPILMADI, canlı indeks olduğu gibi.")
        return 10
    if args.dry_run:
        log("--dry-run: doğrulama tamam, geçiş yapılmadı.")
        return 0

    vec, vec2, vec_old = Path(args.vec), Path(args.vec2), Path(args.vec_old)
    if vec_old.exists():
        log(f"HATA: {vec_old} zaten var (önceki geçişten kalma); elle taşıyın/silin.")
        return 11
    if not vec2.is_dir():
        log(f"HATA: {vec2} yok")
        return 11

    log("=== sunucu durduruluyor ===")
    run(["schtasks", "/end", "/tn", args.task])
    time.sleep(5)

    backup = live / "bulk-v1-yedek"
    backup.mkdir(exist_ok=True)
    moved: list[tuple[Path, Path]] = []
    try:
        for ext in PARTS:  # 3a: canlıyı yedeğe
            src = live / f"{PROV_STEM}{ext}"
            dst = backup / f"{PROV_STEM}{ext}"
            if dst.exists():
                dst.unlink()
            if src.exists():
                shutil.move(str(src), str(dst))
                moved.append((dst, src))
        for ext in PARTS:  # 3b: yeniyi canlıya
            src = stage / f"{PROV_STEM}{ext}"
            dst = live / f"{PROV_STEM}{ext}"
            shutil.move(str(src), str(dst))
            moved.append((dst, src))
        os.rename(vec, vec_old)  # 4: dizin takası (aynı birim → anlık)
        moved.append((vec_old, vec))
        os.rename(vec2, vec)
        moved.append((vec, vec2))
        log(f"indeks ve vektör dizini takas edildi (yedek: {backup}, eski vektörler: {vec_old})")
    except Exception as exc:
        log(f"TAŞIMA HATASI: {exc} — geri alınıyor")
        for dst, src in reversed(moved):
            try:
                (os.rename if dst.is_dir() else shutil.move)(str(dst), str(src))
            except Exception as exc2:
                log(f"  geri alma başarısız {dst} → {src}: {exc2}")
        run(["schtasks", "/run", "/tn", args.task])
        return 12

    # 5: yeniden gömülen kararların delta satırları
    name = args.delta_name
    if not name:
        cands = sorted(glob.glob(str(vec / "delta-reembed-*.manifest.json")))
        name = Path(cands[-1]).name[: -len(".manifest.json")] if cands else ""
    if name:
        env = dict(os.environ, EMSAL_BULK_VEC_DIR=str(vec))
        rc = run([py, "-X", "utf8", str(REPO / "scripts" / "drop_delta_rows.py"), name], env=env)
        if rc != 0:
            log("UYARI: delta satırları silinemedi (kopya sonuç riski, arama çalışır)")
    else:
        log("UYARI: delta-reembed manifest'i bulunamadı, delta satırları dokunulmadı")
    run([str(REPO / ".venv" / "Scripts" / "emsal-mcp.exe"), "semantic", "build-matrix", "--json"])

    log("=== sunucu başlatılıyor ===")
    run(["schtasks", "/run", "/tn", args.task])
    rc = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
              str(REPO / "scripts" / "reembed_health.ps1")])
    if rc != 0:
        log("SAĞLIK BAŞARISIZ: sunucu yeni indeksle açılmadı. Geri dönüş için "
            f"{backup} içindeki üçlüyü {live} üstüne kopyalayın ve {vec}↔{vec_old} takasını geri alın.")
        return 13
    meta = json.loads((live / f"{PROV_STEM}.meta.json").read_text(encoding="utf-8"))
    log(f"GEÇİŞ TAMAM: {meta['count']:,} vektör, chunking_version="
        f"{meta.get('chunking_version')}, {len(meta['files'])} sidecar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
