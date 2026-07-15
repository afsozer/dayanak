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

