# Android devam edebilir medya yükleme — değişiklik özeti ve deneme rehberi (#33)

Bu rehber yapılan değişiklikleri ve bunları **Android uygulamasında** adım adım
nasıl deneyebileceğinizi anlatır. **Tarayıcı** ortak paketi ve sunucu sonucunu
kontrol etmek için kullanılır. Arayüzde yapılamayan hazırlık ve gözlem işlemleri
**PowerShell** komutlarıyla verilir; Python veya SQL kodu yazmanız gerekmez.

> **Durum:** Bu dalda 66 Android birim testi ve 205 backend testi geçti; APK
> derlemeleri ve lint geçti. Bağlı cihaz/emülatör olmadığı için gerçek arka plan,
> ekran kapalı ve arayüz denemeleri yapılmadı. Bağımsız incelemede henüz
> düzeltilmemiş sorunlar bulundu; bölüm 12'yi okuyun. Aşağıdaki “beklenen” sonuçlar
> test ölçütüdür, önceden doğrulanmış başarı iddiası değildir.

> **Yalnız ayrı deneme ortamında çalışın.** Gerçek öğrenci medyası, üretim cihazı
> veya canlı eşleştirme kullanmayın. Planı etkinleştirmeyin, yayın onayı vermeyin,
> Instagram bağlantısı kurmayın. Dosya/paket sınırları tüm istemcileri etkiler.
> Kodları, çerezleri ve `.env` içeriğini paylaşmayın. Rehber orijinal medyayı veya
> veritabanını silmenizi istemez.

## 1. Neler değişti?

| Değişiklik | Deneyebileceğiniz sonuç |
| --- | --- |
| Android Aktif Paket yükleme alanı | Birden fazla fotoğraf/video seçme; ilerleme ve satır başına kontrol |
| Kalıcı dosya erişimi ve kuyruk | Uygulama dışında çalışabilen aktarım; dosyanın tamamını özel depoya kopyalamama |
| 2 MiB parçalar ve SHA-256 doğrulaması | Aynı adlı farklı içerik eski yüklemeye karışmaz |
| Sunucu durumuyla devam etme | Bilinen yükleme kimliği korunur; tamamen kabul edilmiş parçalar atlanır |
| Duraklat / Devam et / Tekrar dene | Duraklatma kalıcıdır; diğer uygun dosyalar devam eder |
| Arka plan işi | Android 14+ UIDT, Android 10–13 ön plan WorkManager |
| Türkçe yükleme bildirimi | Dosya/ilerleme, Duraklat işlemi ve Paket ekranına dönüş |
| Aktarım öncesi boyut kontrolü | Boş veya dosya sınırını aşan medya aktarılmadan reddedilir |
| Kalıcı eşleştirme bağı | Yeni eşleştirme eski kuyruğu devralmaz; eski yanıt yeni kimliği silmemelidir |
| Büyük dosya sözleşmesi | Bayt, ilerleme ve parça konumları `Long`; 2 GiB değeri desteklenir |
| Sonucun ayrılması | %100 aktarım ile sunucuda işlenme/pakete eklenme aynı şey değildir |

**Kapsam dışı:** Android montaj, render/yayın onayı ve dosya çakışmasını çözme
ekranları. Tarayıcı zaten ayrı bir yükleme istemcisine sahiptir; tarayıcıda yükleme
başarmak Android'in arka plan işini doğrulamaz.

## 2. Doğru dal ve deneme sunucusu

Bu değişiklikleri içeren ayrı deneme sunucunuz varsa bölüm 3'e geçin.
Yeni ortam için Docker Desktop'ın Linux motoru, Node.js/npm, Android Studio,
SDK 35 ve Android 10/API 29+ cihaz/emülatör gerekir. Arka plan kabulü için ayrı
API 33 ve API 34+ emülatörlerde tekrarlayın.

PowerShell'i bu worktree'de açın; başka bilgisayarda yolu değiştirin:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo\.worktrees\issue-33-android-upload'
git branch --show-current
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-android33-deneme', '-f', 'ops/docker-compose.yml')
docker info --format '{{.ServerVersion}}'
```

Beklenen dal: `feat/issue-33-android-upload`. Her yeni PowerShell penceresinde
aynı dizini ve `$ComposeArgs` değerini tanımlayın.

`8000`, `5434`, `3000` portları başka ortam tarafından kullanılmamalıdır.
Compose proje adı **tek başına verileri ayırmaz**: `ops/db-data` ve
`ops/media-data` bu worktree'ye bağlıdır. İlk kurulumdan önce kontrol edin:

```powershell
foreach ($Path in 'ops/db-data', 'ops/media-data') {
    if ((Test-Path -LiteralPath $Path) -and
        (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1)) {
        throw "$Path boş değil. Silmeyin; ayrı, temiz bir deneme dizini kullanın."
    }
}
if (-not (Test-Path -LiteralPath ops/.env)) {
    Copy-Item -LiteralPath ops/.env.example -Destination ops/.env
}
notepad ops/.env
```

Kendi deneme ortamınızı yeniden açarken dizinlerin dolu olması normaldir;
boşluk kontrolü yalnız ilk kurulum içindir. Not Defteri'nde bu yerel ortam için:

- `POSTGRES_PASSWORD`: denemeye özel, boş olmayan parola; yerel denemede
  harf/rakam kullanmak bağlantı adresindeki özel karakter sorunlarını önler.
- `COOKIE_SECURE=false`: yalnız yerel HTTP denemesi için.
- `PUBLIC_BASE_URL=http://localhost:3000`
- `PUBLIC_HTTPS_ORIGIN=http://localhost:3000`
- `ANDROID_CURRENT_VERSION_CODE=5`, `ANDROID_MIN_VERSION_CODE=1`.
- Meta/Instagram kimlik bilgisi bu yükleme denemesi için gerekli değildir.

Sunucunun kullandığı şifreleme anahtarı yine gereklidir. Boş
`META_TOKEN_ENCRYPTION_KEY` satırını aşağıdaki PowerShell ile doldurun; mevcut
anahtarı değiştirmez ve anahtarı ekrana yazdırmaz:

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
    $Key = $null
    $Bytes = $null
    $Content = $null
}
```

Kaydedin; başlangıçta worker'ı çalıştırmayın:

```powershell
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose @ComposeArgs up -d --build db backend
if ($LASTEXITCODE -ne 0) { throw 'Deneme sunucusu başlatılamadı.' }
Invoke-RestMethod -Uri 'http://localhost:8000/health'
Invoke-RestMethod -Uri 'http://localhost:8000/api/compat'
```

Sağlık yanıtı `ok` olmalı. Sunucu henüz açılıyorsa biraz bekleyip sorguyu tekrar
çalıştırın. Tarayıcı için ayrı pencerede aynı repo kökünden:

```powershell
npm --prefix web ci
npm --prefix web run dev -- --host localhost --port 3000 --strictPort
```

Terminali açık bırakın; `http://localhost:3000` adresini açın. `8000` API portudur,
web ekranı değildir. Deneme boyunca tarayıcıda aynı origin'i kullanın.

## 3. Android APK'yi kurun ve cihazı eşleştirin

**Android Studio yolu:** Worktree'nin `android` klasörünü açın, SDK 35 kurulu
olsun, Device Manager'dan deneme emülatörünü başlatın ve **app → Run** kullanın.
Üretim uygulamasının üzerine kurmayın; imza uyuşmazlığında onu kaldırmayın.

**PowerShell alternatifi:** Android SDK yolunuz farklıysa `$Sdk` değerini değiştirin.

```powershell
$Sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_HOME = $Sdk
$Adb = Join-Path $Sdk 'platform-tools\adb.exe'
./android/gradlew.bat -p android :app:assembleDebug
if ($LASTEXITCODE -ne 0) { throw 'APK derlenemedi.' }
& $Adb devices -l
$Serial = Read-Host 'Listede device durumundaki deneme emülatörünün seri numarası'
& $Adb -s $Serial install -r 'android/app/build/outputs/apk/debug/app-debug.apk'
if ($LASTEXITCODE -ne 0) { throw 'APK kurulamadı.' }
& $Adb -s $Serial shell am start -n 'com.dojo.aisomedo/.MainActivity'
```

İlk derlemede JDK/bağımlılık indirmesi gerekebilir. SDK/JDK hatasında önce Android
Studio'da eşitlemeyi tamamlayın. `install -r` mevcut debug verilerini korur.

Uygulamadaki **sunucu adresi**:

| Bağlantı | Adres |
| --- | --- |
| Emülatör, backend aynı bilgisayarda | `http://10.0.2.2:8000` |
| USB bağlı deneme cihazı ve aşağıdaki yönlendirme | `http://127.0.0.1:8000` |
| Uzak deneme sunucusu | Kendi `https://...` origin'iniz |

USB ile yerel debug cihaz için gerekiyorsa:

```powershell
& $Adb -s $Serial reverse tcp:8000 tcp:8000
```

HTTP yalnız debug APK'de serbesttir. Adrese `/api`, kullanıcı/parola veya sorgu
eklemeyin. Emülatörde `localhost` bilgisayarınız değildir.

1. Android'de adresi girip **Bağlan**'a basın.
2. PowerShell'de tek kullanımlık kod üretin:

   ```powershell
   docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
   ```

3. **Cihaz adı** olarak `Android Upload33 Deneme` yazın; kodu girip **Eşleştir**'e basın.
4. Kurulum açılırsa **Şimdilik kontrol paneline dön** ile çıkın; **Paket**'e geçin.
   Yükleme için Instagram kurulumu veya yayın onayı gerekmiyor.
5. **Aktif Paket** altında **Fotoğraf/video seç** düğmesini bulun.
6. Tarayıcıyı da eşleştirmek için **yeni kod** üretin. Tarayıcıda eşleştirmeden
   sonra **Güncel Paket** veya `http://localhost:3000/#/package` bölümünü açın.

Android'de seçilen dosyanın Android'e özel yerel satırı tarayıcıda birebir
görünmek zorunda değildir. Tarayıcıdan ortak paket/medya sonucunu karşılaştırın.

## 4. İlk aktarım: hazırlık, ilerleme ve sunucu sonucu

1. Kişisel veri içermeyen geçerli bir JPEG/PNG ve 20–100 MiB veya daha büyük bir
   MP4 hazırlayın. Denemelerde farklı dosya adları kullanın; kopyaları cihazın
   **Download/İndirilenler** klasörüne koyabilirsiniz.
2. Android'de **Fotoğraf/video seç** ile ikisini seçin. Seçici içinde **Dosyalar**
   gibi kalıcı erişim sağlayan bir kaynak kullanın. Android 13+ bildirim iznini verin.
3. **Dosya doğrulanıyor; henüz aktarım değil** durumunu izleyin. Hazırlık sırasında
   dosya okunur; bu, yükleme yüzdesi değildir.
4. **Aktarılıyor** sırasında bayt/yüzde artmalı; sıradaki uygun dosya beklemelidir.
5. Worker kapalıyken sonuç **Aktarım bitti; sunucuda sırada** olmalıdır.
   %100 aktarım, **Aktif Pakete eklendi** demek değildir.
6. Medya işleme sonucunu görmek için yalnız deneme ortamında:

   ```powershell
   docker compose @ComposeArgs up -d --build worker
   ```

7. İşleme süresini bekleyin. Tarayıcıda paketi kontrol edin. Android'de uygulamayı
   arka plana gönderip yeniden açarak durum sorgusu yaptırın; **Yenile** düğmesinin
   yükleme satırını güncellememesi mevcut bilinen sorundur (bölüm 12).

**Beklenen:** Geçerli medya sunucuda doğrulanınca **Aktif Pakete eklendi** görünür
ve paket özeti güncellenir. Geçersiz medya hata verir. Worker'ı açmak tek başına
Instagram'a yayın talimatı değildir; yine de yalnız boş deneme ortamında çalışın.

## 5. Uygulama dışında ve ekran kapalı devam etme

1. Yeni adla, aktarımı birkaç saniyeden uzun süren büyük bir video seçin.
2. **Aktarılıyor** durumunda ilerlemeyi not edin.
3. Telefonun Ana Ekran düğmesine basın; başka bir uygulamayı açın. Dojo'yu
   zorla durdurmayın.
4. Bildirim perdesini açın. Dosya/ilerleme ve **Duraklat** işlemi görünmeli.
5. Ekranı kapatıp 20–30 saniye bekleyin; ekranı açarak bildirimi kontrol edin.
6. Bildirime dokunun: Android **Paket** bölümüne dönmeli.

**Beklenen:** Aktarım, Android'in ağ/pil/sistem kısıtlamaları izin verdiği sürece
devam eder. Dosya çok hızlı bitmişse daha büyük dosyayla tekrarlayın. Bildirimdeki
yüzdeyi tek kanıt saymayın: bölüm 10'daki sunucu sorgusu ile Ana Ekran ve ekran
kapalıyken `received_bytes` artışını ölçebilirsiniz.

Tarayıcı geliştirici araçlarındaki **Offline/Slow 3G**, Android trafiğini etkilemez.
API 33 ve API 34+ sonuçlarını ayrı kaydedin; biri diğerini doğrulamaz.

## 6. Duraklatma, sıradaki dosya ve kalıcı devam

1. İki yeni video seçin; ilk dosya aktarılırken satırındaki **Duraklat**'a basın.
2. İlk satır **Duraklatıldı / Devam et** göstermeli. İkinci uygun dosya devam etmeli.
3. **Ayarlar**'a gidip **Paket**'e dönün; ilk dosya kendiliğinden başlamamalı.
4. Telefonu döndürün; aynı satır/ilerleme kalmalı.
5. İlk satırda **Devam et**'e basın.
6. Başka büyük bir dosyayla bu kez bildirimin **Duraklat** işlemini deneyin.

**Beklenen:** Aynı sunucu yükleme kimliğiyle devam edilir. Sunucuda tamamen kabul
edilmiş 2 MiB parçalar tekrar gönderilmez. Duraklatma anında yolda olan parça
sunucuda kabul edilmiş olabilir; devam ederken bu durum uzlaştırılır.

Uygulama süreci soğukken bildirimin Duraklat işleminin kaybolması mevcut inceleme
bulgusudur. Bunu başarılı kabul etmeyin; soğuk başlatma testi için bölüm 12'ye bakın.

## 7. Bağlantı kesilmesi, tekrar deneme ve zorla durdurma

### 7.1. Bağlantı kesilmesi

1. Yeni büyük video aktarımını başlatın, birkaç MiB ilerlediğini not edin.
2. Gerçek deneme cihazında Wi-Fi ve mobil veriyi kapatın; aktarım durmalı veya
   bağlantı/yeniden deneme durumu göstermelidir.
3. Ağı geri açın. Otomatik yeniden denemeyi bekleyin veya **Tekrar dene** kullanın.
4. Aynı yükleme kimliğinin korunduğunu bölüm 10'dan kontrol edin.

Emülatörün yerel bağlantısını cihaz ayarlarıyla kesemiyorsanız, **yalnız bu
rehberde kurduğunuz deneme backend'ini** geçici durdurup yeniden açın:

```powershell
docker compose @ComposeArgs stop backend
# Android'in bağlantı hatasını göstermesini bekleyin; sonra:
docker compose @ComposeArgs start backend
```

Veritabanı ve medya dizinlerini silmeyin. Başlatma yanıtı kaybolmuş ve kimlik
alınamamışsa açık yeniden deneme gerekir; boş bir sunucu kaydı kalabilir.
Bilinen kimlikteki bağlantı kaybı, sıfırdan yeni yükleme oluşturma gerekçesi değildir.
Beş ardışık geçici hatadan sonra otomatik deneme bırakılır; kullanıcı tekrar denemelidir.

### 7.2. Zorla durdurma — yalnız deneme cihazı

1. Bir miktar ilerleyen yeni aktarımın kimlik/bayt bilgisini not edin.
2. Android **Ayarlar → Uygulamalar → Dojo Yayıncılık → Zorla durdur** kullanın.
3. Bekleyin: uygulama kendiliğinden açılmamalı veya bu kararı aşmamalıdır.
4. Dojo'yu **kendiniz** açın; gerekiyorsa **Devam et / Tekrar dene**'ye basın.
5. Aynı kimliği ve önceden kabul edilmiş baytları kontrol edin.

Bu işlem Activity döndürmekten farklıdır. Sadece döndürme/ekran değişimiyle
gerçek süreç ölümü ve kalıcı kurtarma doğrulanmış sayılmaz.

## 8. Boyut/paket sınırı ve dosya adı çakışması

### 8.1. Dosya sınırı: aktarım başlamadan ret

Önce bölüm 10'dan mevcut dosya/paket sınırlarını not edin. Limit değiştiren ekran
olmadığı için yalnız deneme sunucusunda PowerShell kullanın:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-settings set-upload-limits --max-file-bytes 1048576
```

1. Android'de 1 MiB'den büyük yeni dosya seçin.
2. Boş/büyük dosya uyarısı bekleyin; yeni dosyanın medya baytları gönderilmemeli.
3. Bölüm 10'dan sunucu kayıtlarına bakın: bu reddedilen dosya için yeni yükleme
   başlatılmaması beklenir. Limits/kimlik sorguları normaldir.
4. Önceki dosya sınırını geri yükleyin; eski değer gerçekten varsayılan 2 GiB ise:

   ```powershell
   docker compose @ComposeArgs exec backend .venv/bin/dojo-settings set-upload-limits --max-file-bytes 2147483648
   ```

Boş dosya da seçilebiliyorsa sıfır baytlı kopyayla deneyin. Geçerli 2 GiB+ medya
oluşturmanız şart değildir; `Long` sözleşmesinin otomatik kontrolü bölüm 11'dedir.

### 8.2. Paket kapasitesi

Yalnız ayrı deneme ortamında mevcut paket sınırını not edip geçici küçültün:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-settings set-upload-limits --max-package-bytes 1048576
```

Dosya sınırını aşmayan fakat paket için büyük yeni medya seçin. Kapasite uyarısı
ve **sıfır parça aktarımı** bekleyin. Sonra kaydettiğiniz eski paket sınırını geri
yükleyin; eski değer gerçekten varsayılan 20 GiB ise:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-settings set-upload-limits --max-package-bytes 21474836480
```

### 8.3. Dosya adı çakışması

1. Önce bir dosyayı sunucuda işlenip pakete eklenene kadar yükleyin.
2. Tarayıcıdan aynı adla farklı içerik yükleyerek veya Android'de aynı adı taşıyan
   başka deneme medyası seçerek çakışma oluşturun.
3. Android'de **Dosya adı çakışıyor…** açıklaması görünmeli; otomatik üzerine yazma
   veya otomatik yeni yükleme olmamalıdır.
4. Çözmek isterseniz tarayıcıdaki mevcut çakışma ekranını kullanın:
   [web çakışma rehberi](issue-28-web-dosya-cakismasi-deneme-rehberi.md).

## 9. Bildirim izni, dosya erişimi ve listeden kaldırma

### 9.1. Bildirim izni

Android 13+ cihazda **Ayarlar → Uygulamalar → Dojo Yayıncılık → Bildirimler**
bölümünden izni kapatın. Yeni yükleme deneyin. Çökme olmamalı; görünür bildirim
varmış gibi davranılmamalı. Uygulamada **Bildirim ayarlarını aç** ile izni tekrar
verin ve denemeyi tekrarlayın. Android yine de görev yöneticisinde işi gösterebilir.

### 9.2. Orijinal dosyayı yeniden seçme

1. Yüklemeyi duraklatın. **Deneme kopyasının** erişimini kaldırın veya sağlayıcıda
   taşıyın; orijinal/gerçek kullanıcı dosyasına dokunmayın.
2. Devam etmeyi deneyin. **Orijinal dosyayı seç** gerektiren durum bekleyin.
3. Önce farklı içerik seçin: mevcut yüklemeye karışmamalıdır.
4. Gerçek deneme kopyasıyla aynı içeriği yeniden seçin. Bilinen kimlik varsa
   korunmalıdır. Aynı ad/boyut tek başına eşleşme sayılmaz.

Sağlayıcı yanlış boyut bildirip henüz kimlik oluşmadan hata verdiyse, doğru
sağlayıcıdan yeniden seçim mevcut dalda yine takılabilir; bölüm 12'de kayıtlıdır.

### 9.3. Aynı dosyanın iki satırda kullanılması

1. Worker kapalıyken aynı URI/dosyayı iki kez seçip iki satır oluşturun.
2. Aktarım bittikten veya satırları duraklattıktan sonra birini **Listeden kaldır** ile kaldırın.
3. Diğer satır dosyaya erişebilmeli; Android Dosyalar uygulamasında dosya hâlâ durmalı.
4. İkinci satır da kaldırıldığında orijinal medya yine silinmemelidir.

**Not:** Otomatik tekrar bekleyen satırda Listeden kaldır görünmesine rağmen
işlem yapılmaması bilinen sorundur. Terminal veya duraklatılmış satırla bu denemeyi yapın.

## 10. PowerShell ile sunucunun kabul ettiği baytları gözleme

Bu bölüm arka planı ve “aynı kimlikle devam” davranışını arayüz animasyonuna
bağlı kalmadan ölçer. Ayrı, **yeni bir kod** üretin; Android'in veya tarayıcının
önceden kullandığı kodu tekrar kullanmayın:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
$Base = 'http://localhost:8000'
$Code = Read-Host 'Yeni tek kullanımlık deneme kodu'
$Body = @{ code = $Code; kind = 'browser'; name = 'Upload33 PowerShell gozlem' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/validate" -SessionVariable DojoSession -ContentType 'application/json' -Body $Body | Out-Null
$Code = $null
$Body = $null
$Limits = Invoke-RestMethod -Uri "$Base/api/media/upload-limits" -WebSession $DojoSession
$Limits | Select-Object max_file_bytes, max_package_bytes, active_package_id
```

Çerez yalnız PowerShell oturumunda tutulur; token/çerez yazdırmayın.
Uzak sunucuda `$Base` değerini kendi deneme HTTPS adresinizle değiştirin.
Android'de aktarım sürerken:

```powershell
(Invoke-RestMethod -Uri "$Base/api/media/uploads" -WebSession $DojoSession) |
    Select-Object upload_id, status, received_bytes, declared_size_bytes
$UploadId = Read-Host 'Deneme dosyanızın upload_id değeri'
$EncodedId = [Uri]::EscapeDataString($UploadId)
$Before = Invoke-RestMethod -Uri "$Base/api/media/uploads/$EncodedId" -WebSession $DojoSession
$Before | Select-Object upload_id, status, received_bytes, declared_size_bytes
```

Ana Ekran'a geçin veya ekranı kapatın, birkaç saniye bekleyin; aynı sorguyu tekrarlayın:

```powershell
$After = Invoke-RestMethod -Uri "$Base/api/media/uploads/$EncodedId" -WebSession $DojoSession
$After | Select-Object upload_id, status, received_bytes, declared_size_bytes
"Kabul edilen yeni bayt: $($After.received_bytes - $Before.received_bytes)"
$After.received_ranges | ConvertTo-Json -Depth 4
```

**Beklenen:** Aktarım henüz bitmemişken pozitif bayt artışı; duraklatıldıktan sonra
yeni parçalar başlamaması; devam/bağlantı dönüşünde aynı `upload_id`. Son durum
sorgusunda `queued/processing/finalized` değerlerini ayırın. Terminal kayıt aktif
listeden çıkabilir; kaydettiğiniz kimliğin tekil durum sorgusunu kullanın.

Bu sorgular kabul edilmiş kapsamı gösterir; hiç tekrar PUT yapılmadığını tek
başına kanıtlamaz. Parça isteği/konumunu kesin kanıtlamak için otomatik test veya
deneme sunucusu istek kaydı gerekir. Başka istemcinin kişisel dosyasını sorgulamayın.

## 11. Otomatik kontroller — PowerShell

Bu komutlar hazır testleri çalıştırır; test kodu yazmanız gerekmez:

```powershell
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
if ($LASTEXITCODE -ne 0) { throw 'Android ana makine kontrolü başarısız.' }
```

Rapor: `android/app/build/reports/tests/testDebugUnitTest/index.html`.
Testler 2 GiB değerlerini, kimlik/duraklatma yarışı, kayıp yanıt ve bilinen
kimlikte devam etmeyi cihaz olmadan kontrol eder. Gerçek arka plan kabulünü kanıtlamaz.

**Instrumentation yalnız boş, ayrı test emülatöründe:** Testler hedef uygulamanın
eşleştirme durumunu değiştirebilir. Kişisel/üretim kurulumunda çalıştırmayın.
İncelemede test sağlayıcısının APK/izin sınırı ve sistem-durdurma kanıtı sorunları
bulunduğu için mevcut sürümde başarısız veya yetersiz olabilir (bölüm 12).

```powershell
$env:ANDROID_SERIAL = $Serial
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
```

Sonuçları API 33 ve API 34+ için ayrı kaydedin. **No connected devices!** testin
başarısız ortam kontrolüdür; arka plan özelliğinin çalıştığını göstermez.

## 12. Mevcut inceleme bulguları ve doğrulama sınırı

Bu rehberin yazıldığı anda aşağıdakiler **henüz düzeltilmemiştir**:

| Bulgu | Denemeye etkisi |
| --- | --- |
| Yükleme durum yenilemesi ve aktarımın ortak kilidi | Açılışta durum sorgusu sürerken arka plan işi boş sanılarak bitebilir; başka kullanıcı eylemi gerekebilir |
| Paket'teki Yenile yalnız genel modeli yeniliyor | Satır queued/processing kalabilir; arka plana geçip dönüş geçici alternatif, garantili düzeltme değil |
| Soğuk süreçte bildirim Duraklat | Yerel satırlar henüz görünür değilse işlem kaybolabilir; kalıcı işlem broadcast ömrüyle korunmuyor |
| İlk hazırlıktaki yanlış sağlayıcı boyutu | Yeniden seçim eski yanlış boyutu taşıyabilir; aynı içerik kabul edilmeyebilir |
| Instrumentation belge sağlayıcısı APK/izin sınırı | Test kurulumu gerçek aktarımı denemeden hata verebilir |
| Otomatik sistem-durdurma testi | İş gerçekten çalışırken durduğunu kanıtlamadan yalnız yeniden denemeyle geçebilir |
| İlerleme erişilebilirlik bağlamı | TalkBack'te birden fazla çubuğun dosya adıyla ayrılması yetersiz |
| Otomatik tekrar satırında kaldırma | Düğme görünürken işlem etkisiz kalabilir |

Gerçek cihazda bu sorunları görürseniz sonucu “başarılı” saymayın. Rehber, bu
bulguların çözülmüş olduğunu veya dalın birleştirmeye hazır olduğunu söylemez.
Ekran kapalı çalışma, süreç ölümü, gerçek SAF izinleri, bildirim kısıtlamaları
ve telefon/tablet görselleri cihazda ayrıca doğrulanmalıdır.

## 13. Sonuç kaydı ve denemeyi durdurma

Her senaryo için cihaz/API, dosya boyutu, beklenen/görülen sonuç ve başarısızlık
notunu yazın. Kimlik/bayt bilgisiyle ekran görüntüsü paylaşırken kod/çerez/token
ve kişisel dosya adlarını gizleyin.

- [ ] Küçük medya aktarımı ve queued/finalized ayrımı
- [ ] Ana Ekran ve ekran kapalıyken sunucuda bayt artışı
- [ ] Uygulama ve bildirimden kalıcı duraklatma; sıradaki dosyanın devamı
- [ ] Ağ kesintisi ve kullanıcı tarafından yeniden açılışta aynı kimlikle devam
- [ ] Büyük/boş dosyanın parça göndermeden reddi; paket kapasitesi uyarısı
- [ ] Yanlış dosya reddi, ortak URI erişimi ve orijinal dosyanın korunması
- [ ] İzin reddi, bildirimden Paket'e dönüş ve TalkBack kontrolü

Deneme sonunda değiştirdiğiniz sınırları eski değerlerine döndürün. Yalnız bu
rehberin Compose projesini durdurmak için:

```powershell
docker compose @ComposeArgs stop worker backend db
```

Medya/veritabanı dizinlerini silmeyin; Vite penceresinde `Ctrl+C` kullanın.
[Ayrıntılı doğrulama kaydı](../verification/issue-33-android-upload.md).
