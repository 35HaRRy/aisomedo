# Devam Edebilir (Resumable) Yükleme, Medya Doğrulama ve Sonlandırma — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #7** (Resumable upload, media validation, and finalization)
kapsamında yapılan değişiklikleri özetler ve bunları adım adım deneyebilmen için
komutları gösterir.

## 1. Değişiklik Özeti

### Amaç

Yöneticiler Android ve web'den aktif `Dojo Paylaşım Paketi`'ne fotoğraf ve video
yükler. Yüklemeler büyüktür (mobil video), ağlar kararsızdır ve bozuk ya da
desteklenmeyen medya bir Reel'e asla girmemelidir. Bu ticket şunları getirir:

- **Devam edebilir (resumable) parçalı yükleme** — checksum, ilerleme, duraklatma ve
  tekrar deneme.
- **Gerçek içerik doğrulama** — JPEG, PNG, WebP, HEIC/HEIF, MP4, MOV kabul edilir;
  bozuk/desteklenmeyen medya açıklayıcı bir hata ile reddedilir.
- **Görsel normalizasyon** (Pillow) ve **video transkod** (ffmpeg → H.264/AAC).
- **Dosya başına ve paket başına yapılandırılabilir limitler** (varsayılan 2 GiB / 20 GiB),
  transfer öncesi ve sonlandırmada kontrol.
- **Sonlandırma (finalize)** — doğrulama tamamlanmadan medya pakete girmez;
  geçici yüklemeler temizlenir; tam-kez (exactly-once) garantisi.

### Yapılanlar (16 commit, `development` branch)

| Commit | İçerik |
|---|---|
| `b13b5c3` | **Depolama katmanı** — `Upload`, `Job`, `UploadStatus`, `UploadLimits`, `MediaEntry`, `ProcessedMedia` modelleri; `UploadStore`/`JobStore`/`SettingsStore` portları; `UploadNotFound`/`UploadChecksumMismatch`/`MediaValidationError` vb. istisnalar; migration `0005_media_upload` (`uploads` + `jobs` + `settings` tabloları); `InMemoryStore` + `PostgresStore` yöntemleri; testler |
| `ad17eea` | **`list_stale` düzeltmesi** — ham cutoff (`updated_at < cutoff`); 24 saat TTL, `sweep_stale_uploads` içinde uygulanır |
| `800df89` | **Overload düzeltmesi** — `create`/`update`/`get` için protokol uyumlu `@overload` dağıtıcıları (Python'da argüman tipine göre overload mümkün olmadığından `isinstance` dağıtıcılar + tip stub'ları) |
| `bd0d796` | **`DojoPublishing` seam'i — yükleme yaşam döngüsü** — `start_upload` (dosya güvenliği, dosya limiti, paket limiti, staging), `append_upload_range` (offset/checksum, idempotent aralık birleştirme), `get_upload_status`, `complete_upload` (tam kapsam, job oluşturma), `abort_upload`, `get_upload_limits` |
| `cd4b183` | **Append düzeltmesi** — `open("r+b")` + `seek(offset)`; sıra dışı/çakışan parçalar doğru yazılır (plan: `"ab"` modu `seek`'i yok sayardı) |
| `6508a62` | **Seam — işleme + sonlandırma + süpürme** — `claim_next_job`, `process_job` (lazy `PillowFFmpegProcessor`, `MediaValidationError` → `_fail_job`), `finalize_media` (disk kontrolü, `media/<id>/original.<ext>` + `processed.<ext>`, manifest `media`+`order`, audit), `sweep_stale_uploads`, `StubMediaProcessor`; `UploadStatus.error_reason` eklendi |
| `2cce669` | **Gerçek medya işlemcisi** — `PillowFFmpegProcessor` (`dojo/adapters/media.py`): sihirli baytlarla format tespiti, animasyon reddi, EXIF yönü, RGB JPEG (4000px tavan), ffmpeg transkod; `pillow>=11` + `pillow-heif>=0.16` bağımlılıkları; `test_media_processor.py` |
| `b20fe0d` | **RGBA düzeltmesi** — RGBA (ve diğer modlar) JPEG kaydetmeden önce RGB'ye çevrilir; `test_rgba_png_accepted` |
| `8792a9d` | **Worker entegrasyonu** — `run_tick`: `evaluate_due_work` → `claim_next_job` → `process_job` → `sweep_stale_uploads`; `SpyPublishing` (insan kararı: `_claims_left` sayacı); worker imajına ffmpeg eklendi |
| `e0e0571` | **FastAPI rotaları + CLI** — `routes/media.py` (`POST/PUT/GET /api/media/uploads...`, auth, HTTP hata eşlemesi, 8 MiB parça sınırı); `deps.build_publishing` uploads/jobs/settings store'larına bağlandı; `dojo-settings set-upload-limits` CLI; 9 sözleşme testi |
| `c37d737` | **Tasarım-gerekli testler** — tam-kez finalize ve disk alanı koruması (monkeypatched `shutil.disk_usage`) |
| `14aa6fb` | **Review düzeltmeleri** — fonksiyon-içi import'lar modül tepesine alındı; `list_active` artık `processing` durumunu sayar (paket limiti penceresi kapatıldı); ffprobe artık H.264 + değişmeyen çözünürlük + (ses varsa) AAC doğrular |

### Önemli tasarım kararları

- **Seam**: `DojoPublishing` facade'ı genişletildi (yeni facade yok). `process_job`,
  `clock`/`meta` gibi enjekte edilen değiştirilebilir bir `MediaProcessor` adapter'ı
  kullanır; prod'da `PillowFFmpegProcessor` lazy-import edilir, testlerde `StubMediaProcessor`.
- **Asenkron işleme**: worker medya doğrulama/normalizasyon/transkod sahibidir.
  `complete_upload` bir `media.process` job'ı kuyruğa alır; worker alır, işler, sonlandırır.
- **Orijinal + işlenmiş saklanır**: `media/<media_id>/original.<ext>` ve `processed.<ext>`.
- **Offset tabanlı resumable**: istemci `offset`, `length`, `checksum_sha256` ve parça
  baytları gönderir; sunucu `received_ranges`'e idempotent olarak birleştirir.
  Duraklatma = yükleme yapmaya ara vermek; ilerleme `GET /api/media/uploads/{id}`.
- **Durumlar**: upload `receiving → queued → processing → finalized | failed | aborted`;
  job `queued → processing → done | failed`. Tam-kez, durum korumalarıyla sağlanır.
- **Medya düzeni**: `media/<id>/original.<ext>` + `processed.<ext>` (tasarım dokümanı).
- **Finalize**: doğrulama tamamlandıktan sonra orijinal+işlenmiş `media/<id>/` altına
  taşınır, `manifest.media`'ya `MediaEntry` ve `manifest.order`'a `media_id` eklenir,
  `media.finalized` audit'i yazılır, staging temizlenir.
- **Kapsam**: dojo-core + worker + backend API + CLI **sadece**. Web UI (#26) ve
  Android (#32) bu ticket'ta yok.

---

## 2. Test Rehberi

### Ön koşullar

- Python 3.12 + `uv` kurulu (`uv --version`)
- Postgres testleri için **Docker** çalışıyor olmalı (testcontainers)
- Video testleri için yerel **ffmpeg/ffprobe** (`PATH`'te) — yoksa 2 test **skip**
  edilir (kırılmaz); HEIC testi pillow-heif'in HEIF encode desteğini kullanır
- Komutlar repo kökünden (`C:\Users\35.HaRRy\Desktop\Projects\aisomedo`) çalıştırılır

### Adım 1 — Tüm testleri çalıştır

```powershell
# dojo-core (domain katmanı) — 126 test
uv run --project dojo-core pytest dojo-core/tests -q

# backend (API + CLI) — 36 test
uv run --project backend pytest backend/tests -q

# worker — 3 test
uv run --project worker pytest worker/tests -q
```

Beklenen çıktı: **126 passed, 2 skipped** (skip = video testleri), **36 passed**,
**3 passed**.

### Adım 2 — Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
uv run --project backend ruff check backend/src backend/tests
uv run --project worker ruff check worker/src worker/tests

# (Bu ortamda `uv run ... mypy` Windows App Control tarafından engelleniyor;
#  uvx ile çalıştır.)
uvx mypy dojo-core/src/dojo
uvx mypy backend/src/backend
uvx mypy worker/src/worker
```

Beklenen çıktı: `All checks passed!` ve `Success: no issues found in N source files`.

### Adım 3 — Yükleme akışını domain katmanında doğrula

```powershell
# Yükleme yaşam döngüsü + işleme + süpürme
uv run --project dojo-core pytest dojo-core/tests/test_upload.py -v
```

Kapsanan senaryolar:
- Start: güvenli olmayan dosya adı reddi, dosya limiti aşımı, paket limiti aşımı
  (işlenmekte olan yüklemeler de sayılır), staging + `upload.started` audit
- Append: sıra dışı/çakışan/tekrar parçalar idempotent, checksum uyuşmazlığı reddi,
  bildirilen aralık dışı reddi, bilinmeyen upload, complete sonrası append reddi
- Complete: eksik kapsam reddi, job oluşturma + `upload.completed`, tam-kez
  (ikinci complete → `UploadConflict`)
- Process/finalize: `media/<id>/{original,processed}` dosyaları, manifest `media`+`order`,
  upload/job durumları, `media.finalized` audit, staging temizliği, doğrulama hatası
  durumunda `failed` + `error_reason`, tam-kez finalize, disk alanı koruması
- Abort + sweep: staging silinir, `aborted`/`expired` + audit, 24h TTL

### Adım 4 — Medya işlemcisini doğrula

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_media_processor.py -v
```

Kapsanan senaryolar:
- JPEG kabul + normalizasyon; RGBA PNG kabul (RGB'ye düzleştirilir); boyut tavanı
- HEIC kabul; bozuk görsel reddi; animasyonlu WebP reddi; desteklenmeyen format reddi
- Video transkod (H.264/AAC) ve MOV kabul — yerel ffmpeg/ffprobe yoksa **skip**

Depolama katmanı:

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_store_upload.py dojo-core/tests/test_store_jobs.py dojo-core/tests/test_store_settings.py -v
```

### Adım 5 — Worker'ı doğrula

```powershell
uv run --project worker pytest worker/tests/test_worker.py -v
```

Kapsanan senaryolar:
- `evaluate_due_work` tick başına bir kez çağrılır
- Claim edilen job tam olarak bir kez işlenir (`processed_jobs == ["j-1"]`)
- Claim tükenince sweep yine çalışır (ikinci tick: işleme yok, `sweeps == 2`)

### Adım 6 — API'yi otomasyonla doğrula

```powershell
uv run --project backend pytest backend/tests/test_api.py -q -v
```

Kapsanan senaryolar (`test_media_*`):
- Auth yok → 401 (`test_media_routes_require_auth`)
- Init → range → complete mutlu yol (`test_init_upload_then_range_then_complete`)
- Dosya limiti aşımı → 413 (`test_init_upload_too_large_413`)
- Güvenli olmayan dosya adı → 400 (`test_init_upload_bad_filename_400`)
- Checksum uyuşmazlığı → 400 (`test_range_checksum_mismatch_400`)
- Eksik kapsam complete → 409 (`test_complete_incomplete_409`)
- Durum + liste (`test_upload_status_and_list`), abort (`test_abort_upload`),
  bilinmeyen upload → 404 (`test_missing_upload_404`)

### Adım 7 — CLI'yi elle dene

```powershell
# Yardım / alt komutlar
uv run --project backend dojo-settings --help

# Gerçek Postgres (Docker) gerekir. Postgres ayağa kaldırıldıysa:
uv run --project backend dojo-settings set-upload-limits --max-file-bytes 2147483648 --max-package-bytes 21474836480
```

Çıktı: `upload limits saved`. Limitler `settings` tablosuna yazılır ve
`get_upload_limits()`/`start_upload` tarafından okunur (test: `test_get_upload_limits_defaults_and_settings`).

### Adım 8 — API'yi canlı dene (ops/docker-compose ile)

```powershell
# Postgres + backend ayağa kaldır
docker compose -f ops/docker-compose.yml up -d --build backend
```

Ardından `curl` ile (uygun `{token}` eşleşme token'ı ile — `/api/pairing` akışı kullanılır):

```bash
# Yükleme başlat (dosya limiti öncesi, paket limiti, staging + audit)
curl -X POST http://localhost:8000/api/media/uploads \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"filename":"pic.jpg","content_type":"image/jpeg","declared_size_bytes":100}'

# Parça yükle (checksum_sha256 = parçanın sha256'sı)
curl -X PUT "http://localhost:8000/api/media/uploads/{upload_id}/ranges?offset=0&checksum_sha256={sha}" \
  -H "Authorization: Bearer {token}" \
  --data-binary "@pic.jpg"

# İlerleme / duraklatma / tekrar deneme durumu
curl http://localhost:8000/api/media/uploads/{upload_id} -H "Authorization: Bearer {token}"

# Tamamla (eksikse 409) → queued; worker işler → finalized
curl -X POST http://localhost:8000/api/media/uploads/{upload_id}/complete -H "Authorization: Bearer {token}"

# İptal
curl -X POST http://localhost:8000/api/media/uploads/{upload_id}/abort -H "Authorization: Bearer {token}"
```

### Adım 8 — Parçalı (resumable) yükleme senaryosu — tam örnek
```powershell
$base = "http://localhost:8000"
$headers = @{ Authorization = "Bearer $Token" }
$file = "gs2.jpg"
$partSize = 1024

$shaFull = (Get-FileHash -Path $file -Algorithm SHA256).Hash.ToLower()

# 1) Yükleme başlat
$initBody = @{
    filename = $file
    content_type = "image/jpg"
    declared_size_bytes = (Get-Item $file).Length
} | ConvertTo-Json

$init = Invoke-RestMethod -Method POST -Uri "$base/api/media/uploads" `
    -Headers $headers -ContentType "application/json" -Body $initBody
$uploadId = $init.upload_id

# 2) Parçaları döngüyle yükle
$offset = 0

$fs = [System.IO.File]::OpenRead("$PWD\$file")
$buffer = New-Object byte[] $partSize

while (($read = $fs.Read($buffer, 0, $partSize)) -gt 0) {
    $slice = New-Object byte[] $read
    [System.Array]::Copy($buffer, $slice, $read)

    $sha = (Get-FileHash -InputStream ([System.IO.MemoryStream]::new($slice)) -Algorithm SHA256).Hash.ToLower()

    $resp = Invoke-WebRequest -Method PUT `
        -Uri "$base/api/media/uploads/$uploadId/ranges?offset=$offset&checksum_sha256=$sha" `
        -Headers $headers -ContentType "application/octet-stream" -Body $slice

    $offset += $read
}
$fs.Close()

# 3) Tamamla
Invoke-RestMethod -Method POST -Uri "$base/api/media/uploads/$uploadId/complete" -Headers $headers

# 4) Durumu izle (worker işledikçe: queued → processing → finalized)
Invoke-RestMethod -Method GET -Uri "$base/api/media/uploads/$uploadId" -Headers $headers
```

> Not: `/api/media/uploads` yolları eşleşmiş bir cihaz (bearer token veya tarayıcı
> oturumu) gerektirir; `get_current_client` arkasındalar. Token'sız istekler **401**
> döner. Tam akış en iyi otomasyon testlerinde görülür (Adım 6).

### Adım 9 — Migration'ı doğrula

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py -q -v
```

`test_alembic_upgrade_head_creates_schema`, `0005_media_upload` migration'ının
`0004_active_package`'ten sonra zincirlendiğini ve üç tabloyu (uploads, jobs,
settings) gerçek Postgres'te oluşturduğunu doğrular.

---

## 3. Notlar ve bilinen eksikler (review bulguları)

Standartlar ekseni bulguları (düzeltilmesi önerilen takip maddeleri):
- Durum dizgileri (`"receiving"`, `"queued"`, `"processing"`, vb.) publishing.py/db.py/memory.py
  içinde dağınık; merkezi bir geçiş tablosu/enum önerilir.
- `abort_upload` / `sweep_stale_uploads` / `_fail_job` aynı `update→rmtree→audit` biçimini
  paylaşıyor (Duplicated Code).
- `PostgresStore.get` / `InMemoryStore.get` tek dizge anahtarıyla 3 farklı kaydı
  (Upload/Job/settings) ayırt ediyor; anahtar çakışması yanlış çözüme yol açabilir.
- `_out` (`routes/media.py`) `**status.__dict__` ile pydantic modeli üretiyor; alan adı
  eşleşmesine güveniyor.

Spec ekseni bulguları:
- `upload_id`/`media_id` tasarımda `VARCHAR(36)`/"<uuid>" iken `uuid4().hex` (32 karakter).
- Port imzaları tasarımdan hafif sapıyor: `get(key)` varsayılan almıyor, `claim_next(claimed_at)`,
  `get_by_pk`. Anlamsal olarak eşdeğer.
- Disk koruması aritmetiği `declared + processed.size_bytes`; staging orijinaliyle
  çifte sayım yapıyor (güvenli yön).

## 4. İlgili dokümanlar

- Tasarım: `docs/superpowers/specs/2026-08-15-resumable-upload-media-validation-design.md`
- Plan: `docs/superpowers/plans/2026-08-15-resumable-upload-media-validation.md`
- SDD ilerleme kaydı: `.superpowers/sdd/progress.md`
- Review bulguları + düzeltmeler: issue #7 yorumları
- Issue: #7 (kapatma, /code-review sonrası ayrıca yapılır — açık bırakıldı)