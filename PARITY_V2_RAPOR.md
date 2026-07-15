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

