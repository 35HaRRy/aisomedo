# Medya Kaldırma, Geri Yükleme ve Tamamlanmış Paket Tarama — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #9** (Media removal, restoration, and completed-package
browsing) kapsamında yapılan değişiklikleri özetler ve bunları adım adım
deneyebilmen için PowerShell komutlarını gösterir. Tüm komutlar PowerShell'dir;
Python kodu içermez.

## 1. Değişiklik Özeti

### Amaç

Aktif `Dojo Paylaşım Paketi`'ndeki medyayı kaldırmak Reel'in montaj sırasından
çıkarmalı ama **dosyayı asla silmemelidir**. Kaldırılan medya paket-içi
depoda tutulur, paket aktifken geri yüklenebilir. Paket tamamlandığında içeriği
salt-okunur olur; medya ve render'lar tarayıcıdan görüntülenip indirilebilir.

Bu ticket şunları getirir:

- **Kaldırma (remove)** — `media/<id>/` klasörü `removed/<id>/` altına taşınır,
  manifest girişi `removed` olur, `media_id` `order` listesinden çıkar. Kaynak dosya
  korunur.
- **Geri yükleme (restore)** — `removed/<id>/` `media/<id>/` altına geri taşınır,
  giriş `finalized` olur, `media_id` **orijinal sıradaki konumuna** `order`'a geri
  eklenir.
- **Tamamlanmış paket salt-okunur** — tamamlanan pakete medya eklenemez; kaldırma ve
  geri yükleme tamamlanmış paket üzerinde `409` ile reddedilir.
- **Tarama ve indirme** — tamamlanmış paketler listelenir, içerik görüntülenir ve
  imzalı URL ile indirilir (path-traversal koruması dahil).

### Yapılanlar (tek commit, `development` branch)

| Commit | İçerik |
|---|---|
| `0f2c403` | **`DojoPublishing` seam'i** — `remove_media`, `restore_media` (ortak `_toggle_media`), `list_completed_packages`, `browse_completed_package`, `create_download_url`; `_require_active_package`, manifest yardımcıları |
| `0f2c403` | **İstisnalar** — `PackageCompleted`, `MediaNotFound`, `MediaNotRemovable`, `MediaNotRestorable`; `dojo/__init__.py` dışa aktarımları |
| `0f2c403` | **Depolama katmanı** — `PackageStore`'a `list_completed()`; `InMemoryStore` + `PostgresStore` uygulamaları (`_package_from_row` çıkarıldı) |
| `0f2c403` | **FastAPI rotaları** — `POST /api/packages/active/media/{id}/remove`, `/restore`, `GET /api/packages`, `GET /api/packages/{folder}`, `POST /api/packages/{folder}/download`; ortak hata→HTTP eşlemesi (`_map_mutation_error`) |
| `0f2c403` | **Testler** — dojo-core `test_media_removal.py` (17 test) + backend `test_api.py` sözleşme testleri (14 test) |

### Önemli tasarım kararları

- **Kaldırma dosyayı silmez**: klasör `media/` → `removed/` altına taşınır; dosya
  paket içinde kalır ve tamamlandıktan sonra da indirilebilir.
- **Sıra korunur**: kaldırırken girişe `removed_position` yazılır; geri yüklemede
  medya orijinal konumuna döner.
- **Tamamlanmış paket salt-okunur**: `remove_media`/`restore_media` yalnız aktif
  paket üzerinde çalışır; tamamlanmış bir paketteki `media_id` hedeflenirse
  `PackageCompleted` fırlatılır → HTTP `409`.
- **İndirme güvenliği**: `artifact_ref` çözümlenir, paket klasörünün dışına
  çıkmaya çalışırsa `400` (path-traversal), dosya yoksa `404` döner; URL
  `SignedUrlStore` üzerinden imzalanır.
- **Tarama görünümü**: `browse_completed_package` manifest'ten `media`, `order`,
  `caption`, `render_revision` alanlarını döndürür.

### HTTP durum kodları

| Senaryo | Kod |
|---|---|
| Kaldırma/geri yükleme başarılı | `200` |
| Aktif paket yok / medya yok / paket yok | `404` |
| Kaldırılacak medya zaten `removed` / geri yüklenecek medya `finalized` değil | `409` |
| Tamamlanmış paket medyasına müdahale | `409` |
| İndirmede path-traversal (paket dışına çıkma) | `400` |
| Kimlik doğrulanmamış istek | `401` |

## 2. Ön Hazırlık

1. **Docker'ı başlatın** (testler testcontainers ile gerçek PostgreSQL kullanır):
   - Docker Desktop'ı çalıştırın; PostgreSQL container'ı otomatik açılır.

2. **Bağımlılıkları yükleyin** (repo kökünden):
```powershell
uv sync
```

## 3. Test Adımları

### Adım 1: Dojo-core testleri (kaldırma/geri yükleme/tarama/indirme seam'i)

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_media_removal.py -v
```

Beklenen (17 test geçer):
- `test_remove_media_excludes_from_order_but_keeps_entry` — `order` boşalır, giriş
  `removed`, klasör `removed/` altına taşınır.
- `test_remove_media_preserves_other_media_and_order` — diğer medya ve sırası korunur.
- `test_remove_media_restores_moves_back_and_reappends_to_order` — geri yükleme
  klasörü geri taşır, giriş `finalized`, `order`'a eklenir.
- `test_restore_media_returns_to_original_position` — üç öğe arasından ortadaki
  kaldırılıp geri yüklenince orijinal konuma döner.
- `test_remove_media_unknown_raises` / `test_remove_media_without_active_package_raises` /
  `test_remove_media_already_removed_raises` — `MediaNotFound`, `NoActivePackage`,
  `MediaNotRemovable`.
- `test_restore_media_non_removed_raises` / `test_restore_media_unknown_raises` —
  `MediaNotRestorable`, `MediaNotFound`.
- `test_remove_and_restore_on_completed_package_raises` — `PackageCompleted`.
- `test_list_completed_packages_returns_completed_only` /
  `test_browse_completed_package_returns_manifest_view` / `test_browse_non_completed_or_missing_package_raises`.
- `test_create_download_url_*` — imzalı URL, traversal `ValueError`, dosya yok `MediaNotFound`.

### Adım 2: Backend API testleri (rota sözleşmeleri)

```powershell
uv run --project backend pytest backend/tests/test_api.py -v -k "remove or restore or completed or browse or download or traversal"
```

Beklenen (14 test geçer):
- `test_remove_media_via_api` / `test_restore_media_via_api` — `200`; klasör
  `removed/` ↔ `media/` geçişleri.
- `test_remove_media_not_found_404` — `404`.
- `test_remove_media_on_completed_409` — `409`.
- `test_list_completed_packages` / `test_browse_completed_package` — tamamlanmış paket
  listeleme ve tarama.
- `test_download_completed_artifact` — imzalı URL döner.
- `test_download_artifact_traversal_400` — `400`.
- `test_completed_package_routes_require_auth` — `401`.

### Adım 3: Tüm paketlerin tam takımları

```powershell
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
```

Beklenen: dojo-core **157 geçer, 2 atlanır**, backend **49 geçer**. (Uyarılar
önceden var olan deprecation'lardır: testcontainers.postgres, alembic
path_separator, httpx.)

### Adım 4: Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src/dojo dojo-core/tests/test_media_removal.py
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend ruff check backend/src/backend backend/tests
uv run --project backend mypy backend/src/backend
```

Beklenen: hepsi temiz. (mypy doğrudan engellenirse `uvx mypy ...` ile deneyin.)

## 4. Manuel Deneme (Uçtan Uca)

Gerçek API davranışını el ile görmek isterseniz: FastAPI uygulamasını başlatın, bir
cihaz eşleştirip token alın, sonra:

1. **Aktif paketi oluşturun**:
```powershell
$base = "http://localhost:8000"
$token = "<pairing-token>"
$H = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Method Get -Uri "$base/api/packages/active" -Headers $H
```

2. **Bir fotoğraf yükleyip sonlandırın** (upload API'siyle; isteğe bağlı, `#7`):
   - `POST /api/media/uploads` ile başlat, parça yükle, `complete` çağır.
   - İşleme worker'ı sürer; ardından manifest'e bir `media_id` düşer.

3. **Medyayı kaldırın**:
```powershell
$mediaId = "<media-id>"
Invoke-RestMethod -Method Post -Uri "$base/api/packages/active/media/$mediaId/remove" -Headers $H
```
   - `200 {"status":"removed"}`; `order` artık o `media_id`'yi içermez, dosya silinmez.

4. **Geri yükleyin**:
```powershell
Invoke-RestMethod -Method Post -Uri "$base/api/packages/active/media/$mediaId/restore" -Headers $H
```
   - `200 {"status":"restored"}`; medya orijinal sıraya döner.

5. **Paketi tamamlayın** (bu noktada medya artık salt-okunur):
```powershell
Invoke-RestMethod -Method Post -Uri "$base/api/packages/active/complete" -Headers $H
```

6. **Tamamlanmış paketleri listeleyin ve tarayın**:
```powershell
$completed = Invoke-RestMethod -Method Get -Uri "$base/api/packages" -Headers $H
$folder = $completed[0].folder_name
Invoke-RestMethod -Method Get -Uri "$base/api/packages/$folder" -Headers $H
```

7. **Bir medyayı imzalı URL ile indirin**:
```powershell
$body = @{ artifact_ref = "media/$mediaId/processed.jpg" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/api/packages/$folder/download" -Headers $H -ContentType "application/json" -Body $body
```
   - `{"url":"https://signed.local/..."}` döner.

8. **Tamamlanmış pakete müdahaleyi deneyin**:
```powershell
try { Invoke-RestMethod -Method Post -Uri "$base/api/packages/active/media/$mediaId/remove" -Headers $H }
catch { $_.Exception.Response.StatusCode.value__ }
```
   - `409` döner (aktif paket yeni ve boş; eski medya tamamlanmış pakete aittir).

Not: Manuel akış, oturumda zaten bir aktif paket varsa "tamamla" adımında yeni boş
bir aktif paket oluşturur. Tekrarlayan "yokken oluştur" senaryosu için `tmp_path`
tabanlı testlere güvenin.

## 5. Git Geçmişi

```powershell
git log -1 --oneline
```
- `0f2c403` feat: media removal/restoration and completed-package browsing (#9)

## 6. Known Issues ve Sınırlamalar

- **Postgres gereklidir**: `pg_store` fixture'lı testler gerçek PostgreSQL
  (testcontainers) kullanır; Docker kapalıysa o testler atlanır/başarısız olabilir.
- **Manifest yazımı atomik değildir**: `_write_manifest` doğrudan `write_text`
  kullanır; işlem ortasında çökme manifest'i bozabilir (tasarım kararı, out of scope).
- **Tarama ham manifest alanlarını döndürür**: `browse_completed_package` medya
  girişlerinin `status`, `processed` gibi iç alanlarını olduğu gibi gösterir
  (temizlenmiş/sanitize bir görünüm değildir, minor).
- **Kapsam dışı**: Web UI (#26) ve Android (#32) bu ticket'ta yok. Yükleme akışının
  kendisi `#7`'de yapıldı.
- **Issue #9 açık tutulur**: kapanış /code-review sonrası ayrıca ele alınır.
