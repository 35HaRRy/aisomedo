# Android çevrimdışı mod: değişiklik özeti ve adım adım deneme rehberi (#37)

Bu rehber #37 entegrasyonunu ve inceleme sonrası düzeltmeleri anlatır.
Öncelik **Android uygulaması**; **tarayıcı** ortak sunucu verisini karşılaştırmak
için kullanılır. Arayüzden yapılamayan hazırlık, gözlem ve hata senaryoları için
**PowerShell** komutları verilmiştir. Python veya SQL kodu çalıştırmanız gerekmez.

> **Yalnız ayrı deneme ortamı ve deneme cihazı kullanın.** Gerçek öğrenci medyası,
> üretim eşleştirmesi veya canlı Instagram hesabı kullanmayın. Yayın onayı vermeyin;
> düzenli yayın planını kapalı tutun. Sunucu durdurma, sürüm değiştirme ve cihaz
> iptali adımları bu test ortamındaki diğer istemcileri de etkiler.
>
> Son uygulama doğrulamasında **216 Android birim testi ve 210 backend testi**
> geçti; debug APK, test APK'sı ve lint başarılıydı. Bağlı cihaz/emülatör olmadığı
> için cihaz testleri çalıştırılamadı. Aşağıdaki **beklenen sonuçlar**, elle
> doğrulamanız gereken ölçütlerdir; cihazda önceden doğrulanmış sonuç değildir.
> Ayrıntı: [doğrulama kaydı](../verification/issue-37-android-offline.md).

## 1. Neler değişti?

| Değişiklik | Kullanıcıya görünen sonuç |
| --- | --- |
| Eksik #37 uygulaması mevcut dala bağlandı | Önbellek ve ağ gözlemcisi artık gerçek uygulama akışında kullanılıyor |
| Kalıcı Paket/Hareketler önbelleği | Bağlantı kesilince ve uygulama çevrimdışı yeniden açılınca son bilgiler okunabiliyor |
| Son alınan bilgi zamanı | Eski verinin hangi zamana ait olduğu görülebiliyor |
| Gerçek hareket geçmişi | Son 50 olay; işlem, zaman ve aktör. #36 inceleme gelen kutusu da korunuyor |
| Ortak salt okunur işlem sınırı | Ayarlar, yerel taslak düzenleme, medya değişiklikleri, yeni yükleme ve inceleme kararları çevrimdışı engelleniyor |
| Yeniden bağlantıda güncellik kontrolü | Ağın gelmesi tek başına yazma yetkisi vermiyor; sunucu/kimlik ve ilgili veri yeniden doğrulanıyor |
| Kalıcı aktarım ilerlemesi | Bilinen yükleme kimliği, dosya kimliği ve onaylanan parçalar korunuyor; yalnız eksik parçalar gönderiliyor |
| Yerel Duraklat/Devam et | Uygun mevcut aktarımda çevrimdışı çalışıyor; kullanıcı duraklatması kendiliğinden kaldırılmıyor |
| Belirsiz ilk yükleme isteği koruması | Sunucu kimliği alınmadan bağlantı koparsa oluşturma isteği otomatik tekrarlanmıyor; açık çevrimiçi tekrar deneme gerekiyor |
| Kalıcı güncelleme engeli | Uyumsuz sürüm veya 426 yanıtı, çevrimdışı yeniden açılışla aşılamıyor |
| Arka plan FCM entegrasyonu | Token kaydı çevrimdışı/engellenmiş sürümde gönderilmiyor; alınan 401/426 görünür ekran olmadan ortak oturumu durduruyor |
| Kimlik ve yarış korumaları | Eski sunucu/eşleştirmenin gecikmiş yanıtı yeni oturumu değiştiremiyor; başlangıç ağ kaybı eski bağlı durumunu canlandıramıyor |
| İnceleme önizlemesi ve açık tarih/saat diyaloğu | Yeniden bağlantıda eski önizleme onay yetkisi vermiyor; bağlantı gidince açık diyalog taslağı değiştiremiyor |

**Sınırlar:** Önbellek en fazla 4 MiB metadata tutar; fotoğraf/video, inceleme
videosu, token, komut kuyruğu veya taslak yedeği değildir. Taslakların bağlantı
kesilmesinde korunması, her taslağın zorla durdurma sonrasında geri geleceği
anlamına gelmez. Bu iş web istemcisine Android'in çevrimdışı özelliklerini eklemez.

## 2. Nerede denemelisiniz?

| Kontrol | Kullanılacak yer |
| --- | --- |
| Çevrimdışı paket/geçmiş, yazma engeli, önizleme, Duraklat/Devam et | Android |
| Sunucudaki paket/ayar/geçmiş ile karşılaştırma | Tarayıcı |
| APK kurma, süreç durdurma, kayıtlı yükleme kimliğini okuma | PowerShell + adb; yalnız debug test APK'sı |
| Sunucu erişimini kesme ve minimum sürümü değiştirme | PowerShell; yalnız test backend'i |
| Tek uç nokta hatası, gecikmiş eski yanıt, disk yazma hatası, tam zamanlamalı FCM/ağ yarışı | PowerShell'den hedefli otomatik testler |

**Tarayıcı geliştirici araçlarındaki Network → Offline, yalnız o tarayıcıyı
etkiler. Android testinde telefonun/emülatörün ağını kapatın.** API 33 ve API 34+
denemelerini ayrı yapın: ilki WorkManager, ikincisi UIDT arka plan yolunu kullanır.
API 29 ve telefon/tablet görünümü ayrıca kontrol edilmelidir.

## 3. Çalışma dizini ve test sunucusu

### 3.1. Mevcut test ortamınız varsa

PowerShell'i değişikliklerin bulunduğu **repo kökünde** açın. Eski, silinmiş
issue worktree'lerini kullanmayın. Bu bilgisayarın örnek yolu:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
git status --short
$Repo = (Get-Location).Path
$Api = 'http://localhost:8000'
$Web = 'http://localhost:3000'
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-issue37-deneme', '-f', 'ops/docker-compose.yml')
```

Mevcut **ayrı test** kurulumunun proje adı farklıysa aynı adı kullanın.
Üretim proje adını buraya yazmayın. Her yeni PowerShell penceresinde ilgili
değişkenleri yeniden tanımlayın. Uzak test ortamında `$Api`/`$Web` adreslerini
değiştirin; yerel Compose durdurma/yeniden oluşturma komutlarını kullanmayın.

### 3.2. Yeni yerel test ortamı gerekiyorsa

Gerekenler: Docker Desktop Linux motoru, Node.js/npm, Android Studio, SDK 35 ve
ayrı Android 10/API 29+ test cihazı/emülatörü. `8000`, `5434`, `3000` portları boş
olmalıdır. Dolu port için gerçek ortamı durdurmayın.

**Compose proje adı veri izolasyonu sağlamaz:** `ops/db-data` ve `ops/media-data`
repo dizinine bağlıdır. İlk kurulumda aşağıdaki kontrol hata verirse dizinleri
silmeyin; mevcut ortamınızı tanımlayın veya ayrı temiz test kopyası kullanın.
Bu oturumun değişiklikleri henüz commit edilmediyse sıradan yeni clone bunları içermez.

```powershell
foreach ($Path in 'ops/db-data', 'ops/media-data') {
    if ((Test-Path -LiteralPath $Path) -and
        (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1)) {
        throw "$Path dolu. İlk kurulum için ayrı temiz test dizini kullanın."
    }
}
if (-not (Test-Path -LiteralPath ops/.env)) {
    Copy-Item -LiteralPath ops/.env.example -Destination ops/.env
}
notepad ops/.env
```

Not Defteri'nde yalnız test ortamı için:

- `POSTGRES_PASSWORD` ve `SIGNED_URL_SECRET`: denemeye özel, güçlü değerler yazın.
  Yerel parola için harf/rakam seçmek bağlantı URL'sindeki özel karakter sorununu önler.
- `COOKIE_SECURE=false`, `PUBLIC_BASE_URL=http://localhost:3000`,
  `PUBLIC_HTTPS_ORIGIN=http://localhost:3000` kullanın. Üretimde HTTPS/secure cookie gerekir.
- Mevcut APK `versionCode=5` için `ANDROID_CURRENT_VERSION_CODE=5` ve
  `ANDROID_MIN_VERSION_CODE=4` kullanın. Backend N/N−1 kuralı nedeniyle
  `current=5, minimum=1` geçerli değildir.
- `ANDROID_UPDATE_URL`: varsa gerçek imzalı test sürümünün HTTPS adresi; yoksa boş bırakın.
- Gerçek Instagram/Meta kimlik bilgisi girmeyin.

Boş ilk kurulumda gerekli şifreleme anahtarını PowerShell ile oluşturabilirsiniz.
Bu komut **yalnız boş satırı doldurur**; mevcut anahtarı değiştirmez veya yazdırmaz:

```powershell
$EnvPath = (Resolve-Path -LiteralPath ops/.env).Path
$Content = [System.IO.File]::ReadAllText($EnvPath)
if ($Content -match '(?m)^META_TOKEN_ENCRYPTION_KEY=[ \t]*\r?$') {
    $Bytes = New-Object byte[] 32
    $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Rng.GetBytes($Bytes) } finally { $Rng.Dispose() }
    $Key = [Convert]::ToBase64String($Bytes).Replace('+', '-').Replace('/', '_')
    $Content = [regex]::Replace($Content, '(?m)^META_TOKEN_ENCRYPTION_KEY=[ \t]*\r?$', "META_TOKEN_ENCRYPTION_KEY=$Key")
    [System.IO.File]::WriteAllText($EnvPath, $Content, (New-Object System.Text.UTF8Encoding($false)))
}
$Key = $null
$Bytes = $null
$Content = $null
```

Kaydedin; yalnız veritabanını ve backend'i başlatın:

```powershell
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose @ComposeArgs up -d --build db backend
if ($LASTEXITCODE -ne 0) { throw 'Test backend başlatılamadı.' }
Invoke-RestMethod -Uri "$Api/health"
Invoke-RestMethod -Uri "$Api/api/compat"
```

Beklenen: sağlık `ok`; uyumluluk yanıtında minimum `4`, güncel sürüm `5`.
Sunucu açılıyorsa birkaç saniye sonra sorguyu tekrarlayın.

Tarayıcı için **ikinci PowerShell penceresinde**, aynı repo kökünde:

```powershell
npm --prefix web ci
npm --prefix web run dev -- --host localhost --port 3000 --strictPort
```

Terminali açık tutun; `http://localhost:3000` adresini açın. `8000` API portudur.
Worker'ı başlangıçta çalıştırmayın. Önceden var olan test worker'ı çalışıyorsa
ve gerçek hesap bulunmadığından eminseniz test boyunca durdurabilirsiniz:

```powershell
docker compose @ComposeArgs stop worker
```

## 4. Android APK'yi kurun ve iki istemciyi eşleştirin

### Android Studio ile

1. Bu repo içindeki **android** klasörünü açın; Gradle eşitlemesini tamamlayın.
2. SDK Manager'da SDK 35 kurulu olsun.
3. Device Manager'da ayrı API 33 ve API 34+ test emülatörleri oluşturun.
4. Birini başlatın; **app → Run** ile debug uygulamasını kurun.

### PowerShell alternatifi ve sonraki komutların değişkenleri

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$Sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_HOME = $Sdk
$Adb = Join-Path $Sdk 'platform-tools\adb.exe'
$App = 'com.dojo.aisomedo'
if (-not (Test-Path -LiteralPath $Adb)) { throw 'Android SDK yolunu düzeltin.' }
./android/gradlew.bat -p android :app:assembleDebug
if ($LASTEXITCODE -ne 0) { throw 'APK derlenemedi.' }
& $Adb devices -l
$Serial = Read-Host 'Listede device durumundaki AYRI TEST cihazının seri numarası'
& $Adb -s $Serial install -r 'android/app/build/outputs/apk/debug/app-debug.apk'
if ($LASTEXITCODE -ne 0) { throw 'APK kurulamadı.' }
& $Adb -s $Serial shell am start -n "$App/.MainActivity"
```

SDK/JDK yolları farklıysa değiştirin. `install -r` mevcut debug verilerini korur.
**İmza uyuşmazlığında gerçek uygulamayı kaldırmayın; ayrı test emülatörü kullanın.**

Android'deki sunucu adresi:

| Ortam | Adres |
| --- | --- |
| Android Studio emülatörü; backend aynı bilgisayarda | `http://10.0.2.2:8000` |
| Uzak test sunucusu | Kendi `https://...` origin'iniz |

Adrese `/api`, sorgu veya kullanıcı/parola eklemeyin. HTTP yalnız debug içindir.
Fiziksel USB cihazda `adb reverse` yerel bağlantı için kullanılabilir, ancak
USB tüneli Wi-Fi kapalıyken bile backend'e erişebileceğinden gerçek çevrimdışı
denemeyi emülatörde veya normal ağ bağlantısıyla yapın. Android'in doğrulanmış
ağ bağlantısı bulunmadığında uygulama backend erişilebilir olsa da salt okunur kalır.

1. Android'de sunucu adresini girip **Bağlan**'a basın.
2. Yalnız test backend'inde eşleştirme kodu üretin:

   ```powershell
   docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
   ```

3. **Cihaz adı** olarak `Android Issue37 Deneme` yazıp kodla eşleştirin.
4. Eksik kurulum açılırsa **Şimdilik kontrol paneline dön** ile çıkın.
5. Tarayıcı için **yeni kod** üretin; web eşleştirme ekranında
   `Tarayici Issue37 Deneme` adıyla eşleştirin. Aynı kodu yeniden kullanmayın.

Kodları, çerezleri, `.env` içeriğini veya oturum kayıtlarını paylaşmayın.

## 5. Çevrimiçi başlangıç ve önbelleğin dolması — Android/tarayıcı

1. Test için kişisel veri içermeyen JPEG/PNG ve gerçek, geçerli bir MP4 hazırlayın.
   Dosyayı Android'in İndirilenler klasörüne koyun. Yeniden bağlantı testi için
   aktarımı izleyebileceğiniz büyüklükte, örneğin 20–100 MiB video kullanın;
   sunucu limitini aşmayın. Boş/rastgele bayt dosyası geçerli video değildir.
2. Android **Paket → Fotoğraf/video seç** ile test medyasını yükleyin.
   Android 13+ bildirim izni istenirse verin. Worker kapalıysa
   **Aktarım bitti; sunucuda sırada** sonucu normaldir.
3. İşlenmiş medya/sıralama/kırpma kontrollerini görmek gerekiyorsa yalnız bu
   test ortamında worker'ı açın. Yayın planı kapalı ve gerçek Meta hesabı yok olmalıdır:

   ```powershell
   docker compose @ComposeArgs up -d --build worker
   ```

4. Medya işlendikten sonra Android **Kontrol Paneli → Yenile**, ardından **Paket**
   ve **Hareketler** alanlarını açın. Paket adı, medya, son alınan bilgi zamanı ve
   bir hareketin işlem/zaman/aktörünü not alın. Geçmiş olay adlarının teknik metin
   olarak görünmesi normaldir.
5. Tarayıcı **Güncel Paket** (`#/package`) ve **Hareketler** (`#/activity`)
   alanlarını açıp ortak veriyi karşılaştırın. Tarayıcı sayfa boyutu Android'in
   son 50 olaylık diliminden farklı olabilir; satır sayılarının eşitliği şart değildir.
6. Android **Ayarlar → Kurulumu aç → Açıklama şablonu** alanında bir taslak yazın;
   **kaydetmeyin**. Bağlantı kesilmesindeki taslak kontrolünde bunu kullanın.

Beklenen: Android'de gerçek geçmiş ve paket bilgisi vardır; #36 inceleme gelen
kutusu kaldırılmamıştır. Tarayıcı Android'e özgü yerel aktarım satırlarını
göstermek zorunda değildir; ortak sunucu sonucunu karşılaştırır.

## 6. Çevrimdışı okuma ve tüm düzenlemelerin engellenmesi — Android

1. Android hızlı ayarlardan **Wi-Fi ve mobil veriyi kapatın**. Uçak modu kullanırsanız
   Wi-Fi'nin ayrıca kapalı olduğunu kontrol edin; emülatörde yalnız Wi-Fi'yi
   kapatmak mobil veri bağlantısını açık bırakabilir. Ethernet/VPN gibi başka
   bağlantı varsa ayrıca kesin.
2. Uygulamaya dönün. **Çevrimdışı: kayıtlı bilgiler gösteriliyor...** bildirimi bekleyin.
3. **Kontrol Paneli, Paket, Hareketler, Ayarlar** arasında gezinin.
   Son paket/geçmiş okunabilir ve son alınan bilgi zamanı eski değeriyle kalmalıdır.
4. Aşağıdaki işlemleri deneyin; uygun veri/ekran yoksa o satırı “denenmedi” işaretleyin:

   | İşlem | Beklenen |
   | --- | --- |
   | Açıklama, plan tarihi/saati, rıza kutusu veya diğer kurulum girdisini değiştirme | Yerel taslak düzenlenemez; önceden yazılan taslak korunur |
   | Kaydet, rıza kabulü, Instagram tokenı/OAuth/hesap seçimi, logo/kart yükleme | İşlem engellenir; yeni sunucu yazması yapılmaz |
   | Medya sıralama/sürükleme, kaldırma/geri alma, aralık düzenleme, kaydetme/taslak iptali | Salt okunur; paket değişmez |
   | Yeni dosya seçimi, Tekrar dene, yeniden dosya seçme, satır kaldırma, çakışma kararı | Engellenir |
   | Uygun mevcut aktarımı Duraklat/Devam et | Yalnız yerel niyet değişebilir; çevrimdışı veri gönderilmez |
   | İnceleme Onayla/Atla/Ertele ve render/devam | Engellenir; eski hazır önizleme yetki vermez |

5. Medya/inceleme önizlemesinin çevrimdışı indirilemediği açıklanmalıdır. Bir önceki
   ekranda görülmüş video, kalıcı çevrimdışı medya önbelleği olduğu anlamına gelmez.
6. Tarayıcıyı çevrimiçi tutup paket ve ayarları yenileyin. Android'deki engellenmiş
   denemeler sunucu değerlerini değiştirmemelidir.

**Sunucuya yazma isteği gitmediğini ek olarak gözlemlemek için**, yalnız kendi
test loglarınızı PowerShell'de süzün:

```powershell
docker compose @ComposeArgs logs --since 2m backend |
    Select-String -Pattern '"(POST|PUT|PATCH|DELETE) /api/'
```

Bu sürede tarayıcıdan da yazma yapmayın. Başka istemci/worker kayıtları olabilir;
zaman, yol ve test hareketini birlikte değerlendirin. Logda satır olmaması tek
başına kanıt değildir; erişim logu kapalı olabilir. Doğrudan model çağrıları için §12'yi kullanın.

### Açık tarih/saat diyaloğu

Çevrimiçiyken Android inceleme **Ertele → Tarih/Saat** diyaloğunu açın; ardından
ağı kapatıp farklı değer seçerek onaylayın. Arkadaki tarih/saat taslağı değişmemeli;
diyaloğu kapatabilmelisiniz. Gerçek erteleme veya yayın onayı göndermeyin.
İnceleme üretme ön koşulları: [#36 rehberi](issue-36-android-inceleme-bildirim-deneme-rehberi.md).
Bekleyen inceleme yoksa bu senaryoyu otomatik cihaz testiyle deneyin; yapılmış saymayın.

## 7. Çevrimdışı yeniden açılış, eksik önbellek ve kimlik sınırı

### 7.1. Süreci gerçekten kapatıp yeniden açın

Önce §5'te önbelleği doldurun, sonra §6'da ağı kesin. Uygulamayı son kullanılanlar
listesinden kapatmak her cihazda süreç ölümü değildir. Kesin deneme için:

```powershell
& $Adb -s $Serial shell am force-stop $App
& $Adb -s $Serial shell am start -n "$App/.MainActivity"
```

Beklenen: aynı eşleştirmede Paket/Hareketler okunur; tarihler değişmez; yazma
kontrolleri açılmaz. Bu iki komut uygulama verisini silmez. Sunucu bilgisayarda
açık kalmalıdır. Force-stop sırasında otomatik arka plan çalışma beklenmez;
kurtarma uygulama yeniden açıldıktan sonra değerlendirilir.

### 7.2. Hiç önbellek bulunmaması

İkinci, yeni test emülatöründe APK'yi kurun. Veri almadan ağı kapatıp sunucu
adresine bağlanmayı deneyin. Sahte boş paket/geçmiş değil, bağlantı/kayıtlı bilgi
yokluğu gösterilmelidir. İlk emülatörün verilerini silmeniz gerekmez.

“Başarıyla alınmış ama boş geçmiş” ile “hiç alınmamış geçmiş” ayrımı §12'deki
`SnapshotStoreTest` ve `OfflineAppViewModelTest` içinde sentetik verilerle denenir.
Eşleştirme bile olay üretebildiğinden gerçek veritabanını bu deneme için boşaltmayın.

### 7.3. Sunucu veya eşleştirme değişimi

1. İlk test sunucusunda önbelleği doldurun; ağı kesin.
2. Android **Ayarlar → Sunucuyu değiştir** ile onaylayın. Bu yerel işlem çevrimdışı
   yapılabilir ve yeniden eşleştirme gerektirir.
3. Ayrı ikinci test sunucunuz varsa ona bağlanın. Yoksa aynı test sunucusunda yeni
   kodla yeniden eşleştirme, eşleştirme sınırını kontrol etmek için yeterlidir.
4. Eski kimliğin korumalı Paket/Hareketler verisi gösterilmemelidir. Yeniden
   doğrulama sonrası sunucudan alınan aynı içerik ise elbette tekrar görünebilir.

Gecikmiş eski yanıtın tam yarış zamanlamasını elle yakalamaya çalışmayın; §12'de
`delayedOldSessionCannotCommitCache` ve kimlik değiştirme testleri bulunur.

## 8. Aktarım ilerlemesi, Duraklat/Devam et ve yeniden bağlantı

1. Ağı açın ve uygulamanın güncel doğrulamasını bekleyin.
2. Yeni isimli büyük geçerli video seçin; **Aktarılıyor** ve artan bayt değerini bekleyin.
   Sunucu kimliği alınmış, en az bir parçası onaylanmış aktarımı kullanın.
3. İlerlemeyi not edin, Ana Ekran'a dönün ve Android ağını kesin.
4. Uygulamaya dönün: bekleme, kullanıcı duraklatmasıyla karıştırılmamalı; bilinen
   dosya/yükleme kimliği ve onaylanan ilerleme sıfırlanmamalıdır.
5. Çevrimdışı **Duraklat**'a basıp ardından ağını açın. Kullanıcının duraklattığı
   satır otomatik başlamamalıdır.
6. Ağı yeniden kesin. Duraklatılmış uygun satırda **Devam et**'e basın. Ağ yokken
   veri gönderilmemeli; ağ gelince mevcut kimlikle devam edilmelidir.
7. Aynı denemeyi uygulama arka plandayken ve ekran kapalıyken, API 33 ve API 34+
   cihazlarda ayrı tekrarlayın. Bildirimdeki **Duraklat** da çalışmalıdır.
8. Ağı kesip §7.1'deki force-stop/açılış adımlarını uygulayın; sonra ağı açın.
   Bilinen kimlik/ilerleme korunmalıdır. Tarayıcıda ortak paket sonucunu kontrol edin.

### Kimlik ve onaylanan aralıkları somut karşılaştırma — PowerShell

Yalnız **debug test APK'sında**, sadece yükleme metadata dosyalarını okuyun.
`run-as` release APK'de çalışmaz. Eşleştirme/token dosyalarını okumayın.

```powershell
function Get-TestUploadRows {
    $Names = & $Adb -s $Serial shell run-as $App ls no_backup/uploads
    if ($LASTEXITCODE -ne 0) { throw 'Yükleme dizini yok veya APK debug değil.' }
    foreach ($Name in $Names) {
        $Name = $Name.Trim()
        if ($Name -notmatch '^[0-9a-f-]{36}\.json$') { continue }
        $Raw = & $Adb -s $Serial shell run-as $App cat "no_backup/uploads/$Name"
        if ($LASTEXITCODE -ne 0) { throw 'Test yükleme kaydı okunamadı.' }
        (($Raw -join "`n") | ConvertFrom-Json).row
    }
}
$Before = @(Get-TestUploadRows)
$Before | Select-Object id, filename, phase, intent,
    @{Name='SunucuKimligi'; Expression={$_.status.upload_id}},
    @{Name='OnaylananBayt'; Expression={$_.status.received_bytes}},
    @{Name='DosyaKimligi'; Expression={$_.identity.fingerprint}}
```

Çevrimdışı bekleme/yeniden açılıştan sonra **aynı pencerede**:

```powershell
$After = @(Get-TestUploadRows)
foreach ($Old in $Before) {
    $New = $After | Where-Object { $_.id -eq $Old.id } | Select-Object -First 1
    if ($null -eq $Old.status) { continue }
    if ($null -eq $New) { throw 'Önceki yükleme satırı kayboldu.' }
    if ($New.status.upload_id -ne $Old.status.upload_id) { throw 'Sunucu kimliği değişti.' }
    if ($New.identity.fingerprint -ne $Old.identity.fingerprint) { throw 'Dosya kimliği değişti.' }
    if ($New.status.received_bytes -lt $Old.status.received_bytes) { throw 'Onaylanan ilerleme geriledi.' }
    $New.status | Select-Object upload_id, received_bytes,
        @{Name='Araliklar'; Expression={$_.received_ranges | ConvertTo-Json -Depth 5 -Compress}}
}
```

Karşılaştırma sırasında satırları kaldırmayın veya açıkça yeni yükleme başlatmayın.
Uçuş halindeki parça henüz onaylanmamış olabilir; kaybolan yanıtın ardından durum
sorgusu ilerlemeyi ileri taşıyabilir. Yalnız gerçekten onaylanan parçalar için
yeniden gönderim yapılmaması aranır. Kesin eksik-parça deneyi §12'deki
`reconnectSendsOnlyMissingChunks` testidir; yüzde animasyonu tek başına kanıt değildir.

### İlk oluşturma yanıtının kaybolması

Sunucu kimliği henüz alınmadan ilk oluşturma POST'u belirsiz kalırsa **Tekrar dene**
beklenir; yeniden bağlantı otomatik ikinci oluşturma yapmamalıdır. Henüz POST
gönderilmeden kesilen hazırlık ise otomatik devam edebilir. Bu dar zamanlama için
§12'deki initialization testlerini kullanın. Açık tekrar denemede önceki belirsiz
sunucu kaydı bulunamayabilir ve süre sonuna kadar kalabilir; yeni bir idempotency
API'si eklenmedi. Bu, bilinen kimlikli aktarımın ilerlemesini kaybetmekle aynı durum değildir.

## 9. Ağ var ama backend yok; yeniden bağlanınca yazmaların açılması

1. Android'i çevrimiçi tutun. Paket/geçmişi alın ve kaydedilmemiş taslak bırakın.
2. Yalnız **yerel test backend'ini** durdurun:

   ```powershell
   docker compose @ComposeArgs stop backend
   ```

3. Android **Yenile**'ye basın; isteğin hatayla bitmesini bekleyin.
4. **Sunucu henüz doğrulanmadı...** salt okunur açıklaması bekleyin. Ağ simgesi
   açık olsa bile kaydetme/inceleme açılmamalı; önceki bilgiler okunmalıdır.
5. Test backend'ini geri açın, sağlık yanıtını kontrol edin ve Android'de yenileyin:

   ```powershell
   docker compose @ComposeArgs start backend
   Invoke-RestMethod -Uri "$Api/health"
   ```

6. Uygulama kimlik/uyumluluk ve güncel verileri aldığında ilgili kontroller açılmalıdır.
   Kaydedilmemiş taslak veya önceki belirsiz yazma **otomatik gönderilmemelidir**.

Bir bölümün GET isteğini ayrı bozmak için bu rehber yeni proxy/test backend'i
kurmaz. Başarılı dashboard + başarısız editor/history ve paket değişimi senaryoları
§12'deki `reconnectWaitsForFreshResourceReads` / `replacementPackageInvalidatesOldEditor`
testleriyle denenebilir. Tüm backend'i durdurmak bu bölüm-özel senaryoyu kanıtlamaz.

## 10. Desteklenmeyen sürüm ve güvenli güncelleme ekranı

Sürüm ayarı UI'da bulunmadığından PowerShell'den test `.env` dosyasını açacağız.
**Önce mevcut üç `ANDROID_*` değerini özel olarak not edin; başka ayar değiştirmeyin.**
PowerShell'de `$env:ANDROID_MIN_VERSION_CODE` yazmak, çalışan container'ın
`env_file` değerini değiştirmez. Dosyayı düzenlemek ve backend'i yeniden oluşturmak gerekir.

1. Kuracağınız APK'nin kaynak sürümünü kontrol edin; mevcut değer `5`:

   ```powershell
   Select-String -Path android/app/build.gradle.kts -Pattern '^\s*versionCode\s*='
   notepad ops/.env
   ```

2. Test `.env` içinde mevcut APK 5'i engellemek için
   `ANDROID_CURRENT_VERSION_CODE=6`, `ANDROID_MIN_VERSION_CODE=6` yazın.
   `ANDROID_UPDATE_URL` için gerçekten dağıtılmış **imzalı** test APK'sının HTTPS
   adresini kullanın. Örnek/boş adresle APK kurulum başarısı iddia etmeyin.
   Kaynak sürümü farklıysa minimumu onun üstüne, current'ı en az minimuma ayarlayın;
   minimum ayrıca `max(1, current−1)` değerinin altında olamaz.
3. Yalnız test backend'ini yeni çevre değişkenleriyle oluşturun:

   ```powershell
   docker compose @ComposeArgs up -d --no-deps --force-recreate backend
   if ($LASTEXITCODE -ne 0) { throw 'Test backend yeniden oluşturulamadı.' }
   Invoke-RestMethod -Uri "$Api/health"
   Invoke-RestMethod -Uri "$Api/api/compat"
   ```

4. Sağlık/compat açıldıktan sonra Android'i yenileyin. **Güncelleme gerekli** ekranı
   beklenir; normal sekmeler/aktarımı sürdürme/yazma erişimi açılmamalıdır.
5. Android ağını kesin; §7.1 ile uygulamayı yeniden açın. **Güncelleme gerekli**
   sürmeli. Yenilemenin başarısız olması normal önbellek gezinmesine dönmemelidir.
6. Ağı açın. Gerçek adresiniz varsa indirme düğmesi güvenli HTTPS adresini
   tarayıcıya açmalıdır. Özel GitHub release'i giriş isteyebilir. APK imzasını
   Android kurucusu denetler; HTTPS düğmesi tek başına doğru imza kanıtı değildir.
7. Eksik URL senaryosu için `ANDROID_UPDATE_URL=` yapıp §10.3 komutlarını
   tekrarlayın, Android'i **çevrimiçiyken** yenileyin. İndirme düğmesi yerine
   **Güvenli güncelleme adresi alınamadı...**, yeniden deneme ve sunucu değiştirme
   seçenekleri beklenir. Önceden bilinen adresin bazı 426 yanıtlarında korunması normaldir;
   bu denemede yeni başarılı compat yanıtının boş adresi alındığını kontrol edin.
8. **Deneme sonunda**, orijinal üç değeri geri yazıp §10.3 komutlarını tekrar
   çalıştırın. Android'i çevrimiçi yenileyin; desteklenen kurulu sürüm tekrar açılmalıdır.

Geçersiz `http://...` URL'yi `.env`'ye yazıp backend'in açılmasını beklemeyin:
backend bunu reddeder. Android'in güvensiz URL savunması otomatik testlerdedir.
Güncel imzalı APK üretimi/dağıtımı bu değişikliğin parçası değildir;
[release belgesine](../ops/releases.md) bakın. İmza uyuşmazlığını uygulamayı
silerek aşmayın. Bir APK güncellemesi, önceki sürüme ait 426 reddinin kalıcı kilit
oluşturmadığını ayrıca gösterebilir; sürüm yükseltmek yerine yalnız versionName'i
değiştirmek yeterli değildir.

## 11. Cihaz iptali ve arka plan FCM 401/426

### 11.1. Yalnız Android test cihazını iptal edin — PowerShell/API

UI'da cihaz iptalini bulamazsanız mevcut API'yi kullanın. Tokenı dosyadan çıkarmayın;
ayrı PowerShell tarayıcı oturumu oluşturun. Bunun için **yeni kod** üretin:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
$SecretCode = Read-Host 'Yeni tek kullanımlık eşleştirme kodu' -AsSecureString
$Code = [System.Net.NetworkCredential]::new('', $SecretCode).Password
$Body = @{code=$Code; kind='browser'; name='PowerShell Issue37 Deneme'} | ConvertTo-Json
Invoke-RestMethod -Uri "$Api/api/pairing/validate" -Method Post -Body $Body `
    -ContentType 'application/json; charset=utf-8' -SessionVariable ApiSession | Out-Null
$Code = $null
$Body = $null
$SecretCode.Dispose()
$Clients = Invoke-RestMethod -Uri "$Api/api/pairing/clients" -WebSession $ApiSession
$Clients | Select-Object id, name, kind, revoked_at
```

Android **Ayarlar**'ındaki cihaz numarasını listeden doğrulayın. Yalnız o test
cihazının `kind=device` kaydını seçin; diğer tarayıcı/cihazları iptal etmeyin:

```powershell
$ClientId = [int](Read-Host 'İptal edilecek Android TEST cihazının id değeri')
$Client = $Clients | Where-Object { $_.id -eq $ClientId } | Select-Object -First 1
if ($null -eq $Client -or $Client.kind -ne 'device' -or $Client.name -ne 'Android Issue37 Deneme') {
    throw 'Bu numara rehberde eşleştirdiğiniz Android test cihazına ait değil.'
}
$Confirm = Read-Host "$ClientId numaralı test cihazını iptal etmek için aynı numarayı tekrar yazın"
if ($Confirm -ne "$ClientId") { throw 'İptal onaylanmadı.' }
Invoke-RestMethod -Uri "$Api/api/pairing/clients/$ClientId/revoke" `
    -Method Post -WebSession $ApiSession
```

Beklenen yanıt `revoked=true`. Android'de çevrimiçi **Yenile**:
eşleştirme ekranına dönmeli; korumalı eski Paket/Hareketler gösterilmemelidir.
Ağı kesip yeniden açınca eski korumalı önbellek geri gelmemelidir. Sonraki deneme
için yeni kodla yeniden eşleştirin. Sunucu iptalini Android hiç çevrimiçi öğrenmeden
önce eski tarihi veriyi çevrimdışı okuyabilmesi normaldir; uzaktan iptal bilgisi
bağlantı olmadan keşfedilemez.

### 11.2. FCM sınırı ve deterministik deneme

Gerçek FCM akışı için ayrı test Firebase projesi, o projeye ait Android yapılandırması,
Google Play Services ve izinli cihaz gerekir; [#36 rehberi](issue-36-android-inceleme-bildirim-deneme-rehberi.md)
bu hazırlığı anlatır. Firebase yoksa bu sonucu “denenmedi” yazın; yapay bir API
PUT'unun başarılı olması Android FCM callback'ini doğrulamaz.

- Token kaydı/kaldırma isteği cihaz çevrimdışıyken veya bilinen sürüm engelinde gönderilmemeli.
- Arka planda alınmış 426, güncelleme engelini diske yazıp aktarımları durdurmalı.
- Alınmış 401, o kimliği ve korumalı önbelleği kaldırmalı; başka eşleştirmeyi etkilememeli.
- Yanıt gelmeden ağ kaybolması, **alınmış** 401/426'nın işlenmesini engellememeli.

Token rotasyonunun ve yanıt/ağ kaybının tam zamanlaması UI'dan güvenilir biçimde
üretilemez. Uygulamayı sırf token döndürmek için kaldırmayın. §12'deki
`PushRegistrationTest`, `UploadEngineTest` ve cihazda
`pushRejectionStopsSharedRuntimeWithoutVisibleActivity` senaryolarını kullanın.

## 12. Arayüzde üretilemeyen hata/yarış senaryoları — yalnız PowerShell

Bu komutlar mevcut sentetik JUnit/MockWebServer testlerini çalıştırır; Python/SQL
kodu içermez, gerçek backend veritabanına bağlanmaz. Repo kökünde, §4'teki JDK/SDK
ayarlarıyla çalıştırın. `--tests` filtresi yalnız birim testlerine uygulanır.

| Test sınıfı | Kontrol ettiği değişiklikler |
| --- | --- |
| `OfflineAppViewModelTest` | Soğuk çevrimdışı başlangıç, doğrudan yazma engeli, taslak koruma, kısmi okuma, eski kimlik yanıtı, güncelleme engeli, inceleme/önizleme |
| `SnapshotStoreTest` | Eksik/boş geçmiş ayrımı, bozuk/büyük/şema sürümü farklı dosya, kimlik izolasyonu, atomik yazma hatası |
| `NetworkMonitorTest` | Yeni ağa geçişten sonra eski loss callback'i, ilk loss ve eski başlangıç örneği |
| `PushRegistrationTest` | Çevrimdışı kayıt/kaldırma engeli, kalıcı 426, erişim kaybından sonra alınan red, token rotasyonu ve oturum sınırı |
| `UploadEngineTest` | Aynı kimlikle yalnız eksik parçalar, retry bütçesi, belirsiz ilk oluşturma ve süreç yeniden açılışı, 401/426 |

```powershell
./android/gradlew.bat -p android :app:testDebugUnitTest `
    --tests '*OfflineAppViewModelTest*' --tests '*SnapshotStoreTest*' `
    --tests '*NetworkMonitorTest*' --tests '*PushRegistrationTest*' `
    --tests '*UploadEngineTest*' --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Hedefli testler başarısız; raporu inceleyin.' }
Start-Process (Resolve-Path 'android/app/build/reports/tests/testDebugUnitTest/index.html').Path
```

Beklenen: `BUILD SUCCESSFUL`, HTML raporunda sıfır başarısız test. Hedefli koşunun
sayısı tüm süitin 216 testiyle aynı olmak zorunda değildir. Başarı yalnız host
mantığını gösterir; Android scheduler/UI kabulünün yerine geçmez.

Tüm Android regresyonları, APK'lar ve lint için:

```powershell
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug `
    :app:lintDebug :app:assembleDebugAndroidTest --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Tam host doğrulaması başarısız.' }
```

### Gerçek cihaz senaryoları

**Yalnız gerçek verisi bulunmayan, kilidi açık ayrı test emülatöründe çalıştırın.**
Instrumentation sentetik eşleştirmeler oluşturur ve bazı testler Wi-Fi/mobil veriyi
geçici değiştirir. §4'te seçtiğiniz cihazı iki API seviyesinde ayrı ayrı hedefleyin:

```powershell
$env:ANDROID_SERIAL = $Serial
$ApiLevel = & $Adb -s $Serial shell getprop ro.build.version.sdk
Write-Output "Test cihazı: $Serial; API: $ApiLevel"
./android/gradlew.bat -p android :app:connectedDebugAndroidTest --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Cihaz testleri başarısız veya cihaz bağlı değil.' }
Start-Process (Resolve-Path 'android/app/build/reports/androidTests/connected/debug/index.html').Path
```

Beklenen: seçilen test cihazında testlerin gerçekten çalışması ve rapor oluşması.
`No connected devices!` başarı değil, engeldir. `assembleDebugAndroidTest` de
cihaz testini çalıştırmaz. İş kesilirse ağ ayarlarını kontrol edin. Uygulama
süreci öldürülürken içindeki test sunucusu da öldüğünden gerçek force-stop kabulü
için §7/§8'de bilgisayarda açık kalan backend'i kullanın.

## 13. Son kontroller, geri alma ve sonuç listesi

1. Test backend'inin kapalı kalmadığını kontrol edin; §9'daki `start backend` yoluyla açın.
2. Üç `ANDROID_*` değerini orijinal hâline getirip backend'i §10.3 ile yeniden oluşturun.
3. Cihazın Wi-Fi/mobil veri/uçak modu ayarlarını başlangıç durumuna döndürün.
4. İptal edilen test cihazını gerekiyorsa yeni kodla eşleştirin; eski tokenı canlandırmayın.
5. Yalnız test için başlattığınız worker'ı kapatın. Önceden çalışan test worker'ının
   durumunu kendi başlangıç notunuza göre geri alın; üretim worker'ına dokunmayın.
6. Telefon/tablet, açık/koyu tema, büyük yazı ve TalkBack ile gezinme, zaman
   etiketleri, okunabilir metin ve devre dışı kontrolleri ayrıca deneyin.
7. API/cihaz sürümü, tarih ve ekran görüntüsüyle sonuçları kaydedin. Gizli kod,
   cookie, token ve `.env` içeriğini kayda koymayın. Veritabanı/volume silmeyin;
   bu rehber `down -v`, uygulama verisini temizleme veya gerçek APK'yi kaldırma gerektirmez.

| Senaryo | Geçti / Başarısız / Denenmedi | Cihaz/API ve not |
| --- | --- | --- |
| Çevrimdışı Paket/Hareketler ve eski zaman damgası | | |
| Soğuk çevrimdışı açılış; eksik önbellek ayrımı | | |
| Yerel taslak ve tüm yazma/inceleme kontrolleri engelli | | |
| Açık tarih/saat diyaloğu çevrimdışı taslağı değiştirmiyor | | |
| Yeniden bağlantıda güncel veri/inceleme/önizleme gerekli | | |
| Bilinen yükleme kimliği, aralıklar ve kullanıcı pause niyeti korunuyor | | |
| API 33 arka plan/ekran kapalı devam | | |
| API 34+ arka plan/ekran kapalı devam | | |
| Force-stop sonrası bilinen aktarımın kurtarılması | | |
| Belirsiz ilk oluşturma otomatik tekrarlanmıyor | | |
| Uyumsuz sürüm engeli çevrimdışı açılışta kalıcı; destek geri gelince kalkıyor | | |
| Eksik güncelleme URL'si açıklanıyor; gerçek imzalı APK kurulumu | | |
| 401 sonrası korumalı önbellek yok; eski kimlik yanıtı yeni oturumu bozmuyor | | |
| Arka plan FCM 401/426 ortak oturumu durduruyor | | |
| Host otomatik testleri / cihaz otomatik testleri | | |

**#37'nin tam cihaz kabulü**, ilgili satırlar gerçekten denenip kanıtlandığında
tamamlanmış sayılabilir. Host testlerinin geçmesi veya APK'nin derlenmesi tek başına yeterli değildir.
