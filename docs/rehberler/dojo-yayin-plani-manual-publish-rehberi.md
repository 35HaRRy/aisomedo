# Dojo Yayın Planı ve Manuel Yayınlama — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #13** (Dojo Yayın Planı and manual publication) kapsamında
yapılan değişiklikleri özetler ve bunları adım adım deneyebilmen için PowerShell
komutlarını gösterir. Tüm komutlar PowerShell'dir; Python kodu içermez.

## 1. Değişiklik Özeti

### Amaç

`Dojo` yayın akışına şu yetenekleri kazandırır:

- **Dojo Yayın Planı** — `Europe/Istanbul` saat diliminde **15 günde bir Pazartesi**
  yayın planı. Planın başlangıcı (`anchor_date`), saati (`anchor_time`) ve açık/kapalı
  durumu (`enabled`) ayarlanabilir.
- **Manuel yayınlama** — plan ayarlarından bağımsız, elle bir `Yayın Zamanı` oluşturur
  (hemen, şimdi). Bu, tekrarlayan Pazartesi takvimini **kaydırmaz**.
- **Takvim üretimi** — plan açıkken çalışan `evaluate_due_work`, başlangıç Pazartesi'sinden
  itibaren **geçmiş tüm Pazartesileri** doldurur ve **tam olarak bir gelecek satır** tutar
  (idempotent: yeniden çalıştırmak çoğaltmaz; başlangıç tarihi değişirse eski gelecek
  satırlar temizlenir).
- **Kalıcılık** — oluşumlar yeni `yayin_zamani` tablosunda saklanır (migration `0007`).

### Yapılanlar (`development` branch, 8 commit)

| Commit | İçerik |
|---|---|
| `229a30f` | **Modeller ve istisnalar** — `SchedulePlan`, `YayinZamani` + `PlanInvalid`, `ManualPublishConflict`; `dojo/__init__.py` dışa aktarımları; `test_schedule_models.py` |
| `d0bb8dc` | **Depo portu ve migration** — `ScheduleStore` arayüzü + `yayin_zamani` tablosu (`0007_yayin_zamani.py`) |
| `d870267` | Küçük temizlik — Task 3'e kadar kullanılmayan import kaldırıldı |
| `ecbc924` | **Depo uygulamaları** — `InMemoryStore` ve `PostgresStore` `ScheduleStore`'u uygular; `test_store_schedule.py` |
| `e817518` | **Seam** — `get_plan`, `set_plan`, `manual_publish`, `ensure_schedule_upto`, `list_due_occurrences` + `evaluate_due_work`; `test_schedule.py` (9 test) |
| `ea6ac87` | **Gelecek satır düzeltmesi** — başlangıç tarihi ileri alınınca bayat kalan gelecek satırlar temizlenir (`prune_regular_future`); 1 yeni test |
| `fb25c83` | **FastAPI rotaları** — `GET/PUT /api/settings/plan`, `POST /api/settings/manual-publish`; 4 sözleşme testi |
| `981c4a2` | **422 düzeltmesi** — bozuk `anchor_date`/`anchor_time` artık `500` yerine `422` döner (Pydantic `date`/`time`); 1 yeni test |

### Önemli tasarım kararları

- **Başlangıç Pazartesi olmalı** — `anchor_date` Pazartesi değilse veya boşsa
  `PlanInvalid` fırlar (HTTP `422`).
- **Manuel yayınlama takvimi kaydırmaz** — yalnızca `manual` tipinde, şimdi zamanlı bir
  satır ekler; `regular` satırlara dokunmaz.
- **Bekleyen manuel tek olabilir** — bekleyen bir `manual` satır varken ikinci manuel
  yayınlama `ManualPublishConflict` fırlatır (HTTP `409`).
- **Manuel, plan kapalıyken de çalışır** — `enabled=false` olsa bile manuel yayınlama
  mümkündür.
- **Plan ayarları** — `schedule.enabled`, `schedule.anchor_date` (ISO tarih),
  `schedule.anchor_time` (ISO saat) ayar deposunda saklanır.
- **Saat dilimi sabittir** — `Europe/Istanbul`; DST olmadığı için 14 günlük adım güvenlidir.

### HTTP durum kodları

| Senaryo | Kod |
|---|---|
| Plan okuma / yazma başarılı | `200` |
| Kimlik doğrulanmamış istek | `401` |
| Geçersiz plan (Pazartesi olmayan / bozuk tarih) | `422` |
| Bekleyen manuel varken ikinci manuel | `409` |

## 2. Ön Hazırlık

1. **Docker'ı başlatın** (Postgres + backend + worker):
```powershell
docker compose -f ops/docker-compose.yml up -d --build db backend worker
```
2. **Bağımlılıkları yükleyin** (repo kökünden):
```powershell
uv sync
```

## 3. Test Adımları

### Adım 1: Dojo-core model testleri

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_schedule_models.py -v
```

Beklenen (**4 test geçer**): `SchedulePlan`/`YayinZamani` dataclass'ları, `PlanInvalid`/
`ManualPublishConflict` istisnaları ve `dojo` paketinden dışa aktarım.

### Adım 2: Depo testleri (InMemory/Postgres)

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_store_schedule.py -v
```

Beklenen (**6 test geçer**): `ScheduleStore` arayüzünün tüm metodları
(`create`, `max_regular_due_at`, `has_regular_at`, `has_pending_manual`, `list_due`,
`list_all`).

### Adım 3: Seam testleri (plan, manuel yayınlama, takvim üretimi)

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_schedule.py -v
```

Beklenen (**10 test geçer**):

- `test_set_plan_requires_monday_anchor` / `test_set_plan_defaults_disabled` —
  Pazartesi kuralı ve kapalı varsayılan.
- `test_ensure_schedule_upto_backfills_and_one_future_row` — geçmiş Pazartesiler +
  tam olarak bir gelecek satır.
- `test_restart_idempotent` — aynı depoyu paylaşan yeni bir seam çalıştırması çoğaltmaz.
- `test_plan_edit_reflected_in_future_rows` / `test_forward_anchor_edit_prunes_stale_future_row`
  — başlangıç değişince gelecek satırlar güncellenir; ileri alınan başlangıçta bayat
  satır temizlenir.
- `test_manual_publish_creates_due_slot_without_shifting` — manuel satır `regular`'ları
  kaydırmaz.
- `test_second_manual_publish_conflict` — bekleyen varken ikincisi `ManualPublishConflict`.
- `test_manual_publish_allowed_when_plan_disabled` — `enabled=false` iken manuel çalışır.
- `test_evaluate_due_work_materializes` — işçi döngüsü satırları üretir.

### Adım 4: Backend API sözleşme testleri

```powershell
uv run --project backend pytest backend/tests/test_api.py -v -k "plan or manual"
```

Beklenen (**5 test geçer**):

- `test_plan_routes_require_auth` — üç rota da `401`.
- `test_plan_roundtrip_via_api` — `200`, plan yankılanır, `timezone: Europe/Istanbul`.
- `test_set_plan_non_monday_422_via_api` — Pazartesi olmayan `anchor_date` → `422`.
- `test_set_plan_malformed_input_422_via_api` — bozuk tarih/saat → `422` (500 değil).
- `test_manual_publish_via_api` — `200` ve dönen `kind: manual`; ikinci çağrı `409`.

### Adım 5: Tüm paketlerin tam takımları

```powershell
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
```

Beklenen: dojo-core **222 geçer, 2 atlanır**, backend **64 geçer**. (2 atlama
docker/ffmpeg gerekli işleme testleridir; CI'da doğrulanır.)

### Adım 6: Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src/dojo dojo-core/tests/test_schedule.py dojo-core/tests/test_schedule_models.py dojo-core/tests/test_store_schedule.py
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend ruff check backend/src/backend backend/tests
uv run --project backend mypy backend/src/backend
```

Beklenen: hepsi temiz. (mypy doğrudan engellenirse `uvx mypy ...` ile deneyin.)

## 4. Manuel Deneme (Uçtan Uca)

Gerçek API davranışını el ile görmek için: yığın ayağa kalktıktan sonra bir cihaz
eşleştirip token alın, sonra plan ve manuel yayınlama uçlarını deneyin.

1. **Değişkenleri kurun ve token alın**:
```powershell
$base = "http://localhost:8000"

# 1) Pairing kodu üret (CLI, host:5433 -> Docker'daki Postgres)
$out = uv run --project backend dojo-create-pairing-code create-code
$code = ($out | Where-Object { $_ -like 'Pairing code:*' }) -replace '^Pairing code:\s*',''
$code

# 2) Kodu cihaz olarak doğrula -> Bearer token
$pair = Invoke-RestMethod -Method Post -Uri "$base/api/pairing/validate" `
    -ContentType 'application/json' -Body (@{ code=$code; kind='device'; name='PS' } | ConvertTo-Json)
$H = @{ Authorization = "Bearer $($pair.token)" }
```

2. **Varsayılan planı okuyun** (henüz ayarlanmamışsa `enabled: false` döner):
```powershell
Invoke-RestMethod -Method Get -Uri "$base/api/settings/plan" -Headers $H
```

3. **Planı ayarlayın** (24 Ağustos 2026 = Pazartesi, saat 10:00):
```powershell
$body = @{ anchor_date = '2026-08-24'; anchor_time = '10:00'; enabled = $true } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$base/api/settings/plan" -Headers $H -ContentType "application/json" -Body $body
```
   - `200`; `timezone: Europe/Istanbul`, `enabled: True` döner.
   - Worker `evaluate_due_work` döngüsü plan açık olunca geçmiş Pazartesileri doldurur.

4. **Geçersiz plan deneyin** (25 Ağustos = Salı):
```powershell
$bad = @{ anchor_date = '2026-08-25'; anchor_time = '10:00' } | ConvertTo-Json
try { Invoke-RestMethod -Method Put -Uri "$base/api/settings/plan" -Headers $H -ContentType "application/json" -Body $bad }
catch { $_.Exception.Response.StatusCode.value__ }
```
   - `422` döner (`PlanInvalid`).

5. **Bozuk tarih deneyin** (500 yerine 422):
```powershell
$bad2 = @{ anchor_date = 'not-a-date'; anchor_time = '10:00' } | ConvertTo-Json
try { Invoke-RestMethod -Method Put -Uri "$base/api/settings/plan" -Headers $H -ContentType "application/json" -Body $bad2 }
catch { $_.Exception.Response.StatusCode.value__ }
```
   - `422` döner (düzeltme `981c4a2`).

6. **Manuel yayınlama yapın** (hemen, bekleyen bir satır oluşturur):
```powershell
$occ = Invoke-RestMethod -Method Post -Uri "$base/api/settings/manual-publish" -Headers $H
$occ | Format-List
```
   - `200`; `kind: manual`, `status: pending`, `due_at` şimdiki zaman.

7. **İkinci manuel yayınlama deneyin** (bekleyen varken):
```powershell
try { Invoke-RestMethod -Method Post -Uri "$base/api/settings/manual-publish" -Headers $H }
catch { $_.Exception.Response.StatusCode.value__ }
```
   - `409` döner (`ManualPublishConflict`). Bekleyen satır çözümlenmeden yenisi
     oluşturulamaz.

8. **Planı kapatın** (manuel yine de çalışır):
```powershell
$off = @{ anchor_date = '2026-08-24'; anchor_time = '10:00'; enabled = $false } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$base/api/settings/plan" -Headers $H -ContentType "application/json" -Body $off
Invoke-RestMethod -Method Get -Uri "$base/api/settings/plan" -Headers $H
```
   - Plan `enabled: False` görünür; takvim üretimi durur, manuel yayınlama açık kalır.

## 5. Git Geçmişi

```powershell
git log --oneline -8
```

```text
981c4a2 fix(backend): return 422 (not 500) on malformed plan input via Pydantic date/time (#13)
fb25c83 feat(backend): plan and manual publish routes (#13)
ea6ac87 fix(dojo-core): prune stale regular future rows on anchor edit (#13)
e817518 feat(dojo-core): dojo yayin plani, manual publish, and due-slot emission (#13)
ecbc924 feat(dojo-core): schedule store implementations (#13)
d870267 fix(dojo-core): drop unused YayinZamani import until Task 3 uses it
d0bb8dc feat(dojo-core): schedule store port and yayin_zamani migration (#13)
229a30f feat(dojo-core): schedule models and exceptions (#13)
```

## 6. Known Issues ve Sınırlamalar

- **`prune_regular_future` duruma bakmaz**: `due_at > now` olan tüm `regular` satırları
  siler. Bugün yalnız `pending` satırlar olduğu için güvenlidir; satır çözümlenmeye
  başlayınca (#14) duruma duyarlı olmalıdır.
- **API ile plan sıfırlanamaz**: `anchor_date: null` göndermek `422` döner; yalnız
  `enabled: false` ile kapatılabilir.
- **`max_regular_due_at` çalışma anında kullanılmıyor**: takvim üretimi bunun yerine
  `has_regular_at` korumasını kullanır (aynı idempotens garantisi; metot test edilmiştir).
- **İki test dosyası satır sonu yok**: `test_schedule.py` ve `test_schedule_models.py`
  son satırda yeni satır (newline) içermez — mevcut ruff seçimi uyarmaz.
- **Kapsam dışı**: `Yayın İncelemesi` oluşturma (#14), inceleme çözümleme: atla/yeniden
  zamanla/onayla (#15), hatırlatma ve bildirimler (#16), gösterge paneli "sonraki Yayın
  Zamanı" (#25) bu ticket'ta yok.