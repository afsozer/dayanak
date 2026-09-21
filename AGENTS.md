# Çalışma Kuralları (Antigravity Agent)

Bu dosya Antigravity'nin agent'ı içindir. Bu depodaki çalışmalar için geçerlidir.

## İşi kendin yap ve sonuna kadar bitir
- İşi codex/pi gibi başka bir araca **DEVRETME**. Kod değişikliklerini, komutları, build/test'i **kendin** yap.
- Görevi **tek turda sonuna kadar** tamamla. "Şimdi şunu yapacağım", "sırada şu var", "bunu yapıp sonra devam edeceğiz" deyip turu **BİTİRME** — söylediğin adımı hemen o turda çalıştır ve kesintisiz devam et.
- Komutları **arka plan (background) görevi** olarak başlatıp turu kapatma. `flutter analyze`, build, test gibi adımları **önplanda** çalıştır, çıktısını **BEKLE**, sonucu gör, sonra bir sonraki adıma geç.
- Sadece gerçekten kullanıcı kararı gerektiren (güvenlik/iş tercihi) durumlarda dur ve sor; aksi halde durmadan işi bitir.

## Not
- PowerShell'de Türkçe karakterli prompt'larda kodlama (encoding) sorunlarına dikkat et.
