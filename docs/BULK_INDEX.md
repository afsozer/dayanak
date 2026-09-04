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
