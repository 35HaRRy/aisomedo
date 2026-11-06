# Organizasyon Bazlı Çalışma Alanları Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mevcut veriyi koruyarak aynı PostgreSQL üzerinde organizasyonlara ayrılmış çalışma alanları, organizasyon CLI'sı ve erişim/iş durdurma davranışı sağlamak.

**Architecture:** Organizasyon kapsamı değişmez store nesneleriyle API isteğinden ve worker turundan veri erişimine taşınır. Global store yalnızca organizasyon yönetimi, kimlik bilgisi/kod çözümleme ve altyapı işlemleri içindir; kapsamı olmayan domain sorguları hata verir. Mevcut Python servisleri ve adaptörleri korunur; genel amaçlı tenancy altyapısı eklenmez.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/psycopg, PostgreSQL 18, Alembic, pytest; React/TypeScript/Vitest; PowerShell; mevcut FFmpeg ve Android istemcisi.

**Spec:** `docs/superpowers/specs/2026-11-04-organization-tenancy-design.md`

## Global Constraints

- Ortak veritabanı kullanılacak.
- Organizasyon adı ve e-posta zorunlu, telefon isteğe bağlı olacak.
- İlk organizasyon: `Kaizen Aikido Akademi`, `kaizenaikidoakademi@gmail.com`, telefon boş, aktif.
- Organizasyon silme, organizasyonlar arası taşıma, çoklu üyelik, organizasyon seçici ekran ve yönetim paneli kapsam dışı.
- Mevcut paket kimlikleri, dosya referansları, istemci kimlikleri ve hash'lenmiş kimlik bilgileri korunur.
- Her kimlik doğrulamada organizasyonun aktifliği kontrol edilir.
- Bekleyen iş ve içerikler silinmez; pasif organizasyon işleri otomatik yeniden başlamaz. Yeniden aktifleştirme komutu bu talebin kapsamında değildir.
- Karışık eski/yeni süreçlerle çalışma desteklenmez; canlı veritabanına kendiliğinden migration uygulanmaz.
- Yeni bağımlılık, RLS altyapısı veya genel amaçlı tenancy framework'ü eklenmez.
- Bu planın ara commit'leri dağıtılabilir sürümler değildir; dağıtım tüm test ve son inceleme sonrasında yapılır.

## Review Focus

1. Aynı dakikada iki organizasyonun paket oluşturması: hem DB tekilliği hem dosya yolu hem advisory lock birbirinden bağımsız olmalı (Task 2 ve 4).
2. Kimlik doğrulama ile canlı bağlantı kaydı arasındaki pasifleştirme: açık bağlantı elde edilememeli (Task 5).
3. FFmpeg veya Instagram çağrısı sırasında pasifleştirme: çıktı yayınlanmamalı, belirsiz gönderim yeniden gönderilmemeli (Task 6).
4. Paralel isteklerde organizasyon kapsamı: bir isteğin kapsamı diğerine taşmamalı; OAuth callback ve imzalı URL bu sınırı aşmamalı (Task 4).
5. Eski verili yükseltme ve yeni DB aynı sonuca ulaşmalı: cookie/bearer hash'leri, global politika ve medya yolları korunmalı (Task 1 ve 7).

## Dosya ve sorumluluk haritası

- `dojo-core/src/dojo/organizations.py` (yeni): organizasyon doğrulaması, ad normalizasyonu, yönetim ve aktiflik kontrolü.
- `dojo-core/src/dojo/model.py`, `ports.py`, `exceptions.py`, `__init__.py`: model/port/hata/export değişiklikleri.
- `dojo-core/src/dojo/adapters/db.py`, `memory.py`: sabit kapsamlı store, sahiplik filtreleri, ilişki kontrolleri, global yönetim işlemleri; mevcut büyük adaptörleri sırf bu iş için bölme.
- `dojo-core/migrations/versions/0022_organizations.py` (yeni), `schema_checks.py`: şema/backfill/anahtarlar ve eski şema uyumu. Uygulamaya başlarken migration head'ini tekrar kontrol et; 0022 alınmışsa sonraki numarayı kullan.
- `dojo-core/src/dojo/pairing.py`, `setup.py`, `activity.py`, `meta_connection.py`, `publishing.py`, `branding_assets.py`: organizasyon sahipliği ve aktiflik sınırları.
- `dojo-core/src/dojo/live.py`, `scheduler.py`, `adapters/meta.py`, `adapters/render.py`, `adapters/media.py`, `adapters/preview_process.py`, `adapters/signed_urls.py`: olay/kilit ayrımı, iptal ve dış servis sınırları.
- `backend/src/backend/organizations.py` (yeni): istek için sabit kapsamlı servisleri mevcut bağımlılıklardan kuran küçük fabrika.
- `backend/src/backend/deps.py`, `main.py`, `live.py`, `snapshots.py`, `routes/*.py`: kimlikten kapsam, global endpoint istisnaları, canlı olay yönlendirme; etkilenen route bağımlılıkları birlikte güncellenir.
- `backend/src/backend/cli.py`, `backend/pyproject.toml`: organizasyon komutları ve tüm organizasyon yazan CLI'larda zorunlu seçim.
- `worker/src/worker/main.py`, `monitoring.py`, `dojo-core/src/dojo/monitoring.py`: aktif organizasyon turu ve bildirim ayrımı; süreç sağlığı global kalır.
- `ops/start-local.ps1`, `connect-instagram.ps1`, `acceptance/bootstrap.py`, `acceptance/run.py`, `backend/scripts/seed_completed_package.py`: açık organizasyon seçimi; diğer izlenen CLI çağırıcıları da güncellenir.
- `web/src/components/PairingForm.tsx`, `web/src/promotion/LandingPage.tsx`, `web/src/i18n/tr.ts`, `web/src/demo/{seed,runtime,api}.ts`: sade organizasyon metinleri ve demo uyumu.
- `README.md`, `docs/guide/getting-started.md`, `docs/guide/windows-local-setup.md`: CLI, yükseltme ve pasifleştirme açıklamaları.
- `backend/openapi.json`, `web/src/api/openapi.ts`, `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`: yalnızca mevcut üreteçlerden güncellenir.

## Task 1: Organizasyon modeli ve veri taşıma

**Files:** Yukarıdaki model/port/hata/export, yeni `organizations.py`, DB satır modelleri, migration ve `schema_checks.py`; yeni `dojo-core/tests/test_organizations.py`, `test_organization_migration.py`; mevcut `test_schema_init.py`, `conftest.py`.

**Interfaces:**
- `Organization(id: int, name: str, email: str, phone: str | None, active: bool)`.
- `organization_name_key(name: str) -> str`: `unicodedata.normalize('NFKC', name.strip()).casefold()`; boş ad reddedilir. Gösterilen ad trimlenir; key ayrı, unique kolonda saklanır.
- `OrganizationStore`: `create_organization(name: str, name_key: str, email: str, phone: str | None) -> Organization`, `find_organization(organization_id: int) -> Organization | None`, `find_organization_by_name_key(name_key: str) -> Organization | None`, `list_organizations(*, active_only: bool = False) -> list[Organization]`, `deactivate_organization(organization_id: int) -> None`.
- `DojoOrganizations(store: OrganizationStore)`: `create(*, name: str, email: str, phone: str | None = None) -> Organization`, `require_name(name: str, *, active: bool = True) -> Organization`, `list(*, active_only: bool = False) -> list[Organization]`, `deactivate(name: str) -> None`, `require_active(organization_id: int) -> Organization`.
- Hatalar: `OrganizationInvalid`, `OrganizationNotFound`, `OrganizationInactive`, `OrganizationNameTaken`.

- [ ] **1. Red:** `test_organizations.py` içinde zorunlu/boş ad ve e-posta, geçersiz e-posta, boş telefon, normalize edilmiş yinelenen ad ve idempotent pasifleştirme testleri yaz. Mevcut yüklü e-posta doğrulayıcı kullanılabilir; yeni bağımlılık ekleme. `test_organization_migration.py` içinde 0021 verili DB'den yükseltmede `org.name == 'Kaizen Aikido Akademi'`, `org.email == 'kaizenaikidoakademi@gmail.com'`, `org.phone is None`, eski client hash/id ve package folder değişmemiş assert'lerini ekle.
- [ ] **2. Fail check:** `uv run --project dojo-core pytest dojo-core/tests/test_organizations.py dojo-core/tests/test_organization_migration.py -q`; yeni API/şema olmadığı için başarısız olmalı; ortam hatasını red sayma.
- [ ] **3. Implement:** Organizasyon API'sını DB ve bellek adaptörlerine ekle. Migration'da `organizations` tablosunu ve kök tablolara NOT NULL/FK/index organizasyon alanlarını backfill sonrası ekle. Açık alan envanteri: `packages`, `audit_events`, `pairing_codes`, `clients`, `uploads`, `jobs`, `settings`, `yayin_zamani`, `yayin_incelemesi`, `meta_connections`, `meta_oauth_attempts`, `consent_acceptances`, `live_resource_versions`, `live_change_events`. Bağımlı `package_states` ve `push_registrations` sahipliği FK üzerinden türetilir. Organizasyon sütunu olan ilişkilerde üst kaydın da aynı organizasyona ait olmasını birleşik FK/unique ile koru.
- [ ] **4. Implement constraints:** `settings` PK `(organization_id, key)`, `live_resource_versions` PK `(organization_id, resource)`, `meta_connections` organizasyon başına tek bağlantı, consent acceptance unique `(organization_id, policy_version)` yap. Global consent policy metni/sürümleri global kalır; kabul organizasyon başınadır. Paket, yayın zamanı ve actionable inceleme partial unique index'lerine organizasyon ekle. Global UUID/hash ve mevcut folder tekilliği korunur. `operational_alerts.organization_id` nullable olsun: disk uyarısı global, iş hatası ilgili organizasyona ait; eski job alert'lerini Kaizen'e bağla. Çok organizasyonlu downgrade'i açık hata ile reddet; içerik silerek geri dönüş yapma.
- [ ] **5. Green:** Task komutunu ve `uv run --project dojo-core pytest dojo-core/tests/test_schema_init.py -q` çalıştır. Boş DB yükseltmesini de test et; politika ve mevcut onay geçerliliğini doğrula. PostgreSQL test fixture'ları her test için organizasyonları açıkça oluşturup scoped store döndürecek şekilde güncellensin; registry ayrı erişilebilir olsun.
- [ ] **6. Commit:** Yalnızca Task 1 dosyalarını stage et; `git commit -m "feat: add organizations and migrate existing ownership"`.

## Task 2: Store kapsamı ve bütün veri erişimlerinin izolasyonu

**Files:** `adapters/db.py`, `adapters/memory.py`, `model.py`, `ports.py`, `testing.py`; yeni `dojo-core/tests/test_organization_store.py`; mevcut store ve setup testleri/fixture'ları.

**Interfaces:**
- `PostgresStore(url: str, *, organization_id: int | None = None)`; `for_organization(organization_id: int) -> PostgresStore`, `organization_id` read-only property. Scoped kopya aynı engine/pool'u kullanır; context/transaction state farklı scope arasında paylaşılmaz; engine yalnızca sahibi tarafından dispose edilir.
- `InMemoryStore.for_organization(organization_id: int) -> InMemoryStore`: aynı registry ve global sayaçlardan türeyen, ayrı domain state'li görünüm; farklı organizasyonlarda id çakışması üretme.
- `OrganizationScopeRequired` kapsam olmadan domain sorgusunu reddeder. Registry, global politika, credential/code çözümleme, global monitoring/listener işlemleri açık istisnalar; evrensel filtresiz domain listeleme ekleme.
- `Client` ve `PairingCode` zorunlu `organization_id: int` taşır. Diğer domain modellerine yalnızca scope dışına taşındıkları yerlerde ihtiyaç varsa alan ekle; sahipliği iş payload'ına güvenerek kurma.

- [ ] **1. Red:** `test_organization_store.py` içinde `test_two_active_packages_and_settings_are_independent`, `test_foreign_ids_cannot_read_update_or_delete`, `test_unscoped_domain_access_fails`, `test_cross_organization_relations_are_rejected` testlerini hem bellek hem PostgreSQL için yaz. Eşzamanlı aynı tarihli plan/inceleme, settings upsert, upload/job get/update, consent, Meta, audit, notification ve kilit yollarını parametrize et. `a.get(...)` hiçbir koşulda B kaydı döndürmemeli; B state'i yanlış yazmadan sonra değişmemeli.
- [ ] **2. Fail check:** `uv run --project dojo-core pytest dojo-core/tests/test_organization_store.py -q`.
- [ ] **3. Implement:** Her store metodu için select/get/update/delete/upsert/raw SQL envanteri çıkarıp organizasyon filtresini uygula; PK ile get yapan yolları da atlama. Yeni kayıtlarda organization_id store'dan gelir. İlişkili kayıt ataması öncesi sahipliği denetle; DB kısıtları ikinci güvenlik katmanıdır. Paket/emission kilitlerini sabit namespace + organization_id ile ayır. Mevcut transaction/error handling korunur; otomatik ORM filtresiyle bulk/raw SQL'in de kapsandığını varsayma.
- [ ] **4. Green:** Yeni testleri, `uv run --project dojo-core pytest dojo-core/tests -q` komutunu çalıştır; yeni scope sözleşmesinin kırdığı tüm mevcut test/fixture çağırıcılarını açık organizasyona geçir. Başka organizasyonun kısıtından gelen conflict'i kendi kaydıymış gibi kurtarma.
- [ ] **5. Commit:** `git commit -m "feat: isolate domain stores by organization"` (önce yalnızca ilgili dosyaları stage et).

## Task 3: Pairing, oturum ve organizasyon CLI'sı

**Files:** `pairing.py`, `backend/src/backend/cli.py`, `backend/pyproject.toml`, `backend/src/backend/routes/pairing.py`; `dojo-core/tests/test_pairing.py`, `backend/tests/test_cli.py`; yeni `backend/tests/test_organization_cli.py`.

**Interfaces:**
- `DojoPairing.create_pairing_code(*, requester: str, organization_id: int) -> PairingCodeIssued`.
- Pairing registry ile global credential/hash lookup yapar; validate edilen kodun organizasyonunu zorunlu aktiflik kontrolünden sonra scoped store ile kullanır.
- `DojoPairing.list_clients(*, organization_id: int) -> list[Client]`; `revoke_client(*, client_id: int, requester: str, organization_id: int) -> None`. Auth sonucu `Client.organization_id` taşır; pasif organizasyonda `None` döner.
- Yeni entrypoint `dojo-organizations = backend.cli:organizations_main`; subcommands `create --name ... --email ... [--phone ...]`, `list`, `deactivate --name ...`. Mevcut `dojo-create-pairing-code create-code --organization "..."` zorunlu olur. `mint_code(pairing: DojoPairing, *, organization_id: int) -> PairingCodeIssued`.
- `dojo-settings`, `dojo-render` ve acceptance dışındaki organizasyona yazan diğer komutlar `--organization` zorunlu alır. `dojo-consent set-policy` global kalır; bunu yardım/dokümanda açıkla.

- [ ] **1. Red:** `test_organization_cli.py` içinde create/list/deactivate başarılarını, alan/ad çakışması hatalarını ve eksik/bilinmeyen/pasif `--organization` ile kod çıkmadığını test et. Pairing testlerine koddan doğru sahiplik, pasifleştirmeden önce üretilen kodun reddi, mevcut cookie/bearer erişim reddi, cross-org client iptalinin `ClientNotFound` vermesi ekle. Kod tüketimi yarışında yalnızca bir istemci oluşmalı.
- [ ] **2. Fail check:** `uv run --project backend pytest backend/tests/test_cli.py backend/tests/test_organization_cli.py -q`; `uv run --project dojo-core pytest dojo-core/tests/test_pairing.py -q`.
- [ ] **3. Implement:** Global pairing hash lookup'u ile kod tüketimi/istemci oluşturmayı aynı organizasyon doğrulamalı transaction'da yap; pasifleştirme yarışında kod/credential yaratılmasın. CLI ad çözümlemesi ortak organizasyon servisini kullansın; validation hatası sıfır olmayan exit code ve güvenli mesaj versin. API'deki kod üretimi ve client işlemleri requester organizasyonunu kullansın.
- [ ] **4. Green:** Aynı komutları çalıştır; list çıktısında token/hash bulunmadığını assert et.
- [ ] **5. Commit:** `git commit -m "feat: bind pairing and management commands to organizations"`.

## Task 4: API servis kapsamı, medya yolları ve dış callback'ler

**Files:** `backend/src/backend/organizations.py`, `deps.py`, `main.py`, `snapshots.py`, tüm tenant route bağımlılıkları; `publishing.py`, `branding_assets.py`, `meta_connection.py`, `adapters/signed_urls.py`; yeni `backend/tests/test_organization_isolation.py`; mevcut medya/Meta/branding/publication testleri.

**Interfaces:**
- `OrganizationServices` frozen dataclass: `organization_id`, `publishing`, `setup`, `activity`, `meta`.
- `build_organization_services(organization_id: int) -> OrganizationServices`: mevcut yapılandırma ve ortak engine'den, tüm portları aynı scope'a bağlı servisler kurar. Request başına dependency sonucu tekrar kullanılır; uygulama-global nesnenin scope'u mutate edilmez.
- `get_organization_services(request: Request, client: Client = Depends(get_current_client)) -> OrganizationServices`; route'lardaki mevcut `get_publishing/get_setup/...` bu bundle'dan alır. Snapshot sürüm okuma da aynı scope'u kullanır.
- OAuth callback kapsamı tek kullanımlık doğrulanmış state/attempt'ten, signed fetch kapsamı doğrulanmış tokenın package referansından çözülür; query/body/header'da serbest organization_id güvenilir sayılmaz.

- [ ] **1. Red:** `test_organization_isolation.py` içinde iki oturumun paralel dashboard/settings/package/upload/branding/activity isteklerini karıştır; her yanıt yalnızca kendi verisini içersin. Başkasının id/folder/asset/review/job kimliğiyle erişim `404` vermeli. OAuth state manipülasyonu bağlantıyı değiştirmemeli; imzalı token değiştirilince medya dönmemeli; geçerli eski token referansları çalışmalı.
- [ ] **2. Fail check:** `uv run --project backend pytest backend/tests/test_organization_isolation.py -q`.
- [ ] **3. Implement:** Scope bağımlılıklarını ve boot-time repair'i değiştir; repair aktif organizasyonlarda açık scope ile çalışsın. Yeni package/branding yolları `organizations/{organization_id}/...` altında üretilsin; `folder_name` için DB String(64) sınırını ve kullanıcıya gösterilen ad/paket tarihi ayrımını koru. Kaizen'in eski yolları değiştirilmesin; erişim gerçek sahiplik/manifest/asset kaydı üzerinden sınırlandırılsın, yalnızca yol prefix'ine güvenilmesin. Dosya yolunda traversal/symlink kontrollerini koru.
- [ ] **4. Implement callback gates:** Callback attempt ve signed token doğrulanmadan scope alma; pasif organizasyonda OAuth bağlantısı güncelleme. Pasif organizasyonun signed medya erişimini reddet; zaten başlamış dış yayının sonucu için mevcut uncertain state'i koru. Eski token formatında yalnızca imza doğrulandıktan sonra global unique package folder'dan sahibi bul; tüm organizasyonların dosyalarını tarama.
- [ ] **5. Green:** Yeni test + backend'in tüm testleri: `uv run --project backend pytest backend/tests -q`. Fixture injection'ı scope-aware yap; testsiz varsayılan Kaizen fallback'i ekleme.
- [ ] **6. Commit:** `git commit -m "feat: scope API services and media access to organizations"`.

## Task 5: Canlı olaylar ve bildirim alıcılarının ayrımı

**Files:** `dojo-core/src/dojo/live.py`, DB/bellek change-event metotları; `backend/src/backend/live.py`, `routes/events.py`, `snapshots.py`; `dojo-core/src/dojo/monitoring.py`, `worker/src/worker/monitoring.py`; `backend/tests/test_live_events.py`, `test_live_integration.py`; yeni `dojo-core/tests/test_organization_notifications.py`.

**Interfaces:**
- `ChangeEvent.organization_id: int` (zorunlu); subscriber client id yanında organizasyon id tutar.
- `LiveHub` tek process listener kalır; bildirim yalnızca event'in organizasyonuna fan-out edilir. `deactivate_organization` aynı transaction'da ilgili organizasyonun erişim sonlandırma olayını yayımlar; event commit öncesi teslim edilmez.
- Disk ölçümü/incident'i global kalır; global disk uyarısı yalnızca aktif organizasyonlardaki aktif cihazlara gider. Job failure alert yalnızca job organizasyonuna; retry gönderimi de güncel aktifliği tekrar denetler.

- [ ] **1. Red:** `test_live_integration.py` içinde `test_deactivation_between_auth_and_subscribe_cannot_open_stream`, `test_deactivation_closes_only_its_organization_streams`, `test_other_organization_changes_do_not_reach_stream` yaz. Bildirim testlerinde A'nın job hatasının B'ye gitmediğini, pasif organizasyona yeni/retry push gitmediğini ve global disk uyarısının aktif alıcılarla sınırlı olduğunu assert et.
- [ ] **2. Fail check:** `uv run --project backend pytest backend/tests/test_live_events.py backend/tests/test_live_integration.py -q`; `uv run --project dojo-core pytest dojo-core/tests/test_organization_notifications.py -q`.
- [ ] **3. Implement:** Source version key/okuma ve subscriber yönlendirmesini organizasyona bağla. Başlangıç registration yarışını existing generation/revocation garantileriyle aynı şekilde fence et. Stream kopup yeniden bağlandığında aktiflik tekrar doğrulanır; kalp atışı DB polling'e çevrilmez. Monitoring snapshot ve delivery claim/update yollarında alıcı sahipliği/aktifliği kontrol edilir.
- [ ] **4. Green:** Aynı komutlar ile mevcut live/monitoring testlerini çalıştır; listener restart, rollback, overflow ve credential gizliliği garantileri korunmalı.
- [ ] **5. Commit:** `git commit -m "feat: isolate live events and notification delivery"`.

## Task 6: Aktif organizasyon worker turları ve çalışan işlerin iptali

**Files:** `worker/src/worker/main.py`, `dojo-core/src/dojo/publishing.py`, `scheduler.py`, `adapters/{meta,render,media,preview_process}.py`, gerekli port imzaları; yeni `worker/tests/test_organization_worker.py`, `dojo-core/tests/test_organization_cancellation.py`; mevcut worker tick/render/publication testleri.

**Interfaces:**
- `build_publishing(organization_id: int) -> DojoPublishing`, `build_meta(organization_id: int) -> object | None` worker tarafında explicit scope alır; ana döngü her tur aktif organizasyonları listeler. Her organizasyon için mevcut `run_tick(publishing, meta)` sözleşmesi korunur; başka organizasyonun hatası kalan turları kesmez.
- `DojoPublishing` ve `HttpMetaPublisher` aktiflik kontrolüne aynı registry üzerinden erişir; `require_active` başarısızsa yeni yan etki başlamaz. `ReelRenderer`/media processor ihtiyaç duyulan uzun işlemlerde `cancelled: Callable[[], bool]` alır; mevcut iptal callback'leri ile OR birleşir.
- Mevcut `run_preview_process` poll aralığı 0.25 saniye, terminate grace 2 saniye korunur. Render cancellation callback'i DB aktifliğini en çok saniyede bir yeniden okur, ilk kontrol hemen yapılır; kontrol hatası iptal sayılır. Yeni dış yan etki öncesi kontrol cache'siz yapılır.

- [ ] **1. Red:** Worker testinde A pasif/B aktif olsun: A scheduler/claim/Meta maintain/reconcile/reminder/sweep/repair çağrısı almamalı, B çalışmalı. Sıralı fake clock ile aktif listelemeden sonra pasifleştirmeyi de test et; scoped claim yalnızca aktif organizasyondan iş almalı.
- [ ] **2. Red:** `test_organization_cancellation.py` içinde çalışan fake subprocess'i pasifleştirmede terminate et; çıktı kabul edilmesin, job tekrar claim edilebilir processing durumda kalmasın ve kullanıcı/medya silinmesin. Render iptalinde job `cancelled`, error_reason `organization_inactive` olsun; normal render failure alert'i oluşturulmasın. Kuyruktaki işler queued kalabilir, pasifken alınmaz.
- [ ] **3. Red:** Instagram test double'ında container oluşturma ile publish arasına pasifleştirme yerleştir; publish çağrısı sıfır olmalı. Publish zaten dışarı gönderildiyse yanıt gelmediğinde uncertain durumu korunmalı ve otomatik ikinci publish çağrısı olmamalı. DB aktiflik kontrolü hatasında da yan etki başlamamalı.
- [ ] **4. Fail check:** `uv run --project worker pytest worker/tests/test_organization_worker.py -q`; `uv run --project dojo-core pytest dojo-core/tests/test_organization_cancellation.py -q`.
- [ ] **5. Implement:** Worker wiring, scoped atomic claim, tüm uzun FFmpeg yollarının iptali ve output commit öncesi aktiflik fence'i. Upload processing/thumbnail/section preview dahil subprocess yollarını envantere ekle. Meta create-container/publish/token-refresh ve notifier send öncesi kontrol et; bütün render/HTTP boyunca DB lock tutma. İptal işlemi yalnızca sahip olduğu geçici dosyaları temizler, eski başarılı render'a dokunmaz. Pasifleştirmeden önce kabul edilmiş credential/işlerin sonraki kontrollerinde registry durumu kullanılır, uzun ömürlü aktiflik cache'i yoktur.
- [ ] **6. Green:** Yeni testler + `uv run --project worker pytest worker/tests -q` ve render/review/publication/preview regresyon testleri. Gerçek subprocess testinde iptal callback'inden sonra en fazla mevcut terminate grace + poll toleransı kadar süre tanı; wall-clock yarışına bağlı `sleep` testleri yerine barrier kullan.
- [ ] **7. Commit:** `git commit -m "feat: stop inactive organization sessions and background work"`.

## Task 7: CLI çağırıcıları, demo/metinler, sözleşmeler ve yükseltme rehberi

**Files:** Haritadaki ops/script/web/docs dosyaları; `ops/tests/start-local.Tests.ps1`, `ops/tests/test_acceptance.py`, `web/src/demo/*.test.ts`, `web/src/promotion/LandingPage.test.tsx`, pairing form testleri; OpenAPI üretilen dosyaları ve etkilenen Android test fixture'ları.

**Interfaces:**
- Local starter'a `-OrganizationName` parametresi: varsayılan `Kaizen Aikido Akademi`; çağrılan pairing/ayar/seed CLI'ına daima açık `--organization` iletilir. Python CLI'da default organizasyon yoktur.
- Demo verileri mevcut seed çalışma alanının organizasyonunu tutarlı gösterir; pairing/demo hiçbir gerçek organizasyon listesini anonim kullanıcıya açmaz.
- HTTP `ClientOut` içine `organization_id: int` eklenir; yeni zorunlu DTO alanının tüm mock/Android fixture'ları güncellenir. Token/cookie formatı değişmez. Başka DTO alanı yalnızca gerçek gereksinim varsa eklenir.

- [ ] **1. Red:** Pester testinde starter'ın boş organization adını reddettiğini, belirtilen adı quoting bozulmadan CLI'a ilettiğini assert et. Web pairing testi organizasyona ait kod gerektiği metnini, landing/demo testleri organizasyon anlatımını doğrulasın. Demo seed/client mock'ları organization_id taşımalı; anonim list endpoint'i bulunmamalı.
- [ ] **2. Fail check:** `npm test -- --run` (`web/`); `Invoke-Pester -Path ops/tests/start-local.Tests.ps1` (Pester varsa). Eksik Pester/Docker/SDK kurulumunu kendiliğinden üretim ortamı değiştirerek çözme; raporla.
- [ ] **3. Implement:** Yalnızca gerekli metin/demo/shell çağırıcı değişikliklerini yap; görsel yeniden tasarım yok. İzlenen dosyalarda `dojo-create-pairing-code`, `mint_code`, `PostgresStore(` ve `create_pairing_code(` çağırıcılarını tara ve gereken scope argümanlarını tamamla. Gerçek db-data/media-data ve `docs/linkedin.md` gibi ilgisiz kullanıcı dosyalarına dokunma.
- [ ] **4. Generate:** `uv run --project backend python backend/scripts/export_openapi.py`; `uv run --project backend python backend/scripts/generate_clients.py`. Üretilen dosyaları elle düzenleme. Existing check script'in CLI yardımını okuyup uygun base ile compatibility kontrolünü çalıştır; değişiklik sadece ClientOut alanıysa Android parsing/mock'larını uyumlu tut.
- [ ] **5. Document:** README ve rehberlere create/list/deactivate, `create-code --organization "Kaizen Aikido Akademi"`, adsız/epostasız hata, pasifleştirmenin mevcut oturumlara etkisi ve yeni organizasyonun bağımsız setup gereksinimini yaz. Yedek → API/worker durdurma → mevcut `python -m dojo.schema` şema yükseltme → yeni süreçleri başlatma sırasını, eski medyanın korunduğunu ve dış servise gönderilmiş isteğin geri alınamayacağını belirt.
- [ ] **6. Green:** `npm run typecheck`, `npm test`, `npm run build`, `npm run test:browser` (`web/`); ilgili Pester/ops tests ve Android unit tests (`android/` altında `./gradlew.bat testDebugUnitTest`, SDK varsa). Yeni DB ile local startup ve eski schema fixture'ından migration testini tekrar çalıştır.
- [ ] **7. Commit:** `git commit -m "docs: update organization commands and onboarding flows"`.

## Son doğrulama ve teslim

- [ ] `uv run --project dojo-core pytest dojo-core/tests -q`.
- [ ] `uv run --project backend pytest backend/tests -q`.
- [ ] `uv run --project worker pytest worker/tests -q`.
- [ ] `uv run --group dev ruff check dojo-core/src backend/src worker/src` ve repodaki CI typecheck komutlarını çalıştır; yeni hataları düzelt, ilgisiz kullanıcı değişikliklerini geri alma.
- [ ] Web/ops/Android kontrollerini Task 7 komutlarıyla kaydet; çalıştırılamayanları geçti sayma.
- [ ] `git diff --check`; izlenen değiştirilmiş dosya/CLI çağırıcı envanterini ve organizasyonsuz store istisnalarını son kez denetle.
- [ ] Son bağımsız inceleme: çapraz organizasyon sorguları, bulk SQL/upsert, OAuth/signed URL sınırları, canlı bağlantı yarışları, FFmpeg iptali ve belirsiz Meta gönderimi üzerine odaklan. Kritik bulguları düzelt ve ilgili testleri tekrar çalıştır.
- [ ] Kullanıcıya değişiklikleri, gerçek çalıştırılmış kontrolleri, migration/dağıtım sırasını ve dış servis iptal sınırını bildir. Canlı migration/deploy yapma.

## Plan öz incelemesi

- [x] Spec kapsamı: model/migration (1), veri ayrımı (2), pairing/CLI (3), HTTP/dosya/Meta (4), live/push (5), pasifleştirme/worker (6), doküman/demo/ops/sözleşme (7).
- [x] Önce test, beklenen başarısızlık, minimal uygulama ve green komutları her task'ta var.
- [x] Kapsam kimliği `organization_id`, ad seçimi `--organization`; istemci/kod API'ları ile fixture'lar aynı sözleşmeyi kullanır.
- [x] Beş Review Focus maddesi sahip task'larda testle karşılanır.
- [x] Politika global/onay organizasyona özel kararı net; migration geri dönüşü veri silmez; yeni tenancy bağımlılığı yok.

## Uygulama kaydı

Uygulama `feature/organization` dalında yapıldı. Yukarıdaki adımlar özgün planı korur; gerçek çalıştırma ve plan sapmaları aşağıdadır. Canlı migration, deployment, push veya merge yapılmadı. `docs/linkedin.md` kapsam dışında bırakıldı.

### Uygulayıcı kararları ve bedelleri

1. Kullanıcının seçtiği dal mevcut checkout'ta kullanıldı; ek worktree oluşturulmadı. Bedel: fiziksel çalışma alanı izolasyonu yok.
2. Windows'ta Unix task scriptleri yerine PowerShell komutları ve Markdown ledger kullanıldı. Bedel: ilerleme kaydı elle tutuldu.
3. Şema/store/API değişiklikleri birlikte geliştirildi ve tek entegrasyon commit'inde toplanacak; ara sürümler dağıtılabilir değil. Bedel: commit geçmişi task başına ayrılmadı.
4. ORM SELECT/UPDATE/DELETE savunması SQLAlchemy scope filtresini kullanır; Core insert/upsert ve registry istisnaları açıkça işlendi. Bedel: gelecekteki raw/Core sorguların sahiplik filtresi ayrıca denetlenmeli.
5. Henüz kaydedilmemiş Client/PairingCode sahibi `0`; scoped store gerçek pozitif sahibi yazar ve döndürür. Bedel: kaydedilmemiş modeller doğrudan kimlik doğrulama/yanıta taşınmamalı.
6. Paket klasör adı ve render-job tekilliği organizasyona özeldir. İlk organizasyon `id=1` mevcut medya kökünü korur; diğerleri `organizations/<id>` kullanır. Bedel: bütün servis fabrikaları aynı kök hesaplamasını kullanmalı; ayrılmış `organizations` ve gizli dizinler paket onarımına dahil edilmez.
7. Yapılandırılmış imzalı URL'ler organizasyon/yol/son kullanma içeren HMAC token kullanır; iptal bilgisi mevcut ortak medya volume'ünde yalnızca token hash'i olan marker dosyasında paylaşılır. Bedel: çok küçük iptal dosyaları birikir; hacim büyürse ancak maksimum token ömründen sonra temizlenmeli. Bellek tabanlı eski format dependency-injected test adaptörlerinde korunur.
8. Bağımsız inceleme PostgreSQL yarışlarını ve bütün symlink kombinasyonlarını ayrıca çalıştırmadı. Gerçek PostgreSQL suite'leri bu oturumda çalıştırıldı; kapsamlı adversarial filesystem veya canlı dış servis doğrulaması iddia edilmez.
9. Acceptance seed'in eski mint_code çağrısı incelemede minor olarak raporlandı; acceptance akışını durdurduğu için important sayılıp düzeltildi. Ertelenmiş inceleme bulgusu yok.

### Bağımsız inceleme düzeltmeleri

Her bulgu önce başarısız olan regresyon testiyle yeniden üretildi, sonra düzeltildi:

- Organizasyon 1'in recovery işlemi diğer organizasyonların medya ağacını taşımıyor.
- Thumbnail/section-preview sonucu aktiflik transaction'ından geçmeden diske/manifest'e eklenmiyor.
- Worker'da iptal edilmiş imzalı URL bağımsız API instance'ında da reddediliyor.
- Recovery/publication bildirimleri ve her reminder gönderimi hemen öncesinde aktifliği kontrol ediyor.
- Acceptance seed dört pairing kodunu açık organizasyon kimliğiyle üretiyor.

### Doğrulama

- Web: 471 test; TypeScript ve production build başarılı.
- Tarayıcı: 93 başarılı, 1 atlandı; masaüstü/mobil landing ve pairing ayrıca incelendi. Impeccable detector bulgu döndürmedi.
- Android: `gradlew.bat testDebugUnitTest` başarılı; cihaz/emülatör instrumented testleri çalıştırılmadı.
- Python: core/backend/worker mypy ve kaynak/test Ruff kontrolleri başarılı.
- OpenAPI: mevcut üreteçlerle üretildi; compatibility kontrolü 0 breaking/unproven change.
- PowerShell starter assertion script'i başarılı. Script bir Pester suite'i değil; doğrudan PowerShell ile çalıştırıldı.
- Ops tam koşusunda değişmeyen `test_restore_relocates_firebase_credentials` Windows CRLF/LF beklentisinde başarısız; ilgili backup dosyalarına dokunulmadı. Bu tek test hariç tekrar koşusu ayrıca kaydedildi.
- `npm ci` mevcut 6 güvenlik açığı bildirdi (2 moderate, 2 high, 2 critical); bağımlılık yükseltme bu iş kapsamında yapılmadı.
- Son inceleme düzeltmeleri sonrası tam suite'ler: core **1000 başarılı / 2 atlandı**, backend **333 başarılı**, worker **145 başarılı**. Docker kesintisi sonrası bu koşular yeniden çalıştırıldı.
- Ops son koşu: **145 başarılı / 40 atlandı / 1 deselect**; dışlanan test yukarıda adı belirtilen değişmeyen Windows newline testidir. Acceptance **32 başarılı**.
- Task 1–7 uygulaması ve bağımsız inceleme düzeltmeleri tamamlandı; özgün task commit adımları yukarıdaki tek entegrasyon commit kararıyla birleştirildi.
