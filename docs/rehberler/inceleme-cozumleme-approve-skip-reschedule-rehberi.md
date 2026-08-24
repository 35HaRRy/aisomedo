# İnceleme Çözümleme — Onayla / Atla / Yeniden Zamanla — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #15** (Review resolution: approve, skip, reschedule) kapsamında yapılan
değişiklikleri özetler ve bunları adım adım deneyebilmen için PowerShell komutlarını
gösterir. Tüm komutlar PowerShell'dir; Python kodu içermez.

## 1. Değişiklik Özeti

### Amaç

Vadesi gelen bir `Yayın İncelemesi`'ni üç yolla çözümlemek — **onayla**, **atla**,
**yeniden zamanla** — öyle ki iki eşit cihaz aynı incelemeye aynı anda dokunduğunda
**tam olarak biri** kazanır; kaybeden taraf "başka bir cihaz tarafından zaten çözümlendi"
yanıtı ve taze durum alır. Kilit noktalar:

- **Revizyon farkında atomik CAS** — her inceleme monoton artan bir `version` sayaç taşır.
  `resolve_if_pending` yalnızca `status='pending'` **ve** eşleşen `version` ile yazarken
  `version`'ı artırır; aksi hâlde `None` döner (AC1). Eski revizyona (bayat içerik)
  yapılan işlem **reddedilir** — `ReviewStale` (AC2).
- **Onayla = yalnızca çözümle.** `approve` incelemeyi `approved` yapar, bağlı oluşumu
  çözer ve `review.approved` denetim kaydı yazar. Yayınlama işi (#18) kapsam dışıdır.
- **Atla, açık `confirmed=True` ister.** Onay olmadan `SkipRequiresConfirmation`. Başarıda
  inceleme `skipped` olur, oluşum çözülür, sonuç bir sonraki düzenli zamanı taşır; aktif
  paket **değişmez**, hatırlatmalar durur (AC3).
- **Yeniden zamanla, `kind="oneoff"` oluşum üretir.** `new_due_at` kesin gelecekte olmalı
  (aksi hâlde `RescheduleTimeInvalid`). İnceleme `rescheduled` olur, mevcut oluşum çözülür,
  yeni `oneoff` oluşumu oluşturulur; inceleme `oneoff_occurrence_id` kaydeder. İkinci bir
  yeniden zamanlama önceki `oneoff`'u **değiştirir** (aynı satır, yeni `due_at`), yığmaz.
  Düzenli takvim (recurring cadence) asla kaymaz (AC4).
- **Hatırlatmalar dolaylı durur** — çözümlenen inceleme `list_pending_reviews()` dönüşünden
  çıkar; #16'nın döngüsünün bildireceği bir şey kalmaz.

### Yapılanlar (`development` branch, 2 commit)

| Commit | İçerik |
|---|---|
| `4727c5a` | **Tasarım dokümanı** — `docs/superpowers/specs/2026-08-20-review-resolution-approve-skip-reschedule-design.md` |
| `a651915` | **Uygulama** — `YayinIncelemesi` modeline `version`/`resolved_at`/`resolved_by`/`oneoff_occurrence_id` + `SkipResult`; yeni istisnalar (`SkipRequiresConfirmation`, `RescheduleTimeInvalid`, `ReviewStale`, `ReviewAlreadyHandled`, `ReviewNotFound`); `ReviewStore.get`/`update`/`resolve_if_pending` + `ScheduleStore.update`/`next_regular_after` portları; InMemory/Postgres uygulamaları; `approve`/`skip`/`reschedule` + yardımcılar; migration `0010`; `test_review_resolution.py` + DB testleri |

### Önemli tasarım kararları

- **CAS anahtarı**: `(review_id, version)` → `status`. `version` yalnızca başarılı çözümlemede
  artar; bayat revizyon ayrıca `revision_digest` ile aktif paketin `render_revision`'ına
  karşı denetlenir.
- **`oneoff` yeni `YayinZamani.kind` değeridir** — o tabloda şema değişikliği yoktur;
  mevcut `pending`/`resolved` + `resolved_at` yeniden kullanılır.
- **Çözümleme tek denetim kaydı üretir**: yeniden zamanlama için `_apply_reschedule_oneoff`
  tek `review.rescheduled` kaydı yazar (önceki iki kayıtlık durum düzeltildi).
- **Naive yerel zaman**: istemciden gelen saat-dilimi olmayan `new_due_at` İstanbul saatine
  göre yorumlanır, karşılaştırmada çökmez.
- **Aktif paket yoksa bayat denetimi tetiklenmez**: `render_revision` karşılaştırması yalnızca
  bir paket mevcutken anlamlıdır.

## 2. Ön Hazırlık

1. **Docker'ı başlatın** (DB testleri testcontainers ile geçici Postgres açar):
```powershell
docker compose -f ops/docker-compose.yml up -d --build db backend worker
```
2. **Bağımlılıkları yükleyin** (repo kökünden):
```powershell
uv sync
```

## 3. Test Adımları

### Adım 1: Çözümleme (seam) testleri

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_review_resolution.py -v
```

Beklenen (**10 test geçer**):

- `test_approve_resolves_review_and_occurrence` — onay incelemeyi `approved` yapar, oluşumu
  çözer, `review.approved` denetim kaydı yazar, bekleyen listesi boşalır.
- `test_racing_approve_skip_reschedule_exactly_one_winner` — aynı depoyu paylaşan üç seam
  aynı `version` üzerinde onay/atla/yeniden zamanla yarışır; tam olarak biri kazanır,
  kaybedenler `ReviewAlreadyHandled` ile kazananın durumunu taşır (AC1).
- `test_stale_review_action_rejected` — içerik değiştikten sonra eski revizyona yapılan onay
  `ReviewStale` fırlatır (AC2).
- `test_approve_unknown_review_raises` — olmayan incelemeye onay `ReviewNotFound` fırlatır.
- `test_skip_requires_confirmation` — `confirmed=False` ile atlama `SkipRequiresConfirmation`
  fırlatır, hiçbir şey değişmez.
- `test_skip_resolves_and_returns_next_regular_time` — onaylı atlama incelemeyi `skipped`
  yapar, bir sonraki düzenli zamanı döner, aktif paket değişmez (AC3).
- `test_reschedule_requires_future_time` — geçmiş/şimdiki zaman `RescheduleTimeInvalid` fırlatır.
- `test_reschedule_creates_oneoff_and_replaces_prior` — gelecek zaman `oneoff` oluşturur;
  oluşum `due` olunca doğan yeni incelemeye yeniden zamanlama önceki `oneoff`'u değiştirir,
  yığmaz, düzenli takvim kaymaz (AC4).
- `test_reschedule_naive_time_treated_as_local_zone` — saat-dilimi olmayan gelecek zaman
  İstanbul'a göre yorumlanır.
- `test_reschedule_emits_single_audit_event` — yeniden zamanlama tek `review.rescheduled`
  denetim kaydı üretir.

### Adım 2: Depo (DB) testleri

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py -v -k "resolve or next_regular or oneoff or review"
```

Beklenen (**8 test geçer**, gerçek Postgres üzerinde):

- `test_resolve_if_pending_cas_win_then_lose` — doğru `version` kazanır, `version` artar;
  eski `version` veya zaten çözülmüş incelemeye ikinci deneme `None` döner.
- `test_resolve_if_pending_missing_review` — olmayan incelemede `None` döner.
- `test_review_update_persists_oneoff_occurrence_id` — `oneoff_occurrence_id` güncellemesi
  kalıcıdır ve `get` ile okunur.
- `test_next_regular_after_skips_non_regular` — `oneoff`/`manual` satırları atlanır, sonraki
  düzenli zaman bulunur.
- `test_next_regular_after_none_when_no_regular` — düzenli yoksa `None` döner.
- `test_review_create_get_by_occurrence_and_pending` / `test_review_unique_occurrence_revision`
  / `test_review_different_revision_allowed` — önceki (#14) inceleme deposu davranışı.

> Not: DB testleri testcontainers ile geçici bir Postgres açar; Docker gerekir.

### Adım 3: Migration doğrulaması

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py::test_alembic_upgrade_head_creates_review_resolution_columns -v
```

Beklenen (**1 test geçer**): `0010_review_resolution` dahil tüm migration'lar `head`'e kadar
uygulanır; `yayin_incelemesi` tablosunda `version`/`resolved_at`/`resolved_by`/
`oneoff_occurrence_id` sütunları bulunur.

### Adım 4: Tüm paketlerin tam takımları

```powershell
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
uv run --project worker pytest worker/tests -v
```

Beklenen: dojo-core **250 geçer, 2 atlanır** (atlamalar docker/ffmpeg gerektiren işleme
testleridir; CI'da doğrulanır).

### Adım 5: Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src/dojo dojo-core/tests
uv run --project dojo-core mypy dojo-core/src/dojo
```

Beklenen: hepsi temiz. (`mypy` doğrudan engellenirse `uvx mypy dojo-core/src/dojo` ile
deneyin.)

## 4. Manuel Deneme (Worker + DB)

Yeni API rotası olmadığı için uçtan uca doğrulama worker döngüsü ve doğrudan DB sorgusu ile
yapılır. Yığın ayağa kalktıktan sonra:

1. **Migration'ları uygulayın** — docker-compose migration'ı otomatik çalıştırmaz; DB şeması
   `0010_review_resolution` öncesinde kalmışsa `yayin_incelemesi` tablosunda `version` sütunu
   olmaz ve aşağıdaki sorgular "column \"version\" does not exist" verir. Alembic zaten
   docker DB'sine (`localhost:5433`, kullanıcı/şifre `dojo`) işaret ettiği için şu komut yeterli:
```powershell
uv run --project dojo-core alembic upgrade head
```
   - Beklenen çıktı: `Running upgrade ... -> 0010_review_resolution` satırı.
   - "database does not exist" veya bağlantı hatası alırsan önce DB'nin ayakta olduğundan
     emin olun:
```powershell
docker compose -f ops/docker-compose.yml ps db
```

2. **Aktif pakete medya yükleyip render aldırın** (Android/web istemcisinden ya da mevcut
   test akışlarıyla). Worker'ın birkaç tur atmasına izin verin — vadesi gelen `Yayın Zamanı`
   için bir `Yayın İncelemesi` (`status='pending'`) oluşur:
```powershell
docker compose -f ops/docker-compose.yml logs -f --tail=50 worker
```

3. **Bekleyen incelemeleri ve oluşumları görüntüleyin**:
```powershell
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT id, occurrence_id, revision_digest, status, version FROM yayin_incelemesi ORDER BY id;"
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT id, kind, due_at, status, resolved_at FROM yayin_zamani ORDER BY id;"
```

4. **Çözümlemeyi doğrudan DB'den simüle edin** — CAS'ın etkisini görmek için bir incelemenin
   `status` ve `version` değerini güncelleyin (gerçekte bu çağrı API/worker üzerinden olur;
   bu sadece yazım kuralını gösterir):
```powershell
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "UPDATE yayin_incelemesi SET status='approved', version=version+1 WHERE id=1;"
```
   - `version` artışı, ikinci bir cihazın eski `version` ile yaptığı CAS denemesinin
     başarısız olmasını garantiler (AC1).
   - Bu komut "column \"version\" does not exist" veriyorsa migration'ları henüz
     uygulamamışsın demektir → **Adım 1**'deki `alembic upgrade head`'i çalıştır.

5. **`oneoff` oluşumunu gözlemleyin** — bir incelemeyi yeniden zamanladığınızda
   `yayin_zamani` tablosunda `kind='oneoff'` yeni bir satır belirir ve ilgili incelemeye
   `oneoff_occurrence_id` yazılır; düzenli satırların `due_at`'leri değişmez (AC4).

6. **Yeniden çalıştırma idempotens'i** — çözümlenmiş inceleme artık `pending` olmadığından
   `list_pending_reviews()` dönüşünde yoktur; worker döngüsü onu yeniden değerlendirmez.

7.
```powershell
$env:DATABASE_URL = "postgresql+psycopg://dojo:dojo@localhost:5433/dojo"
uv run --project backend uvicorn backend.main:app --host 0.0.0.0 --port 8000
$token = "<bearer yada session cookie>"
$body = @{ review_id = 1; version = 1; new_due_at = (Get-Date).AddDays(2).ToString("o") } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/packages/actives/reschedule" -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $body
```

## 5. Git Geçmişi

```powershell
git log --oneline -2
```

```text
a651915 feat(review): approve, skip, reschedule with revision-aware CAS (#15)
4727c5a docs(design): review resolution approve/skip/reschedule (#15)
```

## 6. Known Issues ve Sınırlamalar

- **Onay, yayınlama işi başlatmaz**: `approve` yalnızca çözümler; bir yayınlama işi
  sıralamak **#18** kapsamındadır.
- **İnceleme gösterimi API'si yok**: istemciye dönük inceleme görünümü **#25**, bildirim ve
  hatırlatmalar **#16** kapsamındadır.
- **`yayin_incelemesi.occurrence_id` ve `oneoff_occurrence_id` FK değildir**: mevcut
  sade-Integer kalıbını izler; veritabanı düzeyinde ilişki zorlanmaz.
- **Yarış testi sıralıdır**: CAS deterministik olduğundan davranış doğrudur, ancak
  `test_racing_*` gerçek eşzamanlı kesiştirme yerine sabit sırayla üç seam çalıştırır.
- **Migration `0010`** eski satırlar için `server_default="1"` kullanır; mevcut incelemeler
  geçerli bir `version` ile kalır.