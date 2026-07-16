# Yargı-MCP Parite Talimatı — V2

**Amaç:** 2026-07-15 tarihli canlı karşılaştırmada tespit edilen farkları kapatmak. V1 talimatındaki görevler (Solr auto-`+`, relevance sıralaması, upstream hata yüzeyi) tamamlandı; bu belge devamıdır.

**Uygulayıcı:** Otomatik ajan (DeepSeek). **Denetleyici:** Claude / kullanıcı.

## Uygulayıcı için genel kurallar (ZORUNLU)

1. **Görev sırası = öncelik sırası.** Her görev tek başına commit edilebilir; bir görevin doğrulaması geçmeden sonrakine geçme.
2. **Her görev için tek commit**, mesaj formatı: `feat(parity-v2-N): <özet>` veya `fix(parity-v2-N): <özet>`.
3. **DURMA KOŞULLARI** — aşağıdakilerden biri olursa çalışmayı DURDUR, o ana kadarki durumu `PARITY_V2_RAPOR.md` dosyasına yaz ve çık:
   - Aynı görevde 3 denemede de doğrulama (test) geçmiyorsa.
   - Bir görevde 45 dakikadan fazla zaman harcandıysa.
   - `pytest` toplamında görevden ÖNCE geçen bir test görevden sonra kırıldıysa ve 1 denemede onarılamadıysa.
   - Upstream (HUDOC, AYM, Bedesten) beklenen şemada yanıt vermiyorsa — şemayı tahmin ederek kod yazma; gözlemlenen ham yanıtı rapora koy ve dur.
4. **Kapsam disiplini:** Görev metninde adı geçmeyen dosyaları değiştirme. Refactor yapma. Yeni bağımlılık ekleme (Görev D'deki istisna hariç).
5. Her görev sonunda `PARITY_V2_RAPOR.md` dosyasına ekle: görev no, değişen dosyalar, test çıktısı özeti, canlı doğrulama örneği (gerçek sorgu + ilk sonuç).
6. Ağ testlerinde kaynaklara saniyede 1'den fazla istek atma.

---

## Görev 1 — `get_document` çıktı şişkinliğini gider (içerik tekilleştirme)

**Sorun:** `get_document` MCP aracı aynı karar metnini 4 kopya döndürüyor:
`metadata.content` (base64 HTML), `raw.data.content` (aynı base64), `full_text` ve `markdown`. Tek karar ~15k token tutuyor; hosted yargı-mcp aynı belgeyi tek Markdown olarak veriyor.

**Konum:** `src/emsal_mcp/server.py` `get_document` aracı (≈ satır 678–714, `doc.model_dump(mode="json")` dönüşü) ve `src/emsal_mcp/models.py` `Document` modeli; base64 alanlar `src/emsal_mcp/sources/bedesten.py` `get_document` içinde `metadata`/`raw`'a yazılıyor.

**Yapılacaklar:**
1. `Document` modeline bir yardımcı ekle: `to_tool_payload(include_raw: bool = False) -> dict`. Varsayılan çıktıda:
   - `markdown` alanını TEK metin alanı olarak tut; `full_text` alanını çıkar (veya `markdown` yoksa `full_text`'i `markdown` adıyla ver — ikisini birden asla verme).
   - `raw` alanını tamamen çıkar.
   - `metadata.content` (base64) anahtarını çıkar; `metadata`'nın kalanını (documentId, birimAdi, esasNo, kararNo, tarih, alternate_url vb.) koru.
2. `server.py` `get_document` aracı `doc.model_dump(...)` yerine `doc.to_tool_payload()` döndürsün. Araca `include_raw: bool = False` parametresi ekle (debug için ham yanıt isteyen çağıran `True` verebilir).
3. **Cache davranışını BOZMA:** `cache.set(...)` ve `cache.store_document(doc)` çağrıları tam `Document` ile çalışmaya devam etsin (budama yalnız araç çıktısında).
4. `docs/MCP_CONTRACTS.md` ve varsa JSON contract testlerini güncelle.

**Doğrulama:** Birim testi: base64 içerikli sahte `Document` → `to_tool_payload()` çıktısında `raw` yok, `metadata.content` yok, metin alanı tek. Canlı: `get_document("bedesten", "1019816300")` çıktısının JSON uzunluğu eski çıktının %40'ının altında ve `markdown` tam karar metnini içeriyor. `pytest` yeşil.

---

## Görev 2 — `search_decisions` yanıtına toplam sonuç / sayfa bilgisi ekle

**Sorun:** Hosted yargı-mcp `total: 543 · sayfa 1/55` veriyor; bizim araç sadece sonuç listesi döndürüyor. Sayfalayan ajan toplamı bilemiyor.

**Konum:** `src/emsal_mcp/sources/bedesten.py` `BedestenClient.search` (≈ satır 167–191): upstream yanıtı `data` dict'inde toplam kayıt sayısı alanı var (muhtemel adaylar: `total`, `totalCount`, `recordsTotal` — **önce gerçek yanıtı logla ve alan adını doğrula, tahmin etme**). `src/emsal_mcp/server.py` `search_decisions` (≈ satır 419+).

**Yapılacaklar:**
1. `SourceClient.search` imzasını bozmadan toplamı taşı: en pratik yol, ilk `SearchResult.metadata`'ya `search_total: int` ve `search_page: int` koymak YERİNE, `BedestenClient.search`'ün sonuna toplamı `self._last_search_total` gibi state'e yazmak KIRILGANDIR — bunu yapma. Doğru yol: `search()` dönüş tipini `list[SearchResult]`'tan `SearchResponse(results=..., total=..., page=..., page_size=...)` modeline geçirmekse tüm adaptörlere dokunur; bu görevde İZİN VERİLEN kapsamlı değişiklik budur ve şu şekilde sınırlanır:
   - `models.py`'ye `SearchPage` (results, total, page, page_size, total_pages) ekle.
   - `base.py`'de `search()` sözleşmesini koru; YENİ opsiyonel metot ekle: `async def search_page(self, ...) -> SearchPage` — varsayılan implementasyon `search()`'ü çağırıp `total=None` döndürür. Yalnız `BedestenClient` (ve mümkünse `MevzuatClient`) override eder.
2. `server.py` `search_decisions` `search_page()` kullansın; yanıt dict'ine üst düzeyde `total_results`, `page`, `total_pages` ekle (total alınamadıysa `null` + `warnings`'e not).
3. `docs/MCP_CONTRACTS.md` güncelle.

**Doğrulama:** Canlı: `+"tahliye taahhüdü" +kira` → `total_results` ≈ 543 (±, korpus büyüyor olabilir) ve `total_pages` tutarlı. Diğer kaynaklarda (`search_decisions` bedesten dışı akışlar) regresyon yok; `pytest` yeşil.

---

## Görev 3 — Yanıltıcı `metadata_only` mesajını düzelt

**Sorun:** Arama sonuçlarında `content_status: metadata_only` + "Bu kayıtta tam metin yok; ... resmi kaynaktan doğrulayın" deniyor; oysa snippet mevcut ve tam metin `get_document` ile alınabiliyor. Mesaj, LLM'i kaynağı kullanmamaya itiyor.

**Konum:** `recommended_next_step` üretimi — `src/emsal_mcp/server.py` veya `src/emsal_mcp/server_utils.py` içinde "Bu kayıtta tam metin yok" metnini grep'le bul.

**Yapılacaklar:**
1. Bedesten kaynaklı arama sonuçlarında mesajı şu anlama gelecek şekilde değiştir: "Arama sonucu özet niteliğindedir; tam metin için `get_document(source='bedesten', document_id='<id>')` çağırın." (`content_status` alanı `metadata_only` kalabilir — yalan söyleme, sadece yönlendirmeyi düzelt.)
2. Gerçekten tam metni OLMAYAN kaynaklar (PDF-link-only vb.) için eski uyarı kalsın; ayrımı `content_status`/`full_text_available` üzerinden yap.

**Doğrulama:** Canlı aramada yeni mesaj görünüyor; PDF-only kaynak sonuçlarında eski uyarı duruyor. `pytest` yeşil.

---

## Görev 4 — Uzun belgelerde sayfalama (40k karakter)

**Sorun:** Çok uzun kararlar tek parça dönüyor; hosted yargı-mcp 40.000 karakter üstünü `page_number` ile bölüyor.

**Konum:** `server.py` `get_document` (Görev 1'deki `to_tool_payload` üzerine kurulur).

**Yapılacaklar:**
1. `get_document` aracına `page_number: int = 1` parametresi ekle. `markdown` 40.000 karakteri aşarsa paragraf sınırından böl (paragraf ortasından kesme); yanıta `current_page`, `total_pages`, `total_chars` ekle. Aşmıyorsa alanlar `1/1`.
2. Bölme fonksiyonunu `server_utils.py`'ye saf fonksiyon olarak yaz (test edilebilirlik).

**Doğrulama:** Birim testi: 100k karakterlik yapay metin → 3 sayfa, birleşimi orijinale eşit, hiçbir sayfa paragraf ortasından başlamıyor. `pytest` yeşil.

---

## Görev 5 — AİHM/HUDOC kaynağı ekle

**Sorun:** AİHM içtihadı hiç yok. HUDOC'un resmi JSON API'si var — scraping gerekmez.

**Konum:** YENİ dosya `src/emsal_mcp/sources/aihm.py`; kayıt `src/emsal_mcp/sources/registry.py`; araç yüzeyi `server.py` `search_decisions`'a `source="aihm"` olarak.

**API bilgisi (doğrula, sonra kullan):**
- Arama: `GET https://hudoc.echr.coe.int/app/query/results?query=<lucene>&select=itemid,docname,appno,conclusion,importance,kpdate,languageisocode,doctype&sort=&start=0&length=20`
- Sorgu dili: `contentsitename:ECHR AND (respondent:"TUR") AND ...` biçiminde alanlı ifadeler. İlk adım olarak tarayıcı/`httpx` ile bir örnek istek at, gerçek parametre adlarını gözlemle; **şema tahminiyle kod yazma** (durma koşulu 4 geçerli).
- Belge metni: itemid ile `https://hudoc.echr.coe.int/app/conversion/docx/html/body?library=ECHR&id=<itemid>` HTML döndürür.
1. `AihmClient(SourceClient)` yaz: `search(query, limit, **filters)` — desteklenecek filtreler: `ulke` (varsayılan `TUR`), `madde`, `ihlal`, `basvuru_no`, `dil`, `tarih_baslangic/bitis`. `get_document(itemid)` → HTML'i mevcut html→markdown yoluyla çevir (`base.py`/`document.py`'deki mevcut yardımcıları kullan; yeni bağımlılık ekleme — mevcut `beautifulsoup4` yeterli).
2. `registry()`'ye `"aihm"` ekle; capability matrix'te `EXPERIMENTAL` işaretle.
3. `server.py` `search_decisions` docstring'ine `source="aihm"` kullanımını ve filtre adlarını ekle.

**Doğrulama:** Canlı: `search_decisions(source="aihm", query="Kavala")` en az 1 sonuç döndürüyor ve `get_document("aihm", <itemid>)` markdown karar metni veriyor. Offline birim testi: kaydedilmiş örnek JSON yanıtı fixture'dan parse ediliyor. `pytest` yeşil.

---

## Görev 6 — Tek mevzuat içinde boolean arama (`scope='article'` güçlendirme)

**Sorun:** Hosted `mevzuat_icinde_ara`: tek kanun içinde `AND/OR/NOT/"phrase"/()`  operatörlü, madde-düzeyi snippet'li lokal arama. Bizde `search_legislation(scope='article')` var ama operatör desteği ve snippet zayıf.

**Konum:** `src/emsal_mcp/legislation.py` (madde ağacı zaten çekiliyor: `get_legislation part='article_tree'`); `src/emsal_mcp/snippet.py`.

**Yapılacaklar:**
1. `legislation.py`'ye saf bir boolean değerlendirici ekle: BÜYÜK harf `AND`/`OR`/`NOT`, `"tam ifade"`, `()` gruplama; bitişik kelimeler örtük AND; Türkçe büyük/küçük harf duyarsız (İ/i, I/ı doğru katlansın — `casefold` yetmez, mevcut kodda Türkçe fold yardımcısı varsa onu kullan, yoksa `str.translate` tablosu yaz); kelime KÖKten ileri eşleşme (`tazminat` → `tazminatı` eşleşir).
2. `scope='article'` akışı: madde ağacını çek → her maddeyi değerlendir → eşleşme sayısına göre sırala → her sonuçta `madde_no`, `match_count`, `**bold**` işaretli snippet.
3. Araç docstring'ine operatör sözdizimini yaz.

**Doğrulama:** Birim testleri (ağ gerektirmez, fixture madde ağacıyla): `"açık rıza" AND sağlık`, `(ihracat OR ithalat) AND NOT istisna`, örtük AND, Türkçe İ/ı katlama, kök eşleşme. Canlı: KVKK (6698, mevzuat_id 104383) içinde `"açık rıza" AND sağlık` → m.6 ilk sayfada. `pytest` yeşil.

---

## Görev 7 — AYM adaptörünü olgunlaştır

**Sorun:** `AymClient` iskeleti var (`sources/simple_public.py`, registry'de `EXPERIMENTAL`) ama norm denetimi / bireysel başvuru ayrımı ve güvenilir arama yok.

**Konum:** `src/emsal_mcp/sources/simple_public.py` `AymClient`.

**Yapılacaklar:**
1. Önce mevcut `AymClient.search`'ü canlı çalıştır, ne döndürdüğünü rapora yaz. Çalışan kısmı koru.
2. İki bankayı destekle: norm denetimi (`normkararlarbilgibankasi.anayasa.gov.tr`) ve bireysel başvuru (`kararlarbilgibankasi.anayasa.gov.tr`). Filtre: `decision_type: "norm_denetimi"|"bireysel_basvuru"`, `esas_no`/`karar_no` (norm), `basvuru_no` (bireysel), tarih aralığı.
3. Her iki sitenin arama uçları JSON/AJAX olabilir — önce ağ trafiğini gözlemleyip gerçek endpoint'i rapora yaz, sonra implement et (şema tahmini yasak).
4. `get_document`: karar sayfası HTML → markdown.

**Doğrulama:** Canlı: bireysel başvuruda ada göre 1 arama + norm denetiminde esas no ile 1 arama, ikisi de doğru kararı buluyor ve `get_document` metin döndürüyor. Offline fixture testleri. `pytest` yeşil.

---

## Görev 8 — Kurum kaynakları (kullanıcı önceliği: GİB özelge, BTK, Rekabet, Sigorta Tahkim)

**Kullanıcı 2026-07-16'da bu dört kaynağı öncelikli seçti.** Alt görevler bağımsız commit'lenir: `8a` GİB, `8b` BTK, `8c` Rekabet, `8d` Sigorta Tahkim. Uçlar Claude tarafından 2026-07-16'da canlı doğrulandı (aşağıdaki "Canlı doğrulanmış uç" notları). Bu notlardaki gövde/parametre biçimini AYNEN kullan; yine de her alt görevde ilk iş bir canlı istek atıp yanıt şemasını `PARITY_V2_RAPOR.md`'ye yazmak (şema tahmini yasak, durma koşulu 4).

Ortak gereksinimler (dördü için):
- `search_page()` override et → `total`/`total_pages` dön (Görev 2 sözleşmesi). `search()` mevcut `list[SearchResult]` sözleşmesini koru.
- Geniş `except Exception` kullanacaksan hata sınıfını `metadata["error"]`'a yaz (Görev 5b/7b'de yerleşen kural).
- Her alt görev için offline fixture testi (kaydedilmiş gerçek yanıt parçası) + tam suite yeşil.
- PDF çıkarımı gereken yerlerde mevcut `src/emsal_mcp/pdf_extractor.py` kullan; yeni bağımlılık ekleme.

### Görev 8a — GİB özelge (mevcut adaptörü olgunlaştır)

`GibClient` (`src/emsal_mcp/sources/simple_public.py`) zaten çalışıyor. Eksik: toplam sayı ve doğrulama.

**Canlı doğrulanmış uç:** `POST https://gib.gov.tr/api/gibportal/mevzuat/ozelge/list?page=0&size=10&sortFieldName=ozelgeTarih&sortType=DESC`, JSON gövde `{"status":2,"deleted":false,"ktype":99,"title":Q,"kanunNo":Q,"description":Q}`. Yanıt: `resultContainer.content[]` + **`resultContainer.totalElements`** (ör. 7736), `totalPages`, `number`, `size`. Belge id → `content[i].id` (int), tam metin `content[i].description` + başlık alanlarından kuruluyor (mevcut `get_document` doğru).

**Yapılacaklar:** `search_page()` override → `totalElements`/`totalPages`. `page` parametresi 0-tabanlı upstream'e doğru geçiyor mu doğrula (adaptör 1-tabanlı alıp -1 yapıyor). `start_date`/`end_date` filtreleri hâlâ çalışıyor mu canlı test et.

**Doğrulama:** Canlı `search_page("KDV")` → total ≈ 7736; `get_document(<id>)` özelge metni döndürüyor.

### Görev 8b — BTK kurul kararları (YENİ adaptör)

**Canlı doğrulanmış uç:** `GET https://www.btk.gov.tr/kurul-kararlari` (sunucu-render, ~540 KB, tarayıcı UA gerekli). Sayfalama: `?page=N` (1-tabanlı; `?page=2` farklı içerik döndürür — canlı teyit; `/kurul-kararlari/2` yolu 404). Sayfada ~13 karar kartı; her kartta `Karar Tarihi`, `Karar No`, `Konu`, `Yayım Tarihi` etiketli alanlar + S3 PDF linki (`https://www.btk.gov.tr/s3/web-btk-site/.../<uuid>.pdf`). Arama kutusu client-side; **server-side keyword araması YOK** → adaptör listeyi çeker, `query` verilmişse kart metni üzerinde yerel filtre uygular (Türkçe-duyarlı, mevcut yardımcıları kullan).

**Yapılacaklar:**
1. YENİ `BtkClient(SourceClient)` (`simple_public.py` içinde, GibClient komşuluğunda). `search`/`search_page`: kart listesini parse et (title=Konu, `karar_no`, `decision_date`, PDF url metadata'da), `content_status=PDF_LINK_ONLY`. `document_id` = PDF url'yi `_url_id()` ile kodla (mevcut yardımcı). `query` verilmişse kart metninde geçmeyenleri ele; `total` = o an filtrelenmiş liste boyutu (kaç sayfa çekildiyse notu warning'e).
2. `get_document`: PDF'i indir → `pdf_extractor` ile metne çevir → `HTML_MARKDOWN`/`FULL_TEXT`. İndirme/çıkarım başarısızsa `PDF_LINK_ONLY` + url.
3. `registry.py`'ye `"btk": _BtkClient()` ekle (`PARTIAL`), capability/adapter contract testlerine `"btk"` ekle.
4. `server.py` `search_decisions` docstring'ine `source="btk"` notu.

**Doğrulama:** Canlı `search("numara taşınabilirliği", source=btk)` en az 1 kart döndürüyor; `get_document(<pdf id>)` PDF metni veriyor. Sayfa yapısı değişirse (kart bulunamazsa) yapılandırılmış `UNAVAILABLE` + net mesaj (çökme yok).

### Görev 8c — Rekabet Kurumu (mevcut scraper'ı sağlamlaştır)

`RekabetClient` mevcut ve canlı çalışıyor (2026-07-16: `GET /tr/Kararlar?PdfText=<q>` → sayfada ~20 `kararId`).

**Yapılacaklar:**
1. `search_page()`: sayfadaki toplam sonuç sayısını yakala (sayfa altındaki sonuç/sayfa metninden veya `kararId` sayımından; gerçek `total` HTML'de varsa onu kullan, yoksa `total=None` + warning — uydurma). `karar_turu`/tarih filtreleri Yargı PRO'da var; HTML formu destekliyorsa ekle, desteklemiyorsa rapora "desteklenmiyor" yaz.
2. `get_document`: karar detay sayfasındaki PDF linkini indir → `pdf_extractor` ile tam metin (şu an yalnız HTML+pdf link veriyor; PDF çıkarımı ekle). PDF yoksa mevcut HTML davranışı kalsın.
3. Scraper CSS/tablo yapısına bağımlı — kırılırsa `UNAVAILABLE` (mevcut davranış korunur).

**Doğrulama:** Canlı `search("hakim durumun kötüye kullanılması", source=rekabet)` sonuç veriyor; `get_document(<kararId>)` PDF tam metni döndürüyor.

### Görev 8d — Sigorta Tahkim (canlı arama API'si YOK — korpus/dergi yaklaşımı)

**Canlı gözlem (2026-07-16):** `sigortatahkim.org.tr` yalnız minimal açılış sayfası; `hakem-kararlari`/`yayinlar` yolları 404. **Aranabilir karar veritabanı YOK.** Kararlar periyodik "Sigorta Tahkim Hakem Karar Dergisi" PDF sayıları olarak yayımlanıyor (Yargı PRO da bu yüzden dış arama/OCR kullanıyor). Bu, Görev 8'in "API'siz kaynak" durumudur — hedef canlı arama değil, dergi PDF'lerini [[emsal-corpus-state]] korpusuna alıp lokal FTS ile aramak.

**Yapılacaklar (bu alt görev keşif-ağırlıklı — önce DUR ve rapora yaz):**
1. Dergi PDF sayılarının nerede barındırıldığını bul (TSB/sigortatahkim yayın sayfası, arşiv linkleri). Bulunan gerçek URL kalıbını `PARITY_V2_RAPOR.md`'ye yaz. **Bulunamıyorsa burada DUR** (durma koşulu 4) — uydurma URL kalıbı yazma.
2. URL kalıbı netse: dergi PDF'lerini indirip `pdf_extractor` ile metne çeviren, korpusa ekleyen bir crawl adımı ([[deepseek-crawl-workflow]] modeli: durma koşulu + sayfa limiti şart). Adaptörün `search`'ü lokal korpusta arar (`search_local_corpus` altyapısı), `get_document` korpustan/PDF'ten metin verir.
3. Canlı arama API'si icat etme; adaptör capability'sinde açıkça "korpus tabanlı, canlı arama yok" belirt.

**Doğrulama:** En az 1 dergi sayısı korpusa alınıp içinden bir hakem kararı lokal aramayla bulunabiliyor. Korpus boşsa adaptör yapılandırılmış "veri yok" döndürüyor (çökme yok).

---

## Denetleyici kontrol listesi (Claude için — her görev commit'inden sonra)

- [ ] Diff yalnız görevde adı geçen dosyalara dokunuyor mu?
- [ ] `pytest` tam suite yeşil mi (sadece yeni testler değil)?
- [ ] Canlı doğrulama örneği rapora yazılmış mı; ben aynı çağrıyı MCP üzerinden tekrarlayınca aynı sonucu alıyor muyum?
- [ ] Görev 1: cache'e tam `Document` yazılmaya devam ediyor mu (budama yalnız araç çıktısında mı)?
- [ ] Görev 2: bedesten dışı kaynaklarda `search_decisions` hâlâ çalışıyor mu?
- [ ] Görev 5/7: upstream şema alanları gözlemle mi doğrulanmış, yoksa tahmin mi (rapora ham örnek kondu mu)?
- [ ] `docs/MCP_CONTRACTS.md` drift testi geçiyor mu?
