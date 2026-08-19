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

Render işlemini el ile görmek için medya içeren bir aktif paket kurun (yükleme akışı
`#7`'de yapıldı) ve aşağıdaki seam davranışını test edin.

1. **Aktif paketi oluşturun ve logo ayarını koyun** (test ayar deposu üzerinden
   yapılır; bu komutlar `test_render.py`'nin davranışını taklit eder):
```powershell
# Logoyu ayar deposuna yaz (örnek; gerçek değer senin logo yolun)
# Bu adım kod üzerinden yapılır; manuel HTTP ile ayar değiştirilemez.
```

2. **Bir fotoğraf ve bir video yükleyip sonlandırın** (upload API'siyle). Sonlandırma
   ardından ikisi de `order`'a eklenir ve `render_revision` `null` olur.

3. **Preview isteyin** — render job'ı kuyruğa alınır:
```powershell
# Preview, seam/API üzerinden çağrılır; dönen cevap şunları içerir:
#   stale = true | false
#   render_revision = "<sha256-digest>"
```

4. **Worker'ın job'ı işlemesini bekleyin** — `render/reel.mp4` oluşur ve
   `manifest.json` içindeki `render_revision` digest'le dolar.

5. **Manifest'te sonucu doğrulayın**:
```powershell
# Aktif paketin klasöründe manifest.json ve render/reel.mp4 olup olmadığına bak
Get-ChildItem -Recurse -Path "$env:MEDIA_ROOT" -Filter "reel.mp4" | Select-Object FullName, Length
```

6. **Bir düzenleme yapıp bayatlamayı görün** (ör. sıra veya kırpma değiştirin):
```powershell
# Düzenleme sonrası manifest.json içinde render_revision = null olur (render bayat).
# Bir sonraki preview yalnızca bu durumda yeni job üretir.
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