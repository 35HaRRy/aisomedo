# Web dosya adı çakışması — Değişiklik özeti ve deneme rehberi (#28)

Bu rehber, `d1102bc` commitindeki değişiklikleri **tarayıcıdan** adım adım
denemeniz içindir. Arayüzde bulunmayan hazırlık ve dosya kontrolü işlemlerinde
**PowerShell** kullanılır. Python veya SQL kodu içermez.

> **Yalnızca ayrı bir deneme ortamı kullanın.** Üzerine yazma, mevcut medyayı
> sunucudan kalıcı olarak siler; geri alma düğmesi yoktur. Gerçek dojo
> dosyalarıyla denemeyin. Instagram bağlantısı kurmanız, yayın planını açmanız
> veya yayın onayı vermeniz gerekmez.

## 1. Neler değişti?

| Değişiklik | Tarayıcıda göreceğiniz sonuç |
| --- | --- |
| Çakışma karar alanı | **Güncel Paket → Fotoğraf ve video yükle** altında, çakışan satırda üç seçenek bulunur. |
| Mevcut hedefin gerçek önizlemesi | Fotoğraf veya oynatılabilir video; dosya adı, kaynak boyutu, yükleme tarihi ve medya kimliği gösterilir. Video kendiliğinden başlamaz. |
| **İkisini de koru** (`keep_both`) | Mevcut medya kalır; yeni dosya ilk boş sayısal sonekle kaydedilir: `rehber-gorsel (1).png` gibi. |
| **Yeni dosyayı kullan** (`keep_selected`) | Önizlenen mevcut medya, yeni dosya doğrulandıktan sonra silinir ve yerine yeni medya eklenir. |
| **Mevcut dosyayı koru** (`keep_target`) | Yeni yükleme atlanır; satır **Mevcut dosya korundu; yükleme atlandı** olur. |
| **Tümüne uygula** | Yalnızca aktif pakette, aynı normalleştirilmiş dosya adıyla şu anda bekleyen çakışmalara karar uygulanır. Diğer adlar ve gelecekteki yüklemeler etkilenmez. |
| Üzerine yazma güvenliği | Geri döndürülemez uyarısı ve ayrı onay kutusu vardır. Önizleme yüklenmeden veya onay verilmeden üzerine yazma düğmesi açılmaz. |
| Yenileme ve bağlantı hatası kurtarması | Karar sonrası her ilgili yüklemenin durumu kendi kimliğiyle sorgulanır. Mevcut dosyayı koruma niyeti, durum sorgusu başarısız olsa bile kurtarma kaydında tutulur. |
| Etkinlik ayrıntıları | **Mevcut medyanın üzerine yazıldı** olayında dosya adı, silinen medya kimliği ve yeni medya kimliği görünür. |

Çakışma, dosyanın içeriği değil **adı** üzerinden bulunur; büyük/küçük harf farkı
sayılmaz. Karar verilene kadar o yüklemeye ait medya parçaları gönderilmez.
Önizleme yeni seçtiğiniz dosyayı değil, **sunucudaki mevcut hedefi** gösterir.
Sunucu fotoğrafların işlenmiş JPEG, videoların işlenmiş MP4 sürümünü sunar.

Teknik olarak web yükleme denetleyicisi/arayüzü, API istemcisi, Türkçe metinler
ve etkinlik ekranı güncellendi. Backend'e oturum gerektiren hedef önizlemesi
eklendi. Toplu üzerine yazmada seçilen hedefin yerine ilk çakışmanın kullanılması
da düzeltildi. Bu çalışma Android arayüzünü veya medya galerisi eklemeyi kapsamaz.

## 2. Deneme ortamını hazırlayın

Bu değişiklikleri içeren **ayrı ve çalışan** ortamınız varsa bölüm 3'e geçin.
Yeni yerel ortam için Docker Desktop'ın Linux konteynerleri ve Node.js 22/npm
hazır olmalıdır. Komutları bu değişikliklerin bulunduğu repo kökünde çalıştırın.

### 2.1. Dizini ve verileri kontrol edin

```powershell
Set-Location -LiteralPath (Read-Host 'Deneme reposunun tam yolu')
git log -1 --oneline
docker compose version

Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 8000, 5434, 3000 } |
    Select-Object LocalAddress, LocalPort, OwningProcess

foreach ($Path in 'ops/db-data', 'ops/media-data') {
    if ((Test-Path -LiteralPath $Path) -and
        (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1)) {
        throw "$Path boş değil. İlk kurulum için ayrı bir deneme checkout'u seçin; mevcut verileri silmeyin."
    }
}
```

Portlar başka ortam tarafından kullanılıyorsa o ortamı durdurmayın; boş portları
olan ayrı ortam seçin. Son kontrol **ilk kurulum** içindir; kendi deneme
ortamınızı yeniden başlatırken verilerin dolu olması normaldir.

**Sadece Compose proje adını değiştirmek verileri ayırmaz:** bu repo
`ops/db-data` ve `ops/media-data` host dizinlerini bağlar. Gerçek verilerin
bulunduğu checkout'ta aşağıdaki yeni kurulum adımlarını uygulamayın.

### 2.2. Yerel ayarları hazırlayın

```powershell
if (-not (Test-Path -LiteralPath ops/.env)) {
    Copy-Item -LiteralPath ops/.env.example -Destination ops/.env
}
notepad ops/.env
```

Deneme dosyasında şu değerleri ayarlayın:

- `POSTGRES_PASSWORD`: denemeye özel, boş olmayan parola. Yerel örnekte
  harf/rakam kullanmak bağlantı adresindeki özel karakter sorunlarını önler.
- `COOKIE_SECURE=false`: **yalnızca yerel HTTP ortamında**. Üretimde HTTPS ve
  güvenli çerez ayarını koruyun.
- `PUBLIC_BASE_URL=http://localhost:3000`
- `PUBLIC_HTTPS_ORIGIN=http://localhost:3000`

Instagram uygulama bilgilerini doldurmanız gerekmez. Boş şifreleme anahtarı
satırına PowerShell ile yerel anahtar üretin; mevcut anahtar değiştirilmez:

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

`.env`, eşleştirme kodları ve oturum çerezlerini paylaşmayın veya Git'e eklemeyin.

### 2.3. Servisleri açın

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-web-conflict-deneme', '-f', 'ops/docker-compose.yml')
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose @ComposeArgs up -d --build db backend worker
docker compose @ComposeArgs ps
Invoke-RestMethod -Uri 'http://localhost:8000/health'
npm --prefix web ci
npm --prefix web run dev -- --host localhost --port 3000 --strictPort
```

Sağlık yanıtında `status: ok` beklenir. Son komutun terminalini açık bırakın;
tarayıcıda **http://localhost:3000** adresini açın. `8000` backend portudur,
web ekranı değildir. Aynı tarayıcıda sürekli `localhost` kullanın;
`127.0.0.1` farklı çerez/kurtarma kaydı oluşturabilir.

Sonraki komutlar için aynı repo kökünde **ikinci PowerShell penceresi** açın ve
orada da `$ComposeArgs` tanımlayın:

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-web-conflict-deneme', '-f', 'ops/docker-compose.yml')
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
```

## 3. Tarayıcıyı eşleştirin ve örnekleri hazırlayın

1. Üretilen **Pairing code** değerini tarayıcıdaki **Eşleştirme kodu** alanına girin.
2. **Tarayıcı adı** olarak `Web Çakışma Denemesi` yazın; **Eşleştir** düğmesine basın.
3. Kurulum sihirbazı açılsa da **Güncel Paket** bölümüne geçebilirsiniz:
   **http://localhost:3000/#/package**. Bu deneme için Instagram kurulumunu
   tamamlamanız gerekmez.
4. **Fotoğraf ve video yükle** alanındaki dosya/paket sınırlarının yüklenmesini bekleyin.

Ayırt edilebilir iki geçerli fotoğraf hazırlayın: **aynı ada**, farklı içeriğe
sahip olsunlar; örneğin biri turuncu, diğeri mavi. İki ayrı klasörde tutun.
İsterseniz aşağıdaki PowerShell komutları gerçek PNG örneklerini üretir;
mevcut dosyalara dokunmaz:

```powershell
Add-Type -AssemblyName System.Drawing
$TestDir = Join-Path $env:TEMP ('dojo-web-conflict-' + [Guid]::NewGuid().ToString('N'))
foreach ($Name in 'ilk', 'yeni') {
    $Dir = Join-Path $TestDir $Name
    New-Item -ItemType Directory -Path $Dir | Out-Null
    $Image = [System.Drawing.Bitmap]::new(640, 360)
    $Graphics = [System.Drawing.Graphics]::FromImage($Image)
    try {
        $Color = if ($Name -eq 'ilk') { [System.Drawing.Color]::Orange } else { [System.Drawing.Color]::RoyalBlue }
        $Graphics.Clear($Color)
        $Image.Save((Join-Path $Dir 'rehber-gorsel.png'), [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $Graphics.Dispose()
        $Image.Dispose()
    }
}
Copy-Item -LiteralPath (Join-Path $TestDir 'ilk/rehber-gorsel.png') -Destination (Join-Path $TestDir 'ilk/baska-gorsel.png')
Write-Host "İlk dosya: $(Join-Path $TestDir 'ilk/rehber-gorsel.png')"
Write-Host "Yeni dosya: $(Join-Path $TestDir 'yeni/rehber-gorsel.png')"
Write-Host "Diğer ad: $(Join-Path $TestDir 'ilk/baska-gorsel.png')"
```

Bir sonraki adımlarda **ilk** turuncu, **yeni** mavi dosyadır. Klasörlerini ve
dosyalarını denemeler bitene kadar değiştirmeyin. Video için ayrıca aynı adı
taşıyan iki geçerli MP4/MOV dosyasını ayrı klasörlerde hazırlayın; uzantı
değiştirmek bir dosyayı geçerli videoya dönüştürmez.

## 4. İlk yükleme ve çakışmayı görün — tarayıcı

1. **Fotoğraf ve video seç** ile `ilk/rehber-gorsel.png` dosyasını seçin.
2. **Pakete eklendi** durumunu bekleyin. **İşlem sırasına alındı** veya %100,
   doğrulamanın tamamlandığı anlamına gelmez. Worker döngüsü 10 saniyedir;
   görünür sekmede durumlar yaklaşık 5 saniyede yenilenir. Video daha uzun sürebilir.
3. Aynı seçiciden `yeni/rehber-gorsel.png` dosyasını seçin.
4. Yeni satırda **Dosya adı çakışıyor**, üç karar seçeneği ve **turuncu mevcut
   fotoğrafın** önizlemesi görünmelidir. Dosya adı, boyut, tarih ve **Mevcut medya
   kimliği** de gösterilir.
5. Henüz karar uygulamayın. `F12 → Network` alanında bu yükleme için
   `POST /api/media/uploads` yanıtı `status: conflict` olmalı; karar öncesi
   bu kimliğe ait `PUT .../ranges` olmamalıdır. Düzenli durum sorguları normaldir.

Birden fazla mevcut hedef varsa **Değiştirilecek mevcut dosya** seçicisi
görünür. Tek hedef varsa seçici görünmemesi normaldir.

## 5. İkisini de koruyun — tarayıcı

1. Bölüm 4'teki çakışan satırda **İkisini de koru (yeni dosyaya numara ekle)**
   seçili olsun. Bu, başlangıçtaki güvenli seçenektir.
2. **Aynı adlı mevcut çakışmaların tümüne uygula** kutusunu kapalı bırakın.
3. O satırın **Kararı uygula** düğmesine basın.
4. Yükleme devam etmeli ve sonunda **Pakete eklendi** olmalıdır.

Beklenen: turuncu mevcut medya korunur; mavi dosya ilk boş numarayla kaydedilir.
Yeni/boş denemede ad `rehber-gorsel (1).png` olur. Önceki denemeler varsa numara
daha büyük olabilir. Kurtarma satırının başlığı seçtiğiniz orijinal adı göstermeye
devam edebilir; **kaydedilen son adı** bölüm 11'deki salt okunur kontrolden doğrulayın.

## 6. Mevcut dosyayı koruyun — tarayıcı

1. `yeni/rehber-gorsel.png` dosyasını ana seçiciden yeniden seçin.
2. Çakışan yeni satırda **Mevcut dosyayı koru (yüklemeyi atla)** seçin.
3. Tümüne uygulama kapalıyken **Kararı uygula** düğmesine basın.
4. **Mevcut dosya korundu; yükleme atlandı** görünmelidir; yeni medya parçaları
   gönderilmez. Önceki turuncu dosya ve bölüm 5'te eklenen mavi kopya korunur.
5. `Ctrl+R` ile sayfayı yenileyin. Aynı satır hâlâ atlanmış görünmelidir;
   **Yükleme artık mevcut değil** gibi hatalı bir duruma dönüşmemelidir.

**Listeden kaldır** yalnızca tarayıcı satırını/kurtarma kaydını kaldırır;
paketteki medyayı silmez. Çakışan satırı kaldırmak da sunucudaki bekleyen
çakışmayı çözmek değildir; sonraki toplu karara dahil olabilir.

## 7. Yeni dosyayla değiştirin ve etkinlik kaydını kontrol edin — tarayıcı

> Bu bölüm gerçekten medya siler. Yalnızca oluşturduğunuz deneme dosyasını hedefleyin.

1. Mavi dosyayı tekrar seçin. Mevcut hedef hâlâ turuncu görünmelidir.
2. Önizlemenin altındaki **Mevcut medya kimliği** değerini not edin.
3. **Yeni dosyayı kullan (mevcut dosyayı değiştir)** seçin.
4. **Bu işlem geri döndürülemez** uyarısı görünmelidir.
   **Mevcut dosyanın kalıcı olarak silineceğini anlıyorum** kutusu başlangıçta
   boş, **Mevcut dosyanın üzerine yaz** düğmesi kapalı olmalıdır.
5. Önizleme yüklenene kadar bekleyin. Onay kutusunu işaretleyin; düğme açılmalıdır.
   Kararı veya toplu uygulama kutusunu değiştirirseniz onay yeniden istenmelidir.
6. **Mevcut dosyanın üzerine yaz** düğmesine bir kez basın. Karar uygulanırken
   düğmeler kapanır; sonunda **Pakete eklendi** beklenir.
7. **Etkinlik** bölümüne gidin: **Dosya adı çakışması çözüldü** ve işlem
   tamamlandıktan sonra **Mevcut medyanın üzerine yazıldı** olaylarını arayın.
8. Üzerine yazma olayında `rehber-gorsel.png`, not ettiğiniz **Silinen medya**
   kimliği ve farklı bir **Yeni medya** kimliği görünmelidir.
9. Güncel Paket'e dönüp aynı adı yeniden seçin. Bu kez mevcut hedefin önizlemesi
   **mavi** olmalıdır. Bu son denemeyi **Mevcut dosyayı koru** ile kapatın.

Silme, karar düğmesine basıldığı an değil yeni medyanın sunucuda doğrulanması
sırasında yapılır. Bu yüzden sadece karar olayının görünmesi, gerçek üzerine
yazmanın tamamlandığını kanıtlamaz. Mutasyonu worker yaptığı için üzerine yazma
olayında **Sistem** görünmesi normaldir.

## 8. Tümüne uygulamanın sınırını deneyin — tarayıcı

### 8.1. Aynı adlar atlanır, başka ad etkilenmez

1. `ilk/baska-gorsel.png` dosyasını yükleyin; **Pakete eklendi** olmasını bekleyin.
2. `yeni/rehber-gorsel.png` dosyasını iki ayrı seçimle yeniden ekleyin. İki yeni
   satır da **Dosya adı çakışıyor** olmalıdır; henüz karar vermeyin.
3. `ilk/baska-gorsel.png` dosyasını tekrar seçin; üçüncü çakışma satırı oluşsun.
4. `rehber-gorsel.png` satırlarından **birinde**, **Mevcut dosyayı koru** seçin,
   **Aynı adlı mevcut çakışmaların tümüne uygula** kutusunu işaretleyin ve
   aynı satırın **Kararı uygula** düğmesine basın.
5. İki `rehber-gorsel.png` satırı da **Mevcut dosya korundu; yükleme atlandı**
   olmalıdır. `baska-gorsel.png` satırı çakışma olarak kalmalıdır.
6. Kalan başka adlı çakışmayı kendi satırından, toplu kutu kapalıyken çözün.

### 8.2. Aynı adlı iki yükleme birlikte devam eder

1. Mavi `rehber-gorsel.png` dosyasını iki ayrı seçimle yeniden ekleyin.
2. Bir satırda **İkisini de koru**, toplu kutu açık, ardından **Kararı uygula** seçin.
3. İki yükleme de sırayla devam edip **Pakete eklendi** olmalıdır. Son adlarının
   birbirinden farklı numaralar aldığını bölüm 11'den kontrol edin.
4. Aynı dosyayı **karardan sonra** tekrar seçin: yine çakışma sormalıdır;
   önceki toplu tercih yeni yüklemeler için saklanan bir varsayılan değildir.

Toplu üzerine yazmayı seçerseniz ayrıca toplu kapsam uyarısı çıkar ve açık onay
gerekir. Bu, aynı adlı mevcut çakışmaların **üzerine yazma kararını** kapsar;
seçtiğiniz mevcut hedef kimliği değiştirilmez. Güvenli temel toplu denemeler
için yukarıdaki koruma seçeneklerini kullanın. Toplu kapsam sunucudaki mevcut
uyumlu çakışmalardır; yalnızca o anda görünen satırlar olduğunu varsaymayın.

## 9. Yenileme, önizleme hatası ve bağlantı kurtarması — tarayıcı

### 9.1. Çakışma beklerken sayfayı yenileyin

1. Yeni bir çakışma oluşturun ve karar vermeden `Ctrl+R` yapın.
2. Aynı tarayıcı/origin/oturumda satır ve mevcut hedefin önizlemesi geri gelmelidir.
3. **İkisini de koru → Kararı uygula** seçin.
4. **Dosya yeniden seçilmeli** görünmelidir: yenileme sonrası dosyanın içeriği
   tarayıcıda tutulmaz.
5. İlgili satırın **Orijinal dosyayı yeniden seç: ...** alanından aynı orijinal
   dosyayı seçin. Kimlik kontrolünden sonra aynı yükleme devam etmelidir.

Bu denemeyi yeniden yapıp **Mevcut dosyayı koru** seçerseniz dosyayı tekrar
seçmeden atlama kararı verebilmelisiniz. Ana seçiciden yeni satır açmak ile
satırın orijinal dosya seçicisini kullanmak farklı işlemlerdir.

### 9.2. Önizleme yüklenemiyorsa üzerine yazılmasın

1. Chrome/Edge'de `F12 → Network` açın. Bir çakışmanın `.../preview` isteğine
   sağ tıklayıp **Block request URL** seçin; ardından sayfayı yenileyin.
   Gerekirse **Network request blocking** panelinde engellemeyi etkinleştirin.
2. **Önizleme yüklenemedi** uyarısı ve **Önizlemeyi yeniden yükle** düğmesi beklenir.
3. **Yeni dosyayı kullan** seçip onay kutusunu işaretleseniz bile üzerine yazma
   düğmesi kapalı kalmalıdır.
4. İstek engelini kaldırın; **Önizlemeyi yeniden yükle** düğmesine basın.
5. Önizleme tekrar yüklenmeli ve onay yeniden istenmelidir. Denemeyi
   **Mevcut dosyayı koru** ile kapatabilirsiniz; bu karar önizleme şartı taşımaz.

### 9.3. Karar başarılı, sonraki durum sorgusu başarısız olsun — isteğe bağlı

1. Yeni bir çakışma oluşturun; Network'ten onun yükleme kimliğini alın.
2. Yalnızca tam durum adresini engelleyin:
   `http://localhost:3000/api/media/uploads/<yükleme-kimliği>`.
   `/resolve`, `/conflicts/.../preview` veya bütün `/api` isteklerini engellemeyin.
3. **Mevcut dosyayı koru → Kararı uygula** seçin. Network'te `/resolve` isteğinin
   başarılı olduğunu, sonraki durum isteğinin engellendiğini doğrulayın.
4. Engeli kaldırıp `Ctrl+R` yapın. Satır **Mevcut dosya korundu; yükleme atlandı**
   olmalıdır; **Yükleme artık mevcut değil** olmamalıdır.
5. Tüm istek engellerini kapatın. Toplu denemelerde eksik hedef bilgileri önce
   yeniden alınır; alınamıyorsa karar gönderilmez. Bağlantı düzeldikten sonra
   **Çakışmayı yenile** veya aynı karar düğmesiyle tekrar deneyebilirsiniz.

## 10. Video, güvenlik, dar ekran ve klavye — tarayıcı

- **Video:** İlk geçerli MP4/MOV'u yükleyip **Pakete eklendi** bekleyin. Aynı adlı
  ikinci videoyu seçin. Mevcut hedef video oynatıcısında açılmalı, kendiliğinden
  oynamamalıdır. Oynatın ve zaman çizgisinde ileri alın. Denemeyi koruma
  seçeneklerinden biriyle kapatın. Görsel denemelerinin isimleriyle karıştırmayın.
- **Oturumsuz erişim:** Network'teki önizleme URL'sini ayrı, **eşleştirilmemiş**
  gizli pencerede açın. Medya görünmemeli; istek `401` dönmelidir. Gizli pencereyi
  eşleştirmeyin ve çerez kopyalamayın.
- **Hedef sınırı:** Eşleştirilmiş pencerede önizleme URL'sindeki yalnızca hedef
  medya kimliğini `olmayan-hedef` yapın: `404` beklenir. Asıl çakışmayı çözdükten
  sonra eski önizleme adresine yeni istek gönderirseniz `409` beklenir. Network'te
  başarılı önizleme yanıtı `Cache-Control: no-store` ve
  `X-Content-Type-Options: nosniff` başlıklarını taşımalıdır.
- **Dar ekran:** DevTools cihaz görünümünde 390 px ve 320 px genişliği deneyin.
  Uzun dosya adları/kimlikler kırılmalı, seçenekler taşmamalı, yatay kaydırma
  gerekmemelidir. Önizleme ve uyarı okunabilir kalmalıdır.
- **Klavye:** `Tab` ile seçeneklere/düğmelere ulaşın; radyo seçeneklerini yön
  tuşlarıyla, kutuları `Space`, karar düğmesini `Enter` ile kullanın. Görünür
  odak bulunmalı; karar sonrası odak kaybolmak yerine satır başlığına dönmelidir.

## 11. Kaydedilen adları ve değişen kimliği kontrol edin — PowerShell

Bu ekran tam medya galerisi değildir. Son sonekli adlar ve sunucudaki mevcut
kimlikler için, **yalnızca yerel Compose ortamında**, ikinci PowerShell
penceresinden manifest'i salt okunur inceleyebilirsiniz:

```powershell
$PackageFolder = Read-Host 'Güncel Paket ekranındaki klasör başlığını aynen yazın'
$PackageDir = Join-Path 'ops/media-data' $PackageFolder
$ManifestPath = Join-Path $PackageDir 'manifest.json'
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw 'Manifest bulunamadı. Repo dizinini ve aktif paket başlığını kontrol edin.'
}
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$Manifest.media |
    Where-Object { $_.status -eq 'finalized' } |
    Select-Object filename, media_id, status |
    Format-Table -AutoSize
```

- **İkisini de koru:** asıl ad kalır, farklı kimlikli numaralı ad eklenir.
- **Mevcut dosyayı koru:** mevcut medya listesi değişmez.
- **Yeni dosyayı kullan:** asıl ad yeni kimlikle bulunur; not ettiğiniz eski hedef
  kimliği manifest'te artık bulunmaz. Önceki numaralı kopyalar korunur.

Bu kontrol dosyayı değiştirmez. Manifest'i elle düzenlemeyin; medya dizininden
dosya silerek çakışma yaratmaya çalışmayın. Uzak sunucuda bu yerel dizin mevcut
olmayabilir; tarayıcı önizlemesi ve Etkinlik kontrolünü kullanın.

## 12. Sorun çözme, otomatik kontroller ve kapatma

| Gözlem | Kontrol |
| --- | --- |
| Çakışma seçenekleri yok | Backend ve web'in #28 değişikliklerini içerdiğinden emin olun. İlk dosyanın gerçekten **Pakete eklendi** olmasını bekleyin. |
| Önizleme yeni dosyayla aynı görünüyor | Önizleme mevcut hedefindir. Farklı içerikli, aynı adlı iki dosya kullanın. |
| Üzerine yazma düğmesi kapalı | Hedef önizlemesi yüklenmiş ve ayrı kalıcı silme onayı işaretli olmalı. Karar/hedef/toplu kapsam değişince yeniden onay verin. |
| Önizleme hata veriyor | Backend/oturum, istek engelleme ve hedefin hâlâ mevcut olması; **Önizlemeyi yeniden yükle** veya **Çakışmayı yenile**. |
| %100 ama üzerine yazma olayı yok | %100 aktarımı gösterir. Worker doğrulamasının başarıyla bitmesini bekleyin; başarısız medya gerçek üzerine yazma değildir. |
| Toplu işlem başka satırları etkilemedi | Farklı adlar kapsam dışıdır. Aynı ada ilişkin eksik bilgiler/bağlantı hatası varsa kararı yeniden deneyin. |
| Yenilemeden sonra dosya isteniyor | Beklenen: dosya içerikleri tarayıcıda saklanmaz. Satırın orijinal dosya seçicisini kullanın. |
| Oturum tutulmuyor | Yerel HTTP'de `COOKIE_SECURE=false`; aynı `localhost:3000` adresi ve eşleştirilmiş tarayıcı. |

Servis durumunu ve günlüklerini görmek için:

```powershell
docker compose @ComposeArgs ps
docker compose @ComposeArgs logs --tail 60 backend worker
```

İsteğe bağlı otomatik web kontrolleri, repo kökünden:

```powershell
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

Günlükleri paylaşmadan önce hassas değerleri çıkarın. Vite terminalinde `Ctrl+C`
ile kapatın. Yalnızca **bu rehberde başlattığınız deneme projesini**, verileri
silmeden durdurmak için:

```powershell
docker compose @ComposeArgs stop worker backend db
```

`down -v`, veritabanı temizleme veya medya silme komutu gerekmez. Oluşturduğunuz
yerel örnek klasörünü isterseniz daha sonra Dosya Gezgini'nden kaldırabilirsiniz;
bu işlem sunucudaki deneme medyalarını silmez.

## Doğrulama notu ve ilgili rehberler

Geliştirmede web **178**, backend **135**, core **593**, worker **140** test geçti;
core'da **3** test atlandı. Web tip kontrolü ve üretim derlemesi geçti. Önceden
mevcut Python lint/tip hataları bu çalışmada değiştirilmedi.

Chromium'da kontrollü API yanıtlarıyla 1280 px masaüstü ve 390 px mobil görünüm,
önizleme/onay koşulları ve klavyeyle karar uygulama kontrol edildi. Güvenlik ve
video aralık istekleri backend testlerinde sınandı. Bu, yeni bir canlı
Docker/worker ortamında yukarıdaki bütün elle deneme adımlarının çalıştırıldığı
anlamına gelmez. Hazırlık komutları bu rehberi yazarken canlı servislerde
çalıştırılmadı; 10 PowerShell bloğu sözdizimi açısından kontrol edildi. Örnek PNG
üretme bloğu ayrıca Windows'ta geçici bir dizinde başarıyla çalıştırıldı.

- [#27 web yükleme rehberi](issue-27-web-upload-deneme-rehberi.md): duraklatma,
  içerik eşleştirme ve genel aktarım kurtarması. Oradaki “web çakışma çözmez”
  notları #27'nin eski kapsamıdır; #28 için bu rehber geçerlidir.
- [Dosya adı çakışması domain/API rehberi](filename-conflict-cozum-rehberi.md):
  önceki #8 altyapısı. Güncel web denemelerini buradan takip edin.
