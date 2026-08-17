# Dosya Adı Çakışma Çözümü (Filename Conflict Resolution) — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #8** (Filename conflict resolution) kapsamında yapılan değişiklikleri
özetler ve bunları adım adım deneyebilmen için komutları gösterir. Tüm komutlar
**PowerShell** içindir ve repo kökünden (`C:\Users\35.HaRRy\Desktop\Projects\aisomedo`)
çalıştırılır.

## 1. Değişiklik Özeti

### Amaç

Aynı `Dojo Paylaşım Paketi`'ne aynı (büyük/küçük harf farkı da sayılan) dosya adıyla
medya yüklenebilir. Bu ticket, kullanıcının her çakışmada ne olacağına karar vermesini
sağlar ve dosya adlarını güvenli tutar.

- **Unicode adlar korunur**; yol ayraçları (`/`, `\`) ve kontrol karakterleri reddedilir.
- **Büyük/küçük harf duyarsız çakışma** tespiti taşınabilir şekilde yapılır
  (Unicode için `casefold()` normalizasyonu).
- Üç karar türü:
  - **keep_both** — yeni dosya ilk boş sayısal sonekle kaydedilir (`photo (1).jpg`).
  - **keep_selected** — seçilen mevcut medya **gerçekten silinir** ve yerine yenisi yazılır
    (geri döndürülemez; `target_media_id` + `confirmed_overwrite=True` zorunludur; audit'e `media.overwritten` yazılır).
  - **keep_target** — yüklenen dosya atılır; mevcut medya aynen kalır.
- **apply_to_all** — aynı normalleştirilmiş adı paylaşan tüm uyumlu çakışmalara tek karar uygulanır.

### Yapılanlar (tek commit, `development`)

| Alan | İçerik |
|---|---|
| `dojo-core` | `conflict` upload durumu; `resolve_conflict` seam yöntemi; `Upload`'a `conflict_decision` + `conflict_target_media_id`; `UploadStatus.conflicts` (hedef önizleme); `UploadDecisionInvalid` istisnası; `_normalize`/`_manifest_collisions`/`_first_free_suffixed_name` yardımcıları; finalize'da karar uygulama (keep_both → sonekli ad, keep_selected → hedefi sil + `media.overwritten` audit); migration `0006_conflict_resolution` + `PostgresStore`/`InMemoryStore` eşlemesi |
| `backend` | `POST /api/media/uploads/{id}/resolve` rotası; `UploadOut.conflicts`; HTTP hata eşlemesi (400/404/409) |
| Testler | `dojo-core/tests/test_conflict.py` (14 senaryo) + `backend/tests/test_api.py` (4 API senaryosu) |

### Önemli tasarım kararları

- **Çakışma tespiti `start_upload` anında** yapılır: çakışma varsa upload `conflict`
  durumunda oluşturulur, baytlar henüz aktarılmaz. Karar verilince `receiving`'e geçer.
- **keep_selected** hedef önizlemesi `conflicts` alanından gelir; geri döndürülemez uyarıyı
  *göstermek* web (#28) ve Android (#34) UI'larının işidir. Backend, uyarıyı gösterip
  onaylattıktan sonra istemcinin `confirmed_overwrite=True` göndermesini zorunlu kılar ve
  gerçek üzerine yazmayı audit'e kaydeder.
- **Dosya adı yalnızca manifest'te saklanır**; disk düzeni `media/<id>/original.<ext>`
  şeklindedir (değişmez medya ID'si), bu yüzden çakışma çözümünde dosya sistemi taşınması gerekmez.

---

## 2. Test Rehberi

### Ön koşullar

- Python 3.12 + `uv` kurulu (`uv --version`)
- Postgres testleri için **Docker** çalışıyor olmalı (testcontainers)
- Bu ortamda `_pillow_heif` DLL'i Windows App Control tarafından engellenebildiği için
  `test_media_processor.py` / `test_ffmpeg_fixtures.py` toplanmayabilir; onları çıkararak çalıştırıyoruz.

### Adım 1 — Tüm testleri çalıştır

```powershell
# dojo-core (domain katmanı) — çakışma çözümü dahil ~132 test
uv run --project dojo-core pytest dojo-core/tests -q --ignore=dojo-core/tests/test_media_processor.py --ignore=dojo-core/tests/test_ffmpeg_fixtures.py

# backend (API + CLI) — 40 test
uv run --project backend pytest backend/tests -q

# worker — 3 test
uv run --project worker pytest worker/tests -q
```

Beklenen çıktı: **132 passed**, **40 passed**, **3 passed**.

### Adım 2 — Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
uv run --project backend ruff check backend/src backend/tests
uv run --project worker ruff check worker/src worker/tests

uv run --project dojo-core mypy dojo-core/src
```

Beklenen çıktı: `All checks passed!` ve `Success: no issues found in ... source files`.

### Adım 3 — Çakışma çözümünü domain katmanında doğrula

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_conflict.py -v
```

Kapsanan senaryolar:
- Unicode adlar korunur; büyük/küçük harf duyarsız çakışma tespiti (`Photo.jpg` vs `photo.JPG`)
- `keep_both` → `receiving`, finalize'da `photo (1).jpg` sonekli ad; tekrar eden yüklemeler `(1)`, `(2)`...
- `keep_selected` → `confirmed_overwrite=True` zorunlu; hedef manifest'ten ve diskten silinir, `media.overwritten` audit'i
- `keep_target` → upload `aborted`, mevcut medya aynen kalır
- `apply_to_all` → `keep_both`, `keep_target`, `keep_selected` için tüm uyumlu çakışmalara uygulanır
- Hatalı karar (`UploadDecisionInvalid`), çakışma dışı upload'ı çözme (`UploadConflict`), bilinmeyen upload (`UploadNotFound`)

### Adım 4 — Çakışma akışını uçtan uca canlı deneyimle

Aşağıdaki komutlar, yığını (Postgres + backend + worker) ayağa kaldırıp HTTP API'yi
`Invoke-RestMethod` ile sürer; bir medyayı yükler, aynı adla çakışma oluşturur ve
`keep_both` kararını uygular. Media işleme worker'ın içinde (Docker/Linux) koşar; böylece
bu Windows makinedeki `_pillow_heif` DLL engelinden etkilenmezsin.

Ön koşul: repo kökünde `.env` içinde `POSTGRES_PASSWORD` tanımlı olmalı.

```powershell
# 0) Yığını başlat (ilk seferde imajları derler; sonrasında --build gerekmez)
docker compose -f ops/docker-compose.yml up -d --build db backend worker

# 1) Pairing kodu üret (CLI, host:5433 -> Docker'daki Postgres)
$out = uv run --project backend dojo-create-pairing-code create-code
$code = ($out | Where-Object { $_ -like 'Pairing code:*' }) -replace '^Pairing code:\s*',''
$code

# 2) Kodu cihaz olarak doğrula -> Bearer token
$pair = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/pairing/validate' `
    -ContentType 'application/json' -Body (@{ code=$code; kind='device'; name='PS' } | ConvertTo-Json)
$H = @{ Authorization = "Bearer $($pair.token)" }

# 3) Yüklenecek geçerli küçük PNG'yi üret (1x1) ve sha256'sını hesapla
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap 1,1
$bmp.Save("$env:TEMP\photo.png",[System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
$bytes = [System.IO.File]::ReadAllBytes("$env:TEMP\photo.png")
$sha   = [System.BitConverter]::ToString((New-Object System.Security.Cryptography.SHA256Managed).ComputeHash($bytes)).Replace('-','').ToLower()

# 4) photo.png yükle: init -> range -> complete (worker işler)
$init = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/media/uploads' -Headers $H `
    -ContentType 'application/json' -Body (@{ filename='photo.png'; content_type='image/png'; declared_size_bytes=$bytes.Length } | ConvertTo-Json)
Invoke-RestMethod -Method Put -Uri "http://localhost:8000/api/media/uploads/$($init.upload_id)/ranges?offset=0&checksum_sha256=$sha" `
    -Headers $H -Body $bytes -ContentType 'application/octet-stream' | Out-Null
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/media/uploads/$($init.upload_id)/complete" -Headers $H | Out-Null
Start-Sleep -Seconds 15   # worker 10 sn döngüsünde işler

# 5) Aynı adla (harf duyarsız) çakışma oluştur: PHOTO.PNG
$c = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/media/uploads' -Headers $H `
    -ContentType 'application/json' -Body (@{ filename='PHOTO.PNG'; content_type='image/png'; declared_size_bytes=$bytes.Length } | ConvertTo-Json)
"durum: $($c.status) | hedef: $($c.conflicts[0].filename)"

# 6) keep_both ile çöz -> durum receiving
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/media/uploads/$($c.upload_id)/resolve" -Headers $H `
    -ContentType 'application/json' -Body (@{ decision='keep_both' } | ConvertTo-Json) | Select-Object -ExpandProperty status

# 7) Yeni dosyayı gönder ve tamamla (worker işler)
Invoke-RestMethod -Method Put -Uri "http://localhost:8000/api/media/uploads/$($c.upload_id)/ranges?offset=0&checksum_sha256=$sha" `
    -Headers $H -Body $bytes -ContentType 'application/octet-stream' | Out-Null
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/media/uploads/$($c.upload_id)/complete" -Headers $H | Out-Null
Start-Sleep -Seconds 15

# 8) Aktif paketin manifest'indeki dosya adlarını listele
$pkg = Invoke-RestMethod -Method Get -Uri 'http://localhost:8000/api/packages/active' -Headers $H
$manifest = Get-Content -Raw "ops/media-data/$($pkg.folder_name)/manifest.json" | ConvertFrom-Json
"manifest adları: $(($manifest.media | ForEach-Object { $_.filename }) -join ', ')"
```

Beklenen çıktı:

```
durum: conflict | hedef: photo.png
receiving
manifest adları: photo.png, PHOTO (1).PNG
```

> Not: keep_both sonekli ad, yüklenen dosyanın orijinal adının harf düzenini korur
> (`PHOTO.PNG` → `PHOTO (1).PNG`). Çakışma kontrolü yine de harf duyarsızdır.

### Adım 5 — API rotasını doğrula

```powershell
uv run --project backend pytest backend/tests/test_api.py -k "conflict or resolve" -v
```

Kapsanan senaryolar:
- Çakışan yükleme `status=conflict` + `conflicts` hedef listesiyle döner; liste uç noktasında görünür
- `keep_both` ile çözüm `receiving` döner
- Geçersiz karar → **400**
- `keep_selected` için `confirmed_overwrite` eksik → **400**

---

## 3. Bilinen Sınırlamalar

- Geri döndürülemez uyarı metninin ve hedef önizlemesinin *kullanıcıya gösterimi* UI
  işidir: web için **#28**, Android için **#34**.
- `media.overwritten` audit'i `actor="worker"` ile yazılır (mutasyonu worker yapar);
  kararın sahibi olan cihaz, `conflict.resolved` olayında `actor` olarak kaydedilir.
