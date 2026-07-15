# Parity V2 Raporu

## Görev 1 — `get_document` çıktı şişkinliğini gider (içerik tekilleştirme)

**Durum:** ✅ Tamamlandı

**Tarih:** 2026-07-15

### Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/emsal_mcp/models.py` | `Document` modeline `to_tool_payload(include_raw=False)` metodu eklendi. Varsayılan çıktıda: tek `markdown` alanı, `raw` çıkarıldı, `full_text` çıkarıldı, `metadata.content` (base64 HTML) çıkarıldı. |
| `src/emsal_mcp/server.py` | `get_document` aracına `include_raw: bool = False` parametresi eklendi. Dönüş `doc.model_dump(mode="json")` yerine `doc.to_tool_payload(include_raw=include_raw)` kullanıyor. Cache işlemleri (`cache.set`, `cache.store_document`) tam `Document`/`model_dump()` ile çalışmaya devam ediyor. |
| `docs/MCP_CONTRACTS.md` | `get_document` kontratı güncellendi: `include_raw` parametresi ve deduplicated çıktı şekli belgelendi. |
| `docs/JSON_CONTRACTS.md` | `Document` kontratı güncellendi: `raw`, `full_text` (ayrı alan), `metadata.content` varsayılan çıktıdan kaldırıldı. |
| `tests/test_invariants.py` | `TestToToolPayload` test sınıfı eklendi (9 test): tek metin alanı, full_text→markdown promosyonu, raw çıkarma (varsayılan/include_raw), metadata.content çıkarma, boş metadata, boyut kıyaslaması. |

### Test çıktısı özeti

```
pytest tests/test_invariants.py::TestToToolPayload -v
9 passed

pytest -x -q  (tam suite)
1696 passed, 1 warning
```

Regresyon yok.

### Canlı doğrulama örneği

Yerel Python script ile doğrulandı:

```python
doc = Document(
    markdown='metin' * 200,
    full_text='metin' * 200,
    raw={'data': {'content': 'x' * 5000}},
    metadata={'content': 'x' * 5000, 'kararNo': '2024/1'},
)
payload = doc.to_tool_payload()
```

| Metrik | Değer |
|---|---|
| Orijinal `model_dump` boyutu | 20,240 chars |
| `to_tool_payload` boyutu | 6,349 chars |
| Oran | **%31.4** (hedef: <%40) |
| `raw` mevcut mu? | ❌ Hayır ✅ |
| `full_text` mevcut mu? | ❌ Hayır ✅ |
| `metadata.content` mevcut mu? | ❌ Hayır ✅ |
| `markdown` tam metin? | ✅ Evet |
| Cache `store_document` tam `Document` ile çalışıyor mu? | ✅ Evet |

---

## Görev 2 — `search_decisions` yanıtına toplam sonuç / sayfa bilgisi ekle

**Durum:** ✅ Tamamlandı

**Tarih:** 2026-07-15

### Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/emsal_mcp/models.py` | `SearchPage` modeli eklendi: `results`, `total`, `page`, `page_size`, `total_pages` alanları. |
| `src/emsal_mcp/sources/base.py` | `SourceClient`'a opsiyonel `search_page(query, limit, page, **filters) -> SearchPage` metodu eklendi. Varsayılan: `search()`'ü çağırıp `total=None` döndürür. |
| `src/emsal_mcp/sources/bedesten.py` | `search_page()` override edildi: upstream yanıtındaki `data.total` alanını okur (`total=973` vb.), `total_pages` hesaplar. `search()`, `search_page()`'e yönlendirildi (backward compat korundu). |
| `src/emsal_mcp/server.py` | `search_decisions` aracı `search_page()` kullanır oldu. Yanıt dict'inde üst düzey `results`, `total_results`, `page`, `total_pages` alanları. Toplam alınamazsa `null` + warning. |
| `docs/MCP_CONTRACTS.md` | `search_decisions` çıktı kontratı güncellendi: pagination alanları belgelendi. |

### Upstream doğrulama

Canlı sorgu ile upstream yanıtındaki total alan adı doğrulandı:

```
Bedesten API response: {"emsalKararList": [...], "total": 973, "start": 10}
```

Alan adı: **`data.total`** (int, toplam eşleşen kayıt sayısı).

### Test çıktısı özeti

```
pytest -x -q (tam suite)
1696 passed, 1 warning
```

Regresyon yok.

### Canlı doğrulama örneği

```python
sp = await ci.search_page("+tahliye +taahhüt +kira", limit=5, page=1)
```

| Metrik | Değer |
|---|---|
| `total` | 973 |
| `page` | 1 |
| `page_size` | 5 |
| `total_pages` | 195 |
| `results` count | 5 |
| `alternate_url` metadata'da | ✅ Evet |
| `search()` `list[SearchResult]` döndürüyor | ✅ Evet |

---

## Görev 3 — Yanıltıcı `metadata_only` mesajını düzelt

**Durum:** ✅ Tamamlandı

**Tarih:** 2026-07-15

### Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/emsal_mcp/models.py` | `build_content_status_fields` fonksiyonunda `METADATA_ONLY` branch'i: Bedesten kaynaklı sonuçlar için yeni yönlendirme mesajı, diğer kaynaklar için eski uyarı korundu. |

### Değişiklik detayı

**Önce:**
```
METADATA_ONLY → "Bu kayıtta tam metin yok; dilekçede kullanmadan önce resmi kaynaktan doğrulayın."
```

**Sonra:**
```
METADATA_ONLY + source="bedesten" → "Arama sonucu özet niteliğindedir; tam metin için get_document(...) çağırın."
METADATA_ONLY + diğer kaynaklar → (eski mesaj korunur)
PDF_LINK_ONLY → (eski PDF mesajı korunur)
FULL_TEXT / HTML_MARKDOWN → (mesaj yok, korunur)
```

`content_status` alanı `metadata_only` olarak kalır (yalan söylenmez); yalnızca `recommended_next_step` yönlendirmesi düzeltildi.

### Test çıktısı özeti

```
pytest -x -q (tam suite)
1696 passed, 1 warning
```

Regresyon yok.

### Canlı doğrulama örneği

| Test | Mesaj |
|---|---|
| Bedesten METADATA_ONLY | `Arama sonucu özet niteliğindedir; tam metin için get_document(source='bedesten', document_id='1060612000') çağırın.` ✅ |
| KVKK METADATA_ONLY | `Bu kayıtta tam metin yok; dilekçede kullanmadan önce resmi kaynaktan doğrulayın.` (eski) ✅ |
| PDF_LINK_ONLY | `Bu kayıt PDF bağlantısı içerir; ...` (eski) ✅ |
| FULL_TEXT | `None` (mesaj yok) ✅ |

---

## Görev 4 — Uzun belgelerde sayfalama (40k karakter)

**Durum:** ✅ Tamamlandı

**Tarih:** 2026-07-15

### Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/emsal_mcp/server_utils.py` | `split_markdown_for_pagination(text, page_number, max_chars=40000)` saf fonksiyonu + `_split_paragraphs`, `_split_sentences`, `_split_forced` yardımcıları eklendi. |
| `src/emsal_mcp/server.py` | `get_document` aracına `page_number: int = 1` parametresi eklendi. Metin 40k karakteri aşarsa paragraf sınırından böler; yanıta `current_page`, `total_pages`, `total_chars` alanları eklendi. |
| `docs/MCP_CONTRACTS.md` | `get_document` kontratı `page_number` ve sayfa alanları ile güncellendi. |
| `tests/test_invariants.py` | `TestSplitMarkdownForPagination` sınıfı (6 test): kısa metin tek sayfa, 100k+ yapay metin çoklu sayfa, paragraf bütünlüğü, dev paragraf fallback, sayfa sınırı clamp. |

### Test çıktısı özeti

```
pytest tests/test_invariants.py::TestSplitMarkdownForPagination -v
6 passed

pytest -x -q (tam suite)
1702 passed, 1 warning
```

Regresyon yok.

### Yapay test doğrulaması

114k karakterlik yapay metin (2000 paragraf) → 4 sayfa:

| Kontrol | Sonuç |
|---|---|
| Paragraf bütünlüğü | Her paragraf tam olarak 1 sayfada ✅ |
| Sayfa sınırı | Hiçbir sayfa 40k karakteri aşmaz ✅ |
| Birleşim = orijinal | Sayfalar birleştirilince orijinal metin ✅ |
| Kısa metin (< 40k) | `1/1` sayfa bilgisi ✅ |
| Dev tek paragraf | Sentence-boundary fallback ✅ |
| Sayfa numarası clamp | Out-of-bounds → son sayfa / ilk sayfa ✅ |

---

## Görev 5 — AİHM/HUDOC kaynağı ekle

**Durum:** ✅ Kısmen tamamlandı (get_document çalışıyor, search API 404)

**Tarih:** 2026-07-15

### Upstream gözlem (şema tahmini yasak — durma koşulu 4)

HUDOC search API'si (`/app/query/results`) **HTTP 404** döndürüyor — endpoint kaldırılmış veya taşınmış. Session cookie, POST, farklı header kombinasyonları denendi; hepsi 404. Belge API'si (`/app/conversion/docx/html/body`) çalışıyor.

Gözlemlenen ham yanıt:
```
GET https://hudoc.echr.coe.int/app/query/results?query=... -> 404 (37838 bytes)
Content-Type: text/html
<!DOCTYPE html>...<title>404: Not Found</title>...
```

Belge API'si:
```
GET https://hudoc.echr.coe.int/app/conversion/docx/html/body?library=ECHR&id=001-218575 -> 200 (415846 bytes)
Content-Type: text/html (styled document)
```

### Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/emsal_mcp/sources/aihm.py` | **YENİ:** `AihmClient(SourceClient)` — `get_document()` HUDOC HTML API ile çalışıyor; `search()` boş liste döndürüyor (API mevcut değil). |
| `src/emsal_mcp/sources/registry.py` | `_AihmClient` sınıfı + `registry()`'ye `"aihm"` kaydı eklendi. `EXPERIMENTAL` statü. |
| `src/emsal_mcp/server.py` | `search_decisions` docstring: `source="aihm"` belgisi eklendi. |
| `tests/test_adapters.py` | `EXPECTED` listesine `"aihm"` eklendi. |
| `tests/test_capability_contract.py` | `EXPECTED_SOURCES` listesine `"aihm"` eklendi. |

### Test çıktısı özeti

```
pytest -x -q (tam suite)
1702 passed, 1 warning
```

Regresyon yok.

### Canlı doğrulama örneği

| Test | Sonuç |
|---|---|
| `get_document("aihm", "001-218575")` | ✅ 233,937 chars markdown (Kavala kararı, Fransızca) |
| `search("Kavala")` | ✅ Boş liste (çökme yok) |
| `get_source("aihm")` | ✅ Registry'den başarıyla alınıyor |
| Registry status | ✅ `experimental` |

### Bilinen kısıtlamalar

- **Arama API'si mevcut değil:** HUDOC `/app/query/results` endpoint'i HTTP 404. AİHM araması için hosted yargi-mcp `aihm_ictihat_ara` aracı kullanılmalı.
- **Belge dili:** HUDOC belgeleri orijinal dilinde döner (İngilizce/Fransızca); Türkçe çeviri her zaman mevcut olmayabilir.

---

## Görev 6 — Tek mevzuat içinde boolean arama (`scope='article'` güçlendirme)

**Durum:** ✅ Tamamlandı

**Tarih:** 2026-07-15

### Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/emsal_mcp/legislation.py` | `_BooleanEvaluator` sınıfı (recursive-descent parser): `AND/OR/NOT/"phrase"/()` + örtük AND + Türkçe casefold (İ→i, I→ı, ASCII I belirsizliği için çift fold) + kök eşleşme (prefix). `evaluate_boolean_query()` ve `_build_snippet()` fonksiyonları. `search_legislation_articles` güncellendi: boolean evaluator kullanıyor, `match_count` sıralı, `snippet` bold highlight. Whitespace normalizasyonu (`\r\n` → space). |

### Değişiklik detayı

**Boolean evaluator özellikleri:**
- `AND` / `OR` / `NOT` (BÜYÜK harf zorunlu)
- `"tam ifade"` (çift tırnak)
- `()` gruplama
- Bitişik kelimeler → örtük AND
- Türkçe büyük/küçük harf duyarsız: `İ→i`, `I→ı`, ASCII-I belirsizliği için çift fold
- Kelime kökten ileri eşleşme: `tazminat` → `tazminatı` eşleşir
- Whitespace normalizasyonu: `açık\r\nrıza` → `açık rıza` olarak eşleşir

**Araç çıktısı (madde başına):**
- `number` (madde_no)
- `match_count` (eşleşen terim sayısı — relevance sıralama)
- `snippet` (`**bold**` highlight ile ~120 karakterlik pasaj)

### Test çıktısı özeti

```
pytest -x -q (tam suite)
1702 passed, 1 warning
```

### Canlı doğrulama örneği

KVKK (mevzuat_id 104383) içinde `"açık rıza" AND sağlık`:

| Metrik | Değer |
|---|---|
| Eşleşen madde | Madde 6 |
| `match_count` | 2 |
| snippet | `…**sağlık** hizmetlerinin planlanması…` ✅ |
| İlk sonuç | ✅ m.6 |

---

## Görev 7 — AYM adaptörünü olgunlaştır

**Durum:** ⚠️ Kısmen tamamlandı (SPA migrasyonu nedeniyle sınırlı)

**Tarih:** 2026-07-15

### Upstream gözlem (şema tahmini yasak — durma koşulu 4)

AYM 2025'te KBB (Karar Bilgi Bankası) React SPA'ya geçti:
- Eski `/Ara?KelimeAra[]=...` → **404** (endpoint kaldırılmış)
- Yeni `/kbb/core/public/search` → **405** (POST) / **SPA HTML** (GET)
- Belge URL'leri (`/BB/...`, `/ND/...`) → **SPA shell** (2047 byte, karar metni yok)
- API base: `core/public/` (göreceli yol, SPA içinden çağrılıyor)
- Belge ID'leri UUID formatına geçmiş (`a1798dda-...`)

### Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/emsal_mcp/sources/simple_public.py` | `AymClient` yeniden yazıldı: iki banka desteği (BB/ND), `decision_type` filtresi (`norm_denetimi`/`bireysel_basvuru`), `_resolve_base()` yardımcısı, SPA shell tespiti, eski HTML scraping fallback, UUID ID desteği, graceful degradation. |
| `src/emsal_mcp/sources/registry.py` | `_AymClient` kısıtlamaları güncellendi. |

### Test çıktısı özeti

```
pytest -x -q (tam suite)
1702 passed, 1 warning
```

Regresyon yok.

### Bilinen kısıtlamalar

- **Arama API'si mevcut değil:** AYM KBB React SPA; `/kbb/core/public/search` HTTP 405. Canlı AYM araması için hosted `yargi-mcp-pro_aym_ictihat_ara` kullanılmalı.
- **Belge metni direkt alınamıyor:** Eski `/BB/` ve `/ND/` URL'leri SPA shell döndürüyor. Belge metni için `yargi-mcp-pro_ictihat_getir` kullanılmalı.
- **HTML scraping (legacy):** Eski `/Ara` endpoint'i hâlâ çalışıyorsa (intranet/legacy ortamlarda) mevcut scraping kodu korunur.

---

