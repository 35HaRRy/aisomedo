# Issue #29 — Sonraki inceleme ve düzeltme notları

- Tarih: 2026-10-03
- Kaynak dal: `feat/issue-29-media`
- İncelenen uygulama: `1fc600d..31fbd38`
- Önemli inceleme bulgularının düzeltildiği commit: `f65605e`

## Amaç ve kapsam

Bu belge, teslim özetindeki **11 kararı ve ertelenen 1 küçük bulguyu** aynı
numaralandırmayla sonraki çalışmaya taşır. İnceleme hazırlığıdır; onaylanmış yeni
uygulama planı veya bu konuların düzeltildiği iddiası değildir.

Kararların hepsi hata değildir. Özellikle kimlik doğrulamalı indirme, farklı
yerel test portu ve mevcut sorunları ayrı raporlama bilinçli tercihlerdir.
İnceleme sonunda karar korunabilir, belgeler iyileştirilebilir veya kanıtlanmış
sorun için düzeltme yapılabilir. Güvenlik sınırları sırf uyumluluk için gevşetilmez.

Mevcut kanıt: [issue #29 doğrulama kaydı](issue-29-web-media-management.md).

Bağlayıcı tasarım: [onaylı tasarım](../superpowers/specs/2026-10-02-web-media-management-timeline-design.md).

Son uygulama doğrulaması: core 646 geçti / 4 ortam kaynaklı atlama; backend 155,
worker 140, web 233, masaüstü/dokunmatik tarayıcı 4 geçti. Web build/typecheck
geçti. Python statik kontrol ve bağımlılık audit bulguları tamamen temiz değil.
Bu notlar yazılırken ürün kodu değiştirilmedi veya yeni doğrulama çalıştırılmadı.

## Takip listesi

| No | Başlık | Tür | Durum / önerilen sıra |
| --- | --- | --- | --- |
| 1 | Aynı dakikada benzersiz paket klasörü | Karar / kullanım riski | Açık; kimlik ve tarih gösterimi incelemesi |
| 2 | Kimlik doğrulamalı ham dosya indirme | Onaylı güvenlik kararı | Açık; tüketici uyumluluğu incelemesi |
| 3 | Yerel Playwright portu | Test ortamı kararı | Açık; ortam sertleştirme |
| 4 | Mevcut Python lint/typecheck hataları | Doğrulanmış teknik borç | Açık; CI temizliği öncelikli |
| 5 | Bağımlılık audit ve başlangıç bulguları | Risk değerlendirme eksiği | Açık; özellikle high bulguyu değerlendir |
| 6 | Manifest/render eşzamanlılığı ve başarısız digest | Eski davranış / yeniden üretim gerekli | Açık; veri tutarlılığı incelemesi öncelikli |
| 7 | Windows symlink yürütme kanıtı | Platform güvenlik testi eksiği | Açık; Linux ve yetkili Windows doğrulaması |
| 8 | Ondalık klavye ve büyük arşiv performansı | Cihaz/yük testi eksiği | Açık; iki bağımsız alt inceleme |
| 9 | Eski kare-altı trim uyumluluğu | Uyumluluk belirsizliği | Açık; eski manifest örnekleriyle incele |
| 10 | Gerçek tarayıcı–backend uçtan uca doğrulama | Entegrasyon testi eksiği | Açık; dağıtım öncesi öncelikli |
| 11 | Yoğun yükte test zamanlaması | Doğrulama kararlılığı riski | Açık; CI koşullarında tekrar üret |
| 12 | Timeline sınır yuvarlaması | Doğrulanmış küçük hata | Açık; dar kapsamlı düzeltme adayı |

Sıra önerileri yeni güvenlik/audit değerlendirmesinde değişebilir. Her kayıt
sonunda yapılan işlem, test kanıtı ve ilgili commit/issue bağlantısı eklenmeli.

## 1. Aynı dakikada benzersiz paket klasörü

**Karar ve gerekçe:** Aynı dakika içinde tamamlanan paketin yerine oluşturulan
paket eskisiyle aynı klasör kimliğini kullanıyordu. Bu durumda
`expected_folder_name`, eski paket için gönderilen isteği ayırt edemiyordu.
`_create_active_package()` tamamlanmış paket adlarını dikkate alıp sonraki
kullanılmamış dakika biçimli adı seçiyor; `created_at` gerçek zamanı koruyor.

**Risk:** Hızlı rollover işlemlerinde klasör adı gerçek oluşturulma zamanından
ileri görünebilir. Klasör adını tarih olarak yorumlayan ekran, dış araç veya
operatör yanlış sıralama/yorum yapabilir. Bu, kimlik korumasını kaldırmak için
gerekçe değildir.

**İlgili yerler:** `dojo-core/src/dojo/publishing.py::_create_active_package`,
`_require_editor_package`; `dojo-core/tests/test_package_editor.py`;
`backend/tests/test_package_editor_api.py`; `web/src/components/PackageSummary.tsx`.

**Sonraki inceleme:**
- [ ] Sabit saatle aynı dakikada birkaç rollover ve tarih/gün sınırını dene.
- [ ] Ekranların sıralama ve tarih gösteriminde `created_at` mı, klasör adı mı kullandığını belirle.
- [ ] Mevcut tamamlanmış klasörlerle çakışma ve yeniden başlatma davranışını kontrol et.
- [ ] Gerekirse klasör kimliği ile kullanıcıya gösterilen zamanı açıkça ayır;
  yeni kimlik formatı gerekiyorsa eski manifest/istemci uyumluluğunu ayrıca tasarla.

**Kabul:** Kimlikler tekrar kullanılmaz; eski mutation/preview istekleri yeni
pakete uygulanmaz; gerçek oluşturulma zamanı doğru gösterilir; originals korunur.

## 2. Kimlik doğrulamalı ham dosya indirme

**Karar ve gerekçe:** Önceden public signed raw-media indirmesi bekleyen test,
onaylı tasarıma uygun paired same-origin indirmesi bekleyecek şekilde değiştirildi.
`/pub/{token}` yalnızca onaylanmış render için kalır.

**Risk:** Eski istemci veya dış indirme aracı paired kimliğini taşımıyorsa indirme
başarısız olur. Public raw-media URL'lerini geri getirmek bu riskin çözümü değildir.

**İlgili yerler:** `backend/src/backend/routes/packages.py`;
`backend/src/backend/deps.py`; `backend/tests/test_api.py`;
`backend/tests/test_package_editor_api.py`; `web/src/packages/CompletedPackages.tsx`;
`android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`.

**Sonraki inceleme:**
- [ ] Web, Android ve bilinen dış tüketicilerin download akışlarını envanterle.
- [ ] Gerçek paired tarayıcı ve cihazla original/processed/render indirmelerini dene.
- [ ] Eşleştirme iptali, eksik kimlik, Range, Unicode ad ve büyük dosya senaryolarını dene.
- [ ] Eksik tüketici varsa güvenli taşıma/uyumluluk dokümantasyonu veya istemci düzeltmesi yap.

**Kabul:** Yetkili tüketiciler indirir; yetkisiz/revoked tüketiciler reddedilir;
ham medya public olmaz; dosya adı/bytes korunur; browser tüm dosyayı blob'a almaz.

## 3. Yerel Playwright portu ve sunucu kimliği

**Karar ve gerekçe:** Yerel 3000 portunda başka proje çalışıyordu. O projeyi
durdurmadan `PLAYWRIGHT_PORT=3100` kullanıldı; CI varsayılanı 3000 kaldı.
İlk başarısız koşu bizim ürünümüzü değil başka projeyi açtı; ürün regresyonu sayılmadı.

**Risk:** Override unutulursa veya `reuseExistingServer` yanlış sunucuyu kabul
ederse testler yanlış uygulamayı hedefleyebilir. Port seçimi tek başına sunucu
kimliğini kanıtlamaz.

**İlgili yerler:** `web/playwright.config.ts`; `web/e2e/package-management.spec.ts`;
`README.md`; `.github/workflows/ci.yml`.

**Sonraki inceleme:**
- [ ] Boş port, aynı uygulama açıkken reuse ve başka uygulama açıkken çakışma durumlarını dene.
- [ ] Test başlangıcında uygulama kimliğini açıkça doğrulamayı değerlendir.
- [ ] PowerShell ve Linux CI port kullanımını belge ve gerçek komutlarla karşılaştır.

**Kabul:** Yanlış sunucu erken ve açık hata verir; başka projeyi öldürmez;
varsayılan ve override aynı uygulama/test sonuçlarını üretir.

## 4. Mevcut Python lint/typecheck hataları

**Karar ve kanıt:** Feature dışı başlangıç hataları ayrı bırakıldı. `1fc600d`
üzerinden alınan kaynakta da aynı sorunlar görüldü: core 23 E501, backend 4 E501;
27 rapor / 26 benzersiz kaynak satırı. Core mypy, `_notify_recovery()` metadata
sözlüğündeki `recovered: list[str]` ile `str` değerleri arasındaki çıkarımda hata veriyor.

**Risk:** Testler geçse de repository-wide Python lint/type CI kırmızı kalır.
Bu borç yeni feature hatalarıyla karıştırılmamalı, ancak süresiz kabul de edilmemeli.

**İlgili yerler:** `pyproject.toml`; `.github/workflows/ci.yml`;
`dojo-core/src/dojo/publishing.py::_notify_recovery`; ruff çıktısının gösterdiği
core/backend dosyaları. Satır numaraları commitlere göre değişir.

**Sonraki inceleme:**
- [ ] Güncel tüm ruff/mypy çıktısını tekrar kaydet; mevcut sayıları güncel sonuç diye varsayma.
- [ ] E501 düzeltmelerini davranış değiştirmeyen ayrı cleanup olarak yap.
- [ ] Notification metadata sözleşmesini ve alıcılarını okuyup doğru tipi belirle;
  yalnızca type ignore/cast ekleyerek problemi gizleme.
- [ ] Metadata tipi/serileştirme değişiyorsa notifier/Firebase tüketici testlerini çalıştır.

**Kabul:** Core/backend/worker statik CI komutları geçer; recovery metadata ve
bildirim içeriği doğru kalır; runtime davranışı veya API sözleşmesi istemeden değişmez.

## 5. Bağımlılık audit ve başlangıç bulgularının risk değerlendirmesi

**Karar ve kanıt:** Kurulum 4 audit bulgusu raporladı: 3 moderate, 1 high.
Kapsam dışı zorunlu dependency upgrade uygulanmadı. Advisory kimlikleri ve
ulaşılabilir exploit yolları bu çalışmada tek tek doğrulanmadı.

**Risk:** Başlangıçta mevcut olması güvenli olduğu anlamına gelmez. High bulgunun
hangi paketi etkilediği, runtime/dev ayrımı ve dağıtım erişilebilirliği araştırılmalı.
4. madde statik CI onarımıdır; bu madde dependency/security değerlendirmesidir.

**İlgili yerler:** `web/package.json`; `web/package-lock.json`;
`web/vite.config.ts`; `.github/workflows/ci.yml`; deployment dev/prod ayrımı.

**Sonraki inceleme:**
- [ ] `web` dizininde güncel `npm audit --json` çıktısını al; önceki sayıya güvenme.
- [ ] Advisory, etkilenen sürüm, transitif yol, düzeltilmiş sürüm ve erişilebilirliği kaydet.
- [ ] Güvenlik önceliğini high bulgudan başlayarak gerçek kullanım üzerinden belirle.
- [ ] Hedefli uyumlu upgrade seç; `npm audit fix --force` ile kör major upgrade yapma.

**Kabul:** Her advisory giderilmiş veya gerekçeli risk kararı/son tarih ile takipte;
lockfile tekrarlanabilir; install, unit, typecheck, build ve browser testleri geçer.

## 6. Manifest/render eşzamanlılığı ve başarısız digest bastırması

**Karar:** Reviewer'ın eski koordinasyon/recovery mekanizmaları olarak ayırdığı
manifest/render yarışları ve girdiler geri alınınca aynı failed digest'in tekrar
bastırılması bu feature'da değiştirilmedi. Bu belge bunları yeni kanıtlanmış
regresyon olarak sınıflandırmıyor; kontrollü yeniden üretim gerekiyor.

**Risk:** Render sürerken manifest değişirse eski çıktı yeni durumla uyuşmayabilir
veya manifest güncellemesi kaybolabilir. Geçici render hatasından sonra önceki
girdilere dönüş, kullanıcının beklediği yeniden denemeyi üretmeyebilir.

**İlgili yerler:** `dojo-core/src/dojo/publishing.py::_load_manifest`,
`_write_manifest`, `_render_job`, `_render_digest`, `_render_failed_digest`,
`_record_render_failure`, `_enqueue_render`, `render_preview`;
`dojo-core/tests/test_render.py`; `dojo-core/tests/test_review.py`.

**Sonraki inceleme:**
- [ ] Renderer'ı kontrollü bariyerle beklet; ikinci aktörle seçim/sıra değiştir;
  sonra renderer'ı serbest bırak. Gerçek manifest, artifact ve digest sonucunu karşılaştır.
- [ ] Render digest D1 başarısızlığı → D2 değişikliği → D1'e dönüş → normal/explicit retry akışını dene.
- [ ] Uygun atomik yazma/commit doğrulaması/serileştirme sınırını yeniden üretime göre seç;
  yeni genel revision protokolünü varsayılan çözüm olarak ekleme.

**Kabul:** Dosya, manifest ve inceleme digest'i aynı girdiyi temsil eder;
concurrent edit kaybolmaz; stale render onay/yayın için kullanılmaz; retry politikası
belgeli ve kontrollüdür. Originals/completed paketler değişmez.

**Karıştırılmaması gerekenler:** Yeni queued-render validation kilitlenmesi,
own-write draft conflict, yanlış bölüm kaldırma ve uncertain-save discard açıkları
`f65605e` ile RED→GREEN düzeltildi. Bu kaydın kapsamı o dört bulguyu tekrar açmak değil.

## 7. Windows symlink yürütme kanıtı

**Karar ve kanıt:** Yerel Windows ortamında symlink privilege yok; ilgili testler
WinError 1314 ile atlandı. Path containment kodu incelendi ve traversal testleri
çalıştı, ancak bu gerçek symlink yürütme kanıtı değildir. Linux testleri korunuyor.

**İlgili yerler:** `dojo-core/tests/test_branding_assets.py::test_symlink_escape_is_not_previewed`;
`dojo-core/tests/test_package_editor.py::test_artifact_symlink_escape_is_unavailable_and_rejected`;
`dojo-core/src/dojo/publishing.py` asset/artifact resolver'ları;
`backend/tests/test_package_editor_api.py`.

**Sonraki inceleme:**
- [ ] İki testi Linux CI'da skip olmadan çalıştır ve sonucu kaydet.
- [ ] Gerekirse ayrı yetkili Windows test ortamı kullan; mevcut makinenin izinlerini sessizce değiştirme.
- [ ] Outside-root dosyaya symlink ve Windows destekleniyorsa junction durumlarını incele.
- [ ] Artifact/branding endpointlerinin dışarıdaki dosyanın bytes veya yolunu sızdırmadığını doğrula.

**Kabul:** Kök dışına çıkan bağlantılar reddedilir; uygun kök içi dosyalar çalışır;
skip ile pass ayrımı kanıtta açık kalır. Native FFmpeg testlerinin iki ayrı ortam
atlaması bu symlink eksikliğinin parçası değildir.

## 8. Ondalık klavye ve büyük arşiv performansı

**Karar:** Cihaz/yük yeniden üretimi olmadan sayı girişini veya preview modelini
yeniden tasarlamamak. İki alt konu bağımsız incelenmeli.

**8A — Sayı girişi:** `VideoSectionEditor` text + `inputMode="decimal"` kullanır;
raw metin hook'ta korunur, sayısal dönüşüm `Number()` ile yapılır. Türkçe cihaz
klavyesinin virgül sunması, ondalık girişini zorlaştırabilir. Bu cihaz davranışı
yerel Chromium touch emülasyonuyla kanıtlanmadı.

**İlgili yerler:** `web/src/packages/VideoSectionEditor.tsx`;
`web/src/packages/usePackageEditor.ts`; `web/src/packages/ranges.ts`;
`web/src/i18n/tr.ts`; ilgili component/hook testleri.

- [ ] Gerçek Android/iOS Türkçe klavyede nokta, virgül, silinmiş alan ve yarım girişi dene.
- [ ] Virgül desteği gerekliyse gösterim/raw draft korunarak açık normalizasyon politikası tasarla;
  önceki geçerli sayıya sessizce geri dönme.
- [ ] NaN/Infinity, negatif, overlap ve sub-frame kontrollerini koruyan regresyonlar ekle.

**8B — Arşiv:** Aktif panel yalnızca bir video editörü açar, ancak
`CompletedPackages` tarihsel medya preview'larını liste içinde monte edebilir.
Metadata preload büyük arşivde çok sayıda request/decode ve bellek tüketebilir;
ölçüm yapılmadan performans hatası ilan edilmedi.

**İlgili yerler:** `web/src/packages/CompletedPackages.tsx`;
`web/src/packages/ActivePackagePanel.tsx`; `web/src/styles.css`.

- [ ] Örneğin 10/100/500 sentetik medyayla desktop ve düşük güçlü mobil cihazda
  başlangıç request sayısı, etkileşim süresi, bellek ve scroll performansını ölç.
- [ ] Sonuca göre explicit preview açma, lazy mounting veya pagination seçeneklerini değerlendir.

**Kabul:** Gerçek hedef klavyede ondalık değer anlaşılır şekilde girilebilir;
invalid raw giriş kaybolmaz. Arşiv için ölçülmüş bütçe üzerinde anlaşılır,
preview/download erişilebilirliği ve read-only davranış korunur.

## 9. Eski kare-altı trim uyumluluğu

**Karar:** Kullanılabilir render çıktısında kanıtlanmış regresyon olmadan eski
trimleri otomatik yeniden yazmamak. Yeni canonical seçimler minimum `1/25 s`
kuralına bağlı; eski digest biçimi explicit seçim düzenlenene kadar korunuyor.

**Risk:** Eski manifestte 0,04 saniyeden kısa retained trim varsa, canonical
validation/render/edit akışında ek müdahale gerekebilir. Varsayımsal örnek ile
gerçek eski çıktı davranışı birbirinden ayrılmalı.

**İlgili yerler:** `dojo-core/src/dojo/montage.py::manifest_selections`,
`validate_ranges`; `dojo-core/src/dojo/publishing.py::_build_reel`, `_render_digest`;
`dojo-core/tests/test_selections.py`; `dojo-core/tests/test_render_selections.py`.

**Sonraki inceleme:**
- [ ] Eski `trims` manifestiyle 0,039 / 0,04 / 0,041 saniye retained örnekleri oluştur.
- [ ] Başlangıç ve güncel sürüm render/preview/save davranışını sentetik aynı kaynakla karşılaştır.
- [ ] Gerçek gerileme varsa explicit uyarı/yeniden seçim veya uyumlu geçiş politikasını onaya sun.

**Kabul:** Eski originals ve onaylı artifact/digest istemeden değişmez;
geçerli eski içerik kullanılabilir; desteklenmeyen aralık sessizce farklı içeriğe
çevrilmek yerine kullanıcıya açıkça bildirilir.

## 10. Gerçek tarayıcı–backend uçtan uca doğrulama

**Karar ve kanıt:** Playwright testleri gerçek Chromium pointer/touch, native
video ve downloads davranışını sentetik MP4 ile test eder; `/api/` yanıtları mock'tur.
Backend auth/range/FileResponse ve production FFmpeg ayrı gerçek seam testleriyle
doğrulanmıştır. Bunlar birleşik deployment kanıtı değildir.

**Risk:** Reverse proxy, cookie/credentials, Range forwarding, route eşleştirmesi,
content disposition veya worker artifact yaşam döngüsü gerçek ortamda farklı çalışabilir.

**İlgili yerler:** `web/e2e/package-management.spec.ts`; `web/playwright.config.ts`;
`backend/src/backend/routes/packages.py`; `backend/tests/test_package_editor_api.py`;
`dojo-core/tests/test_render_selections.py`; `ops/`; deployment CI konfigürasyonu.

**Sonraki inceleme:**
- [ ] Ayrı test veritabanı/media root ile gerçek backend, worker ve web/proxy kur.
- [ ] Test kimliğini gerçek eşleştirme yoluyla oluştur; API mock kullanma.
- [ ] Sentetik medya yükle → finalize → seç/sırala → render → preview/seek → indir akışını dene.
- [ ] Kontrollü tamamlanmış fixture üzerinden archive download ve revoked-client erişimini dene.
- [ ] Test kaynak bytes hash'i, seçili çıktı süresi/sırası, Range, dosya adı ve cache header'larını kaydet.

**Kabul:** Tarayıcı gerçek servis üzerinden çalışır; ham medya yetkisiz açılmaz;
seçimler/süre/artifact uyuşur; archive immutable kalır; test gerçek Instagram
yayını yapmaz veya üretim kullanıcı verisine dokunmaz.

## 11. Yoğun yükte test zamanlaması

**Karar ve kanıt:** Aynı anda Python/Docker, browser ve sınırsız web workers
çalışırken iki test zamanlama hatası verdi:
`App.test.tsx::resumes incomplete setup once and preserves intentional navigation`
(onboarding lookup) ve
`PackageManager.test.tsx::completed view uses draft decision and cancel keeps editor mounted`
(decision timeout). İkisi izolasyonda geçti; cancellation fixture async guard
serbest bırakılmasını bekleyecek şekilde düzeltildi. Dört worker ile ve daha
sonra normal workers ile tam 233 test geçti. Assertion/product timeout gevşetilmedi.

**Risk:** CI kaynak baskısı hâlâ flake üretebilir. Tek başarılı rerun kalıcı
kararlılık kanıtı değildir; ürün yarışı ile test senkronizasyonu ayrılmalı.

**İlgili yerler:** `web/src/App.test.tsx`; `web/src/packages/PackageManager.test.tsx`;
`web/src/packages/PackageEditorProvider.tsx`; `web/src/navigation.ts`;
`web/vitest.config.ts`; `.github/workflows/ci.yml`.

**Sonraki inceleme:**
- [ ] İki testi ve tam suite'i kontrollü normal/baskılı kaynakta birkaç kez çalıştır;
  başarısızlık oranı, CPU/bellek, worker sayısı ve trace/log kaydet.
- [ ] Event/hash navigation, guard Promise tamamlanması ve test async beklemelerini izle.
- [ ] Reprodüksiyona göre eksik await düzeltmesi veya kaynak bütçesine uygun worker sınırı seç;
  timeout büyütüp hatayı gizleme.

**Kabul:** Kararlaştırılan tekrar setinde açıklanamayan failure yok;
cancel/save/discard route davranışı değişmez; CI süresi ve resource bütçesi belgelenir.

## 12. Küçük bulgu: Timeline sınır yuvarlaması

**Durum:** Reviewer'ın doğrudan yeniden ürettiği, ertelenmiş küçük hata.
`RangeTimeline` önce clamp, sonra `precise()` ile milisaniyeye yuvarlama yapıyor.
Yuvarlama, clamp'in izin verdiği tam sınırın dışına çıkabilir.

**Somut örnek:** Kaynak süresi `30.1236`; end handle üzerinde `End` tuşu
`30.124` üretir. `30.124 > 30.1236`, dolayısıyla legal olmayan endpoint çıkar.
Komşu sınır `10.1236` veya minimum-frame sınırı da benzer şekilde aşılabilir.
Keyboard, pointer ve koordinat dönüşümü ayrı kontrol edilmelidir.

**Etki ve geçici çözüm:** Validation kaydetmeyi engeller; illegal aralık server'a
kalıcı yazılmaz. Draft invalid olduğunda timeline devre dışı kalabilir; kullanıcı
hassas text alanında doğru endpoint'i girerek devam edebilir. Bu yüzden veri
kaybı/persistence hatası değil kullanım hatası olarak Minor bırakıldı.

**İlgili yerler:** `web/src/packages/RangeTimeline.tsx::point`, `move`, `key`,
`precise`; slider `aria-valuemin/max`; `web/src/packages/ranges.ts::validateRanges`;
`web/src/packages/RangeTimeline.test.tsx`; `web/src/packages/VideoSectionEditor.test.tsx`.

**Önerilen sonraki düzeltme:** Son clamp'ten önce yuvarla; exact source/neighbor
sınırlarını clamp sonrasında yeniden yuvarlama. Koordinat üretimi ve ARIA
sınırlarının aynı legal değerleri temsil ettiğinden emin ol. Bir helper'a
toplamak ancak bu invariants netleştirildikten sonra değerlendirilmeli.

**RED→GREEN regresyon adayları:**
- [ ] Duration `30.1236`, end handle `End`: endpoint tam `30.1236`, validation geçerli.
- [ ] Komşu start `10.1236`, önceki end `End`: endpoint komşuyu aşmaz, overlap yok.
- [ ] End `5.1236`, start handle `End`: en az `0.04 s` retained süre korunur.
- [ ] Fractional source/neighbor sınırında pointer resize aynı kuralları sağlar.
- [ ] Home/End, Arrow `0.1 s`, Shift+Arrow `1 s`, cancellation ve ARIA değerleri tutarlı kalır.
- [ ] Masaüstü ve dokunmatik gerçek geometry ile legal sınırlar ve minimum frame doğrulanır.

**Kabul:** Her gesture/keyboard çıktısı finite, source içinde, overlap olmadan
ve en az bir kare uzunluğundadır; timeline kendi legal hareketiyle invalid draft
oluşturmaz; server validation gevşetilmez.

## Sonraki oturum için çalışma kuralı

1. Seçilen kaydı ve güncel kodu oku; bu belgedeki snapshot sayılarını güncel
   doğrulama gibi sunma. İlgili dosya yolları çalışma başlangıcıdır, tam kapsam iddiası değil.
2. Karar/eksik kanıt/hata ayrımını koru; karar korunuyorsa gerekçeyi kaydet.
3. Hata düzeltilecekse önce yeniden üreten test RED, sonra minimal fix GREEN.
4. İlgili suite ve statik/build kontrollerini çalıştır; her atlama ve kalan hatayı raporla.
5. API/privacy, kimlik formatı, dependency major veya deployment değişikliği için
   gerektiğinde yeni tasarım/uygulama onayı al. Bu notlar otomatik uygulama yetkisi vermez.
6. Kayıtta durum, kanıt, commit/issue ve kabul ölçütü sonucunu güncelle.

Şablon: `Durum: incelendi / düzeltildi / karar korundu — Kanıt: ... — Commit/issue: ... — Kalan risk: ...`.
