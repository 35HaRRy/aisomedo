# Immutable Reel Render Pipeline — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #12** (Immutable Reel render pipeline) kapsamında yapılan
değişiklikleri özetler ve bunları adım adım deneyebilmen için PowerShell komutlarını
gösterir. Tüm komutlar PowerShell'dir; Python kodu içermez.

## 1. Değişiklik Özeti

### Amaç

`Dojo Paylaşım Paketi`'nin medyasını **1080x1920 yayına hazır** tek bir Reel
dosyasına dönüştürür. Önemli özellikler:

- **Karışık medya → 1080x1920**: fotoğraf + video birlikte; 9:16 olmayan medya,
  **bulanık arka plan** üzerine sığdırılarak (blurred fit) yerleştirilir.
- **Kırpma ve süre**: video kırpmaları uygulanır; fotoğraf süresi
  `montage.photo_duration_seconds` (varsayılan 3.0s) kadardır.
- **Zorunlu watermark**: her kareye alt-sağ güvenli bölgeye dojo logosu konur;
  logo yoksa render **reddedilir**.
- **Orijinal klip sesi**: videonun sesi korunur; sessi videoya sessiz ses kanalı
  eklenir; isteğe bağlı intro/outro desteklenir.
- **Render yalnız bayatken**: herhangi bir giriş değişince `render_revision`
  temizlenir; render yalnız **preview** istendiğinde veya **due** zamanda üretilir,
  her düzenlemeden sonra değil.
- **Tek digest**: preview ve yayın aynı `render_revision` digest'ini ve aynı
  `render/reel.mp4` dosyasını kullanır.

### Yapılanlar (`development` branch, 1 commit `4a550a7`)

| Dosya | İçerik |
|---|---|
| `dojo-core/src/dojo/model.py` | `ReelClip`, `ReelBuild` modelleri (render için immutable anlık görüntü) |
| `dojo-core/src/dojo/ports.py` | `ReelRenderer` protokolü (`render(build, work_dir, out_path)`) |
| `dojo-core/src/dojo/exceptions.py` | `RenderFailed` istisnası |
| `dojo-core/src/dojo/adapters/render.py` | **Yeni** `FfmpegReelRenderer` — ffmpeg ile 1080x1920, bulanık arka plan, watermark, ses, image loop, trim, concat |
| `dojo-core/src/dojo/adapters/stubs.py` | `StubReelRenderer` (testler için) |
| `dojo-core/src/dojo/publishing.py` | `render_preview()` / `render_if_stale()` — bayatken `render` job'ı kuyruğa alır; worker `render` job'ını işler, `render_revision` digest'ini yazar; süre-limit ve zorunlu-logo korumaları |
| `dojo-core/src/dojo/__init__.py`, `adapters/__init__.py` | Yeni sembollerin dışa aktarımı |
| `dojo-core/tests/test_render.py` | **Yeni** render seam testleri (11 test) |
| `dojo-core/tests/test_ffmpeg_fixtures.py` | Docker tabanlı gerçek render doğrulaması (1080x1920 + ses) |
| `worker/tests/test_worker.py` | `run_tick`'in `render` job'ını işlediğini doğrular |

### Önemli tasarım kararları

- **İş job olarak çalışır**: `render_preview` ağır ffmpeg işini senkron yapmaz;
  `render` job'ı kuyruğa alır, worker `process_job` ile işler (mevcut `media.process`
  deseniyle aynı).
- **Bayat-yalnız tetik**: digest, sıra/kırpma/branding/caption/fotoğraf süresi üzerinden
  SHA-256 ile hesaplanır. `render_preview` digest değişmemişse **job üretmez**.
- **Süre limiti koruması**: toplam süre `montage.max_duration_seconds`'ı aşarsa
  `render_preview` `MontageDurationExceeded` fırlatır; asla sessizce kırpılmaz.
- **Zorunlu watermark**: `_build_reel` logo çözümlenemezse `RenderFailed` fırlatır.
- **Digest-artifakt tutarlılığı**: worker, job'ı işlerken manifest'i yeniden okur ve
  **o manifestin** digest'ini yazar (kuyruğa alınan eski digest'i değil) — kuyruğa
  alma ile işleme arasında giriş değişse bile revision, gerçekte üretilen dosyayla eşleşir.
- **Yayın (#18'e ertelendi)**: `publish()` bu ticket'ta `NotImplementedError` olarak
  kalır; yalnız render + digest + preview + worker işleme kapsamdadır.

## 2. Ön Hazırlık

1. **Docker'ı başlatın** (gerçek ffmpeg render doğrulaması için; Docker yoksa o test atlanır).
2. **Bağımlılıkları yükleyin** (repo kökünden):
```powershell
uv sync
```

## 3. Test Adımları

### Adım 1: Dojo-core render seam testleri

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_render.py -v
```

Beklenen (**11 test geçer**):
- `test_render_requires_active_package` / `test_render_requires_logo` — aktif paket ve
  logo zorunludur (`NoActivePackage`, `LogoNotConfigured`).
- `test_preview_enqueues_render_when_stale` / `test_preview_noop_when_fresh` — bayatken
  `render` job'ı üretilir, tazeyken üretilmez.
- `test_render_job_writes_artifact_and_sets_digest` — `render/reel.mp4` yazılır,
  `render_revision` = preview digest'i, `render.completed` audit edilir.
- `test_render_job_failure_marks_job_failed` — renderer hatası job'ı `failed` yapar,
  `render.rejected` audit edilir.
- `test_digest_changes_on_input_edit` — sıra değişince digest değişir.
- `test_build_reel_resolves_clip_paths_and_assets` — clip yolları ve logo çözümlenir.
- `test_render_preview_rejects_over_limit` — süre limiti aşımı reddedilir
  (`MontageDurationExceeded`).
- `test_render_job_stamps_digest_of_current_manifest` — kuyruğa alındıktan sonra giriş
  değişse bile job, güncel manifest digest'ini yazar.
- `test_build_reel_requires_watermark` — logo yoksa `RenderFailed`.

### Adım 2: Gerçek ffmpeg render doğrulaması (Docker)

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_ffmpeg_fixtures.py::test_reel_render_pipeline_1080x1920_with_audio -v
```

Beklenen: video (sesli) + fotoğraf (sessiz) + logo ile üretilen reel **1080x1920**,
bir **audio** kanalı ve ~2.0s süre içerir. (Docker kapalıysa test **atlanır**.)

### Adım 3: Worker testleri

```powershell
uv run --project worker pytest worker/tests/test_worker.py -v
```

Beklenen (**4 test geçer**): `run_tick` hem `media` hem `render` job'ını işler.

### Adım 4: Tüm paketlerin tam takımları

```powershell
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project worker pytest worker/tests -v
```

Beklenen: dojo-core **202 geçer, 2 atlanır**, worker **4 geçer**. (2 atlama yerel
ffmpeg gerektiren `test_media_processor` testleridir; CI'da doğrulanır.)

### Adım 5: Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src/dojo dojo-core/tests/test_render.py dojo-core/tests/test_ffmpeg_fixtures.py
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project worker ruff check worker/src worker/tests
```

Beklenen: hepsi temiz. (mypy doğrudan engellenirse `uvx mypy ...` ile deneyin.)

## 4. Manuel Deneme (Uçtan Uca)

Render işlemini el ile görmek için yığını ayağa kaldırın, bir cihaz token'ı alın, medya
yükleyin, logoyu ayarlayın ve preview'i CLI üzerinden tetikleyin. Tüm adımlar PowerShell
komutudur; Python kodu içermez. Not: `render_preview` seam'i HTTP'ye açık değildir; bu
yüzden preview, `dojo-render` CLI'ı ile çağrılır (bu rehberle birlikte eklenmiştir).
Render işleminin kendisini Docker'daki **worker** yapar; host üzerinden yalnızca job
kuyruğa alınır.

1. **Yığını ayağa kaldırın ve ortamı kurun** (db + backend + worker; worker, `media` ve
   `render` job'larını işler):
```powershell
# POSTGRES_PASSWORD, ops/.env'dekiyle aynı olmalı
docker compose -f ops/docker-compose.yml up -d --build db backend worker

$base = "http://localhost:8000"
$env:MEDIA_ROOT = (Resolve-Path "ops/media-data").Path
$env:DATABASE_URL = "postgresql+psycopg://dojo:$env:POSTGRES_PASSWORD@localhost:5433/dojo"
```

2. **Logoyu koyun** (zorunlu watermark; logo yoksa render reddedilir):
```powershell
# Logoyu ops/media-data altına kopyala (docker worker ile aynı klasör)
Copy-Item "C:\yol\logo.png" "$env:MEDIA_ROOT\logo.png"
uv run --project backend dojo-settings set-branding --logo-asset "logo.png"
```

3. **Cihaz token'ı alın**:
```powershell
$out = uv run --project backend dojo-create-pairing-code create-code
$code = ($out | Where-Object { $_ -like 'Pairing code:*' }) -replace '^Pairing code:\s*',''
$pair = Invoke-RestMethod -Method Post -Uri "$base/api/pairing/validate" `
    -ContentType 'application/json' -Body (@{ code=$code; kind='device'; name='PS' } | ConvertTo-Json)
$H = @{ Authorization = "Bearer $($pair.token)" }
```

4. **Aktif paketi oluşturup klasörünü not edin**:
```powershell
$pkg = Invoke-RestMethod -Method Get -Uri "$base/api/packages/active" -Headers $H
$pkg.folder_name
$manifest = Join-Path $env:MEDIA_ROOT "$($pkg.folder_name)\manifest.json"
```

5. **Bir fotoğraf ve bir video yükleyin** (tek parça, 8 MiB altı):
```powershell
function Push-Upload($file, $contentType) {
    $init = @{ filename=(Split-Path $file -Leaf); content_type=$contentType;
               declared_size_bytes=(Get-Item $file).Length } | ConvertTo-Json
    $up = Invoke-RestMethod -Method Post -Uri "$base/api/media/uploads" -Headers $H `
        -ContentType 'application/json' -Body $init
    $hash = (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLower()
    $bytes = [System.IO.File]::ReadAllBytes($file)
    $up = Invoke-RestMethod -Method Put `
        -Uri "$base/api/media/uploads/$($up.upload_id)/ranges?offset=0&checksum_sha256=$hash" `
        -Headers $H -ContentType 'application/octet-stream' -Body $bytes
    Invoke-RestMethod -Method Post -Uri "$base/api/media/uploads/$($up.upload_id)/complete" -Headers $H
}

$photo = Push-Upload "C:\yol\foto.jpg" "image/jpeg"
$video = Push-Upload "C:\yol\video.mp4" "video/mp4"
$photo | Format-List upload_id, status, received_bytes
$video | Format-List upload_id, status, received_bytes
```
   Worker ikisini işler, `order`'a ekler ve `render_revision` `null` olur. (Video kırpma
   bilgisi `montage` sırasında yoksa tam süre kullanılır.)

6. **Montage durumunu görün** (sıra, toplam süre, limit):
```powershell
Invoke-RestMethod -Method Get -Uri "$base/api/packages/active/montage" -Headers $H | Format-List
```
   `clips` boşsa medya henüz worker tarafından işlenmemiştir; işlenmesi için birkaç
   saniye bekleyip tekrar bakın (video işlenmeden render'a girmez).

7. **Preview tetikleyin** — `render` job'ı kuyruğa alınır:
```powershell
uv run --project backend dojo-render render-preview
```
   Çıktı:
```
stale: True
render_revision: <sha256-digest>
```
   `stale: True` demek job kuyruğa alındı. Worker job'ı işleyip digest'i yazdıktan sonra
   tekrar çağırırsanız `stale: False` döner (taze; yeni job üretilmez).

8. **Worker'ın job'ı işlemesini bekleyin ve doğrulayın** (docker worker 10 sn'de bir
   tick atar):
```powershell
Start-Sleep -Seconds 15
Get-ChildItem -Recurse -Path "$env:MEDIA_ROOT" -Filter "reel.mp4" | Select-Object FullName, Length
(Get-Content $manifest -Raw | ConvertFrom-Json).render_revision
```
   Beklenen: `render/reel.mp4` 1080x1920, ses kanallı; manifest içindeki
   `render_revision` 7. adımdaki digest ile aynı.

9. **Bir düzenleme yapıp bayatlamayı görün** (sırayı tersine çevirin):
```powershell
$order = (Invoke-RestMethod -Method Get -Uri "$base/api/packages/active/montage" -Headers $H).order
$body = @{ order = @($order[1], $order[0]) } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$base/api/packages/active/order" -Headers $H `
    -ContentType 'application/json' -Body $body | Out-Null

# render bayat: manifest içinde render_revision null
(Get-Content $manifest -Raw | ConvertFrom-Json).render_revision

# Yeni preview yalnızca bayatken job üretir
uv run --project backend dojo-render render-preview
```
   Beklenen: düzenleme sonrası `render_revision` `null` olur; preview yeni digest ile
   `stale: True` döner.

10. **Logo kaldırılırsa render reddedilir** (zorunlu watermark; `--logo-asset` vermeyin
    çünkü boş string `None` değil, render'ı reddetmez):
```powershell
uv run --project backend dojo-settings set-branding
uv run --project backend dojo-render render-preview
```
    Beklenen: `LogoNotConfigured` / "dojo logo watermark asset is not configured". Sonra
    logoyu geri koyun:
```powershell
uv run --project backend dojo-settings set-branding --logo-asset "logo.png"
```

## 5. Git Geçmişi

```powershell
git log --oneline -3
```

```text
4a550a7 feat(dojo): immutable reel render pipeline (#12)
9377fad feat(backend): add publish endpoint for active package and handle logo configuration error
608761d feat(dojo): branding and draft configuration (#11)
```

## 6. Known Issues ve Sınırlamalar

- **ffmpeg/docker gerekli**: `FfmpegReelRenderer` ve gerçek render testi ffmpeg/docker
  gerektirir; Docker yoksa o test atlanır (CI'da doğrulanmalıdır).
- **DB render job'ı kapsam dışı**: `render` job'ı `upload_id = 0` ile oluşturulur;
  seam testleri `InMemoryStore` üzerinde çalışır. PostgreSQL'e gerçek render job
  kalıcılığı (jobs tablosundaki FK) ilerideki ops/scheduler ticket'ına bırakıldı.
- **Yayın ertelendi**: `publish()` `#18`'de işlenecek; bu ticket yalnız render + digest +
  preview + worker işlemeyi içerir. `publish` `_assert_logo_configured` çağırır ve
  `NotImplementedError` fırlatır.
- **Manifest yazımı atomik değildir**: `_write_manifest` doğrudan yazar; işlem ortasında
  çökme manifest'i bozabilir (tasarım kararı, out of scope).
- **Kapsam dışı**: "cards" kavramı (issue metnindeki "optional cards") kullanıcı kararıyla
  yok sayılmıştır. Web (#29/#30) ve Android (#35/#36) bu ticket'ta yok.