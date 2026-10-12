# Android yayın incelemesi, bildirimler ve doğrudan bağlantılar — deneme rehberi (#36)

Tarih: 12 Ekim 2026. Uygulama değişiklikleri: `9c16082`–`6cc100e`;
ayrıntılı doğrulama kaydı: [`docs/verification/issue-36.md`](../verification/issue-36.md).

Bu rehber önce **Android uygulamasında**, sonra ortak sonucu **tarayıcıda**
denemenizi sağlar. Arayüzde bulunmayan hazırlık ve zor üretilebilen hata durumları
için **PowerShell** komutları vardır. Kod bloklarında Python veya SQL kodu yoktur;
test komutları depodaki hazır testleri çalıştırır.

> **Yalnız ayrı deneme ortamını kullanın.** Gerçek öğrenci medyası, üretim
> veritabanı veya kişisel Instagram hesabıyla denemeyin. Atlamak, yeniden
> zamanlamak, açıklama değiştirmek ve yüklemek kalıcıdır; aynı sunucuya bağlı
> diğer istemcileri de etkiler. Eşleştirme kodlarını, oturum bilgilerini ve
> Firebase hizmet hesabı dosyasını paylaşmayın.
>
> **Android’de “Onayla ve paylaş” doğrudan gerçek yayın işlemini başlatır.**
> Web’deki gibi ikinci onay düğmesi yoktur. Yayın için açıkça ayrılmış bir hesap
> ve içerik yoksa bu düğmeye basmayın; güvenli onay denemesi için bölüm 11’i kullanın.
> Bir bildirime veya bildirimin Atla/Yeniden zamanla kısayoluna dokunmak ise
> yalnız ekranı/formu açar; tek başına karar göndermez.

**Doğrulama sınırı:** Geliştirme sonunda 161 Android, 733 çekirdek, 209 backend,
140 worker ve 288 web testi geçti; 4 çekirdek testi atlandı. APK, lint ve cihaz
testi APK’si doğrulandı. Bağlı cihaz/emülatör olmadığı için gerçek oynatıcı,
yerel diyaloglar, cihaz testleri ve FCM teslimatı henüz çalıştırılarak
doğrulanmadı. Aşağıdaki “beklenen” sonuçlar kabul kontrolüdür, yapılmış deneme
iddiası değildir.

## 1. Neler değişti?

| Değişiklik | Denemede göreceğiniz sonuç |
| --- | --- |
| Android odaklı yayın incelemesi | Kontrol Paneli ve Etkinlik → Onay kutusu, ilgili incelemenin Reel’ini ve kaydedilmiş açıklamasını açar. |
| Sürüme bağlı önizleme | Başka paket/sürüm sessizce gösterilmez; oynatıcı hazır olmadan paylaşım onayı verilemez. |
| Karar ekranları | Hazır incelemeyi atlayabilir veya İstanbul saatine göre yeniden zamanlayabilirsiniz. |
| Boş paket kararları | Adı belli aktif paketin bekleyen Yayın Zamanını medya yüklemeden atlayabilir/erteleyebilirsiniz. |
| Kalıcı Onay kutusu | Push kapalı veya Firebase yapılandırılmamış olsa da sunucudaki bekleyen işler görünür. |
| Android FCM desteği | İzin, kayıt durumu, token yenileme ve sonraki yenilemede kayıt tekrar denemesi vardır. |
| Bildirim kısayolları | İncele/Medya yükle, Atla ve Yeniden zamanla doğru bağlamı açar; otomatik karar göndermez. |
| Paylaşım sonucu bildirimi | Doğrulanmış/başarısız sonuç, bildirimin paketine ait Etkinlik bağlamını açar. |
| Aynı Yayın Zamanına devam | Boş paket → yükleme → montaj → render → aynı zamanın hazır incelemesi. |
| Eski veri ve oturum koruması | Tamamlanmış/değişmiş inceleme, başarısız yenileme veya değişen paketle yanlış karar/yükleme engellenir. |
| Bildirim temizliği | Başarılı sunucu yenilemesi, çözümlenmiş veya yerini başka sürüme bırakmış bekleyen işlem bildirimlerini kaldırır. |

Bu iş web’e yeni inceleme ekranı eklemedi; mevcut web ekranları ortak sunucu
sonucunu karşılaştırmak için kullanılır. Onay kutusu tam Etkinlik geçmişi veya
çevrimdışı önbellek değildir. Tamamlanmış paket gezintisi de bu işin kapsamında değildir.

## 2. Hazırlık

### 2.1. Güncel kod ve ayrı deneme sunucusu

1. #36 kodunu içeren backend, worker ve web’in bulunduğu ayrı deneme ortamını
   kullanın. Yeni ortam kurulacaksa
   [Android yükleme rehberinin hazırlık bölümlerini](issue-33-android-upload-deneme-rehberi.md)
   izleyin; eski dal/dizin örneklerini bu işin güncel diziniyle değiştirin.
2. Sunucunun gerekli kurulum adımları tamamlanmış, logo yapılandırılmış ve
   worker çalışıyor olmalı. Düzenli yayın planını deneme için etkinleştirmek
   gerekmez; aşağıda tek bir manuel Yayın Zamanı oluşturacağız.
3. Boş paket denemelerini **medya içermeyen** ayrı bir ortamda başlayarak yapın.
   Dolu paketi silerek veya tamamlayarak bu durumu üretmeyin.

PowerShell’i bu değişikliklerin bulunduğu repo kökünde açın:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo\.worktrees\issue-36'
git branch --show-current
$ComposeProject = Read-Host 'Önceden hazırlanmış ayrı deneme ortamının Compose proje adı'
if ([string]::IsNullOrWhiteSpace($ComposeProject)) { throw 'Deneme proje adı gerekli.' }
$ComposeArgs = @('--env-file', 'ops/.env', '-p', $ComposeProject, '-f', 'ops/docker-compose.yml')
docker compose @ComposeArgs ps
```

Beklenen dal `feat/issue-36-android-review`; başka bilgisayarda dizini değiştirin.
Bu blok ortam kurmaz veya güncellemez. **Compose proje adı tek başına veriyi
ayırmaz:** `ops/db-data` ve `ops/media-data` bind dizinleri üretime aitse durun.
Mevcut ortam başka Compose dosyaları kullanıyorsa onun gerçek argümanlarını
kullanın; yanlış dizinden aynı proje adına komut göndermeyin.

### 2.2. Android uygulaması

1. Android Studio’da **bu repo içindeki `android` klasörünü** açın.
2. SDK 35 ve Android 10/API 29+ ayrı deneme emülatörü/cihazı seçin. Gerçek push
   denemesi için desteklenen Google Play hizmetleri olan cihaz gerekir.
3. **app → Run** ile güncel debug uygulamasını kurun. Mevcut kişisel/üretim
   uygulamasında imza uyuşmazlığı varsa onu kaldırmayın; ayrı emülatör kullanın.
4. Uygulamada sunucu origin’ini girin. Yerel emülatör için
   `http://10.0.2.2:8000`, uzak ortam için kendi deneme HTTPS adresiniz.
   `/api` eklemeyin. Emülatörde `localhost` Windows bilgisayarı değildir;
   yerel HTTP yalnız debug uygulamasında kullanılabilir.
5. Yeni eşleştirme kodunu deneme backend’inde üretin:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
if ($LASTEXITCODE -ne 0) { throw 'Eşleştirme kodu üretilemedi.' }
```

6. Android’de **Cihaz adı**, kod ve **Eşleştir** ile bağlanın. Kurulum açılırsa
   gerekli hazırlığı kontrol edin; hazır ortamda **Şimdilik kontrol paneline dön**
   ile çıkabilirsiniz.

JDK hatası alırsanız Android Studio’nun JBR dizinini kullanın. Bölüm 11’deki
PowerShell derleme komutu burada kullanılan JDK yolunu gösterir.

### 2.3. Tarayıcı ve sentetik medya

Mevcut deneme web adresini açın. Yerel web çalışmıyorsa ayrı PowerShell
penceresinde aynı repo kökünden:

```powershell
npm --prefix web ci
if ($LASTEXITCODE -ne 0) { throw 'Web bağımlılıkları kurulamadı.' }
npm --prefix web run dev -- --host localhost --port 3000 --strictPort
```

Terminal açık kalır. Tarayıcıda `http://localhost:3000/#/dashboard` açın;
8000 backend portudur. Tarayıcı için **yeni bir kod** üretip eşleştirin;
Android’in kullandığı tek kullanımlık kodu tekrar kullanmayın.

Deneme dosyası için depodaki sentetik 30 saniyelik videoyu ayrı dizine kopyalayın:

```powershell
$DemoDir = Join-Path $env:TEMP ('dojo-issue36-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $DemoDir | Out-Null
Copy-Item -LiteralPath 'web/e2e/fixtures/timeline.mp4' -Destination (Join-Path $DemoDir 'inceleme-deneme.mp4')
$DemoDir
```

Dosyayı Android’in Download/İndirilenler klasörüne aktarın veya tarayıcıdan
yükleyin. Gerçek kişi içeren medya gerekmiyor; tek renkli videoda sahne değişimi
beklemeyin. Aynı adlı dosyayı ikinci kez seçmek çakışma denemesi için kullanılabilir.

## 3. Arayüzde olmayan hazırlık — PowerShell

Bu bölüm Instagram’a yayın yapmaz; deneme oturumu, gerekirse aktif paket ve
şimdiki zamana ait karar bekleyen manuel Yayın Zamanı oluşturur.

### 3.1. PowerShell için ayrı oturum

Tarayıcı ve Android oturumları PowerShell’e aktarılmaz. Bölüm 2.2’deki komutla
**üçüncü, yeni bir kod** üretin; ardından aynı PowerShell penceresinde:

```powershell
$BaseUri = 'http://localhost:3000'
$Code = Read-Host 'PowerShell için yeni eşleştirme kodu'
$Body = @{ code = $Code; kind = 'browser'; name = 'Issue36 deneme PowerShell' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$BaseUri/api/pairing/validate" `
    -ContentType 'application/json; charset=utf-8' -Body $Body -SessionVariable DojoSession
$Code = $null
$Body = $null
$Setup = Invoke-RestMethod -Uri "$BaseUri/api/setup" -WebSession $DojoSession
if (-not $Setup.ready) { throw 'Kurulum eksik. Arayüzden tamamlayın veya bölüm 11 güvenli testlerini kullanın.' }
```

Uzak sunucuda `$BaseUri` değerini kendi deneme web origin’inizle değiştirin.
Yerelde `localhost`/`127.0.0.1` arasında geçiş yapmayın. Oturum cookie’si yalnız
bellekte tutulur; terminali kapatırsanız yeni oturum gerekir. Her yeni terminalde
gerekli değişkenleri yeniden tanımlayın.

### 3.2. Adı belli aktif paket ve bekleyen zaman

Önce Android/web **Paket** ekranında ortamın boş olduğunu kontrol edin. Aktif
paket yoksa aşağıdaki API çağrısı oluşturur; varsa mevcut paketi döndürür:

```powershell
$Package = Invoke-RestMethod -Uri "$BaseUri/api/packages/active" -WebSession $DojoSession
$Package | Select-Object id, folder_name, status
$Due = Invoke-RestMethod -Method Post -Uri "$BaseUri/api/settings/manual-publish" -WebSession $DojoSession
$Due | Select-Object id, kind, due_at, status
```

Beklenen: `kind=manual`, `status=pending`. `409` zaten bekleyen manuel zaman
olduğunu bildirir; tekrar tekrar göndermeyin, Kontrol Paneli’ndeki zamanı kullanın.
Aktif paketin adının belli olması boş paket Atla/Yeniden zamanla işlemleri ve
boş paket push’u için gereklidir. Paket yokken sunucu uydurma paket adına bildirim
üretmez; normal medya yükleme girişi kullanılabilir.

Kimlikleri ve ortak durumu gerektiğinde **salt okuyarak** kontrol edin:

```powershell
$Dashboard = Invoke-RestMethod -Uri "$BaseUri/api/dashboard" -WebSession $DojoSession
$Dashboard.pending_actions | Format-Table occurrence_id, review_id, version, package_folder, state, due_at
```

`empty_package`, `preparing` ve `review_ready` sırasıyla boş, hazırlanıyor ve
incelemeye hazır durumlarıdır. `occurrence_id` bu rehberdeki **aynı Yayın Zamanı**
kontrolünün anahtarıdır; `review_id` ile aynı kavram değildir.

## 4. Boş paketi atlama ve erteleme — Android

Bu kararlar zamanı kapatır; her bağımsız deneme için bölüm 3.2’de yeni manuel
zaman oluşturun. Geleceğe ertelenmiş zaman bekleyenlerde görünüyorsa vadesi
gelmeden karar düğmelerinin kullanılmaması normaldir.

### 4.1. Atlamayı iptal edin, sonra onaylayın

1. Android **Kontrol Paneli → Yenile** ile boş paket satırını görün.
2. Satırdaki **Atla**’ya basın. İlgili paket/Yayın Zamanı ve
   **Bu Yayın Zamanı atlanacak; Dojo Yayın Planı değişmez.** uyarısı görünmeli.
3. **Vazgeç** ile çıkın. Onay kutusunda zaman hâlâ beklemeli.
4. Aynı satırda tekrar **Atla → Atlamayı onayla** seçin.
5. **Yayın Zamanı atlandı** sonucunu görün; Kontrol Paneli ve
   **Etkinlik → Onay kutusu → Yenile** ile eski bekleyen satırın kalktığını kontrol edin.
6. Tarayıcı Kontrol Paneli’ni yenileyin. Aynı zaman artık beklememeli; paket
   korunmalı. Düzenli plan etkin değilse sonraki düzenli zaman görünmeyebilir.

### 4.2. Yeniden zamanlayın

1. Yeni manuel zaman oluşturup Android’de yenileyin.
2. **Yeniden zamanla** ile formu açın. Tarih ve saat düğmeleri yerel Android
   seçicilerini açmalı. Birini açıp geri tuşuyla kapatın; karar gönderilmemeli.
3. Geçmiş tarih/saat seçip **Yeni zamanı onayla**’yı deneyin. İstanbul saatinde
   gelecekte zaman gerektiği uyarısı görünmeli; zaman değişmemeli.
4. İstanbul saatine göre birkaç dakika sonrasını seçin; önce **Vazgeç**’i deneyin.
5. Formu tekrar açıp gelecekteki zamanı **Yeni zamanı onayla** ile kaydedin.
6. **Yayın Zamanı yeniden zamanlandı** sonucunu görün. Tarayıcıdaki zaman ve
   düzenli planı karşılaştırın: yeni tek seferlik zaman oluşur, planın ana tarihi
   kaymaz ve paket korunur.

Telefonun saat dilimi farklı olsa da bu form **Europe/Istanbul (UTC+03:00)**
anlamındadır. Sonuç belirsizse tekrar göndermek yerine **Yenile** ile okuyun.

## 5. Boş paket → yükleme → render → aynı inceleme — Android

**Önkoşul:** Vadesi gelmiş boş paket zamanı. Bölüm 4’te çözdüyseniz yeni manuel
zaman oluşturun. Başlangıç `occurrence_id` ve paket adını bölüm 3’teki okumayla not edin.

1. **Kontrol Paneli** veya **Etkinlik → Onay kutusu** satırındaki **Medya yükle**’ye basın.
2. **Paket** ekranında **Bekleyen Yayın Zamanı** başlığı, paket adı,
   **Fotoğraf / video seç**, montaj alanı ve
   **Reel hazırla ve incelemeye devam et** görünmeli.
3. Medya seçmeden devamı deneyin. Geçerli medya/montaj gereksinimi nedeniyle
   render başlamamalı. Hedef henüz doğrulanmadıysa seçim düğmesi de kapalı olabilir.
4. Sentetik videoyu seçin. Yalnız %100 veya **sunucuda sırada** durumunu yeterli
   saymayın; **Aktif Pakete eklendi** sonucunu bekleyin.
5. Dosya çakışması varsa aşağıdaki mevcut çözüm kontrollerini kullanın.
   Bekleyen yükleme/çakışma varken devamı deneyin; render başlatılmamalı.
6. Montaj sırası ve süre sınırını kontrol edin. Bölüm düzenlediyseniz
   **Video bölümlerini kaydet** ile kaydedin; kaydedilmemiş taslakla devam etmeyin.
7. **Reel hazırla ve incelemeye devam et**’e basın. Hazırlanıyor mesajını bekleyin.
   Worker önce davranmışsa mevcut render beklenmeli; ikinci iş oluşturulmamalı.
8. Ekran hazır incelemeye geçmeli. Gerekirse **Yenile** kullanın; yeni manuel
   zaman oluşturmayın. Bölüm 3’teki okuma aynı `occurrence_id`/paket adını,
   artık `review_ready` ve dolu `review_id` değerini göstermeli.
9. Reel hazırlanırken uygulamayı arka plana alın veya ekranı döndürün. Dönüşte
   durum yeniden okunmalı; yeniden oluşturma otomatik render/karar göndermemeli.

Render gerçekten başarısızsa **Reel hazırlanamadı. Tekrar deneyin.** mesajından
sonra yalnız açık **Tekrar dene** işlemi yeni denemeyi başlatmalıdır. Dosya
silerek/bozarak hata üretmeyin; güvenli hata ve yarış testleri bölüm 11’dedir.

Paket değişti uyarısını atlatmak için başka pakete yüklemeyin. Hedef paket veya
oturum seçim sırasında değişirse aktarım reddedilmelidir; bu yarışın deterministik
kontrolü de bölüm 11’dedir.

## 6. Aynı Reel ve açıklamayı iki arayüzde kontrol edin

1. Android Kontrol Paneli’ndeki hazır satırda **İncele**’ye basın.
2. **Yayın incelemesi**, paket adı, yerel video oynatıcısı ve
   **Paylaşılacak açıklama** görünmeli. Kaynak video düzenleyicisi yerine final
   Reel’i görmelisiniz; video ve açıklama bu incelemenin sürümüne aittir.
3. Oynat/duraklat ve geri tuşunu deneyin. Önizleme hazırlanırken veya hata
   varken **Onayla ve paylaş** kapalı olmalı. Açık olması videonun sonuna kadar
   izlendiği anlamına gelmez; içerik kontrolü kullanıcıya aittir.
4. **Kapat** ile geldiğiniz ekrana dönün; **Etkinlik → Onay kutusu → İncele**
   üzerinden aynı kaydı yeniden açın.
5. Tarayıcı **Kontrol Paneli → İnceleme özeti** ile aynı incelemeyi açın.
   Adreste `#/package?review=...` bulunmalı. Paket, Reel ve açıklamayı karşılaştırın;
   bu adresi bölüm 7 için saklayın.
6. Android’de yayın düğmesine basmayın. Web’de isterseniz yalnız ilk
   **Onayla ve yayınla** ile uyarıyı açıp **Vazgeç** seçin;
   **Yayınlamayı onayla** gerçek işlemi başlatır.

Hazır incelemenin **Atla** ve **Yeniden zamanla** formları bölüm 4 gibi çalışır;
bu kez karar inceleme kimliği ve gösterilen sürümle gönderilir.

## 7. Başka cihazda tamamlanmış veya değişmiş inceleme

### 7.1. Başka istemcide atlayın

1. Aynı hazır incelemeyi Android ve tarayıcıda açık tutun.
2. Tarayıcıda **Bu zamanı atla → Atlamayı onayla** seçin.
3. Android’e dönüp **Yenile**’ye basın. **Bu işlem zaten yapıldı.** açıklaması
   veya çözümlenmiş durum görünmeli; yeniden paylaşım onayı verilememeli.
4. Onay kutusunu yenileyin; bekleyen satır kalkmalı. Eski bildirim varsa başarılı
   yenilemeden sonra kaldırılmalı; eski hedef başka hazır incelemeye dönüştürülmemeli.

Ekran açıkken otomatik yenileme işlemi siz basmadan fark edebilir; bu doğrudur.
İki cihazda aynı anda eski sürümle gönderme yarışı bölüm 11’de güvenli test edilir.

### 7.2. Açıklamayı değiştirip eski sürümü kontrol edin

Yeni manuel zaman ve hazır inceleme oluşturun. Android’de o incelemeyi açık tutun.
Odaklı ekranda açıklama düzenleyicisi olmadığından yalnız deneme paketinde:

```powershell
$Body = @{ caption = "Issue36 yeni açıklama`n#dojo #deneme" } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$BaseUri/api/packages/active/caption" `
    -WebSession $DojoSession -ContentType 'application/json; charset=utf-8' -Body $Body
```

1. Android’de **Yenile** seçin. Eski inceleme yeni açıklamayla sessizce
   değiştirilmemeli; değişti/yenileme gerektiği açıklaması ve kapalı karar
   düğmeleri beklenir.
2. Tarayıcı **Güncel Paket → Kaydedilmiş montajı render et** üzerinden güncel
   sürümü hazırlayın; render zaten sürüyorsa bekleyin.
3. Android Onay kutusundan yeni hazır incelemeyi açın. Yeni açıklamayı görün.
   Eski inceleme/notification kendiliğinden bu yeni hedefin onayına dönüşmemeli.

## 8. Push olmadan kullanım, kesinti ve görünüm

1. Firebase dosyası olmayan uygulamada **Ayarlar**’ı açın.
   **Bildirim yapılandırması yok. Onay kutusu kullanılabilir.** beklenir.
   Bu hata, inceleme/yükleme ekranlarını kaldırmamalıdır.
2. Yapılandırılmış uygulamada Android bildirim iznini veya **Yayın incelemeleri**
   kanalını sistem ayarlarından kapatın. Onay kutusunu açıp yenileyin;
   bekleyen işler sunucudan yine okunmalıdır.
3. İnceleme açıkken telefonun ağını kesin; yenilemenin başarısız olmasını
   bekleyin. Eski bilgi görünse bile paylaş/atla/yeniden zamanla işlemleri
   kapalı olmalı. Ağı açıp başarılı **Yenile** yapın.
4. **İşlem sonucu doğrulanamadı** görürseniz işlemi tekrar göndermeyin;
   önce **Yenile** ve diğer istemciden durum kontrolü yapın.
5. İnceleme/erteleme formunu açıp ekranı döndürün, uygulamadan çıkıp dönün.
   Görüntü yeniden okunmalı; kaydedilmiş ekran konumu komut tekrarı olmamalıdır.
6. Küçük ekran/büyük yazı, açık/koyu tema ve TalkBack ile düğme adlarını,
   kaydırmayı, oynatıcı kontrollerini ve geri dönüşü kontrol edin.

Google Play hizmeti bulunmayan cihazda durum bunun kullanılamadığını bildirmeli;
inbox çalışmaya devam etmelidir. Tek cihazda hizmetleri bozarak test etmeyin;
uygun ayrı emülatör veya bölüm 11’deki testleri kullanın.

## 9. Gerçek Android bildirimleri — yalnız yetkili Firebase deneme ortamında

Bu bölüm gerçek ağ teslimatıdır; bölüm 11’deki sahte bildirim testlerinden
farklıdır. Firebase/cihaz yoksa atlayın ve **doğrulanmadı** kaydedin.
`google-services.json` ve hizmet hesabı dosyasını yerleştirmek tek başına
bildirim göstermez; aşağıdaki 9.1–9.2 sırası gerekir.

### 9.0. Yerleştirilen dosyaları doğrulayın (PowerShell)

Repo kökünde çalıştırın. Python/SQL kodu yoktur:

```powershell
Test-Path android/app/google-services.json
Test-Path ops/fcm_credentials.json
git check-ignore -v android/app/google-services.json ops/fcm_credentials.json
$a = Get-Content -Raw android/app/google-services.json | ConvertFrom-Json
$b = Get-Content -Raw ops/fcm_credentials.json | ConvertFrom-Json
$a.project_info.project_id
$b.project_id
$a.client[0].client_info.android_client_info.package_name
```

Beklenen: iki `Test-Path` `True`; `check-ignore` iki satır döndürür
(Git’e eklenmezler); iki proje kimliği aynı (`aisomedo-35`); paket adı
`com.dojo.aisomedo`. Kimlikler farklıysa durun: worker başka projeye gönderir,
uygulama başka projeyi dinler, `sender-id mismatch` olur ve bildirim gelmez.

### 9.1. Yapılandırma ve izin

1. Yetkili operatör, worker’ın Firebase projesinde `com.dojo.aisomedo` Android
   uygulamasını kaydedip onun **google-services.json** dosyasını indirir.
   Bu adım sizde tamam: dosya `android/app/google-services.json` konumunda.
2. Backend hizmet hesabı JSON’u (`ops/fcm_credentials.json`) bu dosyanın yerine
   konmaz; iki dosya da Git’e eklenmez (`git status --short` temiz kalmalı).
3. Worker’da gerçek gönderim için `ops/.env` dosyasına şunları yazın:

   ```powershell
   notepad ops/.env
   ```

   Dosyada `FCM_PROJECT_ID=aisomedo-35` olmalı (9.0’daki kimlikle aynı).
   `FCM_CREDENTIALS_FILE` değeri, hizmet hesabı dosyasının **bu bilgisayardaki
   mutlak yolu** olmalı; örnek: `FCM_CREDENTIALS_FILE=C:/Users/<siz>/.../ops/fcm_credentials.json`.
   Ters eğik çizgi yerine `/` kullanın. Bu dosya Compose tarafından salt okunur
   secret olarak bağlanır; `docker inspect` çıktısında görünmez.
4. Deneme ortamını monitoring dosyasıyla başlatın (proje adınız sizinkiyle değişir):

   ```powershell
   docker compose --env-file ops/.env -p <deneme-projeniz> `
     -f ops/docker-compose.yml `
     -f ops/docker-compose.monitoring.yml up -d --build
   docker compose -p <deneme-projeniz> logs worker --tail 50 | Select-String 'fcm|monitoring'
   ```

   Beklenen: `monitoring enabled` ve `worker started`; `fcm.notifier_unavailable`
   veya `FCM enabled but firebase_admin not configured` **görülmemeli**.
   Bu satırlar varsa `FCM_PROJECT_ID`/`FCM_CREDENTIALS_FILE` yanlıştır; worker
   başlamadan durur. Bu rehber üretim dağıtımı yetkisi vermez.
5. Android Studio’da `android` klasöründen debug uygulamasını yeniden derleyip
   ayrı deneme cihazına kurun (Google Play hizmetleri desteklenmeli):

   ```powershell
   $env:JAVA_HOME = 'C:/Program Files/Android/Android Studio/jbr'
   ./android/gradlew.bat -p android :app:assembleDebug
   if ($LASTEXITCODE -ne 0) { throw 'Derleme başarısız.' }
   adb install -r android/app/build/outputs/apk/debug/app-debug.apk
   if ($LASTEXITCODE -ne 0) { throw 'Kurulum başarısız; cihaz bağlı ve ayrı deneme cihazı olmalı.' }
   ```

6. Cihazı doğru deneme sunucusuna eşleştirin (bölüm 2.2’deki kodla).
7. Android **Ayarlar** ekranını açın. Kayıt sırasında **Bildirim kaydı
   doğrulanıyor**, başarılı kayıttan sonra **Bildirimler açık** beklenir.
   Diğer metinlerin anlamı:

   | Ekrandaki metin | Anlamı ve sonraki adım |
   | --- | --- |
   | Bildirim yapılandırması yok. | `google-services.json` olmadan derlenmiş; 1. adımdaki dosyayla yeniden derleyin. |
   | Bildirim izni kapalı. | **Bildirimlere izin ver**’e basın veya sistem ayarlarından **Yayın incelemeleri** kanalını açın. |
   | Bildirim kaydı başarısız. | Backend/ağ hatası; düzeltip uygulamayı öne alıp **Yenile** seçin, kayıt tekrar denenir. |
   | Google Play hizmetleri kullanılamıyor. | Cihazda Google Play hizmeti yok; ayrı, desteklenen cihaz kullanın. |

Varsayılan teslim penceresi İstanbul’da **08:00 dahil–22:00 hariç**, tekrar aralığı
**360 dakika**dır. Gece bildirim gelmemesi tek başına hata değildir. Saat
değiştirerek veya worker’ı yeniden başlatarak aralığı aşmaya çalışmayın;
kalıcılık/sessiz saat testleri bölüm 11’dedir.

### 9.2. Boş paket ve hazır inceleme kısayolları

Önce tarayıcıda deneme sunucusunun **Ayarlar → Hatırlatmalar** bölümünü açın:
teslim penceresinin içinde olduğunuzu doğrulayın (varsayılan İstanbul’da
08:00 dahil–22:00 hariç). Pencere dışındaysanız bildirim gelmemesi normaldir;
saati değiştirmeyin, denemeyi pencere içine bırakın.

1. Adı belli boş aktif paketle bölüm 3.2’deki PowerShell komutuyla bir zaman
   oluşturun (`POST /api/settings/manual-publish`; tarayıcıda eşdeğer düğme
   yoktur). Worker her 10 saniyede çalışır; teslim penceresi uygunsa boş paket
   bildirimi birkaç dakika içinde gelmelidir.
2. Bildirimin **Medya yükle** girişini açın. Bölüm 5’teki aynı zamanın devam
   ekranı gelmeli; paket adı eşleşmeli.
3. Bildirimde **Atla** veya **Yeniden zamanla** seçin. Yalnız ilgili form açılmalı;
   **Atlamayı onayla/Yeni zamanı onayla** olmadan durum değişmemeli. Formdan çıkın.
4. Bölüm 5 ile hazır incelemeye ilerleyin. Hazır inceleme bildiriminin ana girişi
   aynı Reel/açıklamayı açmalı; kısayollar yine yalnız form açmalıdır.
5. Yeni, uygun bekleyen bağlamlarla üç durumda tekrarlayın: uygulama önde,
   Home ile arkada ve süreç soğuk başlangıç durumunda. Uygulama öndeyken
   bildirim gelişi Onay kutusunun sunucudan yenilenmesini de tetiklemelidir.
6. Soğuk başlangıç için Android Studio’dan süreci durdurup bildirime dokunabilirsiniz.
   Sistem **Zorla durdur** işlemi FCM teslimatını yeniden açılana kadar
   engelleyebilir; bunu arka plan teslimat testi sanmayın.
7. Kararı başka istemcide çözün; Android’e dönüp başarılı **Yenile** yapın.
   Eski bekleyen bildirim kalkmalı; yükleme bildirimleri bu temizlikten etkilenmemeli.

Bir bildirim karar verildiği veya paket değiştiği için artık geçerli değilse
uygulama bunu açıklamalı; yerine başka incelemeyi otomatik onaylamamalıdır.
Aynı mesajın tekrarında tek bildirim kimliği, cold/warm kısayollar ve eski
oturum reddi bölüm 11’de deterministik olarak da kontrol edilir.

### 9.3. Paylaşım sonuçları

Yalnız açıkça yayın için ayrılmış Instagram hesabı/içerikle gerçek paylaşımı
deneyecekseniz hazır incelemede **Onayla ve paylaş** seçin. Sonuç hemen
doğrulanmayabilir; **Paylaşım sonucu bekleniyor; tekrar göndermeyin.** uyarısında
bekleyip yenileyin.

- Doğrulanmış sonuç bildirimi **Paylaşım doğrulandı** bağlamını açmalı.
- Gerçek bir başarısızlık bildirimi ilgili paketin **Paylaşım başarısız** bağlamını açmalı.
- İki durumda da hedef **Etkinlik** ve bildirimin adlandırdığı pakettir;
  mevcut aktif paketin incelemesi değildir. Tamamlanmış paket detay ekranı beklemeyin.

Başarısızlık üretmek için gerçek hesabın erişimini bozmayın. Yayın onayı,
başarısız sonuç ve sonuç bildirimi yönlendirmesini gerçek hesap olmadan bölüm 11
ile kontrol edebilirsiniz; bunlar gerçek FCM/Instagram teslimat kanıtı değildir.

## 10. Takılırsanız

| Belirti | Kontrol / güvenli sonraki adım |
| --- | --- |
| Onay kutusu görünmüyor | Güncel #36 APK’si olduğundan emin olun; Etkinlik ekranını açın. |
| Boş satırda Atla/Yeniden zamanla yok | Paket adı yoksa veya zaman vadesi gelmemişse normal olabilir; bölüm 3’teki kimlik/durum okumasını kullanın. |
| Aktarım %100, devam çalışmıyor | Sunucuda finalizasyon ve çakışma çözümü tamamlanmalı; “Aktif Pakete eklendi” bekleyin. |
| Render hazır olmuyor | Logo/kurulum, worker, kaydedilmiş montaj ve süre sınırını kontrol edin; yeni manuel zaman oluşturmayın. |
| Önizleme hatası | Ağı/boş depolamayı kontrol edip yenileyin; gerçek dosyaları silmeyin, onay korumasını aşmayın. |
| Push yok, inbox var | Firebase dosyası, Google Play hizmetleri, izin/kanal, kayıt durumu, worker FCM projesi ve saat penceresini kontrol edin. |
| `401` / güncelleme gereksinimi | Doğru sunucuya yeniden eşleştirin / uyumlu uygulamayı kurun; eski oturumla devam etmeyin. |
| Eski bağlantı çalışmıyor | Çözümlenmiş/değişmiş hedef olabilir; Onay kutusundan güncel kaydı açın. |

## 11. Arayüzde güvenle üretilemeyen durumlar — PowerShell

Komutları repo kökünde çalıştırın. Bunlar **hazır testleri** çalıştırır;
Python/SQL kodu yazmanız veya üretim veritabanına doğrudan müdahale etmeniz gerekmez.

### 11.1. Android birim testleri, APK ve cihaz testi derleme

```powershell
$env:JAVA_HOME = 'C:/Program Files/Android/Android Studio/jbr'
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
if ($LASTEXITCODE -ne 0) { throw 'Android doğrulaması başarısız.' }
```

JBR yolu sizde farklıysa değiştirin. Beklenen `BUILD SUCCESSFUL` ve test
raporunda sıfır hata; önceki tam çalıştırmada **161 test** geçti.
`android/app/build/reports/tests/testDebugUnitTest/index.html` dosyasını tarayıcıda açın.

Bu takım sahte HTTP sunucularıyla gerçek paylaşım yapmadan şunları kontrol eder:

- Açık onayın gösterilen sürümle bir kez gönderilmesi; form açmanın karar göndermemesi.
- Eski paket/sürüm, yanlış oturum, gecikmiş yanıt ve belirsiz karar sonucu korumaları.
- Başarısız global yenilemede bütün inceleme kararlarının engellenmesi.
- Paket seçicisi açıkken hedef değişimi ve kuyruk yeniden yüklendiğinde yanlış pakete aktarımın reddi.
- Eski hazırlık incelemesinin yeni hazır devamı ele geçirememesi.
- Foreground bildirim alımıyla inbox yenilemesi, tekrar kayıt ve bildirim uzlaştırma mantığı.
- Worker önce render yapmışsa yeni iş göndermeme; render hatasında yalnız açık tekrar denemesi.

### 11.2. Yerel oynatıcı, diyalog ve bildirim testleri — ayrı cihaz şart

**Bu testler oturumları ve sentetik belgeleri hazırlayıp cihaz durumunu değiştirir.
Kişisel/üretim kurulumunda çalıştırmayın.** Android Studio’da yalnız ayrı sentetik
test emülatörü/cihazı açık olsun; diğer cihazları ayırın. Varsayılan Firebase
yapılandırması olmayan test derlemesini kullanın; operatör dosyalarını silmeyin
veya değiştirerek gerçek kurulumu bozmayın.

```powershell
$env:JAVA_HOME = 'C:/Program Files/Android/Android Studio/jbr'
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
if ($LASTEXITCODE -ne 0) { throw 'Cihaz testleri başarısız; cihaz ve test raporunu kontrol edin.' }
```

Rapor: `android/app/build/reports/androidTests/connected/debug/index.html`.
Bu komut, derlenmiş fakat henüz bu işte çalıştırılmamış cihaz testlerini yürütür:

- `ReviewScreenTest`: açıklama, atlama onayı, kapalı stale/handled onayı, tarih/saat iptali.
- `ReviewPreviewTest`: sentetik MP4 ile yerel oynatıcı ve önizleme dosyası sahipliği.
- `ReviewContinuationTest`: devam başlığıyla yükleme seçicisinin birlikte kalması.
- `ReviewNotificationsTest`: tek bildirim kimliği, ayrı immutable kısayollar,
  cold/warm başlangıç, yeniden oluşturma, sonuç → Etkinlik ve çözümlenmiş
  bildirimleri temizlerken yükleme bildirimlerini koruma.

Cihaz yoksa bu adım yapılamaz; yalnız test APK’si derlenmiş olması cihaz
davranışının doğrulandığı anlamına gelmez. Bu testler gerçek FCM göndermez.

### 11.3. Backend kararları, atomiklik ve hatırlatma kalıcılığı

`uv` ve Docker Desktop hazır olmalı. Testlerin geçici PostgreSQL konteynerleri
oluşturmasına izin verin; `DATABASE_URL`/`TEST_DATABASE_URL` gibi mevcut ortam
değişkenlerini üretim veritabanına yönlendirmeyin. Yerel FFmpeg gerektiren
kontroller araç yoksa atlanabilir; atlananı “geçti” saymayın.

```powershell
uv sync --all-packages --frozen
if ($LASTEXITCODE -ne 0) { throw 'Test bağımlılıkları kurulamadı.' }
uv run --project dojo-core pytest dojo-core/tests/test_empty_occurrence.py dojo-core/tests/test_empty_reminders.py dojo-core/tests/test_fcm.py dojo-core/tests/test_review_resolution.py -v -rs
if ($LASTEXITCODE -ne 0) { throw 'Çekirdek inceleme/bildirim testleri başarısız.' }
uv run --project backend pytest backend/tests/test_focused_review_api.py -v
if ($LASTEXITCODE -ne 0) { throw 'Odaklı inceleme API testleri başarısız.' }
```

Beklenen: hata yok; çıktı varsa skip nedenlerini okuyun. Kontroller yanlış
paket/biten zaman, onaysız atlama, geçmiş tarih, eşzamanlı karar ve geri alma,
aynı paket/zamana devam, 360 dakikalık kalıcı tekrar, sessiz saatler ve gerçek
SDK’ye verilen **data-only review/empty** ile **mixed outcome** payload ayrımını kapsar.
FCM SDK çağrıları sahte gönderimle yakalanır; gerçek telefona teslimat yapılmaz.

### 11.4. Gerçek Instagram olmadan görünür tarayıcı testi

Bu test ayrı Chromium açıp `/api/` çağrılarına sahte yanıt verir. Normal
uygulama sekmesinde yayın onayının güvenli olduğu anlamına gelmez.
PowerShell’i repo kökünde açın; aşağıdaki blok geçici olarak `web` klasörüne geçer:

```powershell
Push-Location web
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Web bağımlılıkları kurulamadı.' }
    npx playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Test tarayıcısı kurulamadı.' }
    $env:PLAYWRIGHT_PORT = '4317'
    npx playwright test e2e/focused-review.spec.ts --project=desktop --workers=1 --headed
    if ($LASTEXITCODE -ne 0) { throw 'Tarayıcı inceleme testi başarısız.' }
} finally {
    Pop-Location
}
```

4317’de başka sunucu çalışmamalı; gerekirse boş port seçin. İlk kurulum
Chromium indirir. Test tarayıcısı kendi tıklamalarını yapar; gerçek hesap veya
eşleştirme kodu istemez. Reel/açıklama, ikinci onay, erteleme, başka cihaz
çatışması ve başarısız yayın sonucunu görmenizi sağlar.

## 12. Deneme sonucunu kaydedin

| Kontrol | Sonuç: geçti / başarısız / denenmedi |
| --- | --- |
| Boş pakette atlama ve erteleme; paket/plan korunuyor | |
| Yükleme → render → aynı `occurrence_id` ve paket | |
| Android ve web’de aynı final Reel/açıklama | |
| Başka istemcide çözülmüş ve eski sürüm koruması | |
| Push kapalıyken Onay kutusu; ağ kesintisinde kapalı kararlar | |
| İzin, token kaydı ve yeniden kayıt | |
| Gerçek foreground/background/cold-start FCM ve kısayollar | |
| Yenilemede eski bildirimin kalkması | |
| Paylaşım sonucu → bildirimin paketine ait Etkinlik | |
| Yerel oynatıcı/diyalog, erişilebilirlik ve cihaz testleri | |

APK sürümü, cihaz/API seviyesi, tarih/saat ve kimlikleri not edin; medya,
oturum/token veya hizmet hesabı içeren ekran görüntülerini paylaşmayın.
Gerçek cihaz/FCM yapılmadıysa bunu ayrı yazın; birim testini canlı kabul kanıtı
olarak göstermeyin. Bu rehber push, merge, dağıtım veya issue kapatma yapmaz.
