# docs/COOKBOOK.md — Emsal-mcp Kullanım Rehberi

> Her reçete kendi başına çalıştırılabilir; harici dosya gerektirmez.
> Tüm örnekler sentetik (sahte) veri kullanır.

---

## Reçete 1: İlk Araştırma

**Amaç:** Bir konuyu kaynaklar arasında arayın, belgeleri getirin ve önbellek istatistiklerini görüntüleyin.

**Önkoşul:** `emsal-mcp` kurulu ve çalışır durumda.

**Adımlar:**

1. Kaynakların durumunu kontrol edin:
   ```bash
   emsal-mcp sources --json
   ```

2. Konut kirası tavan fiyat konusunda araştırma yapın:
   ```bash
   emsal-mcp research topic "konut kirası tavan fiyat" \
     --sources bedesten,yargitay \
     --fetch-count 5 \
     --json
   ```

3. Araştırma kalite panosuna bakın:
   ```bash
   emsal-mcp research dashboard .emsal_research/bundle.json --json
   ```

4. Önbellek istatistiklerini görüntüleyin:
   ```bash
   emsal-mcp cache stats
   ```

5. Kaynak health durumunu kontrol edin:
   ```bash
   emsal-mcp circuit health --json
   ```

**Beklenen Çıktı:**
- Kaynak listesi (stable/partial/experimental/unavailable)
- Araştırma paketi: `bundle.json`, `results.json`, `index.md`, `warnings.json`
- Kalite panosu: `full_text_ratio`, `citation_safe_ratio`, `draft_readiness_score`
- Önbellek: toplam belge sayısı, boyut dağılımı

---

## Reçete 2: Dilekçe Hazırlama

**Amaç:** Araştırma sonuçlarından dilemma dilekçe paketi oluşturun, denetleyin ve kontrollü taslak üretin.

**Önkoşul:** Reçete 1'den bir araştırma paketi veya doğrudan JSON belge listesi.

**Adımlar:**

1. Araştırma paketinden dilekçe paketi oluşturun:
   ```bash
   emsal-mcp petition pack \
     "Konut tahliye davası" \
     "Kira sözleşmesi feshi ve tahliye talebi" \
     --research-bundle .emsal_research/bundle.json \
     --out-dir petition_pack \
     --json
   ```

2. Paketi denetleyin (8 Kontrol):
   ```bash
   emsal-mcp petition inspect petition_pack/ --json
   ```

3. Dilekçe ana hatlarını üretin:
   ```bash
   emsal-mcp petition outline petition_pack/ --json
   ```

4. Kontrollü dilekçe taslağını üretin:
   ```bash
   emsal-mcp petition draft petition_pack/ --out-dir draft_output --json
   ```

5. Dilekçe davası zincirini oluşturun ve puanlayın:
   ```bash
   emsal-mcp argument build petition_pack/ --json
   emsal-mcp argument score petition_pack/ --json
   ```

**Beklenen Çıktı:**
- Paket dizini: `petition-brief.json`, `citation-bank.md`, `argument-map.md`, `petition-instructions.md`, `draft-skeleton.md`
- Denetim: 8/8 check geçmeli, `draft_safe: true`
- Taslak: `draft.md`, `draft.json`, `footnotes.json`, `warnings.json`
- Hazırlık skoru: `readiness_score` ≥ 0.4 (medium+)

---

## Reçete 3: Mevzuat Arama

**Amaç:** Mevzuat metinlerinde arama yapın, maddeleri çıkarın ve yapı ağacını görüntüleyin.

**Önkoşul:** `emsal-mcp` kurulu.

**Adımlar:**

1. Mevzuat araması yapın:
   ```bash
   emsal-mcp legislation search "konut kirası" \
     --limit 5 \
     --json
   ```

2. Belirli bir belgeyi getirin:
   ```bash
   emsal-mcp legislation get mevzuat-001 --json
   ```

3. Belge içinde madde arayın:
   ```bash
   emsal-mcp legislation articles mevzuat-001 \
     --article-number 6 \
     --json
   ```

4. Anahtar kelime ile madde arayın:
   ```bash
   emsal-mcp legislation articles mevzuat-001 \
     --article-query "kira bedeli" \
     --json
   ```

5. Kısım/bölüm/madde ağacını görüntüleyin:
   ```bash
   emsal-mcp legislation tree mevzuat-001 --json
   ```

6. Gerekçe metinlerini çıkarın:
   ```bash
   emsal-mcp legislation gerekce mevzuat-001 --json
   ```

7. Kaynak sağlık durumunu kontrol edin:
   ```bash
   emsal-mcp legislation status --json
   ```

**Beklenen Çıktı:**
- Arama sonuçları: `legislation_type`, `legislation_no`, `gazette_date` alanları
- Madde listesi: eşleşen maddelerin `number`, `text`, `preview` alanları
- Yapı ağacı: `parts > sections > articles` hiyerarşisi
- Gerekçe: `genel_gerekce` ve `madde_gerekceleri` listesi
- Yasak uyarısı: `"Yasak: Bu modül hiçbir surette mevzuat numarası uydurmaz."`

---

## Reçete 4: Atıf Analizi

**Amaç:** Atıf grafiğini oluşturun, belgelerin birbirini nasıl referans aldığını haritalandırın.

**Önkoşul:** Önbellekte yeterli belge mevcut.

**Adımlar:**

1. Atıf grafiğini oluşturun:
   ```bash
   emsal-mcp graph build --limit-docs 100 --json
   ```

2. Graf istatistiklerini görüntüleyin:
   ```bash
   emsal-mcp graph stats --json
   ```

3. Belirli bir belgenin atıf ilişkilerini gösterin:
   ```bash
   emsal-mcp graph show doc-001 \
     --source bedesten \
     --direction both \
     --json
   ```

4. Bu belgeyi referans alan belgeleri bulun:
   ```bash
   emsal-mcp graph citing doc-001 \
     --source bedesten \
     --limit 20 \
     --json
   ```

5. Bu belgenin referans verdiği belgeleri bulun:
   ```bash
   emsal-mcp graph cited doc-001 \
     --source bedesten \
     --limit 20 \
     --json
   ```

6. Grafı dışa aktarın (mermaid formatı):
   ```bash
   emsal-mcp graph export --format mermaid --json
   ```

**Beklenen Çıktı:**
- Graf: düğüm ve kenar sayıları, atıf yoğunluğu
- İlişkiler: `citing` (bu belgeyi alan), `cited` (bu belgenintiği), `both`
- Dışa aktarma: JSON, DOT, veya Mermaid formatı

---

## Reçete 5: Semantic Search

**Amaç:** Hibrit arama indeksi oluşturun, filtrelerle.semantic arama yapın.

**Önkoşul:** Önbellekte belgeler mevcut.

**Adımlar:**

1. FTS5 + TF-IDF indeksini oluşturun:
   ```bash
   emsal-mcp semantic index --json
   ```

2. İndeks durumunu kontrol edin:
   ```bash
   emsal-mcp semantic status --json
   ```

3. TF-IDF cosine benzerliği ile arama yapın:
   ```bash
   emsal-mcp semantic search "kira tahliye" \
     --limit 10 \
     --source yargitay \
     --chamber "3. Hukuk Dairesi" \
     --json
   ```

4. Hibrit arama yapın (BM25 + TF-IDF):
   ```bash
   emsal-mcp semantic hybrid "kira tahliye" \
     --limit 10 \
     --weight 0.6 \
     --source bedesten \
     --json
   ```

5. Yoğun embedding indeksi oluşturun:
   ```bash
   emsal-mcp semantic embed-index --json
   ```

6. Yoğun embedding araması yapın:
   ```bash
   emsal-mcp semantic embed-search "kira tahliye" \
     --limit 10 \
     --json
   ```

7. Kademeli güncelleme yapın:
   ```bash
   emsal-mcp semantic update-indexes --json
   ```

**Beklenen Çıktı:**
- İndeks: FTS5 satır sayısı, vektör sayısı, belge toplamı
- Arama: `bm25_score`, `cosine_score`, `hybrid_score`, `snippet`
- Filtreler: `--source`, `--court`, `--chamber` parametreleri
- Embedding: provider bazlı benzerlik sonuçları

---

## Reçete 6: Release & Export

**Amaç:** Release hazırlık merkezini çalıştırın, notlar üretin ve dışa aktarın.

**Önkoşul:** Tüm modüller import edilebilir durumda.

**Adımlar:**

1. Release hazırlık merkezini çalıştırın:
   ```bash
   emsal-mcp release command-center --json
   ```

2. v1.0.0 hazırlık kapısını kontrol edin:
   ```bash
   emsal-mcp release v1-readiness --json
   ```

3. Versiyon artışını hesaplayın:
   ```bash
   emsal-mcp release version-bump --minor --json
   ```

4. İnsan-okunur release özetini oluşturun:
   ```bash
   emsal-mcp release summary --json
   ```

5. Release notlarını üretin:
   ```bash
   emsal-mcp release notes --out exports/release-notes.md
   ```

6. Release arşivi oluşturun:
   ```bash
   emsal-mcp release archive --out-dir exports/release-archive --json
   ```

7. Release geçmişini kaydedin:
   ```bash
   emsal-mcp release history --out-dir exports/release-history --json
   ```

8. Release duman testlerini çalıştırın:
   ```bash
   emsal-mcp smoke --json
   ```

9. Draft'ı düz metin olarak dışa aktarın:
   ```bash
   emsal-mcp export txt draft_output/draft.md \
     --out-path exports/draft.txt \
     --json
   ```

10. Export format yeteneklerini görüntüleyin:
    ```bash
    emsal-mcp export capabilities --json
    ```

**Beklenen Çıktı:**
- Command center: `overall_readiness` skoru (0-100), kontrol durumları
- v1-readiness: `ready: true/false`, kriterler, engelleyici sorunlar
- Release notları: markdown formatında değişiklik özeti
- Arşiv: dashboard + notes + history bir arada
- Export: DOCX, TXT, PDF, UDF formatları (toolkit durumuna göre)

---

## Ek Reçete: Mikro Benchmark

**Amaç:** Performans karşılaştırması için sentetik corpus ile benchmark çalıştırın.

**Adımlar:**

```bash
emsal-mcp benchmark --corpus-size 50 --json
```

**Beklenen Çıktı:**
- Arama süresi, indeksleme süresi, toplam benchmark skoru

---

## Ek Reçete: Kaynak Kalibrasyonu

**Amaç:** Kaynakların güvenli istek oranlarını ölçün.

**Adımlar:**

```bash
emsal-mcp calibrate all --online --json
```

**Beklenen Çıktı:**
- Kaynak başına: ortalama yanıt süresi, güvenli rate-limit aralığı

---

---

## Reçete 9: Niş Korpus İnşası ve Semantik Arama (M-96)

**Amaç:** Belirli bir konuda (ör. iş hukuku, tazminat, boşanma) crawl_full_text
ile full-text korpus oluşturun, M-95 gerçek embedding ile indeksleyin ve
semantik arama performansını ölçün. M-95 öncesi (hash) ve sonrası (multilingual
E5) recall@k farkını sayısal olarak gösterir.

**Önkoşul:** `pip install emsal-mcp[embeddings]` ile fastembed kurulu.
``"fastembed-multilingual-e5"`` aktif provider olarak seçili.

**Adımlar:**

1. **Mevcut sağlayıcıları listeleyin:**
   ```bash
   python -c "from emsal_mcp.embeddings import list_embedding_providers; \
     import json; print(json.dumps(list_embedding_providers(), indent=2))"
   ```
   Çıktıda ``"fastembed-multilingual-e5"`` için ``"status": "available"``
   olduğundan emin olun.

2. **Konu-bazlı korpus crawl:**
   ```bash
   # İş hukuku korpusu — broad anchor ile crawl
   python -c "
   from emsal_mcp.corpus_builder import crawl_full_text
   result = crawl_full_text('bedesten', phrase='tazminat',
       item_type='YARGITAYKARARI', max_docs=200, max_pages=20)
   print('Indexed:', result['documents_stored'])
   print('Status:', result['ok'])
   "
   ```
   İsteğe bağlı: Farklı konularda tekrarlayın (``phrase='boşanma'``, ``phrase='kira'``).

3. **Gerçek embedding ile indeks inşa edin (M-95):**
   ```bash
   # İlk seferde model yaklaşık 120MB indirir, sonra local cache'den çalışır
   python -c "
   from emsal_mcp.semantic import build_embedding_index
   result = build_embedding_index(provider='fastembed-multilingual-e5')
   print('Indexed:', result.get('documents_indexed'))
   print('Seconds:', result.get('elapsed_seconds'))
   print('Dimensions:', result.get('dimensions'))
   "
   ```

4. **Semantik arama ile sorgulama:**
   ```bash
   # Bu sorgu hash ile "isci tazminat" kelimelerini arar;
   # gerçek embedding ile "calisan alacagi" gibi anlamsal eşleri de bulur
   python -c "
   from emsal_mcp.semantic import embedding_search
   import json
   result = embedding_search('is kazasi sonucu maddi tazminat',
       limit=5, provider='fastembed-multilingual-e5')
   for r in result.get('results', []):
       print(r.get('document_id'), r.get('score'), r.get('title', '')[:80])
   "
   ```

5. **Hash vs Gerçek Embedding karşılaştırması:**
   ```bash
   # Aynı sorguyu iki provider ile çalıştırıp farkı görün
   python -c "
   from emsal_mcp.semantic import embedding_search

   query = 'isverenin is sagligi ve guvenligi yukumlulugu'
   for prov in ['local-hash-v1', 'fastembed-multilingual-e5']:
       r = embedding_search(query, limit=10, provider=prov)
       print(f'{prov}: {r.get(\"total_matches\")} eşleşme')
       # İlk 3 sonucun document_id'lerini karşılaştırın
       ids = [d['document_id'] for d in r.get('results', [])[:3]]
       print(f'  Top-3: {ids}')
   "
   ```

6. **Eval ile recall ölçümü (M-71):**
   ```bash
   # Eval koşumunu her iki provider ile yapın
   python -m emsal_mcp.cli eval run --provider local-hash-v1 --json
   python -m emsal_mcp.cli eval run --provider fastembed-multilingual-e5 --json
   ```
   NDCG ve recall@5/recall@10 metriklerini karşılaştırın. Gerçek embedding ile
   özellikle eşanlamlı terim içeren sorgularda (ör. "iş kazası" → "is kazasi",
   "calisma guvenligi") belirgin kazanç beklenir.

**Beklenen Çıktı:**
- Crawl: 200 full-text belge local önbelleğe eklenir
- Embedding index: 200 belge 384-boyutlu vektörlerle indekslenir (yaklaşık 30-60 sn)
- Semantik arama: Anlamsal eşleşme (eşanlamlı terimler) hash'e göre belirgin
  ölçüde daha iyi
- Eval: Multilingual E5 ile recall@5 ve nDCG'de %15-40 arası kazanç

**Notlar:**
- ``fastembed-multilingual-e5`` 100+ dil destekler; Türkçe morfoloji için
  optimize edilmiştir (ekler, büyük-küçük harf, diakritik).
- İndeks yalnızca mevcut provider için geçerlidir; provider değiştirirseniz
  ``build_embedding_index(force_rebuild=True)`` ile yeniden indeksleyin.
- E5 modeli ``query: `` prefix'i ile sorguları, ``passage: `` prefix'i ile
  belgeleri ayırt eder — bu otomatik olarak yapılır.
- Hash provider (``local-hash-v1``) her zaman kullanılabilir; embedding extra'sı
  kurulu değilse otomatik fallback yapılır. Çekirdek stdlib+sqlite3 kalır.

---

## Reçete 10: Core Profil ile Ajan Bağlama + load_extended_tools Akışı

**Amaç:** Core profilde (14 araç) başlayıp, legal_research_guide ile hangi
genişletilmiş kategorileri yüklemeniz gerektiğini öğrenin, ardından
`load_extended_tools` ile seçili kategorileri dinamik olarak sunucuya ekleyin.

**Önkoşul:** `emsal-mcp` kurulu ve çalışır durumda. Varsayılan profil `core`'dur.

**Adımlar:**

1. **Core profilde sunucuyu başlatın ve mevcut araçları listeleyin:**
   ```bash
   emsal-mcp health_check --json
   ```
   Çıktıda `"tool_count": 14` ve core araç listesi görünmeli. Core profil
   şu 14 aracı sunar:
   `search_decisions`, `get_document`, `search_local_corpus`,
   `search_legislation`, `get_legislation`, `research_topic`,
   `citation_check`, `prepare_petition`, `export_document`,
   `read_legal_file`, `list_sources`, `legal_research_guide`,
   `load_extended_tools`, `health_check`.

2. **Genişletilmiş kategorileri keşfedin:**
   ```bash
   emsal-mcp legal_research_guide --json
   ```
   Tam rehberde `extended_tools` başlığı altında 15 kategori listelenir:
   `cache_admin`, `release`, `analytics`, `routing`, `health_admin`,
   `citation_graph`, `dedup`, `watch`, `privacy`, `chambers`, `indexing`,
   `drafting_advanced`, `udf_admin`, `research_admin`, `query_tools`.

3. **Belirli bir kategori hakkında bilgi alın:**
   ```bash
   emsal-mcp legal_research_guide topic=extended_tools --json
   ```
   Her kategorinin tool_count ve örnek araç isimleri görüntülenir.
   Örneğin `citation_graph` kategorisi 6 araç içerir:
   `build_citation_graph`, `get_citation_graph`, `find_citing_documents`,
   `find_cited_documents`, `citation_graph_stats`, `export_citation_graph`.

4. **Seçili kategorileri yükleyin:**
   ```bash
   emsal-mcp load_extended_tools categories="citation_graph,health_admin" --json
   ```
   Beklenen çıktı:
   ```json
   {
     "ok": true,
     "loaded_tools": ["build_citation_graph", "get_citation_graph", ...],
     "already_loaded": [],
     "invalid_categories": [],
     "note": "MCP client tool listesini yenilemelidir."
   }
   ```
   Yüklenen araçlar sunucu yeniden başlatılmadan LLM ajanına görünür hale gelir.

5. **Yüklenen araçların doğrulanması:**
   ```bash
   emsal-mcp health_check --json
   ```
   `"extended_loaded"` alanında yüklenen kategorilerin araç sayısı görünür.
   Örneğin: `"citation_graph": 6, "health_admin": 6`.

6. **Ek kategoriler ekleyin (kademeli genişletme):**
   ```bash
   emsal-mcp load_extended_tools categories="cache_admin,indexing" --json
   ```
   Daha önce yüklenen kategoriler `already_loaded` listesine düşer,
   yalnızca yeni kategoriler aktif edilir. Toplam araç sayısı artar.

7. **Geçersiz kategori hatalarını kontrol edin:**
   ```bash
   emsal-mcp load_extended_tools categories="yanlis_kategori,dedup" --json
   ```
   `"invalid_categories": ["yanlis_kategori"]` döner, `dedup` başarıyla yüklenir.

**Beklenen Çıktı:**
- Core profil: 14 araç, restart gerektirmez
- `legal_research_guide`: 15 kategori, her biri tool_count + örnek listesi
- `load_extended_tools`: success/partial durum, loaded/invalid listesi
- Yükleme sonrası `health_check` ile toplam araç sayısının arttığı doğrulanır
- Kategoriler arası duplicate kontrolü: aynı kategori tekrar yüklendiğinde
  `already_loaded` listesine düşer

**Notlar:**
- Core profil varsayılandır; `EMSAL_TOOL_PROFILE=full` ile 119 araca geçiş
  yapılabilir ama bu durumda `load_extended_tools` anlamsızdır.
- Her yükleme turunda yalnızca belirtilen kategoriler eklenir; önceki
  yüklemeler korunur (stateful).
- MCP client (LLM ajanı) tool listesini yenilemelidir — yükleme
  sunucu tarafında yapılır, client'a bildirim gitmez.

---

## Notlar

- Tüm `--json` çıktıları `JSON_CONTRACTS.md` ile uyumludur.
- Sentetik veriler gerçek vakaları temsil etmez; yalnızca akışı gösterir.
- Kaynak durumları (`stable`, `partial`, `experimental`, `unavailable`) `
  emsal-mcp sources --json` ile doğrulanabilir.
- Atıf güvenliği kuralları için `docs/MCP_CONTRACTS.md`败 bakın.
