# Emsal-mcp

> **v4.0.0** — 120 MCP tools · 161 CLI commands · 53 test files · 42 source modules
>
> [![CI](https://github.com/brachindul/emsal-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/brachindul/emsal-mcp/actions/workflows/ci.yml)

Resmî ve kamuya açık Türk hukuk kaynaklarında (emsal kararlar ve mevzuat) citation-safe arama, araştırma ve belge hazırlık için MCP sunucusu.

## Kırmızı çizgiler

- Karar, metadata, tarih, esas/karar no, daire, atıf veya kanun maddesi uydurulmaz.
- `full_text` / `html_markdown` içeriği olmayan belgeler quote/draft için kullanılmaz.
- `quoteUsable` ve `draftUsable` sadece tam metin/HTML markdown varsa `true` olur.
- Rate-limit bilinçli olarak muhafazakâr değildir; tek kullanıcı/tek bilgisayar hedeflenmiştir.

## Kaynaklar

Registry: Bedesten/Yargıtay, AYM, Danıştay, Uyuşmazlık, Rekabet, Sayıştay, GİB, Mevzuat, Resmî Gazete, KVKK.

## Kurulum

```powershell
# Windows
cd <repo-dizini>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,mcp]"

# macOS / Linux
cd <repo-dizini>
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp]"

emsal-mcp version
emsal-mcp release command-center --json
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

## Özellikler

| Modül | Sürüm | Araç Sayısı | Açıklama |
|-------|-------|-------------|----------|
| **Core** (search, get, capabilities, smoke) | v0.1–0.4 | 5 | Kaynak arama, belge erişimi, yetenek keşfi |
| **Cache v2** | v0.3 | 3 | Yerel arama, istatistikler, belge listeleme |
| **Research** | v0.5 | 3 | Konu araştırması, bundle yenileme, kalite paneli |
| **Citation** | v0.6 | 2 | Hukuk alıntı formatlama ve doğrulama |
| **Petition Pack** | v0.7–0.8 | 6 | Dilekçe paketi, denetim, anahat, kontrollü taslak |
| **UDF Toolkit** | v0.9 | 5 | UDF durumu, yazar kılavuzu, DOCX/UDF dönüşümü |
| **Legislation** | v0.10 | 8 | Mevzuat arama, madde analizi, ağaç yapısı, gerekçe |
| **Semantic Search** | v0.11 | 5 | FTS5 BM25 + TF-IDF cosine hibrit arama |
| **Chamber Profiling** | v0.12 | 4 | Daire analizi, profil, zaman çizelgesi, benzerlik |
| **Release Management** | v0.13 | 4 | Komuta merkezi, sürüm, v1 hazırlık, özet |

**Toplam:** 120 MCP tool · 161 CLI komutu · 53 test dosyası
