# Android uygulaması: değişiklik özeti ve adım adım deneme rehberi (#32)

Bu rehber Android kabuğunu, eşleştirmeyi, Kontrol Paneli'ni ve kurulumu denemek
içindir. Öncelik Android uygulaması ve tarayıcıdır. Yönetim ekranı olmayan
işlemler için yalnız PowerShell komutları kullanılır; Python veya SQL kodu
yazmanız gerekmez.

> **Yalnız ayrı deneme ortamında çalışın.** Rıza, yayın planı, Instagram bağlantısı
> ve marka ayarları bütün eşleştirilmiş cihazları etkiler. Gerçek öğrenci medyası
> kullanmayın. Worker'ı başlatmayın, yayın onayı vermeyin. Bu rehber Instagram'da
> gönderi paylaşmayı gerektirmez. Tokenları, eşleştirme kodlarını veya `.env`
> içeriğini ekran görüntülerine ve komut geçmişine koymayın.

## 1. Neler değişti?

| Değişiklik | Deneyebileceğiniz sonuç |
| --- | --- |
| Yerel Kotlin/Compose arayüz | Kontrol Paneli, Paket, Hareketler ve Ayarlar alanları |
| Uyarlanabilir gezinme | 600 dp altındaki pencerelerde alt çubuk; 600 dp ve üzerinde yan gezinme |
| Sunucu seçimi | İlk açılışta sunucu adresi; üretimde HTTPS, debug derlemesinde yerel HTTP |
| Güvenli eşleştirme | Kodla cihaz eşleştirme; şifreli ve sunucuya bağlı kalıcı cihaz kimliği |
| Sürüm kapısı | Eski sürümde güncelleme ekranı; kimliği silmeden işlemleri engelleme |
| Kontrol Paneli | Bekleyen işlemler, aktif paket, sonraki yayın zamanı, Instagram ve worker durumu |
| Yenileme ve hata ayrımı | Uygulamaya dönünce veya Yenile ile güncelleme; hata halinde son veriyi eski olarak belirtme |
| Kuruluma devam | Backend'in kontrol listesi; Ayarlar'dan yeniden açma ve tamamlanan adımları ziyaret etme |
| Plan, rıza, açıklama | Yerel tarih/saat seçimi, gösterilen rıza sürümünün açık kabulü, kısmi açıklama kaydı |
| Instagram bağlantısı | Maskeli manuel token ve dış tarayıcıda OAuth; hesabı kendiniz seçersiniz |
| Logo ve isteğe bağlı kartlar | Belge seçiciden PNG/JPEG, 10 MiB sınırı, kimlik doğrulamalı önizleme |
| Başarısız görsel kaydını tekrar deneme | Yüklenen görseli yeniden yüklemeden ayarlara kaydetme |
| Ortak API sözleşmesi | OpenAPI'den üretilmiş Kotlin modelleri; mevcut tarayıcı yanıtları korunur |
| Derleme altyapısı | Depoya alınmış Gradle wrapper, JVM testleri, lint ve Android CI işi |

**Kapsam sınırı:** Android Paket alanı salt okunurdur. Android'de medya yükleme,
montaj, render, yayın onayı, tam hareket geçmişi, genel ayar yönetimi ve
bildirimler bu işin parçası değildir. Mevcut web arayüzünde bunlardan bazılarının
bulunması Android'de de tamamlandıkları anlamına gelmez (#33–#38).

**Doğrulama sınırı:** Yerel JVM testleri, APK derlemeleri ve lint çalıştırıldı.
Bu geliştirme ortamında bağlı cihaz/AVD olmadığı için Compose/Keystore
instrumentation testlerinin çalışması ve gerçek cihazdaki görsel inceleme
doğrulanmadı. APK'nin derlenmesi, aşağıdaki elle denemelerin yapılmış olduğu
anlamına gelmez. Ayrıntı: [doğrulama kaydı](../verification/issue-32-android-shell.md).

## 2. Doğru çalışma dizini ve ön koşullar

PowerShell'i bu değişikliklerin bulunduğu worktree'de açın:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo\.worktrees\issue-32-android'
git branch --show-current
$Repo = (Get-Location).Path
$env:COMPOSE_PROJECT_NAME = 'dojo-android32-deneme'
$ComposeArgs = @('--env-file', 'ops/.env', '-f', 'ops/docker-compose.yml')
```

Beklenen dal: `feat/issue-32-android`. Başka bilgisayarda dizini değiştirin.
Her yeni PowerShell penceresinde aynı dizini/proje adını ve `$ComposeArgs`
değerini tekrar ayarlayın.

Gerekenler: Docker Desktop Linux motoru, Node.js/npm, Android Studio ve SDK 35.
Cihaz/emülatör Android 10/API 29 veya üstü olmalı. Gradle daemon ayarı JetBrains
Java 25 kullanır; ilk derlemede belirtilen JDK ve bağımlılıklar indirilebilir.

`8000`, `5434` ve `3000` portları boş olmalı. Compose proje adı tek başına
veritabanını ayırmaz: bu depoda `ops/db-data` ve `ops/media-data` bind dizinleri
kullanılır. **Bu worktree'de bu dizinler boş/yeni olmalı.** Mevcut gerçek ortamın
dizinlerini kopyalamayın, dolu port için gerçek ortamı durdurmayın.

## 3. Deneme sunucusu ve web arayüzü

### 3.1. Yerel ayarları hazırlayın

```powershell
docker info --format '{{.ServerVersion}}'
if (-not (Test-Path -LiteralPath ops/.env)) {
    Copy-Item -LiteralPath ops/.env.example -Destination ops/.env
}
notepad ops/.env
```

Not Defteri'nde:

- `POSTGRES_PASSWORD`: yalnız deneme için güçlü, farklı bir parola girin.
- `COOKIE_SECURE=false`: yalnız yerel HTTP denemesinde. Üretimde HTTPS ve `true`.
- `PUBLIC_BASE_URL=http://localhost:3000` ve
  `PUBLIC_HTTPS_ORIGIN=http://localhost:3000`: yalnız yerel deneme değerleri.
- Android sürüm ayarları varsa minimumun uygulamanın `versionCode=1` değerini
  engellemediğini kontrol edin. İlk deneme için `ANDROID_CURRENT_VERSION_CODE=1`,
  `ANDROID_MIN_VERSION_CODE=1` kullanabilirsiniz; olmayan satırları ekleyin.
- `META_TOKEN_ENCRYPTION_KEY`: Instagram adımını denemek için gerekir. Yeni boş
  kurulumda oluşturma adımları [web kurulum rehberi §2.2](issue-26-web-onboarding-deneme-rehberi.md#22-yerel-yapılandırmayı-hazırlayın)
  içinde PowerShell ile verilmiştir. Mevcut şifreleme anahtarını değiştirmeyin.

Dosyayı kaydedin. Bu rehberde canlı Meta OAuth sağlayıcısı kurulmuyor.

### 3.2. Yalnız veritabanı ve backend'i başlatın

```powershell
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose @ComposeArgs up -d --build db backend
if ($LASTEXITCODE -ne 0) { throw 'Deneme sunucusu başlatılamadı.' }
docker compose @ComposeArgs ps
Invoke-RestMethod -Uri 'http://localhost:8000/health'
Invoke-RestMethod -Uri 'http://localhost:8000/api/compat'
```

Beklenen: sağlık `ok`, minimum Android sürümü `1`. Worker özellikle başlatılmadı;
worker durumunun bilinmiyor görünmesi normaldir. Sunucu henüz açılıyorsa birkaç
saniye sonra sağlık isteğini tekrar çalıştırın.

### 3.3. Tarayıcıyı açın

Ayrı bir PowerShell penceresinde aynı repo kökünden:

```powershell
npm --prefix web ci
npm --prefix web run dev
```

Terminali açık bırakın. Vite'ın yazdığı adresi açın; varsayılan
`http://localhost:3000`. `http://localhost:8000` web arayüzü değil, API adresidir.
Tarayıcı, Android'in Compose görünümünü değil mevcut web istemcisini gösterir;
ortak ayarları değiştirmek ve Android sonucu ile karşılaştırmak için kullanılacak.

## 4. Android APK'yi derleyin ve kurun

### 4.1. Android Studio yolu

1. Android Studio'da worktree içindeki **android** klasörünü açın.
2. SDK Manager'da Android SDK Platform 35 ve Build-Tools 35.0.0 kurulu olsun.
3. Device Manager'da API 29 veya üstü bir telefon emülatörü oluşturup başlatın.
4. Gradle eşitlemesini bekleyin; **app** yapılandırmasını seçip **Run** ile kurun.

İlk derleme internet gerektirir. Android Studio proje kökü yerine `android`
klasörünü açmalıdır. Yerel SDK yolu `android/local.properties` içinde tutulur,
Git'e eklenmez.

### 4.2. PowerShell alternatifi

Bu bilgisayardaki varsayılan kurulum yollarıyla:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$Sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
if (-not (Test-Path -LiteralPath $Sdk)) { throw 'SDK yolunu kendi kurulumunuza göre değiştirin.' }
$env:ANDROID_HOME = $Sdk
if (-not (Test-Path -LiteralPath android/local.properties)) {
    $SdkForGradle = $Sdk.Replace('\', '/')
    Set-Content -LiteralPath android/local.properties -Value "sdk.dir=$SdkForGradle" -Encoding ASCII
}
./android/gradlew.bat -p android :app:assembleDebug
if ($LASTEXITCODE -ne 0) { throw 'APK derlenemedi; kurulum adımına geçmeyin.' }
$Adb = Join-Path $Sdk 'platform-tools\adb.exe'
& $Adb devices -l
```

Android Studio'da emülatörü başlattıktan veya USB hata ayıklamalı cihazı
bağlayıp iznini verdikten sonra listede durumu `device` olan seri numarasını seçin:

```powershell
$Serial = Read-Host 'adb listesindeki deneme cihazı/emülatör seri numarası'
& $Adb -s $Serial install -r 'android/app/build/outputs/apk/debug/app-debug.apk'
if ($LASTEXITCODE -ne 0) { throw 'APK kurulamadı.' }
& $Adb -s $Serial shell am start -n 'com.dojo.aisomedo/.MainActivity'
```

`install -r` verileri koruyarak debug APK'yi günceller. İmza uyuşmazlığı varsa
gerçek uygulamayı kaldırmayın; ayrı emülatör/deneme cihazı kullanın.

### 4.3. Uygulamadaki sunucu adresi

| Ortam | Sunucu alanına yazılacak adres |
| --- | --- |
| Android Studio emülatörü; backend aynı Windows bilgisayarında | `http://10.0.2.2:8000` |
| Gerçek cihaz ve erişilebilir sunucu | Kurulumunuzun gerçek `https://...` origin'i |
| USB bağlı fiziksel debug cihaz; aşağıdaki port yönlendirmesi | `http://127.0.0.1:8000` |

USB üzerinden yerel debug denemesi için:

```powershell
& $Adb -s $Serial reverse tcp:8000 tcp:8000
```

Emülatörde `localhost` emülatörün kendisidir; bilgisayardaki backend için
`10.0.2.2` kullanın. Adrese `/api`, kullanıcı/parola, sorgu veya fragment eklemeyin.
HTTP yalnız debug derlemesinde serbesttir; release derlemesinde HTTPS gerekir.

## 5. İlk açılış ve eşleştirme — Android

1. Uygulamayı açın. Sunucu kaydı yoksa **Dojo sunucusuna bağlan** görünmeli.
2. `https://example.com/api` gibi bir yol içeren adres girin; **Bağlan** ile
   adres uyarısı bekleyin. Ardından §4.3'teki doğru adresi girin.
3. **Bağlan** düğmesine basın. Sunucu erişilebilir ve sürüm destekleniyorsa
   **Cihazı eşleştir** ekranı görünmeli.
4. **Cihaz adı** için `Android Rehber Denemesi` yazın. Önce gerçek sır olmayan
   `gecersiz` koduyla deneyin; kod uyarısı görünmeli, uygulama açılmamalı.
5. PowerShell'de yeni tek kullanımlık kod üretin:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
```

6. Çıktıdaki kodu **Eşleştirme kodu** alanına girip **Eşleştir**'e basın.
7. Eksik kurulum varsa ilk gerekli eksik adım açılır. Kurulum zaten hazırsa
   Kontrol Paneli açılır. Kod alanı gönderimde temizlenir, tekrar gönderme engellenir.
8. Uygulamayı kapatıp tekrar açın: sunucu ve cihaz eşleştirmesi korunmalı;
   yeni kod istenmemeli. Kaydedilmemiş eşleştirme kodunun geri gelmemesi normaldir.

Kod süreli ve tek kullanımlıktır. Tarayıcı için aynı kodu yeniden kullanmayın;
yeni kod üretip web ekranındaki **Eşleştirme kodu / Tarayıcı adı / Eşleştir**
alanlarını kullanın.

## 6. Dört alan ve Kontrol Paneli — Android

Eksik kurulum açıkken **Şimdilik kontrol paneline dön** ile çıkabilirsiniz.
Bu, kurulum adımlarını tamamlanmış saymaz.

1. **Kontrol Paneli:** Bekleyen işlemler önce görünmeli. Yeni boş kurulumda
   **Bekleyen işlem yok**, **Henüz aktif paket yok**, yayın zamanı yok ve bağlantı
   durumları gerçek boş durumlar olmalı; yükleme hatası olarak sunulmamalı.
2. **Paket:** Salt okunur paket özeti açılmalı. Ekrana girmeniz yeni paket
   oluşturmamalı. Aktif paket varsa kimliği/durumu Kontrol Paneli ile aynı olmalı.
3. **Hareketler:** **Hareket geçmişi sonraki sürümde sunulacak.** açıklaması
   görünmeli; başarılı yüklenmiş boş geçmiş gibi davranmamalı.
4. **Ayarlar:** Sunucu, cihaz adı/numarası, sürüm bilgisi ve kurulum durumu görünmeli.
5. Paket/Hareketler/Ayarlar'dayken Android **Geri** düğmesi Kontrol Paneli'ne;
   kurulumdayken kurulumdan çıkışa dönmeli.
6. **Ayarlar → Sunucuyu değiştir**'e dokunun. Yeniden eşleştirme uyarısı görünmeli.
   Önce **Vazgeç** ile eski oturumun korunduğunu deneyin. Gerçek değişiklik için
   **Değiştir ve eşleştirmeyi kaldır**; adres ekranına dönüp yeniden eşleştirin.

Bekleyen `review_ready`, `empty_package`, `preparing` durumlarını gerçek API ile
üretmek medya/worker akışlarını gerektirir. Sırf bu rehber için yayın süreci
başlatmayın. Üç durumun gösterimi derlenmiş Compose fixture testinde vardır;
çalıştırma yolu §12'de. Gerçek Instagram ve worker sağlığının olumlu olması
ayrı servislerin gerçekten çalışmasına bağlıdır.

## 7. Kurulumun yedi adımı — Android ve tarayıcı

Android'de **Ayarlar → Kurulumu aç**. Adım düğmeleri formun altında, backend
sırasında görünür; aşağı kaydırıp tamamlanmış adımlara da dönebilirsiniz.
Tamamlandı/gerekli/isteğe bağlı bilgileri sunucudan gelir.

### 7.1. Eşleştirme

Cihaz kimliği görünmeli. İkinci hesap/parola akışı olmamalı. **Sonraki adım**
yalnız gezinir; sunucuda adım tamamlandığı anlamına gelmez.

### 7.2. Instagram

1. **Instagram erişim tokenı** alanına `deneme-gecersiz-token` yazın.
2. Maskeli alanı kontrol edip **Token ile bağlan**'a basın. Alan temizlenmeli;
   başarısız doğrulama eski bağlantıyı değiştirmemeli.
3. Tekrar bir deneme değeri girip uygulamayı arka plana alın ve geri dönün:
   alan boş olmalı. Adımdan çıkıp yeniden girince de token geri gelmemeli.
4. Geçerli, uygun izinli test hesabı tokenınız varsa aynı alanla bağlanın.
   Başarıdan sonra kullanıcı adı/durum görünmeli; token tekrar gösterilmemeli.
5. **Instagram ile yetkilendir** dış tarayıcıyı açmalı. Dönünce veya
   **Yetkilendirme sonucunu kontrol et** ile sonucu kontrol edin. Aday hesap
   varsa **... hesabını seç** düğmesiyle kendiniz seçin; ilk hesap otomatik seçilmez.

**Canlı sağlayıcı sınırı:** Mevcut backend kurulumu OAuth için
`StubMetaOAuthProvider` kullanır. Yerel OAuth açılışını gerçek Meta hesabına
başarılı bağlantı kanıtı saymayın. Aday seçimi sentetik testlerle denenebilir.
Gerçek bağlantı ön koşulları ve manuel token yolu:
[Instagram token rehberi](instagram-token-baglantisi-rehberi.md).
Tokenınız/Meta hazırlığınız yoksa adımı tamamlanmış saymayın; diğer adımları
bağımsız deneyebilirsiniz. Tarayıcıdaki mevcut kurulum sihirbazı da manuel tokenı
destekler.

### 7.3. Dojo Yayın Planı

1. Tarih düğmesini açın, Pazartesi `2026-10-05` seçin.
2. Saat düğmesinden `18:30` seçin.
3. **Düzenli yayın planı açık** anahtarını kapalı tutun; **Kaydet**'e basın.
4. Adımı yeniden açın: tarih/saat korunmalı; kapalı plan yapılandırılmış sayılmalı.
5. Salı `2026-10-06` seçip kaydetmeyi deneyin: hata olmalı, son geçerli kayıt korunmalı.

Saat dilimi `Europe/Istanbul`, düzen iki haftada bir Pazartesi. Geçmiş örnek tarih
bu kapalı plan denemesinde kullanılabilir. Worker çalıştırmayın; planı açmayın.

### 7.4. Medya rızası

İlk politika metnini oluşturacak Android/web ekranı yoktur. **Yalnız yeni boş
deneme kurulumunda**:

```powershell
docker compose @ComposeArgs exec -T backend .venv/bin/dojo-consent set-policy --version 1 --text 'Deneme medya politikası. Yalnız izinli sentetik medya kullanılır.'
if ($LASTEXITCODE -ne 0) { throw 'Politika kaydedilemedi; mevcut sürümü kontrol edin.' }
```

1. Android'de **Medya rızası → Tekrar dene**. Metnin tamamı ve sürüm görünmeli.
2. Kabul kutusu ilk başta boş; **Bu sürümü kabul et** düğmesi kapalı olmalı.
3. Metni okuyup kutuyu işaretleyin, düğmeyle açıkça kabul edin.
4. Aynı kuruluma eşleştirilmiş tarayıcıdan sihirbazın rıza adımını açın:
   kabul tarihi görünmeli; ikinci kez kabul gerekmemeli.

Sürüm değişimini denemek için önce Android'de sürüm 1'i açık bırakın; kabulü
henüz göndermeden, bu **ayrı deneme kurulumunda**:

```powershell
docker compose @ComposeArgs exec -T backend .venv/bin/dojo-consent set-policy --version 2 --text 'Yeni deneme medya politikası. Bu sürüm ayrıca açık kabul gerektirir.'
```

Android'e dönün/yenileyin. Sürüm 2 görünmeli, önceki kutu işareti temizlenmeli.
Eski gösterilen sürümle gönderim sunucuda `409` olursa yeni metin yüklenir;
yeniden açık kabul gerekir, otomatik ikinci POST yapılmaz. Bu yarışın güvenilir
tekrarı JVM testindedir. Gerçek kurulumda yalnız test amacıyla sürüm artırmayın.

### 7.5. Logo

1. **Dojo logosu → Görsel seç ve kaydet** ile sentetik PNG/JPEG seçin.
2. Yükleme/kayıt bitince adımı yeniden açın; kayıtlı görselin önizlemesini kontrol edin.
3. Uygulamayı yeniden açın: logo kaydı korunmalı; aktif medya paketi gerekmemeli.
4. Seçiciyi açıp iptal edin: önceki logo değişmemeli.
5. 10 MiB'dan büyük deneme dosyası seçerseniz işlem reddedilmeli, önceki logo korunmalı.
6. Yükleme başarılı ama ayar kaydı başarısızsa **Yüklenen görseli kaydetmeyi tekrar
   dene** görünür; bu düğme aynı yüklenen referansı kullanır. Bu iki aşama arasındaki
   hatayı gerçek kurulumda zorlamayın; JVM fixture testiyle kontrol edin.

Tek kare PNG/JPEG, sunucu tarafında en fazla 4096 piksel/kenar. Android belge
seçicisi kullanılır; genel medya/depolama izni istenmez.

### 7.6. Açıklama şablonu ve taslak koruması

1. **Açıklama şablonu** alanına `Dojo denemesi — #dojo` yazıp **Kaydet**'e basın.
2. Adımı yeniden açın: metin aynı; logo ve kartlar değişmemiş olmalı.
3. Metni boşaltın: kaydetme kapalı olmalı. Özel şablon değişkeni desteği varsaymayın.
4. Android'de `Kaydedilmemiş taslak` yazın, kaydetmeyin.
5. Aynı kurulumdaki tarayıcıda sihirbazın açıklamasını `Tarayıcı kaydı` olarak kaydedin.
6. Android'i arka plana alıp geri dönün: taslak korunmalı, sunucu değişikliği uyarısı görünmeli.
7. **Sunucu ayarlarını yeniden yükle**'ye basınca Android alanı `Tarayıcı kaydı` olmalı.
8. Güvenli bir taslak bırakıp ekranı döndürün; taslak kaybolmamalı. Manuel Instagram
   tokenı bu korumaya dahil değildir.

### 7.7. İsteğe bağlı kartlar ve bitirme

1. **Giriş ve çıkış kartları**'nı seçin. Giriş için süre `1.5`, çıkış için `2` girin.
2. Her kartta sentetik PNG/JPEG seçip kaydı bekleyin. Gerekirse adımı yeniden açın.
3. **Kart sürelerini kaydet** ile süreleri kaydedin; önizlemeler/tanımlar korunmalı.
4. Bir kartta **Bu kartı ve süresini kaldır**'ı deneyin. Yalnız o kart ve süresi
   temizlenmeli; diğer kart, logo ve açıklama korunmalı.
5. Süre olarak `0` girip kaydetmeyi deneyin: hata olmalı; son geçerli kayıt korunmalı.
6. Kart istemiyorsanız **Kartları değiştirmeden devam et** kullanın. Bu, mevcut
   kartları silmez. Kartlar gerekli hazır durumu engellemez.
7. **Sonraki adım** ile özete geçin. **Kurulumu bitir ve kontrol panelini aç** yalnız
   backend gerekli kurulumu hazır görüyorsa kullanılabilir.

Instagram bağlantısı gibi gerekli bir adım eksikse hazır özeti beklemeyin. Eksik
kurulumdan çıkmak serbesttir; Kontrol Paneli'nde eksik durum görünür. Bu rehber
kurulum tamamlandıktan sonra da yayın/render/onay başlatmaz.

## 8. Bağlantı kesilmesi ve yeniden açma

Önce Android'de Kontrol Paneli'nin başarıyla yüklendiğinden emin olun. Yalnız
bu deneme backend'ini durdurun:

```powershell
docker compose @ComposeArgs stop backend
```

Android'de **Yenile**. Son veriler varsa eski oldukları ve son güncelleme zamanı
belirtilmeli; yeni/sahte sağlık bilgisi üretilmemeli. İlk açılışta uyumluluk
alınamazsa tekrar dene/sunucu değiştir ekranı gelmeli.

```powershell
docker compose @ComposeArgs up -d backend
```

**Yenile** veya uygulamaya geri dönün. Geçerli eşleştirme korunmalı. Taslak koruması
kalıcı çevrimdışı veri tabanı değildir; Dashboard yalnız bellekteki son veriyi tutar.

## 9. Cihazı iptal etme — PowerShell, ardından Android

Android'deki **Ayarlar** ekranından deneme cihazının numarasını not edin.
İptal yönetimi bu Android sürümünde yoktur. Ayrı yönetici deneme oturumu için
§5'teki CLI ile **yeni** kod üretin, sonra:

```powershell
$Api = 'http://localhost:8000'
$AdminSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$Code = Read-Host 'Yeni tek kullanımlık yönetici deneme kodu'
$Body = @{ code = $Code; kind = 'browser'; name = 'Rehber PowerShell yoneticisi' } | ConvertTo-Json
$null = Invoke-RestMethod -Uri "$Api/api/pairing/validate" -Method Post -ContentType 'application/json' -Body $Body -WebSession $AdminSession
$Code = $null
$Body = $null
Invoke-RestMethod -Uri "$Api/api/pairing/clients" -WebSession $AdminSession | Select-Object id, name, kind, revoked_at
```

Bu PowerShell oturumu cookie kullanır; cihaz tokenını kopyalamanız gerekmez.
Listeden yalnız `Android Rehber Denemesi` kaydını hedefleyin:

```powershell
$ClientId = [int](Read-Host 'Yalniz iptal edilecek Android deneme cihazinin numarasi')
if ($ClientId -le 0) { throw 'Gecerli deneme cihazi numarasi gerekli.' }
if ((Read-Host "Cihaz $ClientId iptal edilsin mi? EVET yazin") -eq 'EVET') {
    $null = Invoke-RestMethod -Uri "$Api/api/pairing/clients/$ClientId/revoke" -Method Post -WebSession $AdminSession
}
```

Android'de **Yenile**/uygulamaya dönüş: eşleştirme ekranı gelmeli, eski cihaz
verisi ve kaydetme kontrolleri kalkmalı. Geçersiz kodla `401` almak ile eşleştirilmiş
cihazın iptalinin `401` olması farklıdır: ilki kod hatası, ikincisi oturum kaybıdır.
Devam etmek için yeni kodla cihazı yeniden eşleştirin.

## 10. Güncelleme kapısı — PowerShell, ardından Android

Önce deneme `.env` dosyasındaki mevcut Android sürüm değerlerini not edin.

```powershell
notepad ops/.env
```

Yalnız deneme sunucusunda `ANDROID_CURRENT_VERSION_CODE=2`,
`ANDROID_MIN_VERSION_CODE=2`, `ANDROID_UPDATE_URL=https://example.com/dojo-update.apk`
olarak ayarlayın. Var olan satırları düzenleyin; aynı anahtarı tekrar eklemeyin.
Örnek HTTPS adresi gerçek APK indirme hizmeti değildir.

```powershell
docker compose @ComposeArgs up -d --force-recreate backend
Invoke-RestMethod -Uri 'http://localhost:8000/api/compat'
```

Android'e dönün/**Yenile**: sürüm 1 uygulamada **Güncelleme gerekli** görünmeli;
gezinme ve kaydetme ekranları kapanmalı. HTTPS adresi varsa indirme düğmesi
tarayıcı açar. Gerçek APK bulunmayan örnek adreste başarılı indirme beklemeyin.

API'nin `426` yanıtını gerçek token kullanmadan da kontrol edebilirsiniz:

```powershell
try {
    Invoke-RestMethod -Uri 'http://localhost:8000/api/dashboard' -Headers @{
        Authorization = 'Bearer sentetik-gecersiz-token'
        'X-Android-Version-Code' = '1'
    }
} catch {
    [int]$_.Exception.Response.StatusCode
}
```

Beklenen `426`; sürüm kontrolü kimlik doğrulamadan önce yapılır. Tarayıcı cookie
oturumları Android sürüm kapısından etkilenmez.

Sonra `.env` içindeki değerleri not ettiğiniz önceki değerlere geri getirin,
backend'i aynı `up -d --force-recreate backend` komutuyla yeniden oluşturun.
Android'de **Tekrar dene**: eşleştirme kimliği korunmuş olmalı; yeniden kod istememeli.

## 11. Telefon/tablet, tema ve erişilebilirlik — Android

1. Telefon emülatörü: dört öğeli alt gezinmeyi kontrol edin.
2. Tablet veya yeniden boyutlandırılabilir emülatör: pencere **600 dp ve üzerine**
   çıkınca yan gezinme ve iki sütunlu Dashboard grupları görünmeli. Fiziksel piksel
   sayısı dp değildir; masaüstü tarayıcıyı büyütmek Android testini yerine getirmez.
3. Ekranı döndürün/bölünmüş ekrana alın: kaydedilmemiş güvenli taslak ve seçili alan
   korunmalı; eşleştirme veya kaydetme ikinci kez gönderilmemeli.
4. Android Ayarlar'dan koyu/açık tema ve büyük yazı seçip uygulamaya dönün.
5. Rıza metninin tamamının kaydırılabildiğini, klavye açıkken alan/düğmelerin
   erişilebilir kaldığını ve Android Geri'nin doğru ekrana döndüğünü kontrol edin.
6. TalkBack ile adım/alan/düğme adlarını ve seçili gezinmeyi dinleyin. Sağlık ve
   kurulum bilgisi yalnız renk ile anlatılmamalı.

Bu kontroller bu ortamda cihaz bulunmadığı için henüz yapılmadı; sonuçları
doğrulama kaydına ayrıca yazın. Tema/yazı ayarlarını deneme sonunda geri alın.

## 12. Arayüzde üretilemeyen koşullar için otomatik PowerShell denemeleri

Gerçek servisleri bozarak yarış, kayıp Keystore anahtarı veya iki aşamalı kayıt
hatası üretmeyin. Sentetik fixture testlerini kullanın. Aşağıdaki komutlarda
Python/SQL kodu yoktur; mevcut test çalıştırıcıları kullanılır.

```powershell
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
if ($LASTEXITCODE -ne 0) { throw 'Android dogrulamasi basarisiz.' }
```

JVM kapsamı: zorunlu nullable alanların JSON çözümü, sunucu adresi doğrulaması,
şifreli kimlik, farklı sunucuya token göndermeme, redirect/kayıt tekrarını engelleme,
401/426, eski yanıt bastırma, plan/rıza/taslaklar, açık OAuth hesap seçimi,
yükleme sonrası PATCH hata/tekrar ve 10 MiB sınırı.

Çalışan emülatör/cihaz varsa Compose ve gerçek Android Keystore testleri:

```powershell
& $Adb devices -l
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
if ($LASTEXITCODE -ne 0) { throw 'Cihaz testleri basarisiz veya cihaz bulunamadi.' }
```

Cihaz yokken yalnız `assembleDebugAndroidTest` başarılı olması testlerin
çalıştığını göstermez. Raporlar:

- `android/app/build/reports/tests/testDebugUnitTest/index.html`
- `android/app/build/reports/lint-results-debug.html`
- Cihaz testi çalıştırılmışsa `android/app/build/reports/androidTests/connected/`

Backend sözleşme kontrolleri için `uv` kurulu bir terminalde:

```powershell
uv sync --all-packages
uv run --project backend pytest backend/tests/test_android_contract.py backend/tests/test_client_generation.py backend/tests/test_contract.py backend/tests/test_meta_token_api.py -q
if ($LASTEXITCODE -ne 0) { throw 'Sozlesme testleri basarisiz.' }
```

Testler Python çalışma zamanını araç olarak kullanır; kendiniz Python kodu veya
SQL yazmazsınız. Bu testler canlı Meta bağlantısını veya gerçek cihaz görünümünü
doğrulamaz.

OpenAPI metadata'sını tarayıcıda `http://localhost:8000/docs` üzerinden okuyun:
`CompatInfo`, `PairingOut` ve manuel Instagram token isteğinin şeması görünmeli.
Gerçek tokenı Swagger denemelerine/HAR kayıtlarına koymayın.

## 13. Güvenli kapatma

Vite terminalinde `Ctrl+C`. Yalnız bu deneme Compose projesini kapatın:

```powershell
docker compose @ComposeArgs down
```

`down -v`, veritabanı silme veya uygulama verilerini temizleme gerekmez.
Deneme kayıtları korunur. USB port yönlendirmesi kullandıysanız:

```powershell
& $Adb -s $Serial reverse --remove tcp:8000
```

Sonuçları değerlendirirken **derlendi**, **sentetik test geçti**, **cihazda denendi**
ve **canlı sağlayıcıyla doğrulandı** ayrımını koruyun.
