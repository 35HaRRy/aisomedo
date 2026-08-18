# Montaj Sıralama, Video Kırpma ve Süre Sınırı — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #10** (Montage ordering, video trims, and duration limits)
kapsamında yapılan değişiklikleri özetler ve bunları adım adım deneyebilmen için
PowerShell komutlarını gösterir. Tüm komutlar PowerShell'dir; Python kodu içermez.

## 1. Değişiklik Özeti

### Amaç

`Dojo Paylaşım Paketi`'ndeki Reel montajına şu yetenekleri kazandırır:

- **Sıralama (order)** — montaj sırası artık açıkça kaydedilir; yeni yüklenen medya
  sıranın **sonuna eklenir**, sıra elle değiştirilebilir.
- **Kırpma (trims)** — her video için isteğe bağlı `{start, end}` saniye aralığı
  kaydedilebilir; kırpılmayan video tüm süresiyle sayılır. Kırpma yalnız videolara
  uygulanır.
- **Süre sınırı (duration limit)** — kırpılmış sürelerin toplamı limiti aşarsa
  değişiklik **reddedilir** (otomatik kırpma YOKTUR); fotoğraf varsayılan 3.0s,
  video süresi `duration − (end − start)`, limit varsayılan 90.0s.
- **Render bayatlaması** — sıra veya kırpma değişince `render_revision` temizlenir
  (render'ın yeniden üretilmesi gerektiği anlaşılır).

### Yapılanlar (`development` branch, 7 commit)

| Commit | İçerik |
|---|---|
| `4a46e65` | Tasarım dokümanı |
| `0c36210` | Uygulama planı |
| `3f53b9c` | **Süre yakalama** — `PillowFFmpegProcessor._probe_duration` (ffprobe), `StubMediaProcessor(duration=...)`, `finalize_media` video süresini yazar + `render_revision` temizler |
| `08b13ab` | **Modeller ve istisnalar** — `MontageLimits`, `MontageClip`, `MontageStatus` + `MontageOrderInvalid`, `MontageTrimInvalid`, `MontageDurationExceeded`; `dojo/__init__.py` dışa aktarımları |
| `215c8d9` | **Seam** — `get_montage_limits`, `get_montage_status`, `set_order`, `set_trims` (+ `_clip_duration`, `_combined_duration`); `test_montage.py` (16 test) |
| `41eb8db` | **FastAPI rotaları** — `PUT /api/packages/active/order`, `PUT /api/packages/active/trims`, `GET /api/packages/active/montage`; 4 sözleşme testi |
| `bd05be4` | Tasarım dokümanı netleştirme (set_trims reddiyet davranışı) |

### Önemli tasarım kararları

- **Reddet, asla kırpma**: toplam süre limiti aşarsa `set_order`/`set_trims`
  `MontageDurationExceeded` fırlatır ve manifest'e **hiçbir şey yazmaz** (değişiklik
  kalıcı olmaz). Hata mesajı sözleşmesi: `trim or remove {excess:.1f}s`.
- **Sıra kesin permütasyon**: `set_order` sıranın tüm sonlandırılmış (`finalized`)
  medya kimliklerini **tam olarak bir kez** içermesini ister; eksik/tekrar/bilinmeyen
  id → `MontageOrderInvalid`.
- **Kırpma kuralları**: video olmayan hedef → `MontageTrimInvalid`; bilinmeyen id →
  `MediaNotFound`; `0 ≤ start < end ≤ duration` ihlali → `MontageTrimInvalid`.
- **Tamamlanmış paket salt-okunur**: tamamlanmış bir pakete ait medyaya
  `set_order`/`set_trims` ile müdahale → `PackageCompleted` (issue #9 invariant'ı).
- **Veri manifest üzerinde**: yeni DB migration'ı YOK; sıra/kırpma dosya sistemindeki
  `manifest.json` içinde saklanır.
- **Ayarlar**: `montage.max_duration_seconds` (varsayılan 90.0), `montage.photo_duration_seconds`
  (varsayılan 3.0) ayar deposundan okunur.

### HTTP durum kodları

| Senaryo | Kod |
|---|---|
| Sıra/kırpma başarılı | `200` |
| Kimlik doğrulanmamış istek | `401` |
| Aktif paket yok (montage durumu) | `404` |
| Geçersiz sıra / geçersiz kırpma | `422` |
| Süre sınırı aşımı / tamamlanmış paket müdahalesi | `409` |

## 2. Ön Hazırlık

1. **Docker'ı başlatın** (testcontainers ile gerçek PostgreSQL kullanan testler için).
2. **Bağımlılıkları yükleyin** (repo kökünden):
```powershell
uv sync
```

## 3. Test Adımları

### Adım 1: Dojo-core testleri (montaj seam'i)

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_montage.py -v
```

Beklenen (**16 test geçer**):
- `test_video_entry_stores_duration` / `test_photo_entry_has_no_duration` — video
  süresi kaydedilir, fotoğrafta yoktur.
- `test_finalize_clears_render_revision` — yeni yükleme `render_revision`'ı temizler.
- `test_set_order_persists_permutation` / `test_set_order_requires_exact_finalized_set` /
  `test_set_order_rejects_removed_ids` — sıra kalıcıdır; eksik/tekrar/bilinmeyen/kaldırılmış
  id reddedilir (`MontageOrderInvalid`).
- `test_set_trims_persists_and_requires_video` / `test_set_trims_requires_video_duration_known` /
  `test_set_trims_unknown_media_raises` — kırpma kalıcıdır; video-gerekli, aralık
  kuralları, bilinmeyen id (`MediaNotFound`).
- `test_combined_duration_math` — fotoğraf 3.0 + video `10 − (6−1) = 5.0` = **8.0s**.
- `test_over_limit_order_rejected_with_action` / `test_over_limit_trims_rejected_and_unchanged`
  — limit aşımı reddedilir, manifest değişmez.
- `test_order_and_trim_edits_clear_render_revision` — düzenlemeler `render_revision`'ı temizler.
- `test_get_montage_status_reports_over_limit_and_action` — `over_limit` ve `required_action` döner.
- `test_montage_mutation_on_completed_package_raises` — `PackageCompleted`.
- `test_montage_without_active_package_raises` — `NoActivePackage`.

### Adım 2: Backend API testleri (rota sözleşmeleri)

```powershell
uv run --project backend pytest backend/tests/test_api.py -v -k "montage or set_order"
```

Not: `-k montage` yalnız 2 testi seçer; iki `set_order` testi isimde "montage"
içermediği için `-k "montage or set_order"` ile 4 testin tümünü çalıştırın.

Beklenen (**4 test geçer**):
- `test_montage_routes_require_auth` — üç rota da `401`.
- `test_set_order_via_api` — `200`, sıra yankılanır, `over_limit: false`.
- `test_set_order_over_limit_409_via_api` — `409`, detail `trim or remove`.
- `test_get_montage_via_api` — `200`, `combined_duration: 3.0`, 1 clip.

### Adım 3: Tüm paketlerin tam takımları

```powershell
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
```

Beklenen: dojo-core **173 geçer, 2 atlanır**, backend **53 geçer**. (2 atlama
docker/ffmpeg gerekli işleme testleridir; onlar CI'da doğrulanır.)

### Adım 4: Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src/dojo dojo-core/tests/test_montage.py
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend ruff check backend/src/backend backend/tests
uv run --project backend mypy backend/src/backend
```

Beklenen: hepsi temiz. (mypy doğrudan engellenirse `uvx mypy ...` ile deneyin.)

## 4. Manuel Deneme (Uçtan Uca)

Gerçek API davranışını el ile görmek isterseniz: FastAPI uygulamasını başlatın, bir
cihaz eşleştirip token alın, sonra:

1. **Değişkenleri kurun**:
```powershell
$base = "http://localhost:8000"
$token = "<pairing-token>"
$H = @{ Authorization = "Bearer $token" }
```

2. **Aktif paketi oluşturun / montaj durumunu görün**:
```powershell
Invoke-RestMethod -Method Get -Uri "$base/api/packages/active/montage" -Headers $H
```
   - Boş pakette `combined_duration: 0`, `over_limit: false` döner.

3. **Bir fotoğraf ve bir video yükleyip sonlandırın** (upload API'siyle; akış `#7`'de
   yapıldı). Sonlandırma ardından her ikisi de `order`'a eklenir.

4. **Sırayı değiştirin** (ör. iki medya için ters çevirin):
```powershell
$order = @("video-media-id", "photo-media-id")
$body = @{ order = $order } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$base/api/packages/active/order" -Headers $H -ContentType "application/json" -Body $body
```
   - `200`; yanıtta `order`, `combined_duration`, `over_limit` görünür.

5. **Videoyu kırpın** (ör. 1.0s–6.0s):
```powershell
$body = @{ trims = @{ "video-media-id" = @{ start = 1.0; end = 6.0 } } } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Put -Uri "$base/api/packages/active/trims" -Headers $H -ContentType "application/json" -Body $body
```
   - `200`; `combined_duration` video için kırpılmış süreyle hesaplanır.

6. **Süre sınırını düşürüp reddedileni deneyin** (ayar ancak kod üzerinden değiştirilir;
   sıra/kırpma ile tetiklenen `409` davranışını görmek için gerçek süreleri yükleyin):
```powershell
try { Invoke-RestMethod -Method Put -Uri "$base/api/packages/active/order" -Headers $H -ContentType "application/json" -Body $body }
catch { $_.Exception.Response.StatusCode.value__ }
```
   - Limit aşılırsa `409`, `detail` içinde `trim or remove <saniye>s` mesajı döner.

7. **Geçersiz kırpma deneyin** (start >= end):
```powershell
$body = @{ trims = @{ "photo-media-id" = @{ start = 0.0; end = 1.0 } } } | ConvertTo-Json -Depth 5
try { Invoke-RestMethod -Method Put -Uri "$base/api/packages/active/trims" -Headers $H -ContentType "application/json" -Body $body }
catch { $_.Exception.Response.StatusCode.value__ }
```
   - Fotoğrafa kırpma uygulanmaya çalışılırsa `422` döner (kırpma yalnız videoya).

## 5. Git Geçmişi

```powershell
git log --oneline -7
```

```text
bd05be4 docs(spec): clarify set_trims rejects unknown/non-video ids (#10)
41eb8db feat(backend): montage order, trims, and status routes (#10)
215c8d9 feat(dojo-core): montage order, trims, and duration limits (#10)
08b13ab feat(dojo-core): montage models and exceptions (#10)
3f53b9c feat(dojo-core): capture per-clip video duration and clear stale render (#10)
0c36210 docs(plan): montage ordering, trims, duration limits (#10)
4a46e65 docs(design): montage ordering, trims, duration limits (#10)
```

## 6. Known Issues ve Sınırlamalar

- **ffmpeg/docker gerekli**: `_probe_duration` ve video `duration` iddiaları
  (`test_media_processor.py`) gerçek ffmpeg gerektirir; yerelde atlanır (2 skip) —
  CI'da doğrulanmalıdır.
- **Manifest yazımı atomik değildir**: `_write_manifest` doğrudan yazar; işlem
  ortasında çökme manifest'i bozabilir (tasarım kararı, out of scope).
- **Fotoğraf kırpılamaz**: kırpma yalnız videolara uygulanır; fotoğraf süresi
  `photo_duration_seconds` (varsayılan 3.0s) olarak sayılır.
- **Süre sınırı ayarlanabilir**: limit varsayılan 90.0s; `montage.max_duration_seconds`
  ayarı ile değişir. Ayarlar kod üzerinden test edilir, manuel HTTP ile değiştirilemez.
- **Kapsam dışı**: Web UI (#26) ve Android (#32) bu ticket'ta yok. Yükleme akışının
  kendisi `#7`'de yapıldı.
