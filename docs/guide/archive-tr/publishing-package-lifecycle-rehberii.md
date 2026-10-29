# Aktif Dojo Paylaşım Paketi Yaşam Döngüsü - Test Rehberi

**Issue:** #6 (Active Dojo Paylaşım Paketi lifecycle) - Dojo Reel Publishing MVP (#1) parçası.
**Dal:** `development`

## Özet Değişiklikler

Bu çalışma, tek bir aktif `Dojo Paylaşım Paketi`'nin (klasör + manifest) tüm yaşam
döngüsünü kurar. Altı commit ile tamamlandı:

**1. Manifest şeması ve depo güncellemesi (Task 1) - `ba90c77`:**
- `Manifest` modeli sekiz anahtara büyütüldü: `media`, `order`, `trims`, `caption`,
  `branding`, `render_revision`, `meta`, `recovery` (hepsi boş varsayılanla).
  `to_dict()` artık sekiz anahtarın tamamını üretir.
- `PackageStore` sözleşmesine `update(package) -> Package` eklendi; in-memory ve
  Postgres adapter'larında uygulandı. Postgres tarafı bulunamayan pakette
  `ValueError` fırlatır (`7080df3` düzeltmesi).
- Migration `0004_active_package`: `packages(status) WHERE status='active'`
  üzerinde kısmi unique index (`ix_packages_status_active`).

**2. Yüzey geçişleri (Task 2) - `97c4b57`:**
- `get_or_create_active_package(*, requester=None)` - aktif paket varsa döner,
  yoksa oluşturur.
- `complete_active_package(*, requester=None)` - aktif paketi tamamlar ve
  sonrakini oluşturur. Sıra (kasıtlı, çökme-güvenli): DB satırı önce
  `completed` yapılır → klasör `-completed` olarak yeniden adlandırılır → satır
  `folder_name` ile güncellenir → `package.completed` audit'i → yeni boş paket
  oluşturulur (audit `package.created`). Aktif paket yoksa `NoActivePackage`
  fırlatır.
- Oluşturma, özel `_create_active_package` yardımcısına taşındı.

**3. API yolları (Task 3) - `9ae6dc4`:**
- `GET /api/packages/active` artık paket yoksa oluşturur (404 dönmez).
- Yeni `POST /api/packages/active/complete` - tamamlar ve yeni aktif paketi
  döner; `NoActivePackage` → 404.
- `POST /api/packages/active` aynı kalır (ikinci denemede 409).

**4. Doğrulama (Task 4) + kod incelemesi:**
- `25a2399` - `pg_store` üzerinden `complete_active_package` roundtrip testi
  (tasarım belgesinin şartı) ve `packages.py` son satır yeni satır düzeltmesi.
- Tüm görevler bağımsız incelemelerden geçti; testler gerçek Postgres ile çalışır.

## Ön Hazırlık

1. Docker'ı başlatın (testler testcontainers ile gerçek PostgreSQL kullanır):
   - Docker Desktop'ı çalıştırın (PostgreSQL container otomatik açılır).

2. Bağımlılıkları yükleyin (repo kökünden):
```bash
uv sync
```

## Test Adımları

### Test 1: Depo sözleşmesi - `update()` ve kısmi unique index

```bash
uv run --project dojo-core pytest dojo-core/tests/test_store_package.py -v
```

Beklenen (6 test geçer):
- `test_memory_update_replaces_row` / `test_pg_update_replaces_row` - `update()`
  satırı yerinde değiştirir.
- `test_memory_update_missing_raises_value_error` /
  `test_pg_update_missing_raises_value_error` - bulunamayan pakette `ValueError`.
- `test_pg_partial_unique_index_blocks_second_active_row` - ikinci bir `active`
  satırı engellenir.
- `test_pg_complete_active_package_roundtrip` - tamamlama geçişi gerçek Postgres
  üzerinde uçtan uca çalışır (klasör yeniden adlandırma, yeni aktif paket, audit'ler).

### Test 2: Migration - kısmi unique index şemada var

```bash
uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py::test_alembic_upgrade_head_creates_schema -v
```

Beklenen: `alembic upgrade head` çalışır ve `ix_packages_status_active` index'i
`packages` tablosunda mevcuttur.

### Test 3: DojoPublishing yüzeyi - get-or-create ve tamamlama

```bash
uv run --project dojo-core pytest dojo-core/tests/test_publishing.py -v
```

Beklenen (11 test geçer). Yeni davranış testleri:
- `test_get_or_create_returns_existing_active_package` - aktif paket varsa aynısını
  döner.
- `test_get_or_create_creates_when_absent` - yoksa klasör + manifest + satır
  oluşturur, `package.created` audit'ini `requester` ile yazar.
- `test_complete_active_package_renames_creates_next_and_audits` - klasör
  `06-08-2026 14-30-completed` olur, yeni paket aktif kalır, `get_active()`
  yeni paketi döner, audit sırası `package.created` (yeni) → `package.completed`.
- `test_complete_active_package_without_active_raises` - paket yoksa
  `NoActivePackage`.
- `test_zero_or_one_invariant_after_completion` - tamamlama sonrası tek aktif
  paket kuralı korunur.

### Test 4: API yolları - otomatik oluşturma ve tamamlama endpoint'i

```bash
uv run --project backend pytest backend/tests/test_api.py -v
```

Beklenen (27 test geçer; ilgili beşi):
- `test_get_active_auto_creates_when_absent` - GET ilk istekte oluşturur (200,
  `package.created` audit'i).
- `test_post_active_second_ensure_returns_409` - POST ikinci denemede 409.
- `test_complete_active_returns_next_package` - POST `/api/packages/active/complete`
  yeni paketi döner (200).
- `test_complete_active_without_package_returns_404` - paket yoksa 404.
- `test_packages_require_auth` - kimliksiz istek 401.

### Test 5: Tüm paketlerin tam takımları (son durum)

```bash
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
```

Beklenen: dojo-core **82 geçer**, backend **27 geçer**. (Uyarılar önceden var olan
deprecation'lardır: testcontainers.postgres, alembic path_separator, httpx.)

### Test 6: Lint ve tip kontrolü

```bash
uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend ruff check backend/src backend/tests
uv run --project backend mypy backend/src/backend
```

Beklenen: hepsi temiz. (mypy doğrudan engellenirse `uvx mypy ...` ile deneyin.)

## Manuel Deneme (Uçtan Uca)

Gerçek API davranışını el ile görmek isterseniz: FastAPI uygulamasını başlatın,
bir cihaz eşleştirip token alın, ardından:

1. İlk GET aktif paketi oluşturur:
   `GET /api/packages/active` → 200, `status: "active"`
2. İkinci GET aynı paketi döner (yeni oluşturmaz).
3. POST `/api/packages/active` → 409 (zaten aktif var).
4. POST `/api/packages/active/complete` → 200, yeni paket döner; diskte eski
   klasör `-completed` olarak yeniden adlandırılır.

Not: Bu akış oturum başına bir kez oluşturulur; tekrarlanan "yokken oluştur"
senaryosu için `tmp_path` tabanlı testlere güvenin.

## Git Geçmişi

```bash
git log f87d7f2..HEAD --oneline
```
- `25a2399` test(dojo-core): pg_store roundtrip of complete_active_package; EOF newline
- `9ae6dc4` feat(backend): active package auto-create on GET and completion endpoint
- `97c4b57` feat(dojo-core): get-or-create and complete active package transitions
- `6fc2d04` docs(dojo-core): update() raises ValueError (plan amendment)
- `7080df3` fix(dojo-core): update() raises ValueError on missing package
- `ba90c77` feat(dojo-core): full manifest schema and package update store support

## Known Issues ve Sınırlamalar

- **Postgres gereklidir:** `pg_store` fixture'lı testler gerçek PostgreSQL
  (testcontainers) kullanır; Docker kapalıysa o testler atlanır/başarısız olabilir.
- **Aynı dakika çakışması bilinçli ele alınmaz:** tamamlama anında oluşan yeni
  paket aynı `dd-MM-yyyy HH-mm` adını kullanır; klasör yeniden adlandırıldığı için
  çakışma olmaz, ancak saniye çözünürlüğü eklenmemiştir (tasarım kararı, out of scope).
- **Kapsam dışı:** medya yükleme (#7), markalama (#11), inceleme (#15), yayın (#18),
  CLI tamamlama giriş noktası. İşçi zamanlayıcı tetiklemesi #18'de yapılacak.
- **Issue #6 açık tutulur:** kapanış /code-review sonrası ayrıca ele alınır.

## Kaynaklar

- Tasarım: `docs/superpowers/specs/2026-08-13-active-dojo-paylasim-paketi-lifecycle-design.md`
- Plan: `docs/superpowers/plans/2026-08-13-active-dojo-paylasim-paketi-lifecycle.md`
- İlerleme günlüğü: `.superpowers/sdd/progress.md`