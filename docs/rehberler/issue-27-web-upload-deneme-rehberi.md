# Tarayıcıdan devam edebilir medya yükleme — Değişiklik özeti ve deneme rehberi (#27)

Bu rehber, yeni yükleme ekranını **tarayıcıda** adım adım denemeniz içindir.
Arayüzde bulunmayan hazırlık/yönetim işlemleri için **PowerShell** komutları
verilir. Python veya SQL kodu çalıştırmanız gerekmez.

> **Ayrı bir deneme ortamı kullanın.** Yüklenen medya, dosya/paket sınırları ve
> istemci erişim kararları sunucuda kalıcıdır. Gerçek dojo verileriyle denemeyin.
> Bu rehber Instagram bağlantısı kurmayı, yayın planını etkinleştirmeyi veya
> yayın onayı vermeyi gerektirmez. Veritabanı ya da medya silme komutu içermez.

## 1. Neler değişti?

| Değişiklik | Göreceğiniz sonuç |
| --- | --- |
| Güncel Paket içinde yükleme alanı | Birden fazla fotoğraf/video seçebilirsiniz. |
| Sıralı, 2 MiB parçalı aktarım | Aynı anda bir dosya aktarılır; diğerleri bekler. |
| Dosya özeti hazırlama | Dosya küçük parçalarla okunur. Bu sırada henüz medya gönderilmez. |
| Sunucunun doğruladığı ilerleme | Gösterilen bayt ve yüzde, sunucunun kaydettiği parçalara dayanır. |
| Duraklat/devam et/tekrar dene | Aynı oturumda dosyayı tekrar seçmeden devam edebilirsiniz. |
| Yenileme sonrası kurtarma | Orijinal dosyayı yeniden seçerek kayıtlı yüklemeye devam edebilirsiniz. |
| Yanlış dosya kontrolü | Aynı ad ve boyutta olsa bile farklı içerik, mevcut yüklemeye bağlanmaz. |
| Sunucudan alınan boyut sınırları | Boş/büyük dosya aktarım başlamadan reddedilir; paket sınırını sunucu denetler. |
| Medya doğrulama sonucu | Kuyruğa alınma, kabul edilme değildir. Başarı yalnızca **Pakete eklendi** durumudur. |
| Dosya adı çakışması | Aktarım durur; bu ekran otomatik yeniden adlandırmaz veya üzerine yazmaz. |
| Oturum kaybı kontrolü | Erişim iptal edilirse aktarım durur ve eşleştirme ekranına dönülür. |

**Önemli ayrım:** Tarayıcı dosyanın içeriğini saklamaz; yalnızca yükleme kimliği,
dosya özellikleri ve içerik özetleri gibi kurtarma bilgilerini saklar. Sayfayı
yenilediğinizde aynı dosyayı yeniden seçmeniz gerekir. Dosyayı deneme bitene kadar
taşımayın, silmeyin veya düzenlemeyin.

## 2. Ortamı hazırlayın

Çalışan, bu değişiklikleri içeren **ayrı bir yerel deneme ortamınız** varsa
doğrudan bölüm 3'e geçebilirsiniz. Yeni ortam için Docker Desktop (Linux
konteynerleri), Node.js/npm ve aşağıdaki çalışma dizini gerekir.

### 2.1. Doğru dal ve güvenli veri dizinleri

PowerShell'i bu değişikliklerin bulunduğu repo/worktree kökünde açın:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo\.worktrees\issue-27-web-upload'
git branch --show-current
docker info --format '{{.ServerVersion}}'
```

Bu oturumda dal `feat/issue-27-web-upload`. Başka bilgisayarda dizini değiştirin.
Eski checkout'tan başlatılan backend/web yeni ekranı içermeyebilir.

`8000`, `5434` ve `3000` portları kullanılabilir olmalıdır. Başka ortamın
servislerini bu rehber için durdurmayın. Yeni kurulumda `ops/db-data` ve
`ops/media-data` boş olmalıdır. **Compose proje adını değiştirmek bu bağlı host
dizinlerini ayırmaz.** Dolu dizin varsa mevcut verileri silmek yerine ayrı bir
deneme checkout'u kullanın.

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 8000, 5434, 3000 } |
    Select-Object LocalAddress, LocalPort, OwningProcess

foreach ($Path in 'ops/db-data', 'ops/media-data') {
    if ((Test-Path -LiteralPath $Path) -and
        (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1)) {
        throw "$Path boş değil. Yeni ortam kurmadan önce ayrı bir deneme dizini seçin."
    }
}
```

Bu boşluk kontrolü **ilk kurulum** içindir. Kendi deneme ortamınızı daha sonra
yeniden başlatırken verilerinin dolu olması normaldir.

### 2.2. Yerel ayarlar

```powershell
if (-not (Test-Path -LiteralPath ops/.env)) {
    Copy-Item -LiteralPath ops/.env.example -Destination ops/.env
}
notepad ops/.env
```

Yalnızca bu yerel ortam için düzenleyin:

- `POSTGRES_PASSWORD`: boş olmayan, denemeye özel bir parola; yerel örnekte
  harf/rakam kullanmak bağlantı adresi sorunlarını önler.
- `COOKIE_SECURE=false`: yalnızca yerel HTTP denemesinde. Üretimde HTTPS ve
  güvenli çerez ayarını koruyun.
- `PUBLIC_BASE_URL=http://localhost:3000`
- `PUBLIC_HTTPS_ORIGIN=http://localhost:3000`
- `META_APP_ID`, `META_APP_SECRET`: bu yükleme denemesi için doldurmanız gerekmez.

Boş `META_TOKEN_ENCRYPTION_KEY` satırına yerel anahtar üretmek için aşağıdaki
PowerShell kodunu kullanabilirsiniz. Mevcut anahtarı değiştirmez; anahtar ekrana
yazdırılmaz:

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

`.env` dosyasını, çerezleri ve eşleştirme kodlarını paylaşmayın veya Git'e eklemeyin.

### 2.3. Backend ve web'i başlatın

İlk aşamada worker'ı başlatmayın. Böylece aktarımın tamamlanması ile medyanın
doğrulanması arasındaki farkı rahatça görebilirsiniz.

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-web-upload-deneme', '-f', 'ops/docker-compose.yml')
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose @ComposeArgs up -d --build db backend
docker compose @ComposeArgs ps
Invoke-RestMethod -Uri 'http://localhost:8000/health'
npm --prefix web ci
npm --prefix web run dev -- --host localhost --port 3000 --strictPort
```

Sağlık yanıtında `status: ok` beklenir. Vite terminalini açık bırakın;
tarayıcıda **http://localhost:3000** adresini açın. `8000` backend portudur,
web arayüzü değildir. Bu rehber boyunca `localhost` adresini kullanın;
`127.0.0.1` ile dönüşümlü kullanmak ayrı çerez/kurtarma kayıtları oluşturur.

Sonraki komutlar için **aynı repo kökünde ikinci PowerShell penceresi** açın ve
orada da şu değişkeni tanımlayın:

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-web-upload-deneme', '-f', 'ops/docker-compose.yml')
```

## 3. Tarayıcıyı eşleştirin ve yükleme ekranını açın

İlk kodu üreten tarayıcı ekranı yoktur. İkinci PowerShell penceresinde:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
```

1. Çıktıdaki **Pairing code** değerini **Eşleştirme kodu** alanına yazın.
2. **Tarayıcı adı** olarak `Web Yükleme Denemesi` girin.
3. **Eşleştir** düğmesine basın.
4. Kurulum sihirbazı açılırsa ana gezinmeden **Güncel Paket** bölümüne geçin.
   Gerekirse **http://localhost:3000/#/package** adresini açın. Yükleme denemesi
   için Instagram/kurulum adımlarını tamamlamanız gerekmez.
5. **Fotoğraf ve video yükle** alanını bulun.

Beklenen: dosya/paket sınırları görünür; sınırlar alınana kadar seçici kapalıdır.
Yeni kuruluma ait varsayılanlar **2 GiB / 20 GiB**. Sunucuya ulaşılamıyorsa
sınırların alınamadığı uyarısı ve **Tekrar dene** görünür; bu durumda medya
gönderilmez.

## 4. Başarılı aktarımı ve doğrulamayı ayrı deneyin

1. Küçük, geçerli bir JPEG/PNG ve mümkünse 20–100 MiB boyutunda geçerli bir
   MP4/MOV hazırlayın. Her denemede farklı dosya adı kullanın.
2. **Fotoğraf ve video seç** ile ikisini birlikte seçin.
3. Dosya adlarını ve **Dosya özeti hazırlanıyor → Yükleniyor** durumlarını izleyin.
   Küçük dosyada ilk durum çok kısa sürebilir.
4. İlk dosya aktarılırken diğeri **Aktarım bekliyor** olmalıdır.
5. Worker kapalıyken tamamlanan aktarım **İşlem sırasına alındı** durumunda kalır.
   Yüzdenin %100 olması **Pakete eklendi** anlamına gelmez.

Bilinen küçük gösterim sınırı: tam sayıya yuvarlanan yüzde, son birkaç bayt
kalmışken de %100 yazabilir. Kesin ilerlemeyi bayt sayacı ve ilerleme çubuğuyla
kontrol edin; başarı ölçütü yine **Pakete eklendi** durumudur.

Medya doğrulamasını çalıştırmak için PowerShell'de:

```powershell
docker compose @ComposeArgs up -d --build worker
```

Tarayıcı açık ve görünürken bekleyin. Worker aralığı bu Compose dosyasında
10 saniye, tarayıcının durum yenilemesi yaklaşık 5 saniyedir; video işleme daha
uzun sürebilir. **Medya doğrulanıyor** kısa sürerse görünmeden geçebilir.
Geçerli medya için son durum **Pakete eklendi** olmalıdır.

**Listeden kaldır** yalnızca terminal durumdaki satırı/kurtarma kaydını kaldırır;
paketteki medyayı silmez. Bu ekran medya galerisi, montaj veya yayın onayı ekranı
değildir. Instagram'a bir gönderi paylaşmayın.

## 5. Duraklatma ve menüler arasında devamlılık — tarayıcı

1. Yeni adla, aktarımı fark edilecek kadar büyük geçerli bir video seçin.
2. Geliştirici araçlarında **Network → throttling → Slow 3G** gibi yavaş bir profil
   seçin. Çok yavaş isteğin 10 saniyelik zaman aşımına düşmesi normaldir; böyle
   olursa bölüm 6'daki **Tekrar dene** yolunu kullanın.
3. **Yükleniyor** sırasında ilgili satırın **Duraklat** düğmesine basın.
4. **Duraklatıldı** görünmelidir. Bir parça sunucuda zaten kaydedilmiş olabilir;
   sayılan baytlar devam ederken sunucudan yeniden öğrenilir.
5. **Ayarlar** bölümüne gidip **Güncel Paket** bölümüne dönün.
6. Aynı satır ve **Devam et** düğmesi kalmalıdır. Dosyayı yeniden seçmeden devam edin.
7. Network ayarını **No throttling** yapın.

Beklenen: yeni bir yükleme oluşturulmaz; sunucunun tamamını aldığı parçalar
atlanır. Eksik bir 2 MiB parça bütünüyle yeniden gönderilebilir. Diğer uygun
dosyalar, duraklatılan satır yüzünden kilitlenmez.

## 6. Bağlantı kesilmesi ve açıkça tekrar deneme — tarayıcı

1. Yeni bir video aktarımı başlatın; gerekirse Network'te yavaşlatın.
2. **Yükleniyor** sırasında **Network → Offline** seçin.
3. İstek başarısız olduğunda **Yükleme kesildi** ve bağlantı/tekrar deneme açıklaması
   beklenir. Offline ayarı yalnızca bu DevTools sekmesini etkiler.
4. **No throttling/Online** durumuna dönün.
5. İlgili yükleme satırındaki **Tekrar dene** düğmesine basın.

Beklenen: tarayıcı sunucu durumunu sorgular ve kayıtlı parçalardan devam eder.
Bağlantının geri gelmesi tek başına kesilmiş medya aktarımını otomatik başlatmaz.
Başlatma isteğinin yanıtı hiç gelmediyse tarayıcı kimliği bilmediği yüklemeye bayt
göndermez; açık tekrar deneme yeni, boş bir sunucu kaydı oluşturabilir.

## 7. Sayfa yenileme, yeniden seçme ve yanlış dosya — tarayıcı

1. Yeni adla video yüklemeye başlayın; bir miktar ilerledikten sonra **Duraklat**.
2. `Ctrl+R` ile yenileyin. **Dosya yeniden seçilmeli** ve
   **Orijinal dosyayı yeniden seç: ...** alanı görünmelidir.
3. Önce farklı bir dosya seçin. **Seçilen dosya orijinal dosyayla eşleşmiyor**
   uyarısı beklenir; mevcut yüklemeye bu içerik gönderilmez.
4. Aynı alandan gerçek orijinal dosyayı seçin.
5. Özet yeniden hesaplanır; içerik eşleşince mevcut yükleme devam eder.

İsterseniz aynı ad ve boyutta farklı içerik kontrolünü PowerShell'de, **orijinale
dokunmadan**, ayrı bir klasöre sahte kopya yazarak deneyebilirsiniz:

```powershell
$Original = (Resolve-Path -LiteralPath (Read-Host 'Orijinal deneme videosunun tam yolu')).Path
if ((Get-Item -LiteralPath $Original).Length -eq 0) { throw 'Boş dosya seçmeyin.' }
$WrongDir = Join-Path $env:TEMP ('dojo-yanlis-dosya-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $WrongDir | Out-Null
$Wrong = Join-Path $WrongDir ([System.IO.Path]::GetFileName($Original))
Copy-Item -LiteralPath $Original -Destination $Wrong
$Stream = [System.IO.File]::Open($Wrong, 'Open', 'ReadWrite')
try {
    $FirstByte = $Stream.ReadByte()
    $Stream.Position = 0
    $Stream.WriteByte([byte]($FirstByte -bxor 1))
} finally { $Stream.Dispose() }
Get-Item -LiteralPath $Original, $Wrong | Select-Object FullName, Length
```

Yeniden seçme alanında `$Wrong` yolundaki dosyayı seçin; sonra `$Original` yolundaki
gerçek dosyayla devam edin. Dosya adı/boyutu aynı kalır; yalnızca içerik değişir.
Bu yardımcı kopya geçerli medya olmak zorunda değildir, yanlış kimlik kontrolü
içindir. Oluşturulan geçici dosyayı daha sonra Dosya Gezgini'nden silebilirsiniz.

**Kuyruğa alınmış veya doğrulanan dosyada** yenileme sonrası tekrar dosya seçmek
gerekmez: medya zaten sunucudadır. Sonuç görünür sekmede sorgulanmaya devam eder.

## 8. Büyük ve boş dosyanın aktarım öncesi reddi

Limit değiştiren web ekranı yoktur. **Yalnızca deneme ortamında** küçük bir dosya
sınırı koyun; önce ekrandaki mevcut iki sınırı not edin:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-settings set-upload-limits --max-file-bytes 1048576
```

1. Tarayıcıyı yenileyin; dosya sınırı **1 MiB** görünmelidir.
2. Bundan büyük bir dosya seçin.
3. Boyut sınırı uyarısı beklenir. Network'te bu dosya için yeni
   `POST /api/media/uploads` veya `PUT .../ranges` olmamalıdır. Durum/limits
   sorgularının sürmesi normaldir.

Boş deneme dosyası üretmek için:

```powershell
$Empty = Join-Path $env:TEMP ('dojo-bos-' + [Guid]::NewGuid().ToString('N') + '.jpg')
[System.IO.File]::WriteAllBytes($Empty, [byte[]]@())
Write-Host $Empty
```

Seçince **Dosya boş** açıklaması beklenir; medya aktarımı başlamaz.

Sonraki testler için sınırı **not ettiğiniz eski değere** geri alın. Örneğin
başlangıç değeri gerçekten 2 GiB ise:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-settings set-upload-limits --max-file-bytes 2147483648
```

Tarayıcıyı tekrar yenileyin. Aynı satırda farklı dosya seçerek tekrar denemek
mümkündür; her yeni denemede aynı hatalı dosyayı göndermek gerekmez.

## 9. Geçersiz medya ve açık yeni deneme

Sadece uzantıyı kontrol etmediğini görmek için küçük bir sahte JPEG oluşturun:

```powershell
$Invalid = Join-Path $env:TEMP ('dojo-gecersiz-' + [Guid]::NewGuid().ToString('N') + '.jpg')
[System.IO.File]::WriteAllText($Invalid, 'Bu bir JPEG dosyasi degildir.')
Write-Host $Invalid
```

1. Worker'ın çalıştığından emin olun: `docker compose @ComposeArgs ps`.
2. Dosyayı normal **Fotoğraf ve video seç** alanından seçin.
3. Aktarım %100 olabilir; önce kuyruğa alınır, sonra **Medya kabul edilmedi** beklenir.
4. Satırda sunucunun doğrulama nedeni görünmelidir. Nedenin tam metni format/işlemciye
   bağlıdır; İngilizce teknik açıklama gelmesi mümkündür.
5. **Yeni dosya seç: ...** alanından gerçekten geçerli, tercihen farklı adlı bir
   görsel seçerek yeni deneme yapın.

**Yeni yükleme başlat**, aynı oturumda dosya hâlâ tutuluyorsa aynı dosyayla yeni
sunucu kaydı açar; aynı bozuk dosya yine reddedilebilir. Yenilemeden sonra
dosya yeniden seçilmeden yeni bir medya aktarımı başlamaz. Başarısız medya
**Pakete eklendi** olarak gösterilmemelidir.

## 10. Paket sınırı ve dosya adı çakışması

### Paket sınırı

Yeni/boş deneme paketinde, not ettiğiniz paket sınırını geçici olarak küçültün:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-settings set-upload-limits --max-package-bytes 1048576
```

Dosya sınırı 1 MiB'den büyükken 1 MiB'den büyük, yeni adlı bir dosya seçin.
Beklenen: sunucu paket kapasitesi uyarısıyla başlangıcı reddeder; bu dosyaya
ait `PUT .../ranges` gönderilmez. Paket zaten doluysa daha küçük dosya da
kapasiteyi aşabilir. Sonra önceki paket sınırını geri alın; varsayılan gerçekten
20 GiB ise:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-settings set-upload-limits --max-package-bytes 21474836480
```

### Dosya adı çakışması

1. Bir dosyanın **Pakete eklendi** olmasını bekleyin.
2. Aynı aktif pakete aynı adı taşıyan dosyayı yeniden seçin.
3. **Dosya adı çakışıyor** beklenir; aralık aktarımı başlamaz.

Bu ekranda üzerine yazma/otomatik ad değiştirme yoktur. #28 ayrı kapsamdır.
Başka deneme yapmak için dosyanın bir kopyasına farklı ad verip ana seçiciden
seçebilirsiniz; mevcut medyanın silinmesi gerekmez.

## 11. Oturum kaybı ve artık mevcut olmayan yükleme — isteğe bağlı

Bu yönetim işlemleri yeni yükleme panelinde yoktur. Tarayıcıdan ayrı bir
PowerShell oturumu eşleştirin; tarayıcının gizli çerezini kopyalamayın:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
$Base = 'http://localhost:8000'
$Code = Read-Host 'Yeni uretilen PowerShell eslestirme kodu'
$Body = @{ code = $Code; kind = 'browser'; name = 'Yukleme Rehberi PowerShell' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/validate" -SessionVariable DojoSession -ContentType 'application/json' -Body $Body | Out-Null
$Code = $null
$Body = $null
Invoke-RestMethod -Uri "$Base/api/media/upload-limits" -WebSession $DojoSession
```

### Yüklemenin sunucuda durdurulması

1. Tarayıcıda yeni bir deneme dosyası yükleyip duraklatın.
2. Network'teki `/api/media/uploads/<kimlik>` isteğinden o satırın yükleme kimliğini
   alın. Paket veya istemci numarasıyla karıştırmayın.
3. **Yalnızca bu deneme yüklemesini** durdurun. Sunucu tarafında geri alınmaz:

```powershell
$UploadId = Read-Host 'Durdurulacak deneme yuklemesinin kimligi'
$EncodedId = [Uri]::EscapeDataString($UploadId)
$Status = Invoke-RestMethod -Uri "$Base/api/media/uploads/$EncodedId" -WebSession $DojoSession
$Status | Select-Object upload_id, status, declared_size_bytes, received_bytes
if ($Status.status -ne 'receiving') { throw 'Yalnizca duraklatilmis receiving deneme yuklemesini hedefleyin.' }
if ((Read-Host 'Bu deneme yuklemesini durdurmak icin EVET yazin') -eq 'EVET') {
    Invoke-RestMethod -Method Post -Uri "$Base/api/media/uploads/$EncodedId/abort" -WebSession $DojoSession | Out-Null
}
```

Tarayıcıda **Devam et** deyin. **Yükleme artık mevcut değil** ve yeni deneme
açıklaması beklenir; eski yükleme sessizce yeniden oluşturulmaz. **Yeni yükleme
başlat** açıkça yeni kayıt açar. Otomatik eski-kayıt temizliğini denemek için
veritabanının tarihlerini elle değiştirmeniz gerekmez.

### Tarayıcı erişiminin iptali

Bu işlem hedef tarayıcıyı çıkarır; geri alınmaz. Yeniden giriş yeni kod gerektirir.
Yalnızca `Web Yükleme Denemesi` adlı deneme tarayıcısını seçin:

```powershell
$Clients = Invoke-RestMethod -Uri "$Base/api/pairing/clients" -WebSession $DojoSession
$Clients | Select-Object id, name, kind, revoked_at | Format-Table
$BrowserId = [int](Read-Host 'Web Yukleme Denemesi tarayicisinin id degeri')
$Target = $Clients | Where-Object { $_.id -eq $BrowserId -and $_.name -eq 'Web Yükleme Denemesi' -and -not $_.revoked_at } | Select-Object -First 1
if ($null -eq $Target) { throw 'Hedef deneme tarayicisi bulunamadi; islem yapilmadi.' }
if ((Read-Host 'Deneme tarayicisinin erisimini iptal etmek icin EVET yazin') -eq 'EVET') {
    Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/clients/$BrowserId/revoke" -WebSession $DojoSession | Out-Null
}
```

Tarayıcıda aktarım varken uygulayın. Sonraki korumalı istek `401` aldığında
satırlar/korumalı bilgiler temizlenir ve **Tarayıcıyı eşleştir** ekranı görünür.
Aktarım kendiliğinden sürmemelidir. Yeniden eşleştirme farklı istemci kimliği
oluşturduğundan eski istemciye ait kurtarma satırları yeni kimliğe taşınmaz.

## 12. Dar ekran, klavye ve kayıt engeli — tarayıcı

- DevTools cihaz görünümünde **320 px** ve normal masaüstü görünümünü deneyin.
  Uzun dosya adları/yeniden seçme etiketleri satır kırmalı; yatay kaydırma olmamalıdır.
- `Tab` ile dosya alanına ve satır düğmelerine ulaşın. Odak çizgisi görünmeli;
  `Enter` ile düğmeler çalışmalıdır.
- **Application → Local Storage → http://localhost:3000** bölümünde
  `aisomedo.uploads.v1:<istemci-kimliği>` kaydını inceleyebilirsiniz. Dosya içeriği
  veya token değil, kimlik/özet/durum bilgisi bulunmalıdır. Değerleri elle değiştirmeyin.
- Tarayıcı/site politikası depolamayı engelliyorsa kurtarmanın kullanılamadığı
  uyarısı beklenir; aynı oturumdaki aktarım engellenmemelidir. Gizli pencere her
  tarayıcıda depolamayı engellemez; sırf gizli pencere açmak bu testi kanıtlamaz.
- Sekme gizliyken kuyruk/işleme durumunun düzenli sorgulanması durur, geri
  dönünce yenilenir. Bu davranış arka plan medya aktarımını garanti etmez;
  tarayıcı sekmeyi askıya alırsa yeniden seçme/tekrar deneme gerekebilir.

## 13. Sorun çözme, otomatik kontrol ve kapatma

| Gözlem | Kontrol |
| --- | --- |
| Yeni alan görünmüyor | Doğru worktree/dal ve `#/package` adresi; eski Vite/backend yerine buradaki derleme. |
| Eşleştirme başarılı ama oturum tutulmuyor | Yerel `COOKIE_SECURE=false`; sürekli aynı `localhost:3000` adresi. |
| Seçici kapalı / sınırlar alınamıyor | Backend sağlığı, Vite `/api` proxy'si, eşleştirme ve **Tekrar dene**. |
| %100 ama pakete eklenmedi | Worker kapalı, işlem sürüyor veya doğrulama başarısız; %100 yalnızca aktarım. |
| Video hemen hata veriyor | Throttling kaynaklı 10 saniyelik istek zaman aşımı; normal bağlantıyla tekrar deneyin. |
| Yenilemeden sonra satır yok | Aynı tarayıcı/origin/istemci kullanılıyor mu; site verisi silindi mi; kayıt uyarısı var mı? |
| Yanlış dosya uyarısı | Aynı ad/boyut yetmez; orijinal içerik gerekir. |
| Çakışma | Yeni dosya adı kullanın; üzerine yazma bu ekranın kapsamı değildir. |

İkinci PowerShell penceresinde servis günlüklerini incelemek için:

```powershell
docker compose @ComposeArgs ps
docker compose @ComposeArgs logs --tail 60 backend worker
```

Günlükleri paylaşırken hassas değerleri çıkarın. İsterseniz web kontrollerini
Python/SQL kodu kullanmadan çalıştırın:

```powershell
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

Vite terminalinde `Ctrl+C` ile kapatın. **Yalnızca bu rehberde başlattığınız
deneme projesini**, verileri silmeden durdurmak için:

```powershell
docker compose @ComposeArgs stop worker backend db
```

`down -v`, veritabanı silme, medya klasörü temizleme veya Git değişikliklerini
geri alma komutu kullanılmaz. Değiştirdiğiniz limitleri önceki değerlerine
getirdiğinizden emin olun.

## Doğrulama kapsamı

Geliştirme sırasında gerçek API istemci sarmalayıcılarıyla otomatik akış testleri;
Chromium'da masaüstü/320 px mobil görünüm, duraklatma, yeniden seçme, yanlış dosya,
boyut reddi ve doğrulama durumları denendi. Tarayıcı kabul testlerinde API
yanıtları kontrollü örneklerdi; canlı çok-GB aktarım ve gerçek worker ile uçtan
uca kabul testi yapılmış sayılmaz. Yukarıdaki yerel ortam adımları bu ayrımı
elle denemeniz içindir.

Bu rehberdeki 21 PowerShell bloğunun sözdizimi kontrol edildi; yeni bir canlı
Docker/worker ortamında bütün rehber adımları bu oturumda yeniden çalıştırılmadı.

Ayrıntılı komut sonuçları ve inceleme notları:
[Issue #27 doğrulama kaydı](../verification/issue-27-web-upload.md).
