# Android dosya adı çakışması — değişiklik özeti ve deneme rehberi (#34)

Bu rehber, #34 için eklenen davranışları **Android uygulamasında** denemenizi
anlatır. **Tarayıcı**, ilk hedef medyayı yüklemek ve ortak paket/etkinlik sonucunu
kontrol etmek için kullanılır. Arayüzde yapılamayan hazırlık, sunucu gözlemi ve
kontrollü hata senaryoları **PowerShell** ile verilir. Python veya SQL kodu içermez.

> **Güvenlik:** Yalnız ayrı deneme sunucusu ve boş deneme cihazı/emülatörü kullanın.
> Üzerine yazma geri alınamaz; gerçek öğrenci medyasıyla denemeyin. Instagram
> bağlantısı kurmayın, yayın planını etkinleştirmeyin ve yayın onayı vermeyin.
> `.env`, eşleştirme kodu, çerez ve token değerlerini paylaşmayın.

> **Doğrulama durumu:** Önceki geliştirme doğrulamasında 88 Android birim testi,
> 205 backend testi, APK derlemeleri ve lint geçti. Bağlı cihaz olmadığı için
> aşağıdaki canlı Android denemeleri henüz çalıştırılmadı. İkinci bağımsız inceleme
> kota nedeniyle tamamlanamadı. “Beklenen” sonuçlar kabul ölçütüdür; cihazda
> doğrulanmış başarı iddiası değildir.

## 1. Ne değişti?

| Değişiklik | Kullanıcının göreceği sonuç |
| --- | --- |
| Android çakışma kontrolleri | **Paket → Aktif Paket** yükleme satırında üç karar ve toplu uygulama kutusu bulunur. |
| Hedef önizlemesi | Sunucudaki mevcut fotoğraf/video, dosya adı, kaynak boyutu, yükleme tarihi ve hedef kimliği gösterilir. Önizleme yeni seçilen dosya değildir. |
| **İkisini de tut** | Mevcut medya korunur; yeni dosya sunucunun belirlediği boş sayısal sonekle eklenir. |
| **Seçileni tut (hedefin üzerine yaz)** | Yalnız seçilen hedef, yeni medya başarıyla doğrulandıktan sonra değiştirilir. |
| **Hedefi tut (yüklemeyi atla)** | Yeni yükleme atlanır; hedef korunur. Atlanmış satır hata/tekrar deneme satırına dönüşmez. |
| **Tüm uyumlu çakışmalara uygula** | Aynı pakette aynı normalleştirilmiş adla şu anda bekleyen uyumlu çakışmalar etkilenir; başka adlar ve sonradan seçilen dosyalar etkilenmez. |
| Üzerine yazma onayı | Geçerli hedef, yüklenmiş önizleme, geri alınamaz uyarısı ve ayrı onay gerekir. Hedef, karar, toplu kapsam veya önizleme değişince onay sıfırlanır. |
| Belirsiz sonuç koruması | Yanıt kaybolduğunda karar otomatik tekrar gönderilmez. Sonuç kesinleşmeden ikinci karar gönderilmesi engellenir; **Yenile** kullanılır. |
| Başka istemcinin kararını kurtarma | Android satırı yenilenir; hedefi koruma ile süre dolması mevcut etkinlik kayıtlarından ayırt edilir. |
| Önizleme güvenliği/temizliği | Kimlik doğrulamalı indirme, yönlendirme engeli, özel geçici dosya ve hata/ayrılma/sonraki süreç açılışında temizlik bulunur. |

Teknik değişiklikler: `ConflictControls.kt` ve `UploadPanel.kt` arayüzü;
`UploadEngine.kt`, `UploadRuntime.kt`, `UploadState.kt`, `UploadStore.kt` karar ve
kurtarma akışı; `DojoApi.kt` önizleme/karar/etkinlik sorguları; Türkçe metinler ve
bildirim durumları. İstemci üreticisine `ResolveConflictIn` Android modeli eklendi;
birim ve Compose cihaz testleri genişletildi. Yeni ürün bağımlılığı veya backend
çakışma mantığı eklenmedi.

**Kapsam sınırı:** Tarayıcının çakışma ekranı önceden vardı; #34 Android ekranını
ekler. Tarayıcıda aynı sonucu görmek, Android önizleme/onay/kurtarma davranışını
tek başına doğrulamaz. Eski [#33 rehberindeki](issue-33-android-upload-deneme-rehberi.md)
“Android çakışmayı webden çözer” notu #33'ün eski kapsamıdır; #34 için bu rehber
geçerlidir. Genel aktarım davranışının bütün eski sorunlarının çözüldüğü iddia edilmez.

## 2. Deneme ortamını hazırlayın

Bu dalın kodunu içeren ayrı sunucunuz hazırsa bölüm 3'e geçin. Yeni yerel kurulum
için Docker Desktop Linux motoru, Node.js 22/npm, Android Studio, SDK 35 ve
Android 10/API 29+ emülatör gerekir. Komutlar Windows PowerShell içindir.
Uzak hazır ortamda tarayıcı adreslerini ve `$Base` değerini kendi deneme HTTPS
adresinizle değiştirin; yerel Compose başlatma/durdurma komutlarını uygulamayın.
Yeni eşleştirme kodunu o ortamın yöneticisinden alın.

### 2.1. Doğru çalışma dizini ve boş veriler

```powershell
Set-Location -LiteralPath (Read-Host 'Issue 34 kodunu içeren deneme reposunun tam yolu')
git branch --show-current
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-android34-deneme', '-f', 'ops/docker-compose.yml')
docker compose version
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 8000, 5434, 3000 } |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Geliştirme dalı `feat/issue-34-android-conflicts`; mevcut worktree
`.worktrees/issue-34-android-conflicts`. Birleştirme sonrası aynı kodu içeren başka
dal da kullanılabilir. Portları başka ortam kullanıyorsa o ortamı durdurmayın;
ayrı deneme ortamı seçin. Her yeni PowerShell penceresinde repo köküne geçin ve
`$ComposeArgs` değerini tekrar tanımlayın.

**İlk kurulumda** aşağıdaki kontrolü yapın. Kendi deneme verilerinizi yeniden
açarken bu kontrolü atlayın; mevcut verileri silmeyin:

```powershell
foreach ($Path in 'ops/db-data', 'ops/media-data') {
    if ((Test-Path -LiteralPath $Path) -and
        (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1)) {
        throw "$Path boş değil. İlk kurulum için temiz bir deneme checkout'u kullanın; verileri silmeyin."
    }
}
if (-not (Test-Path -LiteralPath ops/.env)) {
    Copy-Item -LiteralPath ops/.env.example -Destination ops/.env
}
notepad ops/.env
```

Compose proje adı tek başına veriyi ayırmaz; `ops/db-data` ve `ops/media-data`
host dizinleri kullanılır. Not Defteri'nde yalnız bu yerel deneme için:

- `POSTGRES_PASSWORD`: boş olmayan, denemeye özel parola; harf/rakam bağlantı
  adresindeki özel karakter sorunlarını önler.
- `COOKIE_SECURE=false`: yalnız yerel HTTP denemesinde; üretimde değiştirmeyin.
- `PUBLIC_BASE_URL=http://localhost:3000`
- `PUBLIC_HTTPS_ORIGIN=http://localhost:3000`
- `ANDROID_CURRENT_VERSION_CODE=5`, `ANDROID_MIN_VERSION_CODE=1`.

Instagram bilgileri gerekmez. Boş şifreleme anahtarını PowerShell ile üretin;
aşağıdaki komut mevcut anahtarı değiştirmez veya ekrana yazdırmaz:

```powershell
$EnvPath = (Resolve-Path -LiteralPath ops/.env).Path
$Content = [System.IO.File]::ReadAllText($EnvPath)
if ($Content -match '(?m)^META_TOKEN_ENCRYPTION_KEY=[ \t]*\r?$') {
    $Bytes = New-Object byte[] 32
    $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Rng.GetBytes($Bytes) } finally { $Rng.Dispose() }
    $Key = [Convert]::ToBase64String($Bytes).Replace('+', '-').Replace('/', '_')
    $Content = [regex]::Replace($Content, '(?m)^META_TOKEN_ENCRYPTION_KEY=[ \t]*\r?$', "META_TOKEN_ENCRYPTION_KEY=$Key")
    [System.IO.File]::WriteAllText($EnvPath, $Content, [System.Text.UTF8Encoding]::new($false))
    $Key = $null
    $Bytes = $null
    $Content = $null
}
```

### 2.2. Sunucu ve tarayıcı

İlk kurulumun şema hazırlığını mevcut Compose `init` servisi yapar; elle
veritabanı komutu yazmanız gerekmez:

```powershell
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose @ComposeArgs build backend init worker
if ($LASTEXITCODE -ne 0) { throw 'Deneme imajları derlenemedi.' }
docker compose @ComposeArgs up -d db
docker compose @ComposeArgs run --rm init
if ($LASTEXITCODE -ne 0) { throw 'Deneme veritabanı hazırlanamadı; devam etmeyin.' }
docker compose @ComposeArgs up -d backend worker
if ($LASTEXITCODE -ne 0) { throw 'Servisler açılamadı.' }
Invoke-RestMethod -Uri 'http://localhost:8000/health'
```

Sağlık yanıtında `status: ok` beklenir; açılış sürüyorsa biraz bekleyip sorguyu
tekrarlayın. Worker medyayı işler; bu denemede çalışmalıdır. Ayrı PowerShell
penceresinde aynı repo kökünden:

```powershell
npm --prefix web ci
if ($LASTEXITCODE -ne 0) { throw 'Web bağımlılıkları kurulamadı.' }
npm --prefix web run dev -- --host localhost --port 3000 --strictPort
```

Terminali açık bırakın. Tarayıcıda `http://localhost:3000` açın; `8000` API
portudur, web ekranı değildir. Tarayıcıda deneme boyunca aynı origin'i kullanın.

## 3. Android'i kurun; iki istemciyi eşleştirin

**Android Studio:** Reponun `android` klasörünü açın, SDK 35'i kurun, Device
Manager'dan ayrı ve boş API 29+ emülatörü başlatın; **app → Run** kullanın.
Telefon ve tablet kabulü için ayrı emülatörlerde tekrarlayın.

**PowerShell alternatifi:** SDK yolunuz farklıysa `$Sdk` değerini değiştirin.
Gradle JDK hatası verirse Android Studio'da eşitlemeyi tamamlayın veya kendi
uyumlu JDK kurulumunuzu `JAVA_HOME` ile seçin.

```powershell
$Sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_HOME = $Sdk
$Adb = Join-Path $Sdk 'platform-tools\adb.exe'
./android/gradlew.bat -p android :app:assembleDebug
if ($LASTEXITCODE -ne 0) { throw 'APK derlenemedi.' }
& $Adb devices -l
$Serial = Read-Host 'device durumundaki boş deneme emülatörünün seri numarası'
& $Adb -s $Serial install -r 'android/app/build/outputs/apk/debug/app-debug.apk'
if ($LASTEXITCODE -ne 0) { throw 'APK kurulamadı.' }
& $Adb -s $Serial shell am start -n 'com.dojo.aisomedo/.MainActivity'
```

Gerçek uygulamanın üzerine kurmayın. İmza uyuşmazlığında onu kaldırmayın; ayrı
emülatör kullanın. `install -r` aynı imzalı debug kurulumunun verilerini korur.

1. Android'deki sunucu alanına emülatör için `http://10.0.2.2:8000`, uzak deneme
   sunucusu için kendi `https://...` origin'inizi yazın. `/api` eklemeyin. HTTP
   yalnız debug APK'de kullanılabilir.
2. **Bağlan** düğmesine basın. Yeni kod üretin:

   ```powershell
   docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
   ```

3. **Cihaz adı**: `Android34 Deneme`. Kodu girip **Eşleştir**'e basın.
   Kurulum açılırsa **Şimdilik kontrol paneline dön** ile çıkın; **Paket**'e geçin.
4. Tarayıcı için aynı komutla **yeni** kod üretin. Tarayıcı adı `Web34 Deneme`
   olsun; eşleştirin ve `http://localhost:3000/#/package` açın.

USB bağlı ayrı debug cihazı kullanıyorsanız, bilgisayardaki sunucuya ulaşmak için
aşağıdaki yönlendirmeden sonra Android adresini `http://127.0.0.1:8000` yapabilirsiniz:

```powershell
& $Adb -s $Serial reverse tcp:8000 tcp:8000
```

## 4. Ayırt edilebilir örnek dosyaları hazırlayın

Paint ile iki ayrı klasörde **aynı adlı, farklı renkli** geçerli PNG oluşturabilir
ve Android'e kopyalayabilirsiniz. İsterseniz aşağıdaki Windows PowerShell kodu
benzersiz geçici dizinde örnekleri üretir; mevcut dosyalara dokunmaz:

```powershell
Add-Type -AssemblyName System.Drawing
$TestDir = Join-Path $env:TEMP ('dojo-android34-' + [Guid]::NewGuid().ToString('N'))
foreach ($Folder in 'ilk', 'yeni', 'ikinci', 'casefold', 'farkli') {
    $Dir = Join-Path $TestDir $Folder
    New-Item -ItemType Directory -Path $Dir -Force | Out-Null
    $Image = [System.Drawing.Bitmap]::new(640, 360)
    $Graphics = [System.Drawing.Graphics]::FromImage($Image)
    try {
        $Color = if ($Folder -eq 'ilk') { [System.Drawing.Color]::Orange } else { [System.Drawing.Color]::RoyalBlue }
        $Graphics.Clear($Color)
        $Name = if ($Folder -eq 'casefold') { 'STRASSE.png' } elseif ($Folder -eq 'farkli') { 'baska34.png' } else { 'rehber34.png' }
        $Image.Save((Join-Path $Dir $Name), [System.Drawing.Imaging.ImageFormat]::Png)
    } finally { $Graphics.Dispose(); $Image.Dispose() }
}
Copy-Item -LiteralPath (Join-Path $TestDir 'ilk/rehber34.png') -Destination (Join-Path $TestDir 'ilk/baska34.png')
Copy-Item -LiteralPath (Join-Path $TestDir 'ilk/rehber34.png') -Destination (Join-Path $TestDir 'ilk/Straße.png')
& $Adb -s $Serial push $TestDir '/sdcard/Download/'
if ($LASTEXITCODE -ne 0) { throw 'Deneme örnekleri cihaza kopyalanamadı.' }
Write-Host "Bilgisayardaki örnekler: $TestDir"
Write-Host "Android: Download/$([System.IO.Path]::GetFileName($TestDir))"
```

Android seçicide **Dosyalar → İndirilenler/Download** üzerinden bu klasörleri
bulun. Başka bir sağlayıcıya ihtiyaç duyarsanız kalıcı okuma erişimi sunan kaynak
seçin. Android 13+ bildirim iznini verin. `System.Drawing` kullanılamazsa Paint
ile aynı dosya/klasör düzenini oluşturun ve Dosya Gezginiyle cihaza kopyalayın.

## 5. İlk hedefi yükleyin ve Android'de çakışmayı görün

1. Tarayıcı **Güncel Paket → Fotoğraf ve video yükle** alanından
   `ilk/rehber34.png` seçin. **Pakete eklendi** olmasını bekleyin; %100 veya
   sırada/işleniyor durumu yeterli değildir.
2. Android **Paket → Aktif Paket → Fotoğraf/video seç** ile
   `yeni/rehber34.png` seçin.
3. Satırda **Dosya adı çakışmasını çöz**, üç karar ve toplu kutu görünmelidir.
   Önizleme **turuncu mevcut hedef** olmalı; mavi yeni dosya olmamalıdır.
4. Hedef dosya adı, bayt boyutu, yükleme tarihi ve hedef kimliğini not edin.
   Tek hedef varsa hedef seçicisinin görünmemesi normaldir.
5. Henüz karar vermeyin. Otomatik üzerine yazma olmamalıdır. Kesin bayt/kimlik
   kontrolü isterseniz bölüm 11'deki salt okunur sorguyu kullanın; yeni çakışmanın
   `status` değeri `conflict`, `received_bytes` değeri `0` olmalıdır.

Android'in yerel yükleme satırları tarayıcıda birebir görünmez. Tarayıcı ortak
medya/paket sonucunu gösterir; Android'deki bekleyen satırı webde aramayın.

## 6. Üç kararı sırayla deneyin

### 6.1. İkisini de tut

1. Bölüm 5'teki satırda **İkisini de tut** seçili olsun. Toplu kutu kapalı kalsın.
2. **Kararı uygula**'ya bir kez basın. İşlem sırasında kontroller kapanmalıdır.
3. Android'de **Aktif Pakete eklendi** durumunu bekleyin. Gerekiyorsa uygulamayı
   arka plana gönderip tekrar açın; tarayıcıda ortak paketi kontrol edin.
4. Turuncu hedef kalmalı; mavi dosya `rehber34 (1).png` gibi ayrı adla eklenmelidir.
   Önceki denemeler varsa numara farklı olabilir. Satır başlığı kaynak adını
   göstermeye devam edebilir; son adı tarayıcı medya listesinde kontrol edin.

### 6.2. Hedefi tut; yüklemeyi atla

1. Android ana seçicisinden `yeni/rehber34.png` tekrar seçin; yeni çakışma oluşturun.
2. **Hedefi tut (yüklemeyi atla)** seçin; toplu kutuyu kapalı bırakıp **Kararı uygula**'ya basın.
3. **Hedef korundu; seçilen dosya yüklenmedi** görünmelidir; **Tekrar dene** olmamalıdır.
4. **Ayarlar**'a gidip **Paket**'e dönün; uygulamayı kapatıp yeniden açın. Atlanmış
   satır aynı kalmalıdır; hedef ve önceki numaralı kopya değişmemelidir.
5. **Listeden kaldır**, yalnız yerel satırı kaldırır; orijinal dosyayı ve paketteki
   medyayı silmez. Bu denemede satırı kaldırmayın; yeniden açılış sonucunu kaydedin.

### 6.3. Seçileni tut; önizlenen hedefin üzerine yaz

> Bu deneme sunucudaki hedefi kalıcı değiştirir. Yalnız oluşturduğunuz örnek medyada yapın.

1. Mavi `yeni/rehber34.png` dosyasını yeniden seçin; yeni çakışma oluşsun.
2. **Seçileni tut (hedefin üzerine yaz)** seçin. Şu uyarı görünmelidir:
   **Bu işlem geri alınamaz. Hedef dosya kalıcı olarak değiştirilecek.**
3. **Kalıcı değişikliği onaylıyorum** boşken **Hedefin üzerine yaz** kapalı olmalıdır.
   Önizleme henüz yüklenmediyse onay kutusu da kullanılamamalıdır.
4. Önizleme yüklendikten sonra onay verin. Toplu kutuyu değiştirin: onay sıfırlanmalı.
   Toplu kutuyu tekrar kapatın; yeniden onay verin.
5. Kararı **İkisini de tut** yapıp tekrar **Seçileni tut** seçin: onay yine boş olmalı.
6. Satır içindeki **Yenile**'ye basın: önizleme yenilenmeli, eski onay taşınmamalı.
7. Önizlemeyi bekleyin, yeniden onay verin ve **Hedefin üzerine yaz**'a bir kez basın.
8. Android'de **Aktif Pakete eklendi** bekleyin. Tarayıcı **Etkinlik** ekranında
   **Dosya adı çakışması çözüldü**, ardından **Mevcut medyanın üzerine yazıldı** olayını bulun.
   Silinen kimlik, not ettiğiniz hedef olmalı; yeni kimlik farklı olmalıdır.
9. Aynı dosyayı Android'de tekrar seçin: bu kez hedef önizlemesi **mavi** olmalıdır.
   Bu son satırı **Hedefi tut** ile kapatın. Önceki numaralı kopya korunmalıdır.

Karar olayı tek başına gerçek üzerine yazmanın tamamlandığını kanıtlamaz.
Değiştirme yeni medyanın sunucuda doğrulanması sırasında yapılır; worker olayı
**Sistem** aktörüyle görünebilir. Başarısız medya hedefi başarıyla değiştirmiş sayılmaz.

## 7. Toplu kapsam ve Unicode adları

### 7.1. İki uyumlu satır değişsin, başka ad değişmesin

1. Tarayıcıdan `ilk/baska34.png` yükleyin; pakete eklenmesini bekleyin.
2. Android'de `yeni/rehber34.png` ve `ikinci/rehber34.png` dosyalarını ayrı
   seçimlerle ekleyin. İki çakışma da beklesin; karar vermeyin.
3. Android'de `farkli/baska34.png` seçin; üçüncü, başka adlı çakışma beklesin.
4. `rehber34.png` satırlarından birinde **Hedefi tut**, **Tüm uyumlu çakışmalara
   uygula**, ardından **Kararı uygula** seçin.
5. İki `rehber34.png` satırı atlanmalı; `baska34.png` çakışma olarak kalmalıdır.
   Kalan satırı toplu kutu kapalıyken ayrıca çözün.
6. Aynı iki `rehber34.png` dosyasını yeniden seçerek denemeyi **İkisini de tut**
   ile tekrarlayın: ikisi de eklenmeli, farklı boş numaralı adlar almalıdır.
7. Karardan sonra aynı dosyayı yeniden seçin: yeniden çakışma sormalı; önceki toplu
   karar varsayılan olarak saklanmamalıdır.

Toplu kapsam yalnız ekranda görünen satırlardan ibaret değildir; sunucudaki o
anda mevcut uyumlu çakışmaları kapsar. Ayrı deneme ortamı bu yüzden önemlidir.

### 7.2. Büyük/küçük harften daha güçlü eşleştirme

1. Tarayıcıdan `ilk/Straße.png` yükleyin; pakete eklenmesini bekleyin.
2. Android'de bu dosyayı ve `casefold/STRASSE.png` dosyasını ayrı seçimlerle ekleyin.
3. İkisinin de aynı hedefle çakışmasını bekleyin. Birinde **Hedefi tut** ve toplu
   kutuyla kararı uygulayın: ikisi de atlanmalıdır.

Bu örnek sunucunun Unicode normalleştirmesini sınar; Android yalnız kendi
büyük/küçük harf dönüşümüne göre toplu grubu seçmez.

**Toplu üzerine yazma:** Yalnız örnek medyada, iki uyumlu satırla tekrarlayabilirsiniz.
Ek toplu uyarıyı okuyun; önizlenen hedef kimliğini kaydedin ve açık onay verin.
Yüklemeler aynı seçilen hedefe göre çözülür; birinin başarısız olması mümkündür.
Her satırın sonucunu ve etkinliği ayrı kontrol edin; hepsinin aynı anda veya aynı
sonuçla biteceğini varsaymayın. Birden fazla hedefin gösterildiği gerçek bir deneme
veriniz varsa hedef değişince önizleme ve onayın sıfırlandığını da sınayın; böyle
veri yoksa bu alt kontrolü “denenmedi” kaydedin, manifest'i elle değiştirmeyin.

## 8. Önizleme hatası, yenileme ve video

### 8.1. Önizleme başarısızken üzerine yazma kapanmalı

1. Yeni Android çakışması oluşturun. Yalnız bu rehberin deneme backend'ini durdurun:

   ```powershell
   docker compose @ComposeArgs stop backend
   ```

2. Android satırındaki **Yenile**'ye basın. Ağ zaman aşımını bekleyin; önizleme
   hatası görünmeli, uygulama çökmemelidir. **Seçileni tut** için üzerine yazma
   kapalı kalmalıdır. Eski önizleme/onay yeni izin olarak kullanılmamalıdır.
3. Diğer iki karar önizleme şartı taşımaz; ancak sunucu kapalıyken kararın uygulanması
   beklenmez. Sunucuyu açın:

   ```powershell
   docker compose @ComposeArgs start backend
   ```

4. Önizleme alanında **Tekrar dene** veya satırda **Yenile** kullanın. Yüklenmiş
   önizleme ve yeni onayla üzerine yazma açılmalıdır. Denemeyi **Hedefi tut** ile kapatabilirsiniz.

Tarayıcı DevTools'taki Offline/istek engelleme yalnız tarayıcıyı etkiler; Android
trafiğini kesmiş sayılmaz. Bu durdurma denemesi kararın sunucuda uygulanıp yanıtın
kaybolduğu dar aralığı deterministik olarak üretmez; o kontrol bölüm 12'deki testlerdedir.

### 8.2. Video ve geçici dosya temizliği

1. Kişisel veri içermeyen, aynı adlı iki **geçerli** kısa MP4'ü ayrı klasörlerde
   hazırlayın. Farklı içerik kullanın; uzantı değiştirmek geçerli video oluşturmaz.
2. İlkini tarayıcıdan yükleyip pakete eklenmesini bekleyin; ikinciyi Android'de seçin.
3. Hedef MP4 önizlemesi hazırlanmalı; kendiliğinden oynatılmamalıdır. Önizlemeye
   dokunup yerel oynatma kontrollerini açın; oynat/duraklatı deneyin.
4. Ana Ekran'a gidin: oynatma duraklamalı. Geri dönün; çökme veya eski onay olmamalı.
5. Paket ekranından ayrılın. Debug kurulumunda özel önizleme dosyalarını salt okunur
   görmek için:

   ```powershell
   & $Adb -s $Serial shell run-as com.dojo.aisomedo ls -l cache/conflict-previews
   ```

6. İlgili önizlemenin geçici dosyası ayrılma sonrası kalmamalıdır. Başka açık
   önizlemeler varsa onların dosyaları bulunabilir. Dizin henüz oluşmamışsa
   `No such file or directory` normaldir; release APK'de `run-as` çalışmaz.

Önizleme sınırı işlenmiş JPEG için **10 MiB**, MP4 için **512 MiB**. Daha büyük,
yavaş veya çözülemeyen önizleme hata verebilir; bu, üzerine yazma izni sağlamaz.
Bozuk MP4'ün yerel oynatıcı hata/temizlik yolu canlı sunucuda geçerli medya olarak
oluşturulamaz; hazır `ConflictPreviewTest` bunu kontrollü yanıtla dener (bölüm 12).

## 9. Ekran değişimi, süreç ölümü ve erişilebilirlik

1. Yeni çakışmada üzerine yazma seçin; önizlemeyi yükleyip onay verin ama uygulamayın.
2. Telefonu döndürün; **Ayarlar → Paket** gidip dönün. Yeni ekranın onay kutusu
   boş olmalıdır. Kararın güvenli başlangıç seçeneğine dönmesi normaldir.
3. Yeni bir satırı **Hedefi tut** ile atlayın. Android **Ayarlar → Uygulamalar →
   Dojo Yayıncılık → Zorla durdur** kullanın ve uygulamayı kendiniz yeniden açın.
   Atlanmış satır korunmalı, tekrar yüklenmemelidir.
4. İsterseniz yalnız seçtiğiniz deneme emülatöründe aynı süreç denemesini yapın:

   ```powershell
   & $Adb -s $Serial shell am force-stop com.dojo.aisomedo
   & $Adb -s $Serial shell am start -n 'com.dojo.aisomedo/.MainActivity'
   ```

5. Telefon ve tablet emülatöründe açık/koyu tema, Android Ayarlar'dan büyük yazı
   (yaklaşık 1,3×) ve TalkBack ile tekrar deneyin. Uzun Türkçe ad, kimlik, uyarı,
   radyo seçenekleri ve kutular okunmalı; düğmeler kaydırmayla erişilebilir olmalı.
   TalkBack seçenekleri/kutuları ve durum değişimlerini ayırt edebilmelidir.
6. Emülatör ekran görüntüsü düğmesiyle sonuçları kaydedin; kod/token veya kişisel
   medya bulunmadığından emin olun. Tarayıcının mobil görünümü Android ekranı değildir.

Zorla durdurma sonrası uygulama kendiliğinden açılmamalıdır. Döndürme, süreç
ölümünün veya kayıp karar yanıtının tek başına kanıtı değildir.

## 10. Başka istemciden Android çakışmasını çözme

Android'in yerel bekleyen satırını tarayıcı arayüzü doğrudan yönetmez. Bunun için
aynı API'ye ayrı bir PowerShell tarayıcı oturumu açın; Android tokenını kopyalamayın.
Deneme **yalnız hedefi koruma** kararı verir; üzerine yazma yapmaz.

1. Android'de **tek bir yeni** `rehber34.png` çakışması oluşturun; karar vermeyin.
2. Yeni kod üretip PowerShell oturumunu eşleştirin:

   ```powershell
   docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
   $Base = 'http://localhost:8000'
   $Code = Read-Host 'Yeni tek kullanımlık deneme kodu'
   $Body = @{ code = $Code; kind = 'browser'; name = 'Android34 PowerShell Deneme' } | ConvertTo-Json
   Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/validate" -SessionVariable DojoSession -ContentType 'application/json' -Body $Body | Out-Null
   $Code = $null
   $Body = $null
   ```

3. Çakışmaları ve hedeflerini listeleyin. Yalnız kendi yeni örneğinizin kimliğini
   seçin; yükleme kimliği ile hedef medya kimliği farklıdır:

   ```powershell
   $Uploads = Invoke-RestMethod -Uri "$Base/api/media/uploads" -WebSession $DojoSession
   $Uploads | Where-Object { $_.status -eq 'conflict' } |
       Select-Object upload_id, received_bytes, @{Name='Hedefler'; Expression={ ($_.conflicts | ForEach-Object { $_.filename }) -join ', ' }} |
       Format-Table -AutoSize
   $UploadId = Read-Host 'Yalnız yeni Android deneme satırının upload_id değeri'
   $EncodedId = [Uri]::EscapeDataString($UploadId)
   $Current = Invoke-RestMethod -Uri "$Base/api/media/uploads/$EncodedId" -WebSession $DojoSession
   if ($Current.status -ne 'conflict') { throw 'Satır artık çakışma değil; karar göndermeyin.' }
   $Current.conflicts | Select-Object media_id, filename, size_bytes, uploaded_at
   ```

4. Listelenen hedef gerçekten deneme dosyanızsa onaylayıp **bir kez** uygulayın:

   ```powershell
   if ((Read-Host 'Bu yalnız kendi deneme yüklemeniz mi? EVET yazın') -cne 'EVET') { throw 'İşlem iptal edildi.' }
   $Decision = @{ decision = 'keep_target'; apply_to_all = $false; confirmed_overwrite = $false } | ConvertTo-Json
   Invoke-RestMethod -Method Post -Uri "$Base/api/media/uploads/$EncodedId/resolve" -WebSession $DojoSession -ContentType 'application/json' -Body $Decision | Out-Null
   ```

5. Android'de satır içindeki **Yenile**'ye basın veya uygulamayı arka plana gönderip
   tekrar açın. **Hedef korundu; seçilen dosya yüklenmedi** beklenir; süre dolması
   veya **Tekrar dene** olmamalıdır.

Komutun yanıtı kaybolursa POST'u tekrar çalıştırmayın. Bölüm 11'den durumu ve
etkinliği okuyun. `aborted` tek başına atlandı demek değildir; Android
`conflict.resolved` + `keep_target` etkinliğiyle ayrım yapar. Durum ve etkinlik
yazımı arasında kısa fark olabilir; sonucu bekleyip yenileyin.

## 11. Sunucu sonucunu salt okunur kontrol edin

Bu bölümde bölüm 10'daki `$Base`, `$DojoSession`, `$UploadId`, `$EncodedId`
değişkenleri kullanılır. Yeni satır için listeleme/seçme bloğunu tekrar çalıştırın;
karar bloğunu çalıştırmanız gerekmez. Kod/çerez/token ekrana yazdırılmaz.

```powershell
$State = Invoke-RestMethod -Uri "$Base/api/media/uploads/$EncodedId" -WebSession $DojoSession
$State | Select-Object upload_id, status, received_bytes, declared_size_bytes, package_id
$State.received_ranges | ConvertTo-Json -Depth 4
$Cursor = $null
do {
    $Uri = "$Base/api/activity?limit=100"
    if ($null -ne $Cursor) { $Uri += "&before_id=$Cursor" }
    $Page = Invoke-RestMethod -Uri $Uri -WebSession $DojoSession
    $Page.events | Where-Object { $_.details.upload_id -eq $UploadId } |
        Select-Object action, occurred_at, @{Name='Karar'; Expression={ $_.details.decision }}, @{Name='Hedef'; Expression={ $_.details.target_media_id }}
    $Next = $Page.next_cursor
    if ($null -ne $Next -and ($Next -le 0 -or ($null -ne $Cursor -and $Next -ge $Cursor))) {
        throw 'Geçersiz etkinlik sayfalama yanıtı.'
    }
    $Cursor = $Next
} while ($null -ne $Cursor)
```

- Karar öncesi: `conflict`, sıfır kabul edilmiş bayt.
- İkisini de tut/seçileni tut: `receiving → queued/processing → finalized` beklenir;
  çok hızlı adımlar gözden kaçabilir. Son medya/kimliği tarayıcı paketinden kontrol edin.
- Hedefi tut: `aborted` ve ilgili `conflict.resolved` olayında `keep_target`; bayt
  ilerlememelidir. Android bunu atlandı olarak gösterir.
- Yeni kimlik/son ad/gerçek üzerine yazma: tarayıcı **Güncel Paket** ve **Etkinlik**
  ekranlarından kontrol edilir; manifest düzenlemek veya veritabanı sorgusu gerekmez.

Bu sorgular hiç ikinci PUT/POST yapılmadığını tek başına kanıtlamaz. Kayıp yanıt,
408/429, eski eşleştirme yanıtları ve yarışların deterministik kanıtı hazır
testlerdedir. Büyük etkinlik geçmişinde sayfalama zaman alabilir.

## 12. Arayüzden güvenilir üretilemeyen durumlar — hazır testler

PowerShell'den mevcut testleri çalıştırın; test kodu yazmanız gerekmez:

```powershell
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
if ($LASTEXITCODE -ne 0) { throw 'Android doğrulaması başarısız.' }
Start-Process 'android/app/build/reports/tests/testDebugUnitTest/index.html'
```

Hazır birim testleri: yanıtın başka toplu satıra ait olması, kayıp yanıt sonrası
POST tekrarlamama, değişmeyen çakışma/yeniden başlatma, 408/429, 404, etkinliğin
geç yazılması, başkasının kararı, eski eşleştirme, geçersiz hedef, önizleme sınırı,
yönlendirme ve iptal temizliği. Bunlar gerçek video oynatımı/TalkBack yerine geçmez.

**Yalnız boş ayrı emülatörde**, onu açıp kilidini kaldırdıktan sonra:

```powershell
& $Adb devices -l
$env:ANDROID_SERIAL = Read-Host 'Yalnız boş test emülatörünün seri numarası'
./android/gradlew.bat -p android :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.UploadPanelTest,com.dojo.aisomedo.ui.ConflictPreviewTest'
if ($LASTEXITCODE -ne 0) { throw 'Cihaz testleri başarısız; raporu inceleyin.' }
Start-Process 'android/app/build/reports/androidTests/connected/debug/index.html'
```

Bu Compose testleri yüklü önizleme/onay, dar ekran kontrolü, yenileme sıralaması,
revizyon değişiminde iptalden kurtarma ve çözülemeyen video temizliğini dener.
Test çalıştırma kurulum/eşleştirme verilerini etkileyebilir; kişisel kurulumda
kullanmayın. `No connected devices!` cihaz kanıtı değildir. Bütün instrumentation
paketini çalıştırmak isterseniz sınıf filtresini kaldırın; yine ayrı emülatör kullanın.

Bu rehberi yazarken Docker kurulumunu, cihaz kurulumunu veya canlı kararları
çalıştırmadık. Girintili bloklar dahil **20 PowerShell bloğu** sözdizimi açısından
kontrol edildi; yerel belge bağlantıları da doğrulandı. Bu, komutların sunucunuzda
başarıyla yürütüldüğü anlamına gelmez. ADB başvuru:
[Android Developers](https://developer.android.com/tools/adb).

## 13. Sorunlar, sonuç kaydı ve kapatma

| Gözlem | Kontrol |
| --- | --- |
| Android hâlâ webden çözün diyor | #34 kodundan APK derleyip aynı imzalı debug kurulumu güncelleyin. |
| Çakışma oluşmuyor | İlk dosya gerçekten pakete eklenmiş, aynı aktif pakette ve aynı normalleştirilmiş adda mı? |
| Önizleme yeni dosya gibi | İçerikleri farklı örnekler kullanın; üzerine yazma denemesinden sonra mevcut hedefin mavi olması normaldir. |
| Üzerine yazma kapalı | Geçerli hedef, hazırlanmış önizleme, yeni onay ve kesinleşmiş önceki karar sonucu gerekir. |
| Karar sonucu doğrulanamadı | **Yenile** kullanın; aynı kararı yeniden göndermeyin. Bağlantı/etkinlik düzelmeden kilit açık kalabilir. |
| %100 ama hedef değişmedi | Worker doğrulama sonucunu ve gerçek üzerine yazma etkinliğini bekleyin. |
| Başka istemcinin kararı görünmedi | Android satır içindeki **Yenile**, uygulamaya dönüş; API/etkinlik erişimini kontrol edin. |
| Video yüklenmiyor | Geçerli işlenmiş MP4, bağlantı, cihaz çözücüsü ve 512 MiB önizleme sınırı; hata üzerine yazmayı açmamalı. |
| 401 veya güncelleme istiyor | Eşleştirme ve sunucunun Android minimum sürümünü kontrol edin; gerçek ortam ayarını düşürmeyin. |

Her senaryo için cihaz/API, beklenen/görülen sonuç, ilgili deneme kimliği ve
gerekirse ekran görüntüsü kaydedin:

- [ ] Hedef fotoğraf/video doğru; önizleme yeni dosya değil.
- [ ] İkisini de tut ayrı numaralı medya ekliyor.
- [ ] Hedefi tut atlanmış kalıyor; yeniden açılışta tekrar deneme yok.
- [ ] Üzerine yazma yalnız yüklenmiş önizleme ve taze onayla mümkün.
- [ ] Toplu işlem uyumlu satırları kapsıyor, ilgisiz/sonraki satırları kapsamıyor.
- [ ] Unicode adlar ve başka istemciden hedefi koruma kurtarılıyor.
- [ ] Önizleme hata/yenileme/ayrılma, video duraklatma ve temizlik doğru.
- [ ] Telefon/tablet, tema, büyük yazı ve TalkBack sonucu kaydedildi.
- [ ] Hazır testlerin sonucu ve denenemeyen alt senaryolar açıkça kaydedildi.

Yalnız bu rehberin deneme servislerini verileri silmeden durdurun; Vite
penceresinde `Ctrl+C` kullanın:

```powershell
docker compose @ComposeArgs stop worker backend db
$DojoSession = $null
```

`down -v`, uygulama verilerini temizleme veya medya/veritabanı silme gerekmez.
Canlı Android kabulü ve bağımsız takip incelemesi bitmeden #34'ü kapatılmış saymayın.
[Ayrıntılı doğrulama kaydı](../verification/issue-34-android-conflicts.md).
