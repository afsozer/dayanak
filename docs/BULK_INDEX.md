# Toplu içtihat korpusu: HF veri seti + FAISS toplu indeks

2 Eylül 2026'da `hamzabagirsakci/turkish-court-decisions` (11.045.085 karar,
CC0) korpus tabanı olarak alındı. Bu belge kurulum sırasını, ölçümleri ve
sunucuya taşıma adımlarını anlatır.

## Parçalar

| Adım | Betik | Girdi → Çıktı | Ölçüm |
|---|---|---|---|
| 1. Kararları SQLite'a al | `scripts/import_hf_parquet.py` | parquet → `documents_v2` (+FTS5 trigger) | 11 M satır 86 dk, DB 72 GB, FTS sorgusu 0,65 s |
| 2. Parçalı gömme | `scripts/embed_parquet_worker.py` | parquet → `<kaynak>-<dosya>.vectors.npy` (fp16) + `.keys.parquet` | RTX 4060: ~360-540 parça/sn; M5 MPS: ~335 |
| 3. Toplu indeks | `emsal-mcp semantic bulk-build <vec_dir>` | sidecar'lar → `bulk-<provider>.faiss/.keys.npz/.meta.json` | 11,5 M vektör 7 dk; 27 M ≈ 15 dk |

Kaynak eşlemesi: HF `yargitay/emsal/danistay` kimlikleri Bedesten kimlikleriyle
aynı (2.000 örnekte %97,7 örtüşme ölçüldü) → `source='bedesten'`; AYM →
`source='aym'`. Köken `metadata_json.origin = hf_turkish_court_decisions`.

## Arama nasıl çalışır

`semantic.embedding_search` önce `bulk_index.bulk_search`'ü dener:

1. Sorgu vektörü (fastembed ONNX q8 ya da aynı modelin fp16/fp32'si; kosinüs
   0,999, ilk 10'da 7-9 örtüşme) IVF16384,PQ64 indeksinde `nprobe=128` ile
   2.000 aday parça bulur (64 B/vektör → 27 M vektör ≈ 1,7 GB RAM).
2. Adaylar `vec/` dizinindeki fp16 sidecar'lardan (memmap) tam iç çarpımla
   yeniden puanlanır (**refine**). Ölçüm, 3,3 M vektör / 15 sorgu, tam aramaya
   göre recall@10: PQ tek başına 0,29; + refine 0,87 (q8 sorgu) / 0,89 (fp16).
   Gecikme Mac'te 6-30 ms.
3. Aynı kararın parçaları belge bazında en yüksek skorla tekilleştirilir.
4. `embedding_vectors` tablosundaki vektörler (crawl'dan gelen, indeks sonrası)
   eski yolla (mmap matrisi) taranıp aynı belgede max skorla birleşir.
   Yöntem adı `dense_bulk`.

Refine için vektör dosyaları sunucuda bulunmalı: `EMSAL_BULK_VEC_DIR` ya da
cache'in yanındaki `vec/`. Yoksa PQ skoruyla (düşük kalite) devam eder,
`bulk-status` bunu söyler.

## Büyük korpus korumaları (`_BIG_CORPUS_DOCS = 2 M`)

11 M kararda ölçülen tuzaklar ve yapılan değişiklikler:

- Hibrit BM25 aşaması genişletilmiş terimleri OR'luyordu: 185 s. Şimdi önce ham
  kelimeler AND (1,2 s); OR'a yalnız küçük korpusta düşülür.
- `search_vectors` boşsa sorgu anında TF-IDF hesaplanıyordu (11 M belge için
  saatler). Büyük korpusta atlanır, uyarı döner.
- `best_dense_provider` toplu indeks varsa onun sağlayıcısını döner
  (`mode='semantic'` artık TF-IDF'e düşmez).
- `COUNT(*) documents_v2` yerine FTS `docsize` gölge tablosu (ms).

## Sunucuya (desktop) taşıma

1. `pip install faiss-cpu` (1.15, numpy 2 ile uyumlu) sunucu venv'ine.
2. `cache.sqlite3` (72 GB) + `bulk-*.{faiss,keys.npz,meta.json}` + `vec/`
   (≈20 GB fp16) → `EMSAL_CACHE_PATH` dizini. Aynı ağda LAN ile taşıyın.
3. Mevcut desktop DB'sinden yalnız iki şey aktarılır: `uyap_arsiv` (2020 UYAP
   offline arşivi: Uyuşmazlık, AİHM) ve HF kesiminden (Yargıtay Mayıs 2026,
   Emsal Haziran 2026) sonra crawl'lanan `bedesten` satırları.
4. Crawl başlangıcını kesim tarihine çekin; yeni kararlar `embedding_vectors`'a
   girer (delta), indeks ara ara `bulk-build` ile yenilenir.

## Tuzaklar

- **faiss + torch aynı süreçte segfault** (iki OpenMP). Sorgu tarafı fastembed
  (onnxruntime) ile sorunsuz; torch yalnız gömme worker'ında.
- `np.save` `.npy` ile bitmeyen ada uzantı ekler (geçici dosya adı `.tmp.npy`).
- Windows pip: `--no-warn-script-location` şart (PATH'teki bir klasör WinError
  448 veriyor); SSH'ta `timeout /t` çalışmaz.
- macOS: `tests/test_semantic.py::TestMatrixRebuildIsAtomic::test_force_rebuild_while_matrix_is_mapped`
  temiz ağaçta da düşer (mmap'li dosya silme davranışı Windows'a göre yazılmış).

## Parçalama düzeltmesi ve yeniden gömme (Eylül 2026)

`chunking.chunk_text` örtüşmeyi **iki kez** uyguluyordu: `_hard_split_v1`
paragraf sınırı olmayan metni zaten `overlap` kadar örtüşen parçalara bölüyor,
birleştirme döngüsü aynı kuyruğu bir kez daha başa ekliyordu. Sonuç: parça
kendi ilk 200 karakterini birebir tekrar ediyor, sınırlar kayıyor.

Ölçüm (3.000 gerçek karar, ortalama 10.707 karakter, `chunk_size=1600`,
`overlap=200`):

| | parça | ort. uzunluk | içinde tekrar eden parça | tekrar eden karakter |
|---|---|---|---|---|
| v1 (hatalı) | 26.697 | 1.377 | 2.083 (%7,8) | 421.455 |
| v2 (düzeltilmiş) | 26.428 | 1.388 | 30 (%0,1) | 7.881 |

Kalan %0,1 metnin kendisinde tekrar eden pasajlardır. Parça sayısı %1
azalır (31,0 M → ~30,4 M).

**Sürüm bayrağı — canlı uyumluluk.** `chunk_index` ancak indeksi üreten
parçalayıcıya göre anlamlıdır; `bulk_search` alıntıyı (`snippet`) belgeyi
yeniden parçalayarak üretir. Bu yüzden:

- `chunking.CHUNKING_VERSION = 2`, eski davranış `chunk_text(..., version=1)`
  ile korunur (silinmedi).
- `embed_parquet_worker.py` → `done.json`, `embed_delta_chunks.py` /
  `reembed_delta.py` → `manifest.json` içine `chunking_version` yazar.
- `build_bulk_index` bunu `meta.json`'a taşır, **karışık sürümlü** vektör
  dizinini reddeder; `append_sidecar` indeksle sürümü uyuşmayan sidecar'ı
  reddeder; `embed_delta_chunks.py` mevcut indeksin sürümüyle parçalar.
- Alanı olmayan meta = v1 → **canlı indeks (5 Eyl 2026, 31.001.060 vektör)
  düzeltme yüklendikten sonra da v1 parçalayıcıyla çözülür**, alıntılar kaymaz.

### Yeniden gömme koşusu

`schtasks` görevi **EmsalReembed** (tek seferlik, `/rl limited`, 7 Eyl 2026
23:00) → `scripts/reembed_all.cmd`:

1. `embed_parquet_worker.py` → `<bench-dizini>\vec2` (30 HF parquet dosyası,
   ~30,4 M parça). Resumable: `done.json` olan dosya atlanır.
2. `reembed_delta.py` → aynı dizine `delta-reembed-<tarih>` sidecar'ı: parquet
   dışında kalan kararlar (eski `vec\*.manifest.json` listesi 52.731 karar +
   `embedding_vectors`'taki 928 karar; uyap_arsiv, bedesten, mevzuat).
3. `build_bulk_index.py --cache <veri-dizini>\staging\cache.sqlite3` →
   **hazırlık** indeksi; canlı `bulk-*.faiss` dosyalarına dokunulmaz.
4. `reembed_switch.py` → doğrula, geç (aşağıda).

Süre ölçümü: ilk koşu 30,59 M parça / 29,06 saat (ortalama 292 parça/sn).
6 Eyl 2026'da aynı dosya (`aym_norm`) v2 ile 219,9 parça/sn ölçüldü
(v1'de 280,3) → **29-38 saat** beklenir; indeks kurulumu +~1,2 saat.
Günlük crawl (04:30) gömmeyi CPU'da (fastembed ONNX) yapar, GPU'yu
kullanmaz — VRAM çakışması yok.

### Geçiş (`scripts/reembed_switch.py`, ~1-2 dk kesinti)

1. `reembed_check.py`: vektör sayısı canlının en çok %1 altında mı,
   `chunking_version == 2`, `meta.files`'taki sidecar'lar `vec2`'de var mı,
   4 örnek Türkçe sorgu sonuç + alıntı döndürüyor mu (skor ≥ 0,75).
   Başarısızsa hiçbir şey değişmez, sunucu çalışmaya devam eder.
2. `schtasks /end /tn EmsalMcpHttp`.
3. Canlı `bulk-*.{faiss,keys.npz,meta.json}` → `<veri-dizini>\bulk-v1-yedek\`
   (**silinmez**), hazırlık üçlüsü canlı dizine taşınır. Taşıma yarıda
   kalırsa geri alınır ve sunucu eski indeksle açılır.
4. Dizin takası: `vec` → `vec_v1`, `vec2` → `vec`. `EMSAL_BULK_VEC_DIR`
   değişmez (`emsal-env.cmd`, `mcp_http_sunucu.cmd` dokunulmadı).
5. `drop_delta_rows.py delta-reembed-<tarih>`: yeniden gömülen kararların
   delta satırları silinir. Koşu sırasında crawl'ın eklediği YENİ kararlar
   manifest'te olmadığı için delta'da kalır → aramada görünmeye devam eder.
   Ardından `semantic build-matrix`.
6. `schtasks /run /tn EmsalMcpHttp` + `reembed_health.ps1` (streamable-http
   ucu GET'e 406 döner; 12 deneme × 5 sn).

Log: `<veri-dizini>\crawl_logs\reembed.log`, son satır `REEMBED-EXIT <rc>`
(0 tamam, 2 parquet gömme, 3 delta gömme, 4 indeks, 10 doğrulama,
12 taşıma+geri alma, 13 sağlık).

**Geri dönüş:** sunucuyu durdur, `bulk-v1-yedek\` içindeki üçlüyü
`<veri-dizini>`'ya geri taşı, `vec` → `vec2` ve `vec_v1` → `vec` takasını
tersine çevir, sunucuyu başlat. Eski vektör dizini (`vec_v1`, 24 GB) ve
yedek indeks koşudan sonra elle silinir; disk: 186 GB boş ölçüldü
(6 Eyl 2026), vec2 için ~24 GB gerekir.
