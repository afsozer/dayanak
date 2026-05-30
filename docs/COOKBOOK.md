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

## Notlar

- Tüm `--json` çıktıları `JSON_CONTRACTS.md` ile uyumludur.
- Sentetik veriler gerçek vakaları temsil etmez; yalnızca akışı gösterir.
- Kaynak durumları (`stable`, `partial`, `experimental`, `unavailable`) `
  emsal-mcp sources --json` ile doğrulanabilir.
- Atıf güvenliği kuralları için `docs/MCP_CONTRACTS.md`败 bakın.
