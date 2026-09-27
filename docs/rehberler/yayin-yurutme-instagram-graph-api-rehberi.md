# Yayın Yürütme (Instagram Graph API) — Değişiklik Özeti ve Deneme Rehberi

Bu doküman issue #18 (Instagram Graph API üzerinden yayın yürütme) kapsamında
yapılan değişiklikleri özetler ve tamamen PowerShell ile adım adım denemeni sağlar.

## Ne değişti

Onay artık doğrudan yayını tetikliyor. `approve()` bir review'u çözdükten sonra
paketi atomik olarak `-publishing` durumuna alıyor: klasör yeniden adlandırılıyor,
onaylı revizyon + review kimliği manifestin `meta.publication` kaydına yazılıyor,
ardından dış işlem başlıyor.

Yalnızca onaylı render (`render/reel.mp4`) kısa ömürlü imzalı HTTPS URL ile
Meta'ya açılıyor; ham medya yolu asla üretilemiyor. URL, Meta videoyu içine
alıp container `FINISHED` olunca iptal ediliyor; her fetch denetim kaydına
`publication.artifact_fetched` olarak düşüyor.

Meta akışı üç adımda yürüyor ve her adım kalıcılaşıyor: container oluştur
(container ID saklanır) → container durumu yokla → container yayınla (media ID
saklanır). Sonuç belirsizse (timeout/5xx) paket `-publishing` olarak kalıyor,
taze yayın yasaklanıyor; `reconcile` kayıtlı container ID ile devam ediyor ve
asla yeni container üretmiyor — yani ikinci Reel basılamıyor. Kesin
başarısızlıkta paket aktif duruma dönüyor ve `retry` ile yeniden denenebiliyor.
Başarıda paket `-completed` oluyor, hemen ardından yeni boş aktif paket açılıyor
ve eşleşmiş cihazlara push bildirimi gidiyor.

Yeni parçalar: `HttpMetaPublisher` (resmi Graph API: container oluştur, durum
yokla, yayınla; geçici hatalar belirsiz, 4xx hatalar kesin sayılır),
`HmacSignedUrlStore` (yalnızca `render/reel.mp4` kapsamı, süre sonu, iptal),
`GET /pub/{token}` (kimliksiz Meta fetch), `GET/POST /api/packages/active/publication`
(durum, retry, reconcile), worker tick içinde `reconcile_publication` çağrısı.
`POST /api/packages/active/publish` artık retry görevi görüyor: yayın sürerken
409, yayına hazır onay yoksa 409, başarısız/belirsiz sonuçta 502 dönüyor.

## Deneme adımları

Repo kökünde (`aisomedo`) PowerShell aç ve aşağıdaki adımları sırayla çalıştır.

### 1. Branch ve commit durumunu doğrula

```powershell
rtk git log --oneline -3
rtk git status --short
```

`1e1e50c` commit'i görünmeli; `setup.py` ve `routes/setup.py` dışındaki
yayın dosyaları temiz olmalı (o iki dosya daha önceki işin bekleyen değişikliği).

### 2. Yayın testlerini çalıştır (TDD çekirdeği)

```powershell
rtk uv run --project dojo-core pytest dojo-core/tests/test_publication.py dojo-core/tests/test_meta_publisher.py dojo-core/tests/test_signed_urls.py -q -p no:cacheprovider
```

Beklenen: `14 passed` (7 yayın durum makinesi + 3 Meta adapter + 4 imzalı URL).
`test_publication.py` şunları kanıtlar: onayda claim + ID kalıcılığı + tamamlanma,
takılı `-publishing` iken ikinci claim'in `PublicationInProgress` ile engellenmesi,
kesin hatada aktif'e dönüş + retry, belirsiz timeout'ta aynı container ile uzlaşma
(yeni container yok), onaysız `publish()` çağrısında `PublicationNotReady`.

### 3. Komşu davranış testleri (approve/publish/review/branding)

```powershell
rtk uv run --project dojo-core pytest dojo-core/tests/test_publishing.py dojo-core/tests/test_branding.py dojo-core/tests/test_review.py dojo-core/tests/test_review_resolution.py -q -p no:cacheprovider
```

Beklenen: tamamı geçer. `test_publishing.py` ve `test_branding.py` içindeki publish
testleri artık `PublicationNotReady` bekler; review testleri approve'un tetiklediği
yayının yan etkisine rağmen geçer.

### 4. Backend yayın API testleri

```powershell
rtk uv run --project backend pytest backend/tests/test_publication_api.py -q -p no:cacheprovider
```

Beklenen: `3 passed`. Kapsananlar: tamamlanmış yayın sonrası durum, imzalı fetch
(`GET /pub/{token}` yalnızca render sunar, fetch denetlenir, ham yol reddedilir,
bilinmeyen token 404), onaysız publish'in 409 eşlemesi.

### 5. Tip denetimi

```powershell
rtk uv run --project dojo-core mypy dojo-core/src/dojo/publishing.py dojo-core/src/dojo/adapters/meta.py dojo-core/src/dojo/adapters/signed_urls.py
```

Beklenen: `Success: no issues found in 3 source files`.

### 6. Lint (yalnızca yeni kod)

```powershell
rtk uv run --project dojo-core ruff check dojo-core/src/dojo/adapters/signed_urls.py dojo-core/tests/test_publication.py dojo-core/tests/test_meta_publisher.py dojo-core/tests/test_signed_urls.py backend/src/backend/routes/publication.py backend/tests/test_publication_api.py --output-format concise
```

Beklenen: çıktı yok (temiz). Not: `publishing.py` içindeki 5 ruff bulgusu
HEAD'de de var olan eski ihlallerdir; bu iş yeni ihlal eklemez:

```powershell
rtk git stash push -- dojo-core/src/dojo/publishing.py
rtk uv run --project dojo-core ruff check dojo-core/src/dojo/publishing.py --output-format concise
rtk git stash pop
```

### 7. Tam paketler (bir kez, sondan)

```powershell
rtk uv run --project dojo-core pytest dojo-core/tests -q -p no:cacheprovider
rtk uv run --project backend pytest backend/tests -q -p no:cacheprovider
```

Beklenen: dojo-core `277 passed, 2 skipped`; backend `76 passed`.

## 8. Uçtan uca deneme (gerçek Instagram hesabıyla yayın)

Bu bölüm, Meta panelinden alınmış geçerli bir Instagram Login access token'ı
olan bir hesabın gerçekten Reel yayınlaması için gerekli işlemleri sırayla verir.
Tüm adımlar PowerShell'dir. Kritik önkoşul: `PUBLIC_BASE_URL` internetten
erişilebilir bir HTTPS adresi olmalıdır; Meta videoyu bu adresten çeker,
`localhost` URL'sini çekemez ve container `ERROR` ile kesin başarısızlığa düşer.

### 8.1. Ortam değişkenlerini hazırla

`ops/.env` dosyasına üç değer girilir: veritabanı şifresi, token şifreleme anahtarı
ve imzalı URL gizlisi. Şifreleme anahtarı backend ve worker'da aynı olmalıdır;
üretimi için Fernet anahtarı gerekir (bir kez üretilir, dosyaya yazılır):

```powershell
notepad ops/.env
```

Dosyada şu satırlar dolu olmalı (örnek değerler değil, kendi değerlerin):

```powershell
Select-String -Pattern 'POSTGRES_PASSWORD|META_TOKEN_ENCRYPTION_KEY' ops/.env
```

Ardından herkese açık taban adresi ortama tanımlanır (Meta'nın videoyu çekeceği
adres; tünel yoksa gerçek yayın yapılamaz, hazırlık adımları yine de denenebilir):

```powershell
$env:PUBLIC_BASE_URL = 'https://dojo.example.com'
$env:SIGNED_URL_SECRET = 'uzun-rastgele-bir-gizli-dize'
```

### 8.2. Veritabanı + backend + worker'ı ayağa kaldır

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml up -d db
docker compose --env-file ops/.env -f ops/docker-compose.yml up -d backend worker
docker compose --env-file ops/.env -f ops/docker-compose.yml ps
```

Backend sağlığı beklenir:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/health'
```

### 8.3. Cihaz eşleştir (Bearer token al)

```powershell
$pairBody = @{code='<ESLESTIRME_KODU>'; kind='device'; name='PowerShell'} | ConvertTo-Json -Compress
$paired = Invoke-RestMethod -Uri 'http://localhost:8000/api/pairing/validate' -Method Post -ContentType 'application/json' -Body $pairBody
$headers = @{Authorization="Bearer $($paired.token)"}
```

Eşleştirme kodu `dojo-create-pairing-code` komutuyla üretilir. `($paired.token)`
değeri sonraki tüm çağrılarda `$headers` ile taşınır; ekrana yazdırılmaz.

### 8.4. Instagram token'ını bağla

```powershell
.\ops\connect-instagram.ps1 -BaseUrl 'http://localhost:8000'
```

Script Dojo Bearer token'ı ve Instagram access token'ı gizli girişle sorar.
Başarılı çıktı `health`, `ig_user_id`, `ig_username` alanlarını içerir.
Bağlantı durumu her zaman şu uçtan denetlenir:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/meta/status' -Headers $headers
```

`health` değeri `healthy` olmalıdır; `reconnect_required` ise yayın engellenir,
önce yeniden bağlanılır.

### 8.5. Logo ve başlık şablonunu ayarla

Yayın için zorunlu logo watermark'ı ayarlanır (`logo_asset` backend'in
`MEDIA_ROOT` içindeki bir dosyayı göstermelidir):

```powershell
$branding = @{logo_asset='logo.png'; caption_template='Haftanın dojodan kareleri'} | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://localhost:8000/api/settings/branding' -Method Put -Headers $headers -ContentType 'application/json' -Body $branding
```

### 8.6. Medya yükle (devam edebilir yükleme)

Her dosya için üç çağrı: başlat, parça gönder, tamamla. Tek parça örneği:

```powershell
$file = Get-Item '.\ornek.jpg'
$init = @{filename=$file.Name; content_type='image/jpeg'; declared_size_bytes=$file.Length} | ConvertTo-Json -Compress
$up = Invoke-RestMethod -Uri 'http://localhost:8000/api/media/uploads' -Method Post -Headers $headers -ContentType 'application/json' -Body $init
$bytes = [System.IO.File]::ReadAllBytes($file.FullName)
$hash = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash.ToLower()
Invoke-RestMethod -Uri "http://localhost:8000/api/media/uploads/$($up.upload_id)/ranges?offset=0&checksum_sha256=$hash" -Method Put -Headers $headers -Body $bytes -ContentType 'application/octet-stream'
Invoke-RestMethod -Uri "http://localhost:8000/api/media/uploads/$($up.upload_id)/complete" -Method Post -Headers $headers
```

Video dosyalarında `content_type` değeri `video/mp4` kullanılır. Worker
yüklemeyi işleyip pakete ekler; kuyruk şu uçtan izlenir:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/media/uploads' -Headers $headers
```

### 8.7. Manuel yayın slotu aç

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/settings/manual-publish' -Method Post -Headers $headers
```

Worker (10 saniyelik döngü) render'ı üretip `Yayın İncelemesi` oluşturur.
Oluştuğu, aktivite akışındaki `review.created` kaydından doğrulanır:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/activity' -Headers $headers
```

### 8.8. Onayla (yayın bu adımda tetiklenir)

Onay, eşleşmiş inceleme istemcisinden verilir (web odaklı inceleme akışı #30,
Android inceleme akışı #36). HTTP'de review route'u henüz yoktur; istemci
`approve()` çağırdığında claim → container → durum → yayın → iptal →
`-completed` → yeni boş aktif paket zinciri senkron yürür ve Instagram'da Reel
belirir.

### 8.9. Sonucu izle

Yayın durum makinesi şu uçtan okunur:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/packages/active/publication' -Headers $headers
Invoke-RestMethod -Uri 'http://localhost:8000/api/activity' -Headers $headers
```

Başarıda aktivitede sırayla `publication.claimed`, `publication.container_created`,
`publication.signed_url_revoked`, `publication.confirmed`, `package.completed`
görülür; tamamlanan paket listelenir:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/packages' -Headers $headers
```

### 8.10. Belirsiz/kesin sonuçta kurtarma

Belirsiz sonuçta (timeout) paket `-publishing` kalır; kayıtlı container yoklanır,
yeni container üretilmez:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/packages/active/publication/reconcile' -Method Post -Headers $headers
```

Kesin başarısızlıkta paket aktif'e döner; aynı onaylı revizyonla yeniden denenir:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/packages/active/publication/retry' -Method Post -Headers $headers
```

Retry `409` dönerse ya başka yayın sürüyordur ya da paket onay sonrası değişmiştir;
aktivitedeki `publication.failed` kaydının `error` alanı nedeni söyler.

### 8.11. Kapatma

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml down
```

Bilinen sınırlar: claim tek worker varsayımıyla korunur (liderlik #21'de);
imzalı URL kayıtları bellektedir, restart kendini container `ERROR` → aktif'e
dönüş + retry ile iyileştirir.
