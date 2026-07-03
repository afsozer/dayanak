# Yargı-MCP Parite Talimatı

**Amaç:** emsal-mcp'nin karar/mevzuat arama kalitesini hosted yargı-mcp (api.yargimcp.com) seviyesine yaklaştırmak.

**Bağlam:** İki araç da aynı arka ucu (Bedesten API, `bedesten.adalet.gov.tr`) kullanıyor. Kalite farkı veri kaynağından değil, dört şeyden geliyor: sıralama stratejisi, sorgu dialekti dokümantasyonu, snippet eksikliği ve mevzuat tarafında yanlış API tercihi. Bu talimat, tespit edilen farkları öncelik sırasıyla kapatır.

**Genel kural:** Her görev bağımsız uygulanabilir ve tek başına commit edilebilir. Görev sırası = öncelik sırası. Her görevin sonunda doğrulama adımı var; doğrulama geçmeden sonraki göreve geçme.

---

## Görev 1 — Bedesten Solr operatör dokümantasyonunu düzelt (boşluk = OR)

**Sorun:** `src/emsal_mcp/server.py` içindeki `search_decisions` docstring'i (≈ satır 451–479, "QUERY HYGIENE" ve "BEDESTEN SOLR OPERATOR COOKBOOK" bölümleri) çıplak kelimeler arası boşluğun AND anlamına geldiğini varsayan örnekler veriyor:

- `"iş kazası" tazminat → exact phrase "iş kazası" AND term "tazminat"` — **YANLIŞ**
- `boşanma tazminat* → "boşanma" AND any word starting "tazminat"` — **YANLIŞ**

Bedesten, Solr StandardQueryParser kullanıyor ve varsayılan operatör **OR**'dur. Yani `tahliye taahhüdü geçerlilik` sorgusu bu üç kelimeden HERHANGİ BİRİNİ içeren kararları döndürür. Yargı-mcp'nin araç şeması bunu açıkça belirtiyor: *"Whitespace between bare terms means OR, NOT AND — to require multiple concepts mark EACH with `+`"*.

**Yapılacaklar:**

1. Docstring'deki cookbook'u düzelt. Ana mesaj şu olmalı:
   - ⚠️ Çıplak terimler arası boşluk **OR** demektir. Birden fazla kavramı zorunlu kılmak için HER terime `+` öneki koy ya da büyük harf `AND` kullan.
   - Doğru örnekler: `+"tahliye taahhüdü" +geçerlilik`, `+işçi +"kıdem tazminatı"`, `kıdem AND ihbar AND tazminat`.
   - Yanlış örnek olarak göster: `tahliye taahhüdü geçerlilik` (OR'a dönüşür, alakasız sonuç getirir).
2. Aynı yanlış varsayım başka yerde varsa düzelt: `legal_research_guide` aracının içeriği, `docs/COOKBOOK.md`, `docs/MCP_CONTRACTS.md` içinde `boşanma tazminat*` / "implicit AND" benzeri ifadeleri ara ve düzelt.
3. **Otomatik güvenlik ağı (opsiyonel ama önerilir):** `BedestenClient.search` içinde (`src/emsal_mcp/sources/bedesten.py`) sorgu ön-işleme ekle: sorgu hiç operatör içermiyorsa (`+`, `-`, `"`, `AND`, `OR`, `NOT`, `(` yoksa) ve birden fazla kelime varsa, her kelimeye otomatik `+` öneki ekle. Bu davranışı sonuç metadata'sında `query_rewritten: true` olarak raporla ki şeffaf kalsın. Docstring'e de yaz.

**Doğrulama:** `pytest` yeşil; `grep -ri "implicit AND\|boşanma tazminat\*" src/ docs/` yanlış örnek döndürmüyor. Otomatik `+` katmanı eklendiyse birim testi yaz: `"tahliye taahhüdü geçerlilik"` → `"+tahliye +taahhüdü +geçerlilik"`, ama `'+"tahliye taahhüdü" +geçerlilik'` değişmeden geçer.

---

## Görev 2 — Relevance (alaka) sıralaması ekle, varsayılan yap

**Sorun:** `src/emsal_mcp/sources/bedesten.py` (≈ satır 63) `sortFields: ["KARAR_TARIHI"]` değerini sabitliyor → her arama "en alakalı" değil "en yeni" kararları döndürüyor. Hosted yargı-mcp, `phrase` varsa varsayılan olarak relevance sıralaması kullanıyor ve `sort_by: relevance|date` parametresi sunuyor. `src/emsal_mcp/sources/mevzuat.py` (≈ satır 26) aynı sorunu `RESMI_GAZETE_TARIHI` ile yaşıyor.

**Yapılacaklar:**

1. **Önce API davranışını doğrula** (Bedesten Solr'u ara sıra arıza veriyor — `metadata.FMTY == "ERROR"` dönerse sonra tekrar dene). Aynı sorguyu iki payload ile gönder ve sonuç sıralamasının değiştiğini teyit et:
   - a) `sortFields: ["KARAR_TARIHI"], sortDirection: "desc"` (mevcut davranış)
   - b) `sortFields` ve `sortDirection` alanları **hiç gönderilmeden** (Solr varsayılanı = skor/alaka sıralaması)
   - Test sorgusu önerisi: `+"tahliye taahhüdü" +geçerlilik`, `itemTypeList: ["YARGITAYKARARI"]`.
   - (b) çalışmazsa `sortFields: []` ve `sortFields: ["SCORE"]` varyantlarını dene.
2. `BedestenClient.search`'e `sort_by` filtresi ekle: `"relevance"` → sortFields gönderme; `"date"` → mevcut davranış. **Varsayılan: sorguda `phrase` doluysa `relevance`, boşsa (sadece esas/karar no veya tarih filtresi) `date`.**
3. Aynı mantığı `MevzuatClient.search`'e uygula.
4. `search_decisions` ve `search_legislation` MCP araç imzalarına `sort_by: "relevance" | "date"` parametresini ekle, docstring'de varsayılanı açıkla. `docs/MCP_CONTRACTS.md`'yi güncelle (drift testi var: `tests/` altındaki contract testinin geçtiğinden emin ol).

**Doğrulama:** Canlı test — `+"tahliye taahhüdü" +geçerlilik` sorgusu relevance modda, tarih modundan farklı ve konuyla daha ilgili ilk-5 döndürüyor. Contract/drift testleri yeşil.

---

## Görev 3 — Upstream hatasını sessizce "0 sonuç"a çevirme

**Sorun:** Bedesten arıza durumunda `{"data": null, "metadata": {"FMTY": "ERROR", "FMC": "ADALET_RUNTIME_EXCEPTION", ...}}` döndürüyor. `src/emsal_mcp/sources/bedesten.py` (≈ satır 91–96) `data` dict değilse sessizce `[]` döndürüyor. LLM bunu "emsal bulunamadı" diye yorumluyor — halüsinasyona veya yanlış "içtihat yok" sonucuna yol açıyor. (Bu davranış canlı gözlemlendi: 2026-07-03'te Solr arızası sırasında `ftsemsal.uyap.gov.tr/solr` IOException'ı boş sonuç olarak yutuldu.)

**Yapılacaklar:**

1. `src/emsal_mcp/sources/base.py` içine ortak bir kontrol ekle: yanıtın `metadata.FMTY` alanı `"ERROR"` ise yapılandırılmış hata üret (mevcut hata modeliniz neyse onu kullan — invariant #3: exception değil, yapılandırılmış sonuç). Hata mesajına `FMC` ve `FMTE` alanlarını koy ki üst katman "kaynak geçici olarak arızalı, sonuç yokluğu anlamına gelmez" diyebilsin.
2. `BedestenClient.search`, `BedestenClient.get_document`, `MevzuatClient.search`, `MevzuatClient.get_document` bu kontrolü kullanmalı.
3. Bir kez otomatik retry (kısa bekleme ile) makul; ikinci deneme de hata verirse yapılandırılmış hata döndür.
4. MCP araç çıktısında bu durum `ok: false` + açıklayıcı Türkçe mesaj olarak görünmeli: örn. *"Bedesten kaynağı geçici hata döndürdü (ADALET_RUNTIME_EXCEPTION); bu 'sonuç yok' anlamına gelmez, sorguyu daha sonra tekrarlayın."*

**Doğrulama:** Birim testi — mock yanıt `{"data": null, "metadata": {"FMTY": "ERROR", ...}}` verildiğinde `search` boş liste DEĞİL yapılandırılmış hata döndürüyor. `data: null` ama `FMTY != "ERROR"` (örn. son sayfa ötesi) durumunda eski davranış (boş liste) korunuyor.

---

## Görev 4 — Arama sonuçlarına snippet ekle

**Sorun:** `search_decisions` sonuçları `METADATA_ONLY` — başlık sadece "mahkeme | daire | tarih | esas | karar". LLM hangi kararın alakalı olduğunu göremeden ya körlemesine seçiyor ya da her kararı tek tek `get_document` ile çekiyor. Yargı-mcp ilk sonuçlar için karar metninden eşleşen pasajı (`snippet`) döndürüyor; cache'lenmiş sonuçlarda snippet bedava.

**Yapılacaklar:**

1. `search_decisions`'a `include_snippets: bool = False` parametresi ekle.
2. `include_snippets: true` ise: ilk N (öneri: 5) sonucun tam metnini **eşzamanlı** çek (`concurrency.py`'deki mevcut altyapıyı kullan), sorgu terimlerinin geçtiği ilk pasajı (~300–400 karakter, terim ortalanmış) `snippet` alanı olarak sonuca ekle. PDF-only belgeleri atla; atlananları `snippet_note` ile raporla.
3. **Yerel korpus entegrasyonu (bedava snippet):** sonuçtaki `document_id` yerel korpusta (~88k karar) zaten varsa, ağa çıkmadan korpustan snippet üret — `include_snippets: false` olsa bile bu bedava snippet'leri ekle.
4. Çekilen tam metinler mevcut cache'e yazılsın ki peşinden gelen `get_document` çağrısı ağa çıkmasın.
5. `SearchResult` modeline (`src/emsal_mcp/models.py`) `snippet: str | None` alanı ekle; `docs/MCP_CONTRACTS.md` ve JSON contract'ları güncelle.

**Doğrulama:** Canlı test — `include_snippets: true` ile arama, ilk 5 sonuçta sorgu terimlerini içeren snippet döndürüyor. Korpusta var olan bir kararın snippet'i ağ çağrısı olmadan geliyor (test: ağ mock'lanmışken korpus-hit snippet'i dolu).

---

## Görev 5 — Mevzuat aramasını mevzuat.gov.tr yaklaşımına taşı

**Sorun:** `src/emsal_mcp/sources/mevzuat.py` Bedesten'in mevzuat endpoint'ini yalnızca gövde-metni araması + Resmî Gazete tarihi sıralamasıyla kullanıyor. Sonuç: "kişisel verilerin korunması" araması en yeni yönetmelik değişikliklerini üste koyuyor; KVKK'nın kendisi listeye girmeyebiliyor. Yargı-mcp `mevzuat_ara`'da şunları sunuyor:

- `mevzuat_adi` — **yalnızca başlıkta** arama (çok-kelime AND'lenir, operatör yok)
- `mevzuat_no` — resmi numara ile doğrudan bulma (6698 → KVKK, 5237 → TCK)
- `mevzuat_tur_list` — 12 tür filtresi (KANUN, KHK, TUZUK, YONETMELIK, CB_KARARNAME, CB_YONETMELIK, CB_KARAR, CB_GENELGE, KKY, UY, TEBLIGLER, MULGA)
- Varsayılan relevance sıralaması; `kayit_tarihi` / `resmi_gazete_tarihi` opsiyonel

**Yapılacaklar:**

1. `MevzuatClient.search`'e `mevzuat_adi` (başlık araması), `mevzuat_no` ve `mevzuat_tur_list` (çoklu tür) filtrelerini ekle. Önce Bedesten mevzuat endpoint'inin bu alanları destekleyip desteklemediğini payload denemeleriyle keşfet (`mevzuatAdi`, `mevzuatNo`, `mevzuatTurList` alan adlarını dene). Desteklemiyorsa mevzuat.gov.tr'nin kendi arama API'sini ikinci adaptör olarak ekle (yargı-mcp'nin açık kaynak reposundaki `mevzuat_mcp_module` — github.com/saidsurucu/yargi-mcp — endpoint ve payload formatı için referans alınabilir).
2. Sıralama: Görev 2'deki `sort_by` mantığı buraya da (relevance varsayılan).
3. `search_legislation` MCP aracının imzasını ve docstring'ini güncelle: LLM'e "kanun adı biliniyorsa `mevzuat_adi`, numara biliniyorsa `mevzuat_no` kullan; gövde metni aramasını (`query`) yalnızca kavram ararken kullan" talimatı ver. Numara ASLA tahmin edilmesin; emin değilsen önce `mevzuat_adi` ile ara.
4. `query_understanding.py`'deki `_LAW_ABBREV` tablosu zaten kısaltma → kanun no eşlemesi içeriyor; `search_legislation` bu tabloyu kullanarak "TCK", "HMK" gibi sorguları otomatik `mevzuat_no` aramasına yönlendirsin.

**Doğrulama:** Canlı test — `mevzuat_adi: "kişisel veri"` araması KVKK'yı (6698) ilk sayfada döndürüyor; `mevzuat_no: "6698"` doğrudan KVKK'yı buluyor; "TCK 157" sorgusu 5237'ye yönleniyor.

---

## Görev 6 — Araç yüzeyi ergonomisi: birleşik içtihat araması + daire enum'ları

**Sorun:** `search_decisions(source=...)` LLM'i önce kaynak seçmeye zorluyor. Yargı-mcp'nin `ictihat_ara`'sı tek çağrıda çoklu mahkeme tarıyor: `court_types` listesi (varsayılan `["YARGITAYKARARI", "DANISTAYKARAR"]`; ayrıca `YERELHUKUK`, `ISTINAFHUKUK`, `KYB`) ve `birimAdi` için kısa enum kodları (`H1`–`H23`, `C1`–`C23`, `HGK`, `CGK`, `D1`–`D17`, `IDDK`, `VDDK` …).

**Yapılacaklar:**

1. `search_decisions`'da `source` parametresini opsiyonel yap; verilmezse Bedesten üzerinden `court_types` listesiyle ara ve varsayılanı `["YARGITAYKARARI", "DANISTAYKARAR"]` yap. (Bedesten `itemTypeList` zaten çoklu tür destekliyor — `bedesten.py` bunu şimdiden alıyor.)
2. `birimAdi` için `src/emsal_mcp/birim_enum.py`'deki mevcut eşlemeyi araç şemasına enum olarak yansıt; docstring'e kod tablosunu koy (H12 = Yargıtay 12. Hukuk Dairesi vb.).
3. Yargı-mcp'nin koruma kuralını ekle: **en az bir kriter zorunlu** — `query`, `esas_no`/`karar_no`, `birimAdi` veya tarih sınırından biri yoksa arama reddedilir (yalnız `court_types` yetmez). Bu, boş/anlamsız taramaları engeller.
4. `docs/MCP_CONTRACTS.md` + drift testini güncelle.

**Doğrulama:** `search_decisions(query="+\"kıdem tazminatı\" +zamanaşımı")` kaynak belirtmeden Yargıtay+Danıştay sonuçlarını karışık döndürüyor; kritersiz çağrı yapılandırılmış hata veriyor; contract testleri yeşil.

---

## Görev 7 — Semantik aramayı keşif aracı olarak konumlandır + eşleşen alıntılar

**Sorun:** Mevcut docstring'ler semantik/yerel aramayı "yasak, sadece re-rank" diye eziyor. Yargı-mcp ise `semantik_ictihat_ara`'yı "kelimesi bilinmeyen hukuki KAVRAM için emsal keşfi" aracı olarak sunuyor ve her sonuçla eşleşen alıntı pasajları (`related_quotes`) döndürüyor. Elinizde ~88k kararlık yerel korpus var — bu, aynı deneyimi yerelde vermek için yeterli.

**Yapılacaklar:**

1. `search_local_corpus` sonuçlarına `related_quotes` ekle: eşleşen chunk'lardan alaka sırasıyla pasajlar (chunk başına ~200–300 karakter). Aynı kararın birden çok chunk'ı tek sonuçta birleşsin (dedup), tüm eşleşen pasajlar o sonucun altında listelensin.
2. Docstring'i yeniden yaz: *"Hukuki bir KAVRAM için emsal ararken ve tam kelime bilinmiyorken kullan; doğal dil Türkçe sorgu yaz (operatör yok). Döndürdüğü her kararın güncel/tam metnini `get_document` ile doğrula. Korpus tarihi eskidir — güncel içtihat için `search_decisions` şart."* Yasaklayıcı dil kalksın; iki aracın rolleri tamamlayıcı olarak anlatılsın (keşif = semantik, güncellik + atıf doğrulama = canlı arama).
3. Sorgu kılavuzunu yargı-mcp'den uyarla: ✅ iyi örnek `kira sözleşmesinde tahliye taahhüdünün geçerlilik şartları` (kavramsal, odaklı cümle), ❌ kötü örnek tek kelime (`tahliye`) veya kullanıcının tüm sorusunun yapıştırılması.
4. Korpusun kapsadığı tarih aralığını sonuç metadata'sında bildir (örn. `corpus_coverage: "... - 2025-XX"`) ki LLM eksik dönemi canlı aramayla kapatacağını bilsin.

**Doğrulama:** `search_local_corpus("işçinin haklı nedenle feshinde kıdem tazminatı hakkı")` dedup'lu sonuçlar + her sonuçta en az bir `related_quotes` pasajı döndürüyor.

---

## Görev sonrası: uçtan uca kalite testi

Tüm görevler bitince aynı 5 gerçek soruyu iki araçta da çalıştırıp ilk-5 sonucu karşılaştır (örnek sorular: tahliye taahhüdünün geçerliliği, kıdem tazminatında zamanaşımı, destekten yoksun kalma tazminatı hesabı, idari işlemin iptalinde yürütmeyi durdurma şartları, KVKK veri ihlali bildirimi süresi). Hedef: emsal-mcp'nin ilk-5 alaka isabeti yargı-mcp ile başa baş. Fark kalan sorular için hangi görevden kaynaklandığını not et ve ROADMAP'e madde aç.

---

## Kaynak notları

- Hosted yargı-mcp davranışları bu talimatta araç şemalarından (2026-07-03'te bağlı sürüm) alınmıştır; şemalar `ictihat_ara`, `mevzuat_ara`, `semantik_ictihat_ara`, `legal_research_guide` araçlarının parametre açıklamalarında dialekt ve sıralama davranışını açıkça belgeliyor.
- Açık kaynak referans: github.com/saidsurucu/yargi-mcp — dikkat: repodaki Bedesten istemcisi de `sortFields: ["KARAR_TARIHI"]` varsayılanını kullanıyor; relevance sıralaması hosted sürüme sonradan eklenmiş bir iyileştirmedir. Yani Görev 2 için repo değil, bu talimattaki API-doğrulama adımı esas alınmalı.
- Bedesten Solr arıza imzası: `{"data": null, "metadata": {"FMTY": "ERROR", "FMC": "ADALET_RUNTIME_EXCEPTION"}}` (Görev 3'ün test fikstürü olarak kullanılabilir).
