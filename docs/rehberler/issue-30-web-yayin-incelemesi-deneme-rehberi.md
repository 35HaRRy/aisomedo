# Web Yayın İncelemesi — Değişiklik özeti ve deneme rehberi (#30)

Bu rehber `902ec1f` commit'indeki değişiklikleri anlatır. Öncelik **tarayıcıda
deneme**; arayüzde bulunmayan hazırlık işlemleri için **PowerShell** kullanılır.
Kod bloklarında Python veya SQL kodu yoktur. Test komutları mevcut proje
testlerini çalıştırır; uygulama kodu yazmanız gerekmez.

> **Gerçek yayın uyarısı:** **Onayla ve yayınla → Yayınlamayı onayla**, bağlı
> Instagram hesabına gerçekten yayın yapmayı başlatır. Sayfayı açmak, videoyu
> oynatmak veya yalnız ilk düğmeye basmak yayın yapmaz. Canlı ortamda deneme
> yapmayın. Son onayı güvenle denemek için bölüm 10'daki sahte API'li tarayıcı
> testini kullanın. Atlamak ve ertelemek de kalıcı işlemlerdir; yalnız ayrı
> deneme ortamında uygulayın.

## 1. Neler değişti?

| Değişiklik | Göreceğiniz sonuç |
| --- | --- |
| Odaklı inceleme ekranı | Kontrol Paneli veya Etkinlik bağlantısı artık ilgili incelemeyi açar; normal paket düzenleyicisini değil. |
| Sürüme bağlı Reel ve açıklama | İncelemenin kaydedilmiş açıklaması ve aynı render sürümü gösterilir. Paket sonradan değiştiğinde eski ekranda yeni içerik sessizce gösterilmez. |
| İki aşamalı yayın onayı | Önizleme yüklenmeden yayın düğmesi açılmaz; ilk tıklamadan sonra ayrıca yayınlama onayı gerekir. |
| Atla ve ertele | Atlamadan önce sonraki düzenli zaman gösterilir. Ertelemede gelecekteki İstanbul tarihi/saati seçilir. |
| Eski/çözümlenmiş işlem koruması | Başka cihazın işlemi görünür; durum yenilenir, yayın isteği otomatik tekrar gönderilmez. |
| Boş paket devamı | Aynı Yayın Zamanı üzerinden medya yüklenir, render hazırlanır ve hazır inceleme aynı ekranda açılır. |
| Backend güvenlik düzeltmesi | Render geçersizleştiyse onay, incelemeyi çözümlenmiş işaretlemeden reddedilir. |

Yeni `GET /api/reviews/{id}` yanıtı inceleme kimliğini, sürümünü, açıklamasını,
önizleme adresini ve sonraki düzenli zamanı taşır. Önizleme adresi paket adı ve
render sürümüne bağlıdır; eşleştirme gerektirir.

**Terimler:** Aktif Paket medya ve montajı taşır. Yayın Zamanı, karar bekleyen tek
bir zamandır. Yayın İncelemesi o zaman için üretilmiş belirli Reel sürümüdür.
Atlama/erteleme paketi tamamlanmış yapmaz ve düzenli Dojo Yayın Planı'nı kaydırmaz.

## 2. Hangi deneme yolunu seçmeliyim?

- **Hazır, ayrı bir backend/worker deneme ortamınız varsa:** bölümler 3–9 ile
  gerçek tarayıcı akışını deneyin. Yayınlama onayında son düğmeye basmayın.
- **Instagram bağlamak, Docker kurmak veya gerçek veri değiştirmek istemiyorsanız:**
  doğrudan bölüm 10'a geçin. Tarayıcı testleri sentetik video ve sahte API kullanır;
  gerçek Instagram, backend ve veritabanı gerekmez. Bu yol gerçek render/Meta
  entegrasyonunu değil, ekranın davranışını doğrular.

Gerçek worker, zorunlu kurulum tamamlanmadan inceleme üretmez. Medya yüklenmiş
ve render hazır olsa bile eksik kurulumda inceleme beklemeyin. Kurulum için
[web onboarding rehberini](issue-26-web-onboarding-deneme-rehberi.md) kullanın;
eski rehberdeki worktree/branch yolunu değil **bu değişikliği içeren checkout'u**
kullanın. Gerçek kurulumun Instagram adımını atlamanın desteklenen bir yolu yoktur.

## 3. Gerçek deneme ortamını açın

### 3.1. Backend, worker ve web

PowerShell'i repo kökünde açın. Örnek yolu kendi deneme checkout'unuza göre değiştirin:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
git log -1 --oneline
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 8000, 5434, 4310 } |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Bu rehber web için **4310**, mevcut Vite proxy'si backend için **8000** kullanır.
Başka uygulamanın portunu kullanmayın veya o uygulamayı zorla kapatmayın.

Mevcut **deneme** Compose ortamınızı başlatmak veya güncellemek gerekiyorsa,
önce uygulama süreçlerini durdurun, veritabanını yedekleyin ve migration'ları
uygulayın. Image build etmek mevcut veritabanını güncellemez; `/health` yanıtının
`ok` olması da şemanın güncel olduğunu doğrulamaz.

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-f', 'ops/docker-compose.yml')
docker compose @ComposeArgs stop backend worker
if ($LASTEXITCODE -ne 0) { throw 'Uygulama süreçleri durdurulamadı.' }
docker compose @ComposeArgs build backend worker
if ($LASTEXITCODE -ne 0) { throw 'Image build başarısız.' }
docker compose @ComposeArgs up -d db
if ($LASTEXITCODE -ne 0) { throw 'Veritabanı başlatılamadı.' }

$BackupName = 'dojo-before-migration-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
$BackupDir = Join-Path $env:LOCALAPPDATA 'Temp\opencode\db-backups'
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$BackupPath = Join-Path $BackupDir $BackupName
docker compose @ComposeArgs exec -T db pg_dump -U dojo -d dojo --format=custom --file="/tmp/$BackupName"
if ($LASTEXITCODE -ne 0) { throw 'Yedek alınamadı; migration çalıştırmayın.' }
docker compose @ComposeArgs cp "db:/tmp/$BackupName" $BackupPath
if ($LASTEXITCODE -ne 0) { throw 'Yedek kopyalanamadı; migration çalıştırmayın.' }
docker compose @ComposeArgs exec -T db pg_restore --list "/tmp/$BackupName" | Out-Null
if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath $BackupPath).Length -eq 0) {
    throw 'Yedek arşivi doğrulanamadı; migration çalıştırmayın.'
}
Write-Output "Veritabanı yedeği: $BackupPath"

docker compose @ComposeArgs run --rm --no-deps backend .venv/bin/python -m dojo.schema
if ($LASTEXITCODE -ne 0) { throw 'Migration başarısız; backend/worker başlatmayın.' }
docker compose @ComposeArgs up -d backend worker
if ($LASTEXITCODE -ne 0) { throw 'Uygulama süreçleri başlatılamadı.' }
docker compose @ComposeArgs ps
Invoke-RestMethod -Uri 'http://localhost:8000/health'
```

`python -m dojo.schema`, projenin mevcut migration komutudur; Python kodu
yazmanız gerekmez. **Database schema is at head.** çıktısını bekleyin. Yedek
oturum ve bağlantı bilgileri içerebilir; paylaşmayın ve güvenli saklayın.

Migration sırasında “table/constraint already exists” çıkarsa durun. Eski
başlangıç yolu `create_all`, yeni tabloları oluştururken mevcut tablolara eksik
sütunları eklemez; sonuç karışık bir şema olabilir. Tabloları silmeyin veya
`stamp head` ile migration'ları uygulanmış göstermeyin. Bu durum yedek ve
mevcut tablo içerikleri incelenerek ayrıca düzeltilmelidir. Bu rehberde örnek
alınan yerel ortamda boş izleme tabloları ayrı kurtarma şemasında korunmuş,
ardından gerçek migration'lar uygulanmıştır.

Mevcut ortamınız özel Compose proje adı kullanıyorsa `$ComposeArgs` içine aynı
`-p` ve proje adını ekleyin. Sağlık yanıtında `status: ok` beklenir. Yeni kurulum
için önce onboarding rehberindeki `.env`/veri dizini hazırlığını tamamlayın.
**Compose proje adı değiştirmek `ops/db-data` ve `ops/media-data` bind dizinlerini
ayırmaz. Üretim verisi bulunan dizinlerde bu komutları çalıştırmayın.**

Yerel HTTP testinde `COOKIE_SECURE=false`; üretimde HTTPS ve güvenli cookie
korunmalıdır. Backend/worker aynı test veritabanını ve medya dizinini kullanmalıdır.

```powershell
npm --prefix web ci
npm --prefix web run dev -- --host localhost --port 4310 --strictPort
```

Web terminali açık kalır. Tarayıcıda **http://localhost:4310/#/dashboard** açın.
8000 web arayüzü değildir. `localhost` ile `127.0.0.1` arasında geçiş yapmayın;
cookie ve tarayıcı depolaması farklı kapsamlardır. Sonraki komutlar için aynı
repo kökünde ikinci PowerShell terminali açın ve `$ComposeArgs`'ı orada da tanımlayın.

### 3.2. Tarayıcı ve PowerShell oturumlarını eşleştirin

Tarayıcı henüz eşleştirilmediyse yeni kod üretin:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
```

Tarayıcıda **Eşleştirme kodu** ve **Tarayıcı adı** alanlarını doldurup **Eşleştir**
düğmesine basın. Ayarlar/kurulum sihirbazında zorunlu adımların tamamlandığını
kontrol edin. Düzenli plan, geçerli tarih/saatle tanımlanıp **kapalı** tutulabilir;
aşağıdaki manuel Yayın Zamanı için düzenli planı etkinleştirmek gerekmez.

Hazırlık API istekleri için PowerShell'e **başka bir yeni kod** üretin:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
$BaseUri = 'http://localhost:4310'
$Code = Read-Host 'PowerShell için yeni eşleştirme kodu'
$Body = @{ code = $Code; kind = 'browser'; name = 'Inceleme rehberi PowerShell' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$BaseUri/api/pairing/validate" `
    -ContentType 'application/json; charset=utf-8' -Body $Body -SessionVariable DojoSession
$Code = $null
$Body = $null
$Setup = Invoke-RestMethod -Uri "$BaseUri/api/setup" -WebSession $DojoSession
if (-not $Setup.ready) { throw 'Zorunlu kurulum eksik. Sihirbazı tamamlayın veya bölüm 10 yolunu kullanın.' }
```

Kod tek kullanımlıktır; tarayıcıda kullanılan kod PowerShell'de tekrar kullanılamaz.
`$DojoSession` cookie'yi bellekte tutar. Cookie, kod ve tokenları paylaşmayın.
PowerShell cookie'si tarayıcıya otomatik aktarılmaz; iki oturum ayrı eşleştirilmiştir.

## 4. Boş paketten yükleme → render → inceleme

**Önkoşul:** ayrı deneme ortamında aktif paket yok veya paket henüz boş.
Mevcut medyayı silerek bu durumu üretmeyin; dolu ortamda bu senaryoyu atlayın.

### 4.1. Yayın Zamanı oluşturun — PowerShell

Bu hazırlık işleminin #30 ekranında düğmesi yoktur:

```powershell
$Due = Invoke-RestMethod -Method Post -Uri "$BaseUri/api/settings/manual-publish" -WebSession $DojoSession
$Due | Select-Object id, kind, due_at, status
```

Bu komut **hemen Instagram'a yayın yapmaz**; şimdiki zamana ait karar bekleyen
bir Yayın Zamanı oluşturur. `kind: manual`, `status: pending` beklenir.
`409` alırsanız zaten bekleyen manuel zaman vardır; tekrar tekrar oluşturmayın.
Kontrol Paneli'ndeki mevcut zamanı kullanın.

### 4.2. Medyayı yükleyin — tarayıcı

1. **Kontrol Paneli**'ne dönün; bekleyen işlemler içindeki boş paket satırında
   **Pakete git** bağlantısına basın. Üstteki genel paket bağlantısıyla karıştırmayın.
2. Adreste `#/package?occurrence=...` bulunmalı. Paket varsa `folder=...` da görünür.
3. **Yayın İncelemesi**, yükleme alanı ve **Render ve incelemeye devam et** görünmeli.
   Medya henüz yokken devam düğmesi kapalı olmalıdır.
4. Gerçek kişi içermeyen kısa bir video seçin. İsterseniz depodaki sentetik
   30 saniyelik videoyu yeni adla hazırlayın:

```powershell
$DemoDir = Join-Path $env:TEMP ('dojo-review-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $DemoDir | Out-Null
Copy-Item -LiteralPath web/e2e/fixtures/timeline.mp4 -Destination (Join-Path $DemoDir 'inceleme-deneme.mp4')
$DemoDir
```

5. **Fotoğraf ve video seç** ile dosyayı yükleyin. **Pakete eklendi** sonucunu
   bekleyin; %100 veya yalnız işlem sırasına alınması yeterli değildir.
6. Devam düğmesi açılınca basın. Worker otomatik render'a başlamışsa düğme
   kapalı kalabilir ve hazırlık mesajı görünür; ek iş oluşturmaya çalışmayın.
7. Render tamamlanınca yükleme ekranı yerini Reel ve açıklama içeren incelemeye
   bırakmalı. Gerekirse **İncelemeyi yenile**'ye basın.

**Beklenen:** ilk Yayın Zamanı devam eder; yeni manuel zaman yaratmak gerekmez.
Paket, yükleme sırasında ilk kez oluşmuş olabilir; sonrasında aynı paket kullanılır.
Boş pakette doğrudan atlama/erteleme düğmeleri bu #30 devam ekranına eklenmedi.

## 5. Exact Reel/açıklama ve kazara yayın koruması — tarayıcı

1. Kontrol Paneli'nde **İnceleme özeti**'ni açın. Adres `#/package?review=...`
   şeklindedir. Bu adresi sonraki denemeler için saklayın.
2. Paket adı, final Reel ve **Yayın açıklaması** görünmeli. Normal medya düzenleyicisi
   veya kaynak videonun bölüm editörü burada açılmamalıdır.
3. Videoyu oynatın; kaydedilmiş montaj, logo ve varsa kartları kontrol edin.
   Sentetik video tek renk olduğundan görünümde sahne değişimi beklemeyin.
4. Önizleme henüz yüklenmediyse **Onayla ve yayınla** kapalı olmalıdır. Yüklendikten
   sonra açılması **videonun sonuna kadar izlendiğini doğruladığı anlamına gelmez**;
   içerik kontrolü sizin sorumluluğunuzdadır.
5. **Onayla ve yayınla**'ya basın. Instagram'da hemen yayınlanacağına dair uyarı ve
   ikinci **Yayınlamayı onayla** düğmesi çıkmalı.
6. **Vazgeç**'e basın. İnceleme bekleyen durumda kalmalı; yayın başlamamalıdır.
7. **Etkinlik**'te incelemeye ait **İnceleme özeti** bağlantısı varsa açın. Yeni
   inceleme oluşturma kaydı Yayın Zamanı üzerinden devam bağlantısı taşıyabilir;
   çözümleme kayıtları ilgili inceleme kimliğini açar.

**Son yayınlama onayını burada vermeyin.** Gerçek yayın denemesi yapacaksanız
yalnız açıkça yayın için ayrılmış hesap/medya kullanın. “Yayınlama onayı alındı.”
mesajı, her durumda Instagram'ın yayını tamamladığının kanıtı değildir;
[yayın yürütme rehberindeki](yayin-yurutme-instagram-graph-api-rehberi.md) durum
kontrollerini ayrıca uygulayın.

## 6. Başka zamana planlayın — tarayıcı

Bu deneme mevcut incelemeyi kapatır; sonraki atlama denemesi için yeni incelemenin
oluşmasını bekleyeceğiz.

1. **Başka zamana planla**'ya basın.
2. **Yeni Yayın Zamanı (İstanbul)** alanına geçmiş bir tarih girin.
   **Yeni zamanı onayla** kapalı olmalıdır.
3. İstanbul'daki şimdiki zamandan birkaç dakika sonrasını seçin. Bilgisayarın
   saat dilimi farklı olsa bile alanın anlamı **İstanbul saatidir (UTC+03:00)**.
4. Önce **Vazgeç**'i deneyin; hiçbir zaman değişmemeli.
5. Tekrar gelecekteki zamanı girip **Yeni zamanı onayla**'ya basın.
6. **Yeni Yayın Zamanı kaydedildi. Paket korunuyor.** mesajını görün.
7. Kontrol Paneli'nde yeni tek seferlik zaman görünmeli; düzenli plan değişmemelidir.
8. Yeni zaman gelince worker'ın ve sayfanın yenilenmesini bekleyin. Paket değişmediyse
   yeni inceleme aynı Reel sürümünü kullanabilir. Yeni **İnceleme özeti**'ni açın.

İşlemin sonucuna ulaşamadıysanız tekrar onaylamadan önce **İncelemeyi yenile**
ve Kontrol Paneli ile sunucudaki durumu kontrol edin.

## 7. Atlayın ve eski bağlantıyı deneyin — tarayıcı

1. Bekleyen yeni incelemenin adresini kaydedip ikinci sekmede de açın.
2. İlk sekmede **Bu zamanı atla**'ya basın. Paket/düzenli planın korunacağı uyarısı
   ve **Sonraki düzenli Yayın Zamanı** görünmeli. Düzenli zaman yoksa bunun
   belirlenmediği yazabilir; kapalı planla denemede bu normaldir.
3. **Vazgeç**'i deneyin; ardından tekrar açıp **Atlamayı onayla**'ya basın.
4. **Bu Yayın Zamanı atlandı. Paket korunuyor.** mesajını görün.
5. **Güncel Paket**'te medyanın hâlâ bulunduğunu kontrol edin; bu işlem yayınlama
   veya paket temizleme değildir.
6. İkinci sekmeye dönün veya kaydettiğiniz eski inceleme adresini yeniden açın.
   **Bu inceleme başka bir cihazda tamamlanmış veya artık mevcut değil.**
   mesajı görünmeli; tekrar yayın onayı verilememelidir.

Görünür/çevrimiçi ekran yaklaşık beş saniyede bir ve tekrar odaklanınca yenilenir.
Bu nedenle ikinci sekme, siz eski düğmeye basamadan kapanmış incelemeyi gösterebilir;
bu doğru davranıştır. Aynı anda gönderilmiş eski sürüm isteği de backend'de reddedilir.

## 8. İçerik değişikliği ve yeni sürüm — tarayıcı + PowerShell

**Önkoşul:** çözülmemiş hazır inceleme. Bölüm 7'de atladıysanız önce bölüm 4.1 ile
yeni manuel zaman oluşturup hazır incelemeyi bekleyin. Paket doluysa tekrar yükleme
gerekmez. Bu senaryo için iki sekmede aynı hazır incelemeyi açın.

Taslak açıklama düzenleme alanı bu odaklı ekranda yoktur; PowerShell'de değiştirin:

```powershell
$Body = @{ caption = "Yeni inceleme denemesi`n#dojo #deneme" } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$BaseUri/api/packages/active/caption" `
    -WebSession $DojoSession -ContentType 'application/json; charset=utf-8' -Body $Body
```

1. Eski inceleme sekmesine dönüp **İncelemeyi yenile**'ye basın.
2. Eski açıklama kaydı değişmeden kalır; eski Reel artık kullanılabilir değilse
   içerik değişikliği/yeni render uyarısı görünür ve karar düğmeleri kapanır.
   Eski incelemenin yeni açıklamayla sessizce yayınlanmasına izin verilmemelidir.
3. **Paketi düzenle** ile Güncel Paket'e geçin. Gerekirse **Paketi yenile** deyin.
4. **Kaydedilmiş montajı render et**'e basın; otomatik render zaten sürüyorsa bitmesini
   bekleyin. Sonra Kontrol Paneli'nden **hazır** inceleme bağlantısını açın.
5. Yeni açıklama ve yeni sürüme bağlı Reel görünmeli. Aynı Yayın Zamanı için eski
   hazırlık satırı ile yeni hazır inceleme birlikte bulunabilir; eski bağlantıyı
   kullanmayın. Yayın Zamanı devam ekranı hazır incelemeyi tercih eder.

Worker çok hızlıysa render'ın geçersiz olduğu kısa aralığı yakalayamayabilirsiniz;
eski bağlantının yeni içeriğe dönüşmemesi ve yeni incelemenin ayrı açılması esas kontroldür.

## 9. Bağlantı kesintisi ve mobil görünüm — tarayıcı

1. Hazır incelemeyi açın; geliştirici araçlarının **Network** sekmesinde
   **Offline** seçin. Bir yenileme turu bekleyin veya **İncelemeyi yenile**'ye basın.
2. Bilgilerin yüklenemediği/yenileme gerektiği uyarısını ve kapalı işlem düğmelerini
   kontrol edin. Görünen eski verilerle otomatik onay yapılmamalıdır.
3. **No throttling/Online** durumuna dönün. **İncelemeyi yenile**'ye basın;
   sunucu yanıtı ve önizleme tekrar yüklenene kadar yayın düğmesi açılmamalıdır.
4. Önizleme yüklenemezse **Video önizlemesi yüklenemedi.** uyarısı ve kapalı yayın
   düğmesi beklenir. Önizleme hatasını gerçek dosyaları silerek üretmeyin.
5. Device Toolbar ile yaklaşık **390 px** genişlik seçin. Reel ve açıklama alt alta
   yerleşmeli; yatay taşma olmadan onay, tarih alanı ve geri bağlantıları kullanılmalı.
6. Tab tuşuyla düğmeleri gezin; Enter ile ilk onay adımını açın ve **Vazgeç** ile
   kapatın. Son yayınlama onayına basmayın.

## 10. Instagram olmadan güvenli tarayıcı testi — PowerShell

Bu bölüm ayrı bir test tarayıcısı açar. Testin `/api/` istekleri sahte yanıtlarla
karşılanır; **Yayınlamayı onayla** adımı bile gerçek yayın yapmaz. Normal uygulama
sekmesinde aynı düğmeye basmanın güvenli olduğu anlamına gelmez.

Repo kökünden:

```powershell
npm --prefix web ci
Push-Location web
npx playwright install chromium
$env:PLAYWRIGHT_PORT = '4311'
npm run test:browser -- e2e/focused-review.spec.ts --headed --workers=1
Pop-Location
```

4311 boş olmalı; başka uygulama çalışıyorsa boş bir port seçin. Test sunucusu
otomatik başlar. Docker, Instagram tokenı ve eşleştirme kodu gerekmez.

**Beklenen:** desktop ve mobile projelerinde toplam **4 test geçer**. Tarayıcıda
testler otomatik olarak şunları yapar:

- Kontrol Paneli'nden belirli incelemeyi açar; 30 saniyelik videoyu ve açıklamayı doğrular.
- İlk onaydan sonra **Vazgeç**'i, ardından iki aşamalı yayın onayını dener.
- Geçmiş tarihi engeller, İstanbul saatli erteleme isteğini kontrol eder.
- Başka cihaz işlemi için `409` yanıtını simüle eder; eski karar düğmelerinin kalktığını doğrular.

Daha yavaş, adım adım görmek için otomatik test komutu yerine:

```powershell
Push-Location web
$env:PLAYWRIGHT_PORT = '4311'
npm run test:browser -- e2e/focused-review.spec.ts --project=desktop --debug
Pop-Location
```

Playwright Inspector'da **Step over** ile ilerleyin. Testin inceleme ekranına
ulaştığı satırlarda durup tarayıcıdaki metinleri/önizlemeyi inceleyin. **Resume**
teste devam eder. Manuel tıklamalar testin beklediği durumu değiştirebilir;
test başarısını kontrol ederken adımları Inspector'dan ilerletin.

## 11. Tarayıcıda zor üretilebilen durumları mevcut testlerle doğrulayın

Gerçek backend'e hatalı onay gönderip veri değiştirmek yerine şu testleri kullanın:

```powershell
npm --prefix web test -- src/reviews/ReviewFlow.test.tsx
uv run --project backend pytest backend/tests/test_focused_review_api.py -q
```

Bu commit'te beklenen sonuçlar **11 web testi** ve **7 backend testi**dir.
Sonraki değişikliklerle sayılar artabilir. Backend testleri için Python 3.12 ve
`uv` kurulumu gerekir; komutta Python kodu veya SQL yazılmaz. Bu odaklı testler
bellek içi depo/sahte renderer kullanır; üretim veritabanınızı kullanmaz.

Kontroller: render değişince onayın incelemeyi çözmeden reddedilmesi; eski sürüm
isteğinin reddi; yetkisiz önizleme; aynı Yayın Zamanıyla yükleme devamı; eski
hazırlık kaydının yeni hazır incelemeyi gölgelememesi; yenileme başarısız olsa
bile bilinen “başka cihazda tamamlandı” sonucunun gösterilmesi.

## 12. Sorun giderme ve denemeyi bitirme

| Belirti | Kontrol / sonraki adım |
| --- | --- |
| Yeni inceleme ekranı yok | Backend ve web aynı güncel checkout'tan mı? Yeni backend endpoint'i için Docker image yeniden build edilmiş mi? |
| `/api/setup` veya dashboard `500`, `/health` ise `200` | Şema güncel olmayabilir. Bölüm 3.1'deki yedek/migration sırasını uygulayın; yalnız image build etmek yeterli değildir. |
| Yükleme bitti, inceleme oluşmuyor | Zorunlu kurulum hazır mı? Worker çalışıyor mu? Logo mevcut, montaj limit içinde ve render tamamlanmış mı? |
| Onay düğmesi kapalı | Reel yüklenmesini bekleyin; okuma/önizleme hatası varsa incelemeyi yenileyin. |
| `401` / eşleştirme ekranı | Doğru origin, yeni tek kullanımlık kod ve geçerli oturum kullanın. Yerel HTTP cookie ayarını kontrol edin. |
| Manuel zaman oluştururken `409` | Bekleyen manuel zaman zaten var; Kontrol Paneli'ndeki mevcut işlemi açın. |
| İçerik değişti / paket değişti | Eski URL'yi kullanmak yerine Kontrol Paneli'nden güncel hazır işlemi açın. |
| İşlemin sonucu doğrulanamadı | Önce yenileyin; özellikle yayınlama isteğini körlemesine tekrar göndermeyin. |
| Tarayıcı testi başka siteyi açıyor | Seçtiğiniz portta başka sunucu var; Playwright onu yeniden kullanmış olabilir. Boş port seçin. |

Worker durumunu incelemek için, yalnız deneme ortamınızda:

```powershell
docker compose @ComposeArgs logs --tail 80 worker
```

Vite'ı çalıştıran terminalde **Ctrl+C** ile web sunucusunu kapatabilirsiniz.
Bu rehber veritabanı/medya silme, manifest düzenleme, SQL ile durum değiştirme
veya mevcut ortamı zorla sıfırlama adımı içermez. Deneme kayıtları ayrı test
ortamınızda kalır.
