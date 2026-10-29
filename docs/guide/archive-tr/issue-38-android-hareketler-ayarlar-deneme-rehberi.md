# Android Hareketler ve Ayarlar: değişiklik özeti ve deneme rehberi (#38)

Bu rehber `1e7b03d` commit'indeki değişiklikleri anlatır. Öncelik Android
uygulamasıdır; tarayıcı, aynı sunucudaki kayıtları karşılaştırmak ve ikinci
istemciden değişiklik yapmak için kullanılır. Arayüzde yapılamayan hazırlık ve
kontroller için yalnız PowerShell komutları vardır; Python veya SQL kodu yoktur.

> **Ayrı test sunucusu ve test cihazı kullanın.** Plan, marka ayarları, hatırlatma
> politikası, Instagram bağlantısı ve rıza bütün eşleştirilmiş istemciler için
> ortaktır. Worker kapalı, düzenli yayın planı kapalı olsun. Yayın onayı vermeyin;
> gerçek öğrenci medyası kullanmayın. Instagram denemesinde ayrı test hesabı kullanın.
> Token, eşleştirme kodu veya oturum bilgilerini paylaşmayın.
>
> Geliştirme sırasında 247 Android birim testi geçti; APK/test APK'sı ve lint
> derlemeleri başarılıydı. Bağlı cihaz veya emülatör olmadığı için yerel UI testleri
> çalıştırılamadı. Aşağıdaki beklenen sonuçlar **sizin doğrulamanız gereken ölçütlerdir**,
> cihazda önceden denenmiş sonuçlar değildir. Ayrıntı:
> [doğrulama kaydı](../verification/issue-38-android-settings.md).

## 1. Neler değişti?

| Değişiklik | Görünen sonuç |
| --- | --- |
| Ayarlar artık yalnız kuruluma yönlendirmiyor | Plan, hatırlatma, logo, açıklama, kartlar, Instagram ve rıza aynı sayfadan bulunabiliyor |
| Mevcut kurulum düzenleyicileri yeniden kullanılıyor | Tarih/saat seçimi, görsel yükleme ve bağlantı davranışları kurulumla aynı |
| Hatırlatma politikası Android'den kaydediliyor | Pozitif dakika aralığı ve bildirim başlangıç/bitiş saatleri sunucuda saklanıyor |
| Gece yarısını geçen bildirim penceresi destekleniyor | Örneğin `21:00–09:00` geçerli; aynı başlangıç/bitiş geçersiz |
| Hatırlatma saatlerinin hassasiyeti korunuyor | Yalnız dakika aralığını değiştirince sunucudaki saniyeli başlangıç/bitiş silinmiyor |
| Ayarlar açılışta ve yenilemede yükleniyor | Sihirbazı açmadan güncel değerler geliyor; geri dönülen Ayarlar ekranı da yükleniyor |
| Kaydedilmemiş alanlar korunuyor | Başka istemcide yapılan değişiklik yenilemede taslağınızı ezmiyor; açık yeniden yükleme seçeneği var |
| Instagram durumu ve yeniden bağlantı | Hesap/durum gösteriliyor; token ve dış tarayıcı yetkilendirmesi Ayarlar'dan erişilebilir |
| Rıza Ayarlar'da salt okunur | Metin, sürüm ve kabul durumu görülebiliyor; kabul işlemi kurulumdan yapılıyor |
| Mevcut Hareketler akışı korunuyor | Son 50 olay, zaman/aktör, yenileme ve kayıtlı çevrimdışı geçmiş; Onay kutusu da yerinde |

**Bu işin eklemediği şeyler:** yeni backend uç noktası, yeni yayın akışı,
çevrimdışı ayar gönderme kuyruğu veya yeni bildirim altyapısı. Ayarı kaydetmek
tek başına bildirimin telefona ulaştığını kanıtlamaz; FCM/worker denemeleri ayrı
[bildirim rehberindedir](issue-36-android-inceleme-bildirim-deneme-rehberi.md).

## 2. Hazırlık

### 2.1. Sunucu ve istemciler

Çalışan ayrı test ortamınız varsa onu kullanın. Yoksa
[çevrimdışı deneme rehberinin 3 ve 4. bölümleri](issue-37-android-cevrimdisi-deneme-rehberi.md#3-çalışma-dizini-ve-test-sunucusu)
test backend'i, tarayıcı ve Android eşleştirmesini PowerShell ile anlatır.
Eski #32 worktree'sini değil, bu değişikliklerin bulunduğu güncel repo kopyasını kullanın.

- Android 10/API 29+ cihaz veya emülatör gerekir.
- Tarayıcı ve Android **aynı test backend'ine**, ayrı tek kullanımlık kodlarla eşleşmeli.
- Tarayıcı için örnek adres `http://localhost:3000`; API `http://localhost:8000`.
- Aynı bilgisayardaki Android Studio emülatörü için API origin'i
  `http://10.0.2.2:8000`; uzak ortamda kendi HTTPS adresiniz.
- HTTP yalnız debug/yerel test içindir. Origin'e `/api` eklemeyin.
- Mevcut APK sürüm kodu `5`; sunucunun minimum sürümü bu sürümü kabul etmeli.
- İlk eşleştirmede kurulum açılırsa Android'de **Şimdilik kontrol paneline dön**
  ile çıkın. Ayarlar'ı denemek için tüm kurulumu tamamlamak zorunda değilsiniz.

**Dikkat:** Docker Compose proje adı tek başına veri izolasyonu sağlamaz;
`ops/db-data` ve `ops/media-data` repo içindeki ortak bind dizinleridir.
Üretim verisi içeren dizinleri kullanmayın veya temizlemeyin.

PowerShell'i repo kökünde açın:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
$Api = 'http://localhost:8000'
$Web = 'http://localhost:3000'
git log -1 --oneline
Invoke-RestMethod -Uri "$Api/health"
Invoke-RestMethod -Uri "$Api/api/compat"
Start-Process "$Web/#/settings"
```

Repo/adresleri kendi test ortamınıza göre değiştirin. Son commit farklı olabilir;
önemli olan `1e7b03d` değişikliklerinin mevcut olmasıdır.

### 2.2. Güncel Android APK'sını yükleyin

Android Studio'da repo içindeki **android** klasörünü açıp **app → Run**
kullanabilirsiniz. PowerShell alternatifi:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$Sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_HOME = $Sdk
$Adb = Join-Path $Sdk 'platform-tools\adb.exe'
$App = 'com.dojo.aisomedo'
.\android\gradlew.bat -p android :app:assembleDebug --console=plain
if ($LASTEXITCODE -ne 0) { throw 'APK derlenemedi.' }
& $Adb devices -l
$Serial = Read-Host 'Listede device durumundaki ayrı TEST cihazının seri numarası'
& $Adb -s $Serial install -r 'android/app/build/outputs/apk/debug/app-debug.apk'
if ($LASTEXITCODE -ne 0) { throw 'APK kurulamadı.' }
& $Adb -s $Serial shell am start -n "$App/.MainActivity"
```

JDK/SDK yolları farklıysa düzeltin. `install -r` mevcut verileri korur.
İmza uyuşmazlığında gerçek uygulamayı kaldırmayın; ayrı test emülatörü kullanın.

## 3. Ayarlar'ın doğrudan açılması — Android

1. Alt gezinmeden **Ayarlar**'a geçin; tablette yan gezinmeyi kullanın.
2. Yükleme bitene kadar bekleyin. Gerekirse üstteki **Yenile**'ye basın.
3. Aşağı kaydırarak şu bölümleri bulun:
   - **Dojo Yayın Planı**
   - **İnceleme hatırlatmaları**
   - **Dojo logosu**
   - **Açıklama şablonu**
   - **Giriş ve çıkış kartları**
   - **Instagram**
   - **Medya rızası**
4. **Kurulumu aç**'a basmadan bu alanlara erişebildiğinizi kontrol edin.
5. Başka sekmeye geçip Ayarlar'a dönün.

**Beklenen:** Ayarlar sihirbaza dönüşmez. Sunucu, cihaz kimliği ve sürüm bilgileri
korunur. Güncel okunamayan bölümlerde salt okunur uyarı bulunur; veri alınmadan
veya çevrimdışıyken kayıt yapılamaz.

## 4. Plan ve marka ayarlarının kalıcılığı — Android + tarayıcı

Önce test sunucusundaki mevcut değerleri not alın. Görsel değişiklikleri denemek
için eski görsellerin kopyalarını da saklayın; yalnız önizleme ekran görüntüsü
eski görseli yeniden yüklemek için yeterli değildir.

### 4.1. Plan

1. Android **Ayarlar → Dojo Yayın Planı**'nda gelecekte bir **pazartesi** ve
   örneğin `18:30` seçin.
2. **Düzenli yayın planı açık** anahtarını kapalı bırakın; **Kaydet**'e basın.
3. Tarayıcı **Ayarlar** (`#/settings`) sayfasını yenileyin. Aynı başlangıç
   tarihi/saati ve kapalı planı kontrol edin.
4. Android'den çıkıp uygulamayı yeniden açın, Ayarlar'a gidin ve yüklemeyi bekleyin.
5. İsteğe bağlı: salı günü seçip kaydetmeyi deneyin; sonra yeniden pazartesi seçin.

**Beklenen:** Geçerli pazartesi planı kalıcıdır; iki haftada bir İstanbul saatine
göre çalışacak kuralı tanımlar. Kapalı plan da yapılandırılmış sayılır. Salı
başlangıcı reddedilir; önceki sunucu kaydı değişmez. Bu deneme planı etkinleştirmez.

### 4.2. Açıklama, logo ve kartlar

1. **Açıklama şablonu**'na `Issue38 deneme #dojo` yazıp **Kaydet**'e basın.
2. **Dojo logosu → Görsel seç ve kaydet** ile kişisel veri içermeyen PNG/JPEG seçin.
   En fazla 10 MiB; sunucu içerik ve boyutları ayrıca doğrular.
3. **Giriş ve çıkış kartları**'ndan test görselleri seçin; örneğin `3` saniye
   süre kullanın. Görsel seçimi yükleyip kaydeder; mevcut süre değişikliğinde
   **Kart sürelerini kaydet**'e basın.
4. Tarayıcı Ayarlar sayfasını yenileyip açıklama, görseller ve süreleri karşılaştırın.
5. Android'i yeniden açıp Ayarlar'da aynı değerleri kontrol edin.
6. İsteğe bağlı: yalnız test kartında **Bu kartı ve süresini kaldır**'ı deneyin.

**Beklenen:** Sunucu değerleri iki istemcide aynıdır; kart kaldırıldığında kart ve
süresi birlikte temizlenir. Ayarlar'da sihirbaza özel **Kartları değiştirmeden
devam et** düğmesi bulunmaz. Ayar değişikliği paylaşım onayı veya otomatik yayın değildir.

## 5. Hatırlatma kaydı ve geçersiz giriş — Android + tarayıcı

1. Android **İnceleme hatırlatmaları**'nda mevcut değerleri not alın.
2. Aralık `90`, bildirim başlangıcı `09:00`, bitişi `21:00` seçin;
   **Hatırlatmaları kaydet**'e basın.
3. Tarayıcı **Ayarlar → Hatırlatmalar**'ı yenileyin. Aynı değerleri doğrulayın.
4. Android'i yeniden açıp değerlerin sunucudan geldiğini kontrol edin.
5. Başlangıcı `21:00`, bitişi `09:00` yapıp tekrar kaydedin.
6. Sırayla aralığı `0`, ardından boş yapıp kaydetmeyi deneyin. Sonra `90`'a dönün.
7. Başlangıç ve bitişi aynı yapıp kaydetmeyi deneyin.
8. Tarayıcıyı yenileyin; son geçerli kayıtla karşılaştırın.

**Beklenen:** Gece yarısını geçen pencere geçerlidir. Aralık pozitif tam sayı,
başlangıç/bitiş farklı olmalıdır. Geçersiz denemeler hata gösterir, sunucudaki
geçerli kaydı değiştirmez. İki istemci de `Europe/Istanbul` kullanır.

Bu adım yalnız politikanın kalıcılığını doğrular. Gerçek bildirim testi için
bekleyen Yayın İncelemesi, çalışan worker ve yapılandırılmış bildirim servisi gerekir.

## 6. Başka istemciden değişiklik ve taslak koruması — Android + tarayıcı

1. Android'de hatırlatma aralığını `91` yapın; **kaydetmeyin**.
2. Tarayıcıda aralığı `120` yapıp kaydedin. İsterseniz başlangıcı `10:00` yapın.
3. Android Ayarlar'daki üst **Yenile** düğmesine basıp yüklemenin bitmesini bekleyin.
4. Hatırlatma bölümünü kontrol edin.
5. Bu bölümdeki **Sunucu ayarlarını yeniden yükle**'ye basın.
6. Aynı denemeyi açıklama şablonunda da yapabilirsiniz: Android'de kaydedilmemiş
   metin tutarken tarayıcıda farklı bir metin kaydedin, Android'i yenileyin.

**Beklenen:** Android'de düzenlediğiniz `91` taslağı `120` ile ezilmez; sunucu
ayarlarının değiştiği uyarısı görünür. Düzenlemediğiniz saat alanı güncellenebilir.
Açık yeniden yükleme seçeneği yerel taslağı bırakıp sunucudaki `120` değerini getirir.
Yalnız üstteki **Yenile**, taslaktan vazgeçme anlamına gelmez.

**Sınır:** Bu koruma otomatik çakışma birleştirme değildir. Değişmiş ayarların
üzerine eski taslağı kaydetmek başka istemcinin değerini değiştirebilir. Uyarı
geldiğinde önce sunucu değerlerini değerlendirin. Sistem tarafından ekran
yeniden oluşturulması ve zorla durdurma aynı şey değildir; kaydedilmemiş taslağın
her süreç ölümünde geri gelmesi garanti edilmez.

## 7. Instagram durumu ve yeniden bağlantı — Android

1. **Ayarlar → Instagram** bölümüne gidin. Hesap adını ve durumunu not alın.
   Hesap yoksa **Bağlı hesap yok**, yapılandırmaya göre bağlantı/durum uyarısı normaldir.
2. Gerçek sır olmayan `deneme-gecersiz-token` yazıp **Token ile bağlan**'a basın.
3. Alanın maskeli olduğunu ve gönderimden sonra temizlendiğini kontrol edin.
4. Ayrı test hesabı ve çalışan Meta yapılandırması varsa **Instagram ile
   yetkilendir**'e basın. Dış tarayıcıda işlemi tamamlayıp uygulamaya dönün.
5. Gerekirse **Yetkilendirme sonucunu kontrol et**'e basın. Birden fazla aday
   geldiyse istediğiniz test hesabını açıkça seçin.
6. Ayarlar'ı yenileyin; tarayıcı Ayarlar sayfasındaki hesap/durumla karşılaştırın.

**Beklenen:** Geçersiz token başarılı bağlantı sayılmaz; önceki doğrulanmış hesap
korunur. Yetkilendirme hesabı sessizce seçmez. Başarıda yeni hesap/durum gösterilir;
token Ayarlar'da yeniden gösterilmez. Ayarlar'da kalırsınız, sihirbaz ilerlemez.

Geçerli token edinme ön koşulları:
[Instagram token bağlantısı rehberi](instagram-token-baglantisi-rehberi.md).
Meta yapılandırması veya gerçek sağlayıcı yoksa servis/yetkilendirme hatası
görülebilir; canlı yeniden bağlantıyı **denenmedi** işaretleyin. Düğmenin tarayıcı
açması tek başına başarılı bağlantı kanıtı değildir. Bu adımda yayın onayı vermeyin.

## 8. Rızanın salt okunur gösterimi — Android + tarayıcı

1. Android **Ayarlar → Medya rızası**'na gidin.
2. Metni ve sürümü kontrol edin. Kabul edilmişse kurulum genelindeki kabul zamanı;
   edilmemişse henüz kabul kaydı olmadığı açıklaması görünmelidir.
3. Ayarlar'da kabul onay kutusu veya **Bu sürümü kabul et** düğmesi olmadığını doğrulayın.
4. Aynı sunucunun tarayıcı Ayarlar sayfasıyla karşılaştırın.
5. Yalnız test politikası için kabul akışını denemek istiyorsanız Android'de
   **Kurulumu aç → Medya rızası**'na geçin, metni okuyun, açık kabul verin.
6. Kurulumdan çıkıp Ayarlar'ı yenileyin; kabul durumunu tekrar kontrol edin.

**Beklenen:** Kabul kurulumdan yapılır ve tüm istemciler için aynı sürüme bağlıdır.
Metin tanımlı değilse eksik politika uyarısı görünür; uygulama kendi metnini üretmez.
Kabul kaydını bu rehberle geri alma adımı yoktur; kabul testini yalnız ayrı test
kurulumunda yapın. Mevcut kabulü kaldırmak için veritabanı düzenlemeyin.

## 9. Hareketler ve çevrimdışı davranış — Android

1. Geçerli bir açıklama veya hatırlatma değişikliği kaydedin.
2. **Hareketler → Yenile**'ye basın. Onay kutusunun altında yakın geçmişi bulun.
3. İşlem adı, zaman, aktör ve **Son alınan bilgi** zamanını kontrol edin.
   Teknik olay adlarının görünmesi normaldir.
4. Tarayıcı **Etkinlik** (`#/activity`) ile yeni olayları karşılaştırın.
   Android son 50 olayı ister; iki istemcinin satır sayıları aynı olmak zorunda değildir.
5. Android Ayarlar'da bir taslak bırakın; kaydetmeyin. Wi-Fi ve mobil veriyi
   kapatın; varsa Ethernet/VPN bağlantısını da kesin.
6. Çevrimdışı uyarısını bekleyin. Ayarlar'da kayıt, tarih/saat seçimi, görsel
   seçimi, token ve Instagram yetkilendirmesinin kullanılamadığını kontrol edin.
7. Hareketler'e geçin: önceden alınan geçmiş ve zamanı okunabilir olmalıdır.
8. Ağı açın, Ayarlar'a dönün ve **Yenile**'ye basın. Güncel veri alınana kadar
   kayıt işlemlerinin etkinleşmediğini; taslağın otomatik gönderilmediğini kontrol edin.

**Beklenen:** Çevrimdışı işlemler sunucuya yazmaz veya daha sonra gönderilmek üzere
kuyruğa alınmaz. Bu oturumda yüklenmiş Ayarlar bilgileri okunabilir; uygulama
çevrimdışı yeniden başlatıldığında tüm Ayarlar değerlerinin kalıcı önbellekten
geleceği garanti edilmez. Hareketler'in kayıtlı geçmişi ayrı çevrimdışı önbellektir.

Tarayıcı geliştirici araçlarındaki **Offline**, Android'in bağlantısını kesmez.
USB `adb reverse` tüneli de erişimi sürdürebilir. Gerçek ağ kesintisini cihazdan yapın.
Hareket kaydı yoksa boş geçmiş metni; hiç alınmamışsa kayıtlı bilgi olmadığı
açıklaması beklenir. Eşleştirme/ayar işlemleri olay ürettiğinden boş geçmişi
canlı veriyi silerek oluşturmayın; gerekirse 11. bölümdeki otomatik UI testini kullanın.

## 10. Saniyeli saatlerin korunması — PowerShell + Android

Android saat seçicisi saniye girişi sunmadığından, bu uç durumu API üzerinden
hazırlayın. **Yalnız test sunucusu:** örnek pencere dar bir bildirim aralığıdır.
Komutlar önceki hatırlatma politikasını saklar ve `finally` ile geri yükler.
Konsolu zorla kapatmayın; aksi halde geri yükleme çalışmayabilir.

### 10.1. Ayrı test istemcisiyle API'ye erişin

Yeni eşleştirme kodu üretin. `$ComposeArgs` değerini kendi **test** projenize göre
ayarlayın; farklı ortam için bu yerel Docker komutunu kullanmayın:

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-issue38-deneme', '-f', 'ops/docker-compose.yml')
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
if ($LASTEXITCODE -ne 0) { throw 'Eşleştirme kodu üretilemedi.' }
$SecureCode = Read-Host 'Yeni test eşleştirme kodu' -AsSecureString
$Code = [System.Net.NetworkCredential]::new('', $SecureCode).Password
$Body = @{ code = $Code; kind = 'device'; name = 'Issue38 PowerShell Deneme' } | ConvertTo-Json
$Pair = Invoke-RestMethod -Method Post -Uri "$Api/api/pairing/validate" -ContentType 'application/json' -Body $Body
$Headers = @{ Authorization = "Bearer $($Pair.token)"; 'X-Android-Version-Code' = '5' }
$Code = $null
$SecureCode = $null
$Body = $null
$Pair = $null
```

Yanıtı veya `$Headers` değişkenini yazdırmayın. Bu oturum Android'in saklı tokenını
okumaz; ayrı bir test cihazı kaydı oluşturur. Kod tek kullanımlıktır.

### 10.2. Dar pencereyi hazırlayın, Android'de yalnız aralığı değiştirin

```powershell
$Before = Invoke-RestMethod -Uri "$Api/api/settings/reminders" -Headers $Headers
try {
    $SecondsPolicy = @{
        interval_minutes = 60
        delivery_start = '09:00:10'
        delivery_end = '09:00:50'
        timezone = 'Europe/Istanbul'
    } | ConvertTo-Json
    Invoke-RestMethod -Method Put -Uri "$Api/api/settings/reminders" -Headers $Headers -ContentType 'application/json' -Body $SecondsPolicy | Out-Null
    Read-Host 'Android Ayarlar → Yenile. Gerekirse bu bölümün Sunucu ayarlarını yeniden yükle düğmesiyle eski taslağı bırakın. Yalnız aralığı 90 yapıp kaydedin; saat düğmelerine dokunmayın. Bitince Enter'
    $After = Invoke-RestMethod -Uri "$Api/api/settings/reminders" -Headers $Headers
    $After | Select-Object interval_minutes, delivery_start, delivery_end, timezone
    if ($After.interval_minutes -ne 90 -or $After.delivery_start -ne '09:00:10' -or $After.delivery_end -ne '09:00:50') {
        throw 'Aralık kaydı veya saniyeli saatlerin korunması beklenen sonucu vermedi.'
    }
    'Kontrol başarılı: saniyeli pencere değişmedi.'
}
finally {
    $Restore = $Before | Select-Object interval_minutes, delivery_start, delivery_end, timezone | ConvertTo-Json
    Invoke-RestMethod -Method Put -Uri "$Api/api/settings/reminders" -Headers $Headers -ContentType 'application/json' -Body $Restore | Out-Null
}
$Headers = $null
```

**Beklenen:** `90`, `09:00:10`, `09:00:50`, `Europe/Istanbul`. Başlangıç ve bitiş
aynı dakikada olsa da farklı saniyeler geçerlidir. Sonunda Android'i yenileyip
önceki politikanın geri geldiğini doğrulayın. Saat seçicisini kullanırsanız
seçtiğiniz alan dakika hassasiyetinde değiştirilir; bu adım o alanı değiştirmiyor.

## 11. Arayüzden üretilemeyen hata/yeniden oluşturma kontrolleri — PowerShell

Sunucu reddi, tam zamanlamalı ağ kaybı ve model yeniden oluşturulmasını elle
üretmek yerine mevcut otomatik testleri çalıştırın. Bunlar Python/SQL kodu yazmadan
Gradle ile gerçek model, HTTP taşıması ve test oturumunu çalıştırır:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
.\android\gradlew.bat -p android :app:testDebugUnitTest --tests 'com.dojo.aisomedo.AppViewModelTest.settingsLoadsConfigurationWithoutOpeningOnboardingAndRestoresDestination' --tests 'com.dojo.aisomedo.AppViewModelTest.reminder*' --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Hedefli Ayarlar testleri başarısız.' }
```

Beklenen: Ayarlar'a doğrudan geçiş, yeniden oluşturma sonrası yükleme/taslak,
geçerli kayıt, geçersiz giriş, reddedilen kayıtta taslak, uzak değişiklik ve
saniyeli saat kontrolleri geçer. Testler geçici sunucu kullanır, canlı test
backend'inizin verilerini değiştirmez.

Bağlı cihaz/emülatörde Ayarlar, geçmiş boş/eksik durumları ve diğer mevcut UI
kontrolleri için:

```powershell
.\android\gradlew.bat -p android :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.DojoAppTest' --console=plain
if ($LASTEXITCODE -ne 0) { throw 'UI testleri tamamlanmadı; çıktıyı kontrol edin.' }
```

`No connected devices!` bir ürün testi sonucu değildir; cihaz testinin
çalışamadığını gösterir. PowerShell'de noktalı Gradle parametresini tırnak içinde tutun.
Bu testler debug uygulamasını test cihazına kurabilir; kişisel cihaz yerine ayrı
emülatör kullanın. Gerçek Meta hesabında OAuth başarısını kanıtlamazlar.

Tam Android kontrolü:

```powershell
.\android\gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Android kontrolü başarısız.' }
```

Beklenen `BUILD SUCCESSFUL`. Lint uyarıları bulunabilir; test APK'sının derlenmesi
cihaz testlerinin çalıştığı anlamına gelmez.

## 12. Son kontrol ve temizlik

- [ ] Ayarlar sihirbaz açılmadan tüm bölümleri gösterdi.
- [ ] Plan, açıklama, logo/kart ve hatırlatma kayıtları yeniden açılışta kaldı.
- [ ] Tarayıcı ve Android aynı sunucu değerlerini gösterdi.
- [ ] Geçersiz hatırlatma girişleri kayıt yapmadı; gece penceresi kaydedildi.
- [ ] Uzak değişiklik taslağı ezmedi; açık yeniden yükleme sunucu değerini getirdi.
- [ ] Instagram durumu görüldü; gerçek yeniden bağlantı denendiyse sonucu kaydedildi.
- [ ] Rıza metni/sürümü/kabul durumu salt okunur gösterildi.
- [ ] Hareketler yenilendi; çevrimdışı geçmiş okunabildi, Ayarlar yazması engellendi.
- [ ] Saniyeli pencere yalnız hatırlatma aralığı değiştirildiğinde korundu.
- [ ] Telefon/tablet, koyu tema ve büyük yazı boyutunda alanlar/tuşlar erişilebilir kaldı.

Test sonunda not aldığınız plan/hatırlatma/açıklama değerlerini arayüzden geri
yükleyin; gerekiyorsa sakladığınız eski görselleri tekrar seçin. Planı kapalı
tutun. Rıza kabulü ve hesap bağlantısı için otomatik geri alma vaat edilmez;
bu yüzden bunları ayrı test ortamında deneyin. **Sunucuyu değiştir** eşleştirmeyi
kaldırır, sunucudaki ortak ayarları geri almaz.

Her maddeye **geçti / kaldı / denenmedi** yazın. Özellikle gerçek Instagram,
bildirim teslimi ve cihaz UI davranışını host testleriyle doğrulanmış saymayın.
