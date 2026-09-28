# Çoklu Açık Klasör Kurtarma — Değişiklik Özeti ve Deneme Rehberi

Bu doküman issue #20 (multi-open-folder recovery) kapsamında yapılan
değişiklikleri özetler ve canlı sistemi adım adım denemeni sağlar.
Tarayıcıda yalnızca tek bir kontrol yapılabilir (API dokümantasyon ekranı
kapalı ve korumalı uçlar `Authorization` başlığı ister); geri kalan her şey
PowerShell ile, içinde Python ve SQL kodu olmadan denenir.

## Ne değişti

Başlangıçta birden fazla soneksiz paket klasörü bulunması artık onarılıyor:
zaman damgası en yeni olan klasör Aktif Paket olur, eski klasörler içerikleri
korunarak atomik şekilde `-recovered` adını alır, onarım denetlenir ve
kayıtlı cihazlara bildirim gönderilir. Kurtarılan medya yalnızca aktif
paketin normal çakışma akışı (`start_upload` → `conflict`/`receiving`) üzerinden
içeri alınır; işi biten klasör `-resolved` olarak işaretlenir ve ikinci kez
içe aktarılamaz.

Dosya bazında:

- `dojo-core/src/dojo/publishing.py`
  - `repair_open_folders()`: soneksiz klasörleri listeler, en yeniyi seçer,
    eskileri `-recovered` yapar, DB'deki aktif satırı kazananla hizalar,
    `package.recovery` denetimi yazar, bildirim gönderir.
  - `_is_settled()` / `_is_recovered()`: `-publishing`, `-completed`,
    `-recovered`, `-resolved` ve `(2)` gibi çakışma varyantları asla "açık"
    sayılmaz; aynı kural listelemede de kullanılır.
  - `-publishing` iddiası varken DB'ye dokunulmaz (belirsiz yayın sonucu
    varken taze yayın yasağı korunur); dosya karantinası yine yapılır.
  - `list_recovered_folders()`, `import_recovered_media()`,
    `mark_recovered_resolved()`: listeleme, çakışma akışından içe aktarma
    (dosya bazında hata yalıtımı + `failed` listesi + her durumda denetim),
    `-resolved` işareti (manifest bayrağı + yeniden adlandırma).
- `backend/src/backend/routes/packages.py`: `GET /api/packages/recovered`,
  `POST /api/packages/recovered/{klasör}/import`,
  `POST /api/packages/recovered/{klasör}/resolve` (hata eşlemesi:
  404/400/409/413).
- `backend/src/backend/main.py`, `worker/src/worker/main.py`: açılışta
  en iyi çabayla `repair_open_folders()`; onarım asla açılışı engellemez.
- Testler: `dojo-core/tests/test_recovery_folders.py` (12 test),
  `backend/tests/test_packages_recovery.py` (2 test).

Commit'ler (`development` dalı): `36b562a`, `4782cdd`, `be20ff8`.

## Deneme adımları

Repo kökünde (`aisomedo`) PowerShell aç. Tüm komutlar PowerShell cmdlet'i
veya `curl.exe`/`uv`/`docker` çağrısıdır; Python ve SQL yok.

### 1. Hazırlık: veritabanı ve izole medya klasörü

```powershell
git log --oneline -3
docker compose --env-file ops/.env -f ops/docker-compose.yml up -d db
$env:MEDIA_ROOT = "C:\Temp\dojo-deneme"
New-Item -ItemType Directory -Force -Path $env:MEDIA_ROOT
```

`be20ff8` commit'i en üstte görünmeli. `MEDIA_ROOT` geçici klasörü,
gerçek medyaya dokunmadan deneme yapmanı sağlar.

### 2. Backend'i başlat (ayrı pencere)

İkinci bir PowerShell penceresinde:

```powershell
$env:MEDIA_ROOT = "C:\Temp\dojo-deneme"
. ./ops/Load-Env.ps1
uv run --project backend python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 3. Tarayıcı kontrolü

Tarayıcıda aç: `http://127.0.0.1:8000/health`

Beklenen: `{"status":"ok"}`. Başka tarayıcı adımı yok; aşağıdaki tüm
uçlar giriş ister ve başlık gerektiği için PowerShell ile denenir.

### 4. Eşleş ve jeton al

İlk pencerede:

```powershell
. ./ops/Load-Env.ps1
uv run --project backend dojo-create-pairing-code create-code
```

Çıktıdaki `Pairing code:` değerini `$code` değişkenine koy:

```powershell
$base = "http://127.0.0.1:8000"
$code = "BURAYA-KODU-YAZ"
$token = (Invoke-RestMethod -Method Post -Uri "$base/api/pairing/validate" `
  -ContentType "application/json" `
  -Body (@{code=$code; kind="device"; name="Deneme"} | ConvertTo-Json)).token
$h = @{Authorization = "Bearer $token"}
$token
```

Beklenen: uzun bir jeton metni. Sonraki tüm isteklerde `$h` kullanılır.

### 5. Aktif paket aç ve klasör adını not et

```powershell
$active = Invoke-RestMethod -Method Post -Uri "$base/api/packages/active" -Headers $h
$active.folder_name
Get-ChildItem -LiteralPath $env:MEDIA_ROOT
```

Beklenen: `28-09-2026 ...` gibi bugünün klasörü oluşur.

### 6. Sahte açık klasörler yarat (sunucu DURUKEN)

Backend penceresinde `Ctrl+C` ile sunucuyu durdur. Sonra:

```powershell
New-Item -ItemType Directory -Force -Path "$env:MEDIA_ROOT\01-01-2027 10-00"
New-Item -ItemType Directory -Force -Path "$env:MEDIA_ROOT\01-08-2026 10-00"
Set-Content -LiteralPath "$env:MEDIA_ROOT\01-01-2027 10-00\manifest.json" -Encoding utf8 `
  -Value '{"media":[],"order":[]}'
Set-Content -LiteralPath "$env:MEDIA_ROOT\01-08-2026 10-00\manifest.json" -Encoding utf8 `
  -Value '{"media":[],"order":[]}'
"eski-icerik" | Set-Content -LiteralPath "$env:MEDIA_ROOT\01-08-2026 10-00\not.txt" -Encoding utf8
```

`01-01-2027 10-00` gelecek tarihli olduğu için onarımda kazanan olur;
`01-08-2026 10-00` ise `-recovered` adayıdır (`not.txt` içerik koruma
kanıtı için).

### 7. Worker'ı başlat (ayrı pencere)

```powershell
$env:MEDIA_ROOT = "C:\Temp\dojo-deneme"
. ./ops/Load-Env.ps1
uv run --project worker python -m worker.main
```

### 8. Sunucuyu başlat ve onarımı doğrula

2. adımdaki komutla sunucuyu yeniden başlat (açılış onarımı lifespan
içinde çalışır). İlk pencerede:

```powershell
Get-ChildItem -LiteralPath $env:MEDIA_ROOT
Invoke-RestMethod -Uri "$base/api/packages/active" -Headers $h
Invoke-RestMethod -Uri "$base/api/packages/recovered" -Headers $h
```

Beklenen: `01-01-2027 10-00` durur, `01-08-2026 10-00` gitmiş yerine
`01-08-2026 10-00-recovered` gelmiştir; `/active` kazananı, `/recovered`
ise eski klasörü listeler. İçerik koruma kanıtı:

```powershell
Get-Content -LiteralPath "$env:MEDIA_ROOT\01-08-2026 10-00-recovered\not.txt"
```

Denetim kanıtı:

```powershell
(Invoke-RestMethod -Uri "$base/api/activity?limit=10" -Headers $h).events |
  Where-Object { $_.action -eq "package.recovery" } |
  Select-Object action, actor, details
```

Beklenen: `details.active = "01-01-2027 10-00"`,
`details.recovered = ["01-08-2026 10-00-recovered"]` içeren bir olay.

### 9. Kurtarılan klasöre medya hazırla ve içe aktar

Gerçek bir dosyayı kurtarılan klasörün beklediği düzene koy
(`media/<id>/dosya` + manifest kaydı):

```powershell
$rec = "$env:MEDIA_ROOT\01-08-2026 10-00-recovered"
New-Item -ItemType Directory -Force -Path "$rec\media\rec-0"
Copy-Item -LiteralPath "ops/dummies/gs1.png" -Destination "$rec\media\rec-0\gs1.png"
$size = (Get-Item -LiteralPath "$rec\media\rec-0\gs1.png").Length
@"
{"media":[{"media_id":"rec-0","filename":"gs1.png","content_type":"image/png","size_bytes":$size,"uploaded_at":"2026-08-06T14:30:00+03:00","status":"finalized","processed":{}}],"order":["rec-0"]}
"@ | Set-Content -LiteralPath "$rec\manifest.json" -Encoding utf8
$folder = "01-08-2026 10-00-recovered" -replace " ","%20"
Invoke-RestMethod -Method Post -Uri "$base/api/packages/recovered/$folder/import" -Headers $h
```

Beklenen: `imported = 1`, `uploads[0].status = queued` (worker çalışmadığı
için kuyrukta bekler; bu normaldir — dosya çakışma akışına girmiştir,
doğrudan pakete kopyalanmamıştır).

### 10. Çöz olarak işaretle ve çift aktarımı dene

```powershell
$r = Invoke-RestMethod -Method Post -Uri "$base/api/packages/recovered/$folder/resolve" -Headers $h
$r
Invoke-RestMethod -Uri "$base/api/packages/recovered" -Headers $h
Get-ChildItem -LiteralPath $env:MEDIA_ROOT
```

Beklenen: `resolved = "01-08-2026 10-00-resolved"`, liste boş, klasör
yeniden adlandırılmış. Şimdi aynı içe aktarmayı tekrarla:

```powershell
try {
  Invoke-RestMethod -Method Post -Uri "$base/api/packages/recovered/$folder/import" -Headers $h
} catch {
  $_.Exception.Response.StatusCode.value__
}
```

Beklenen: `404` — çözülmüş klasör ikinci kez içe alınamaz.

### 11. (İsteğe bağlı) Çakışma yolunu canlı gör

Aktif pakete aynı isimde gerçek bir dosya yükleyip worker ile
sonlandırdıktan sonra içe aktarma `conflict` döner. Üçüncü bir pencerede
worker'ı başlat (aynı `MEDIA_ROOT` ile):

```powershell
$env:MEDIA_ROOT = "C:\Temp\dojo-deneme"
$env:WORKER_INTERVAL_SECONDS = "2"
. ./ops/Load-Env.ps1
uv run --project worker python -m worker.main
```

İlk pencerede aynı dosyayı API ile yükle:

```powershell
$src = "ops/dummies/gs1.png"
$size = (Get-Item -LiteralPath $src).Length
$up = Invoke-RestMethod -Method Post -Uri "$base/api/media/uploads" -Headers $h `
  -ContentType "application/json" `
  -Body (@{filename="gs1.png"; content_type="image/png"; declared_size_bytes=$size} | ConvertTo-Json)
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $src).Hash.ToLower()
curl.exe -s -X PUT "$base/api/media/uploads/$($up.upload_id)/ranges?offset=0&checksum_sha256=$hash" `
  -H "Authorization: Bearer $token" --data-binary "@$src"
Invoke-RestMethod -Method Post -Uri "$base/api/media/uploads/$($up.upload_id)/complete" -Headers $h
Start-Sleep -Seconds 8
Invoke-RestMethod -Uri "$base/api/media/uploads/$($up.upload_id)" -Headers $h
```

`status` değeri `finalized` olunca (Pillow/ffmpeg yoksa `failed` olur;
o durumda bu adım atlanır), yeni bir `-recovered` klasöre 8. adımdaki
gibi `gs1.png` hazırla ve içe aktar — yanıt `status = conflict` olur.
Çakışmayı çözmek (mevcudu koru):

```powershell
$folder2 = "<YENI-RECOVERED-KLASOR>" -replace " ","%20"
$imp = Invoke-RestMethod -Method Post -Uri "$base/api/packages/recovered/$folder2/import" -Headers $h
$cid = ($imp.uploads | Where-Object { $_.status -eq "conflict" }).upload_id
Invoke-RestMethod -Method Post -Uri "$base/api/media/uploads/$cid/resolve" -Headers $h `
  -ContentType "application/json" `
  -Body (@{decision="keep_target"; apply_to_all=$false; confirmed_overwrite=$false} | ConvertTo-Json)
```

Beklenen: `status = aborted`, mevcut medya değişmeden kalır.

### 12. Testler ve tip denetimi

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_recovery_folders.py -q
uv run --project backend pytest backend/tests/test_packages_recovery.py -q
uv run --project dojo-core pytest dojo-core/tests -q
uv run --project backend pytest backend/tests -q
```

Beklenen: `12 passed`, `2 passed`, `301 passed, 2 skipped`, `83 passed`.
(2 skip, Docker gerektiren render testleridir.)

```powershell
uvx ruff check dojo-core/tests/test_recovery_folders.py backend/src/backend/routes/packages.py backend/src/backend/main.py backend/tests/test_packages_recovery.py worker/src/worker/main.py
```

Beklenen: `All checks passed!`

### 13. Temizlik

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml stop db
Remove-Item -Recurse -Force -LiteralPath "C:\Temp\dojo-deneme"
```

Gerçek `ops/media-data` klasörüne hiç dokunulmadığı için üretim medyası
güvendedir; tüm deneme izole klasörde kaldı.
