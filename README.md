# Emsal-mcp

Fatih Sözer'in yerel makinesinde çalışan, resmi/public hukuk kaynak odaklı, citation-safe MCP araştırma ve belge hazırlık sistemi.

## Kırmızı çizgiler

- Karar, metadata, tarih, esas/karar no, daire, atıf veya kanun maddesi uydurulmaz.
- `full_text` / `html_markdown` içeriği olmayan belgeler quote/draft için kullanılmaz.
- `quoteUsable` ve `draftUsable` sadece tam metin/HTML markdown varsa `true` olur.
- Rate-limit bilinçli olarak muhafazakâr değildir; tek kullanıcı/tek bilgisayar hedeflenmiştir.

## Kaynaklar

MVP registry: Bedesten/Yargıtay, AYM, Danıştay, Uyuşmazlık, Rekabet, Sayıştay, GİB, Mevzuat.

## Kurulum

```powershell
cd C:\Users\Sozer\Emsal-mcp
python -m venv .venv
.\.venv\Scripts\pip install -e .[dev,mcp]
pytest
```

## CLI örnekleri

```powershell
emsal-mcp sources
emsal-mcp search bedesten "muvazaa" --limit 5
emsal-mcp get bedesten DOCUMENT_ID
emsal-mcp smoke --offline
```

## MCP server

```powershell
emsal-mcp-server
```

Tool'lar: `search_decisions`, `get_document`, `build_input_pack`, `draft_document`, `export_bundle`, `read_udf`, `write_udf`, `source_capabilities`, `release_smoke`.
