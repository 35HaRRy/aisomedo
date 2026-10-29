# Android medya yönetimi ve sürükle-bırak montaj sırası — deneme rehberi (#35)

Tarih: 11 Ekim 2026.

Bu rehber değişiklikleri özetler; önce **Android uygulamasında**, ardından ortak
sonucu **tarayıcıda** kontrol etmenizi sağlar. Arayüzden oluşturulamayan hata
senaryoları için hazır testleri çalıştıran **PowerShell** komutları vardır.
Python veya SQL kodu yazmanız, veritabanına doğrudan müdahale etmeniz gerekmez.

> **Yalnız ayrı deneme ortamında çalışın.** Gerçek öğrenci medyası kullanmayın.
> Yayın planını etkinleştirmeyin, Instagram bağlantısı kurmayın, yayın onayı
> vermeyin. Sıra ve kaydedilmiş video bölümleri aynı sunucuya bağlı bütün
> istemcileri etkiler. Eşleştirme kodlarını, çerezleri ve `.env` içeriğini paylaşmayın.

**Doğrulama durumu:** 10 Ekim'deki geliştirme kontrolünde 82 Android birim testi,
206 backend testi ve 688 çekirdek testi geçti; çekirdek takımında 4 test atlandı.
APK ve test APK'si derlendi; lint hata vermedi. Bağlı cihaz/AVD olmadığı için
sürükleme, otomatik kaydırma ve cihaz görüntüleri henüz çalıştırılarak doğrulanmadı.
Aşağıdaki **beklenen sonuçlar kabul ölçütüdür**, yapılmış cihaz denemesi değildir.
[Ayrıntılı doğrulama kaydı](../verification/issue-35-android-media.md).

## 1. Neler değişti?

| Değişiklik | Kullanıcıya etkisi |
| --- | --- |
| Android **Paket → Montaj medyası** | İşlenmiş fotoğraf/videolar kayıtlı montaj sırasında gösterilir. |
| Sürükleme tutamacı | Medyayı önce/sonra çizgisine bırakarak sıralayabilirsiniz; kayıt bırakınca yapılır. |
| Kenarda otomatik kaydırma | Uzun listede tutamacı ekranın içerik alanının üst/alt kenarında tutabilirsiniz. |
| Yukarı/aşağı düğmeleri | Sürükleme yapmadan aynı sıralama işlemini gerçekleştirir. |
| **Montajdan kaldır / Montaja geri yükle** | Medya montajdan çıkar; kaynak dosyası silinmez. |
| Bir veya birden çok video bölümü | Başlangıç/bitiş saniyelerini seçebilir, bütün videoya dönebilirsiniz. |
| Toplam süre ve sınır uyarısı | Fotoğraflar, seçilen video bölümleri ve varsa kartlar hesaba katılır. |
| Taslak ve eski veri koruması | Belirsiz işlemden sonra yeniden yazmadan önce yenileme gerekir; taslağı silmek bu korumayı aşmaz. |
| Ortak sunucu sonucu | Android'deki kayıtlı sıra/bölümler tarayıcıdan da görülebilir. |

**Önemli ayrım:** Sıralama, kaldırma ve geri yükleme işlemleri anında sunucuya
gönderilir. Video bölümleri ise **Video bölümlerini kaydet** ile gönderilir.
Taslak değişikliklerden vazgeçmek, kaydedilmiş sıralamayı veya kaldırmayı geri almaz.

Bu iş tarayıcıya yeni özellik eklemedi; mevcut web montaj ekranı karşılaştırma
için kullanılır. Android'de fotoğraf süresi düzenleme, video oynatıcılı önizleme,
Reel render başlatma ve yayın onayı bu değişikliğin kapsamında değildir.

## 2. Hazırlık

### 2.1. Sunucu ve deneme dosyaları

1. Bu değişiklikleri içeren, önceden hazırlanmış **ayrı deneme sunucusunu** açın.
   Yeni ortam gerekiyorsa [Android yükleme rehberinin hazırlık bölümlerini](issue-33-android-upload-deneme-rehberi.md)
   kullanın. Oradaki eski dal/worktree yolunu aynen kullanmayın; #35 kodunun
   bulunduğu güncel dizini seçin.
2. Deneme için farklı isimli bir JPEG/PNG ve iki MP4 hazırlayın. Örnek:
   `foto-deneme.jpg`, `video-a.mp4`, `video-b.mp4`. Videoların her biri en az
   10 saniye olsun; ilk toplam ekranda gösterilen süre sınırının altında kalsın.
3. Dosyaları Android'in **İndirilenler/Download** klasörüne koyun veya tarayıcıdan
   yüklenebilecek bir yerde tutun. Rastgele baytları `.mp4` diye adlandırmayın;
   gerçekten oynatılabilir medya kullanın.
4. Sunucu tarafındaki medya işleme tamamlanmalı. **Aktarım bitti; sunucuda sırada**
   ile **Aktif Pakete eklendi** aynı durum değildir.

Yerel Docker deneme ortamı zaten hazırlanmışsa, PowerShell'i repo kökünde açın:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
git branch --show-current
$ComposeProject = Read-Host 'Mevcut ayrı deneme ortamınızın Compose proje adı'
if ([string]::IsNullOrWhiteSpace($ComposeProject)) { throw 'Deneme proje adı gerekli.' }
$ComposeArgs = @('--env-file', 'ops/.env', '-p', $ComposeProject, '-f', 'ops/docker-compose.yml')
docker compose @ComposeArgs ps
```

Başka bilgisayarda yolu değiştirin. Her yeni PowerShell penceresinde değişkenleri
yeniden tanımlayın. Bu blok **yeni ortam kurmaz**. Compose proje adı tek başına
verileri ayırmaz; `ops/db-data` ve `ops/media-data` dizinleri gerçek ortamınıza
aitse komutları orada çalıştırmayın. Dizinleri silmeyin.

### 2.2. Güncel Android uygulaması

**Android Studio:** Güncel repo içindeki `android` klasörünü açın. SDK 35 ve
Android 10/API 29+ ayrı deneme emülatörüyle **app → Run** kullanın.

**PowerShell alternatifi:** SDK yolunuz farklıysa `$Sdk` değerini değiştirin.

```powershell
$Sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_HOME = $Sdk
$Adb = Join-Path $Sdk 'platform-tools\adb.exe'
./android/gradlew.bat -p android :app:assembleDebug
if ($LASTEXITCODE -ne 0) { throw 'APK derlenemedi.' }
& $Adb devices -l
$Serial = Read-Host 'device durumundaki ayrı deneme cihazının/emülatörünün seri numarası'
if ([string]::IsNullOrWhiteSpace($Serial)) { throw 'Cihaz seri numarası gerekli.' }
& $Adb -s $Serial install -r 'android/app/build/outputs/apk/debug/app-debug.apk'
if ($LASTEXITCODE -ne 0) { throw 'APK kurulamadı.' }
& $Adb -s $Serial shell am start -n 'com.dojo.aisomedo/.MainActivity'
```

`install -r` debug uygulamanın verilerini korur. İmza uyuşmazlığında kişisel/üretim
uygulamasını kaldırmayın; ayrı deneme emülatörü kullanın. JDK/SDK hatasında önce
Android Studio'da proje eşitlemesini tamamlayın.

Uygulama eşleştirilmemişse:

1. Sunucu adresini girin: yerel emülatörde `http://10.0.2.2:8000`; uzakta kendi
   deneme HTTPS origin'iniz. Adrese `/api` eklemeyin. Yerel HTTP yalnız debug APK'de
   kullanılabilir; emülatörde `localhost` Windows bilgisayarı değildir.
2. Deneme backend'inde tek kullanımlık kod üretin:

   ```powershell
   docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
   ```

3. Android'de **Cihaz adı** ve kodu girip **Eşleştir**'e basın.
4. Kurulum açılırsa **Şimdilik kontrol paneline dön** ile çıkın. **Paket**'i açın.
5. **Montaj medyası** başlığı görünmeli. Görünmüyorsa eski APK kullanıyor olabilirsiniz.

### 2.3. Tarayıcı ve ortak paket

Mevcut web adresinizi açın. Yerel web istemcisi kapalıysa ayrı PowerShell
penceresinde aynı repo kökünden:

```powershell
npm --prefix web ci
if ($LASTEXITCODE -ne 0) { throw 'Web bağımlılıkları kurulamadı.' }
npm --prefix web run dev -- --host localhost --port 3000 --strictPort
```

Terminali açık bırakın; `http://localhost:3000/#/package` adresini açın.
`8000` backend portudur, web ekranı değildir. Tarayıcı için gerekirse **ayrı, yeni
eşleştirme kodu** üretin; Android'in kullandığı kodu yeniden kullanmayın.

Android veya tarayıcıdan deneme medyalarını yükleyin. İşleme için yalnız hazırladığınız
deneme ortamında gerekiyorsa:

```powershell
docker compose @ComposeArgs up -d --build worker
if ($LASTEXITCODE -ne 0) { throw 'Deneme worker başlatılamadı.' }
```

Worker yalnız montaj için değil yayın işleri için de çalışır: ortamda yayın planı,
Instagram bağlantısı veya onaylanmış yayın bulunmamalı. İşleme bitince Android'de
**Montaj medyası başlığının altındaki Yenile**'ye basın. Yükleme kuyruğunun altındaki
başka Yenile düğmesiyle karıştırmayın.

**Beklenen:** Üç dosya montaj listesinde görünür. Paket adı/klasörü tarayıcıyla aynı
olur. Yerel Android yükleme satırlarının tarayıcıda birebir görünmesi gerekmez.

## 3. Sürükle-bırak sıralamayı deneyin — Android, ardından tarayıcı

1. Başlangıç sırasını not edin; örneğin `foto → video-a → video-b`.
2. İlk medyanın solundaki üç yatay çizgili **sıralama tutamacını** sürükleyin.
   Dosya adına, kırpma alanına veya kaldırma düğmesine değil tutamaca dokunun.
3. Son medyanın alt yarısına götürün. Sürüklenen satır vurgulanmalı; bırakılacak
   yerin önce/sonra çizgisi görünmelidir.
4. Parmağınızı kaldırın. Örnekte yeni sıra `video-a → video-b → foto` olmalıdır.
   Kayıt sırasında işlem bitene kadar bekleyin; ayrıca bölümleri kaydetmeniz gerekmez.
5. Android'de **Yenile**'ye basın, başka sekmeye gidip Paket'e dönün.
6. Tarayıcıdaki **Aktif paket medyası** alanını yenileyin. Aynı sırayı kontrol edin.

**Beklenen:** Sıra sunucuda kalıcıdır. Web'deki yatay yerleşimde sol/sağ sırası,
Android'deki yukarı/aşağı sırasına karşılık gelir. Sıra kaydı reddedilirse bunu
başarılı saymayın; süre/bağlantı uyarısını okuyup yenileyin.

### 3.1. İptal, otomatik kaydırma ve düğme alternatifi

- **İptal:** Tutamacı sürüklerken Android **Geri** düğmesine basın, sonra parmağınızı
  kaldırın. Paket ekranından hemen çıkmak yerine sürükleme iptal olmalı. Yenileme
  sonrası sıra aynı kalmalıdır. Aynı konuma bırakmak da sırayı değiştirmemelidir.
- **Otomatik kaydırma:** Liste ekrana sığmıyorsa, tutamacı sürüklerken içerik alanının
  alt kenarına yaklaştırıp orada tutun. Liste aşağı kaymalı; üst kenarda ters yönde
  kaymalıdır. Gerekirse kişisel veri içermeyen ek fotoğraflar yükleyin; toplam süre
  sınırını aşmayın. Kısa, ekrana sığan listede kaydırma olmaması normaldir.
- **Yukarı/aşağı:** Bir orta satırın oklarına basın. Tek basış bir konum taşımayı
  sağlamalı ve tarayıcıda da kalıcı olmalıdır. İlk satırın yukarı, son satırın aşağı
  düğmesi pasif olmalıdır.
- **Yeni yükleme:** Sıra değişmişken farklı isimli bir fotoğraf yükleyin. İşleme
  tamamlandıktan sonra önceki sıra korunmalı, yeni medya sona eklenmelidir.

Tarayıcı sürüklemesi kendi web arayüzünü sınar; Android dokunma hareketini veya
Android kenar kaydırmasını doğrulamaz.

## 4. Montajdan kaldırma ve geri yükleme

1. Android'de `video-a` satırında **Montajdan kaldır**'a basın.
2. Video üst listeden çıkmalı; **Kaldırılan medya** bölümünde görünmelidir.
3. Toplam süre azalmalı. Tarayıcıyı yenileyin; aynı dosya orada da kaldırılmış olmalı.
4. Android'de **Montaja geri yükle**'ye basın. Video tekrar sıralı listeye dönmelidir.
5. Yenileyin ve tarayıcıdan da kontrol edin. Diğer medyaların göreli sırası
   bozulmamalı; geri yüklenen öğe sunucunun tuttuğu kaldırılma konumuna göre yerleşir.

**Beklenen:** Kaynak dosya silinmez; sunucuda montajdan ayrı tutulur. Telefonunuzdaki
orijinal dosyanın durması tek başına sunucu kopyasının korunduğunu kanıtlamaz;
sunucu dosya durumunu görmek için bölüm 9.1 kullanılabilir.

**Karıştırmayın:** Yükleme kuyruğundaki **Listeden kaldır**, montaj medyasındaki
**Montajdan kaldır** ile aynı işlem değildir.

## 5. Video bölümleri ve birden fazla aralık

1. `video-a` için **Video bölümlerini düzenle**'yi açın. Kaynak süresini okuyun.
2. **Bölüm ekle**'ye basın; **Başlangıç** `1`, **Bitiş** `4` girin.
3. Bir bölüm daha ekleyin; **Başlangıç** `6`, **Bitiş** `9` girin.
4. Önerilen video katkısı **3 + 3 = 6 saniye** olmalıdır. Aralıklar tutulacak
   kısımlardır: `1–4` seçmek bu kısmı kesip atmak değil, bu kısmı kullanmak demektir.
5. **Video bölümlerini kaydet**'e basın. Kaydedilmemiş bölüm uyarısı kalkmalıdır.
6. Android'i yenileyin. Tarayıcıda dosyanın **bölümlerini düzenle** simgesini açın;
   iki aralık aynı görünmelidir.
7. `video-b` üzerinde örneğin `2–5` aralığını kaydedin. `video-a`'nın iki aralığının
   hâlâ korunduğunu iki istemciden kontrol edin.

Kaynak video 9 saniyeden kısaysa bu değerleri kullanmayın; iki çakışmasız aralığı
kendi kaynak süreniz içinde seçin. Aralıklar kaynak zamanına göre oynatılır;
alanları ters sırayla eklemek video parçalarının oynatma sırasını tersine çevirmez.

### 5.1. Bütün videoya dönme, taslak ve geçersiz giriş

- **Bütün videoya dön:** **Videonun tamamını kullan**'a, sonra **Video bölümlerini
  kaydet**'e basın. Video katkısı kaynak süresine dönmelidir. Bütün bölüm satırlarını
  kaldırmak da tam videoya dönme taslağı oluşturur.
- **Taslağı iptal:** Bir alanı değiştirin; kaydetmeden **Taslak değişikliklerden
  vazgeç**'e basın. Son kayıtlı bölümler geri gelmelidir; diğer kaydedilmemiş video
  değişiklikleri de geri alınır. Tarayıcıda kayıtsız Android taslağı görünmez.
- **Ondalık virgül:** Android'de `1,5–4,5` girin. Kaydedilebiliyorsa katkı 3 saniye
  olmalıdır. Bu Android giriş davranışıdır; web'de gerekirse nokta kullanın.
- **Geçersiz değerler:** Boş başlangıç, `5–2`, negatif başlangıç, kaynak süresinden
  büyük bitiş, `0–0,01` ve birbiriyle çakışan `1–4 / 3–5` aralıklarını deneyin.
  Uyarı görünmeli; kayıt düğmesi pasif olmalı ve sunucudaki eski bölümler korunmalıdır.
- **Etkileşim ayrımı:** Açık bölüm alanlarında metin seçmeye/düzenlemeye çalışın.
  Bunun montaj sıralamasını başlatmaması gerekir.

Minimum bölüm uzunluğu **0,04 saniye**dir. Hata denemesi sonrası değerleri düzeltin
veya taslaktan vazgeçin. Fotoğraflarda video bölümü düzenleme düğmesi bulunmamalıdır.

## 6. Toplam süre, sınır ve render durumu

Android'in **Toplam süre** satırındaki limiti esas alın; sabit 90 saniye varsaymayın.
Toplam = fotoğraf süreleri + tutulacak video bölümleri/tam videolar + varsa kartlar.
Örneğin 3 saniyelik fotoğraf ve `1–4 / 6–9` video bölümleri, başka medya/kart yoksa
**9 saniye** eder. Satırdaki **Kaydedilmiş medya süresi**, kayıt öncesinde eski
değeri gösterebilir; taslak toplamı üstteki **Toplam süre** satırından okuyun.

1. Kaydedilmiş toplam sınır altındayken geçerli video bölümlerini not edin.
2. Bölümleri tam videoya genişleterek bir **sınır aşan taslak** oluşturun. Kaynaklar
   kısa kalıyorsa ek bir geçerli, uzun deneme videosu yükleyin. Örneğin limit 90,
   önceki toplam 43 ise 60 saniyelik ek video toplamı 103'e çıkarır.
3. En az kaç saniye azaltmanız gerektiğini söyleyen uyarıyı kontrol edin.
   **Video bölümlerini kaydet** pasif olmalı; otomatik kesme/bölme yapılmamalıdır.
4. Bölümleri toplam sınırın altına indirecek şekilde kısaltın veya fazla medyayı
   **Montajdan kaldır** ile çıkarın. Geçerli taslağı kaydedip iki istemciden yenileyin.

**Beklenen:** Limit, giriş/çıkış kartları varsa onları da kapsar. Sunucuda zaten
sınır aşan montaj varsa sıralama kaydı da reddedilebilir; önce trim/kaldırma ile
toplamı düzeltin. Bu rehber limit ayarını doğrudan değiştirmeyi gerektirmez.

Kaydedilmiş sıra/bölüm değişince Android yeniden Reel oluşturulması gerektiğini
belirtebilir. Android'de render başlatma düğmesi yoktur. Gerçek çıktıyı denemek
isterseniz **tarayıcıda**, gerekli dojo logosu yapılandırılmış deneme paketinde:

1. Bölümleri önce kaydedin; kayıtsız taslağın render'a girmesini beklemeyin.
2. **Kaydedilmiş montajı render et**'e basın; worker sonucunu bekleyin.
3. **Kaydedilmiş Reel önizlemesi** üzerinden sıralama/bölümleri izleyin.
4. Sonra sırayı değiştirin: önceki render güncel kabul edilmemeli, yeniden render
   istenmelidir. Logo/worker eksikse render başarısı beklemeyin. Yayın onayı vermeyin.

## 7. Başka istemcide değişiklik ve bağlantı kesilmesi

### 7.1. Kaydedilmemiş taslak varken web sırasını değiştirin

1. Android'de bir video aralığını değiştirin; **kaydetmeyin**.
2. Tarayıcıda başka bir sıralama kaydedin.
3. Android'i arka plana alıp tekrar açın; otomatik sorgu bitince taslak korunmalı,
   çakışma/eski veri uyarısı varsa yazma işlemleri engellenmelidir.
4. **Montaj medyası → Yenile**'ye basarak güncel veriyi açıkça alın.
5. Aynı pakette kaldıysanız taslak korunabilir; sonucu inceleyip kendiniz kaydedin
   veya **Taslak değişikliklerden vazgeç** ile iptal edin.

Paket tamamen başka pakete geçmişse eski taslak yeni pakete otomatik
uygulanmamalıdır. **Vazgeç**, ardından **Yenile** ile devam edin. Bunun için gerçek
bir paketi yayınlamanız/silmeniz gerekmez; paket değişimi otomatik testte sınanır.

### 7.2. Okuma hatası ve tekrar yazma koruması

1. Android'de kaydedilmemiş bir bölüm taslağı bırakın.
2. Deneme cihazında ağı kapatın, sonra **Montaj medyası → Yenile**'ye basın.
3. Taslak kaybolmamalı; sonraki yazma işlemleri engellenmelidir.
4. **Taslak değişikliklerden vazgeç**'e basmak bağlantı/okuma korumasını kaldırmamalı.
5. Ağı açın ve **Yenile**'ye basın; başarılı okuma sonrası tekrar düzenleyin.

Yerel emülatörde ağı gerçekten kesemiyorsanız yalnız önceden seçtiğiniz **ayrı
deneme backend'ini** PowerShell'den durdurup yeniden başlatabilirsiniz:

```powershell
docker compose @ComposeArgs stop backend
# Android'de Yenile ve hata/engelleme kontrolünü yapın; sonra:
docker compose @ComposeArgs start backend
```

Sunucu açılınca Android'de **Yenile** kullanın. Kaydetme yanıtının tam kaybolduğu
anı elle tutturmanız gerekmez; bölüm 9.3'teki testler bu yarışı kontrollü sınar.

## 8. Görünüm ve erişilebilirlik — Android

1. Telefonu döndürün; açık taslak kaybolmamalı. Uygulamayı zorla kapatmayı bu
   denemeyle eş tutmayın; süreç ölümünde taslak korunması bu işte garanti edilmez.
2. Android'in koyu/açık temasında başlık, uyarı, tutamaç ve bırakma çizgisini kontrol edin.
3. Sistem yazı boyutunu büyütün; uzun dosya adları ve bölüm alanları kesilmemelidir.
4. TalkBack açın; dosya adını içeren yukarı/aşağı eylemleriyle sırayı değiştirin.
5. Tablet veya geniş pencerede gezinmeyi ve medya alanını kontrol edin; ekran
   klavyesi açıkken alanlara ve kaydetme düğmesine ulaşılabilmelidir.

## 9. Arayüzden yapılamayan kontroller — PowerShell

### 9.1. Sunucudaki dosya, sıra ve bölümleri yalnız okuyarak gözleme

Bu bölüm isteğe bağlıdır. Yeni bir kodla ayrı gözlem oturumu kurar; kimlik bilgisi
ekrana yazdırmaz. `$Base` değerini kendi deneme backend origin'inizle değiştirin.
Yerel HTTP sunucusunda deneme çerez ayarı `COOKIE_SECURE=false` olmalıdır.

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
$Base = 'http://localhost:8000'
$Code = Read-Host 'Yeni tek kullanımlık deneme kodu'
$Body = @{ code = $Code; kind = 'browser'; name = 'Montaj35 PowerShell gozlem' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/validate" -SessionVariable DojoSession -ContentType 'application/json' -Body $Body | Out-Null
$Code = $null
$Body = $null
$Snapshot = Invoke-RestMethod -Uri "$Base/api/packages/active/editor" -WebSession $DojoSession
$Snapshot.package | Select-Object id, folder_name, status
$Snapshot.montage | Select-Object combined_duration, max_duration_seconds, over_limit, duration_complete, card_duration
$Snapshot.montage.order
$Snapshot.montage.selections | ConvertTo-Json -Depth 8
$Snapshot.media | Select-Object media_id, filename, status, source_duration, effective_duration
```

Aktif paket yoksa editor isteğinin `404` dönmesi normaldir; gözlem için paket
oluşturulmaz. Android'de kaldırma yaptıktan sonra sunucu kaynağını kontrol edin:

```powershell
$Snapshot = Invoke-RestMethod -Uri "$Base/api/packages/active/editor" -WebSession $DojoSession
$MediaId = Read-Host 'Kaldirdiginiz deneme dosyasinin media_id degeri'
$Media = @($Snapshot.media | Where-Object { $_.media_id -eq $MediaId })
if ($Media.Count -ne 1) { throw 'Tek bir deneme medyasi secilmeli.' }
$Media[0] | Select-Object filename, status
$Media[0].artifacts | Where-Object { $_.kind -eq 'original' } | Select-Object kind, available
```

**Beklenen:** Kaldırılmış medyada `status=removed`, orijinal dosyada `available=True`.
Geri yüklemeden sonra aynı kimlik `finalized` olmalıdır. `selections` kaydedilmiş
bölümleri gösterir; kayıtsız Android taslağını göstermez. Test medyası dışındaki
kişisel dosya adlarını veya oturum nesnesini paylaşmayın.

### 9.2. Eski paket kimliğine yazma reddi

Android eski paket kimliği alanını kullanıcıya açmaz. Bölüm 9.1 oturumunda,
kimlik korumasını **bilerek yanlış folder** ile test edebilirsiniz. Bu sırada diğer
istemcilerden değişiklik yapmayın; yalnız deneme dosyasını seçin.

```powershell
$Before = Invoke-RestMethod -Uri "$Base/api/packages/active/editor" -WebSession $DojoSession
$Id = @($Before.montage.order)[0]
if ([string]::IsNullOrWhiteSpace($Id)) { throw 'Once montaja bir deneme medyasi ekleyin.' }
$EncodedId = [Uri]::EscapeDataString($Id)
$WrongFolder = [Uri]::EscapeDataString("$($Before.package.folder_name)-eski-deneme")
try {
    Invoke-RestMethod -Method Post -Uri "$Base/api/packages/active/media/$EncodedId/remove?expected_folder_name=$WrongFolder" -WebSession $DojoSession | Out-Null
    throw 'Yanlis paket kimligi kabul edildi; deneme basarisiz.'
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        'Beklenen sonuc: 409; yanlis pakete kaldirma uygulanmadi.'
    } else { throw }
}
$After = Invoke-RestMethod -Uri "$Base/api/packages/active/editor" -WebSession $DojoSession
$After.montage.order
$After.media | Where-Object { $_.media_id -eq $Id } | Select-Object media_id, status
```

**Beklenen:** Sıra değişmemiş, seçilen medya hâlâ `finalized` olmalıdır. Bu API
kontrolü Android'in ekran etkileşimini değil sunucudaki yanlış-paket korumasını sınar.

### 9.3. Kaybolan yanıt, bilinmeyen süre ve eşzamanlılık testleri

Ekrandan yapay sunucu yanıtı, bilinmeyen süre veya tam zamanlanmış paket değişimi
üretemezsiniz. Aşağıdaki komutlar mevcut otomatik testleri çalıştırır; kod yazmazsınız.
Repo kökünde, cihaz olmadan:

```powershell
./android/gradlew.bat -p android :app:testDebugUnitTest --tests '*MediaEditorTest' --tests '*AppViewModelTest' --tests '*DojoApiTest'
if ($LASTEXITCODE -ne 0) { throw 'Medya/API durum testleri basarisiz.' }
Start-Process (Resolve-Path 'android/app/build/reports/tests/testDebugUnitTest/index.html').Path
```

Raporda özellikle şunları arayın:

- `acknowledgedWriteCannotDiscardDraftIfReadBackIsAnotherPackageOrDifferentSelections`
- `failedPackageWriteRetainsDraftAndRequiresExplicitReadBeforeRetry`
- `discardingDraftCannotBypassFailedWriteReadBackGuard`
- `automaticRefreshDoesNotAuthorizeOverwritingConcurrentMontageChanges`
- `limitAndUnknownSourceBlockSavingWithoutInventingDuration`
- `editorReadFailureBlocksWritesAndRevocationClearsEditor`

Tam Android ana makine kontrolü:

```powershell
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
if ($LASTEXITCODE -ne 0) { throw 'Android ana makine kontrolu basarisiz.' }
```

### 9.4. Otomatik dokunma testleri — yalnız ayrı test emülatörü

Testler uygulamayı kurabilir ve test etkinliği açabilir. Kişisel/üretim kurulumunda
çalıştırmayın. Başka cihazları ayırıp yalnız ayrı emülatörü bağlı bırakın; `$Serial`
ve `$Adb` bölüm 2.2'deki değerlerdir.

```powershell
& $Adb devices -l
$env:ANDROID_SERIAL = $Serial
./android/gradlew.bat -p android :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.MediaEditorPanelTest'
if ($LASTEXITCODE -ne 0) { throw 'Montaj arayuz testleri calisamadi veya basarisiz.' }
Remove-Item Env:ANDROID_SERIAL -ErrorAction SilentlyContinue
```

Bu sınıf bırakmadan kayıt yapılmamasını, iptal/Geri davranışını, pasif tutamacı,
yukarı/aşağı alternatifi, alan doğrulamasını ve kenarda kaydırmayı sınar.
**No connected devices!** cihaz eksikliğidir; arayüzün çalıştığının kanıtı değildir.
Test APK'sinin yalnız derlenmiş olması da bu testlerin geçtiği anlamına gelmez.

## 10. Sonuç kaydı

Her denemeye cihaz/API, uygulama sürümü, beklenen/görülen sonuç ve varsa hata notu
ekleyin. Ekran görüntülerinde kod/çerez/token ve kişisel dosya adlarını gizleyin.

- [ ] Sürükle-bırak sırası Android ve tarayıcıda kalıcı.
- [ ] İptal/Geri sırasında sıra değişmiyor; kenarda kaydırma çalışıyor.
- [ ] Yukarı/aşağı alternatifi ve yeni medyanın sona eklenmesi doğru.
- [ ] Kaldırma/geri yükleme çalışıyor; sunucu kaynağı korunuyor.
- [ ] Çoklu video bölümleri ve diğer videoların bölümleri korunuyor.
- [ ] Tam videoya dönüş, taslak iptali ve geçersiz giriş kontrolü doğru.
- [ ] Toplam süre/kartlar hesaba katılıyor; sınır aşımı açıkça engelleniyor.
- [ ] Çakışma/okuma hatası sırasında taslak korunuyor; vazgeçmek korumayı aşmıyor.
- [ ] Telefon/tablet, koyu tema, büyük yazı ve TalkBack kontrol edildi.

Deneme sonunda yalnız kendiniz başlattığınız deneme worker'ını gerekiyorsa
`docker compose @ComposeArgs stop worker` ile durdurun; web terminalinde `Ctrl+C`
kullanın. Medya/veritabanı dizinlerini silmeyin. Bu rehber gerçek Instagram yayını
veya paketi tamamlanmış duruma zorlamayı gerektirmez.
