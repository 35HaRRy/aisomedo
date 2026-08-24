# Hatırlatma ve Android Bildirim — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #16** (Pending-review reminders and Android notifications) kapsamında yapılan
değişiklikleri özetler ve bunları adım adım deneyebilmen için PowerShell komutlarını gösterir.
Tüm komutlar PowerShell'dir; Python kodu içermez.

## 1. Değişiklik Özeti

### Amaç

Vadesi gelen `YayinIncelemesi` (`status='pending'`) için **yapılandırılabilir hatırlatma** ve **Android'e FCM push**.
Vekil noktalar: sessiz saatler, 6 saat aralığı, worker yeniden başlasa bile kalıcı kadans, çözümlemede otomatik durma.

### Kararlar

- **Mevcut `DojoPublishing` genişletildi.** Ayrı bir `DojoNotifications` modülü veya outbox eklenmedi; tek derin seam korundu.
- **Kadans `YayinIncelemesi.last_reminded_at` ile kalıcı.** Onayla / atla / yeniden zamanla incelemeyi `pending` dışına çıkarır → `list_pending_reviews()` boşalır → hatırlatma durur. Ayrı iptal yolu yok.
- **Sessiz saatler ilk push'u da kapar.** Varsayılan `08:00` dahil – `22:00` hariç, `Europe/Istanbul`. Gece yarısını geçen pencereler desteklenir (`22:00-06:00` gibi), eşit sınırlar geçersiz.
- **Cihaz başına bir FCM kaydı.** Aynı token başka eşleşmede varsa **transfer** olur; tarayıcı kayıt edemez `422`; iptal edilmiş cihaz kayıt edemez `422`.
- **Toplu `Notifier` adaptörü.** `send(notification, tokens) -> NotificationResult` ile `delivered` / `invalid_tokens` / `transient_failures` sınıflandırması. Geçersiz token silinir, geçici hata bir sonraki normal aralığa kalır, tüm çağrı hatası `last_reminded_at` ilerletmeden `notification.failed` yazar.
- **Worker ayakta kalır.** Bildirim hatası `evaluate_due_work` / `process_job` / `sweep_stale_uploads` akışını kesmez.

### Yapılanlar (`development` branch, 2 commit)

| Commit | İçerik |
|---|---|
| `dd6d14d` | **Tasarım dokümanı** — `docs/superpowers/specs/2026-08-24-pending-review-reminders-android-notifications-design.md` |
| `4281e5f` | **Uygulama** — `ReminderPolicy`/`PushRegistration`/`Notification`/`NotificationResult` + sabitler; `Notifier` toplu sözleşme + `PushRegistrationStore` + `ReviewStore.update_last_reminded_at`; InMemory/Postgres uygulamaları + `StubNotifier` güncellemesi; `DojoPublishing.get_reminder_policy`/`set_reminder_policy`/`register_push_token`/`remove_push_token`/`send_due_reminders` + `_in_delivery_window`; `FcmNotifier`; `GET/PUT /api/settings/reminders` ve `PUT/DELETE /api/pairing/me/push-token` rotaları; `worker` tick sırası `evaluate -> claim/process -> send_due_reminders -> sweep`; migration `0011_pending_review_notify` (`yayin_incelemesi.last_reminded_at` + `push_registrations`); plan dokümanı |

### Kapsam dışı (bilinçli erteleme)

- **Yayın başarı/başarısızlık bildirimleri** — #18/#19 terminal yayın durumları üretince eklenecek. #16 bu kriteri bilinçli eksik bırakır.
- **Android inbox / deep link / UI** — #36 bu sunucu sözleşmesini tüketir.
- **Web Push / e-posta / SMS** — MVP dışı.

## 2. Ön Hazırlık

1. **Docker'ı başlat** (DB testleri testcontainers ile geçici Postgres açar):
```powershell
docker compose -f ops/docker-compose.yml up -d --build db
```

2. **Bağımlılıkları yükle** (repo kökünden):
```powershell
uv sync
```

3. **Issue kaynağını gör**:
```powershell
gh issue view 16 --json number,title,body,labels,state,url
```

## 3. Test Adımları

### Adım 1: Tip kontrolü (ayrı paket bazlı)

```powershell
uv run mypy dojo-core/src --show-error-codes
```

Beklenen: `Success: no issues found in 18 source files`

```powershell
uv run mypy backend/src --show-error-codes
```

Beklenen: `Success: no issues found in 12 source files`

```powershell
uv run mypy worker/src --show-error-codes
```

Beklenen: `Success: no issues found in 2 source files`

### Adım 2: Çekirdek ve API testleri

```powershell
uv run pytest dojo-core/tests/test_review.py dojo-core/tests/test_review_resolution.py -v
```

Beklenen: 17 geçer — durable inceleme ve CAS çözümleme bozulmadı.

```powershell
uv run pytest backend/tests/test_api.py -v
```

Beklenen: 59 geçer — paket, pairing, activity, upload, montage, branding, plan akışları sağlam.

```powershell
uv run pytest worker/tests/test_worker.py -v
```

Beklenen: 4 geçer — `run_tick` artık `send_due_reminders` çağırır, hata süpürmeyi atlamaz.

```powershell
uv run pytest dojo-core/tests -k "not pg_store and not pg and not test_db" -q
```

Beklenen: 223 geçer, 2 atlanır.

### Adım 3: Migration doğrulama

```powershell
Get-Content dojo-core/migrations/versions/0011_pending_review_notify.py
```

Beklenen: `last_reminded_at` sütunu ve `push_registrations` tablosu (client_id PK/FK, token unique).

```powershell
uv run alembic --cwd dojo-core history | Select-String "0011"
```

Beklenen: `0011_pending_review_notify` satırı `0010` sonrası görünür.

```powershell
uv run alembic --cwd dojo-core upgrade head
```

Beklenen: `Running upgrade ... -> 0011_pending_review_notify`

Yerel Postgres'e direkt bakış (docker DB ayakta iken):

```powershell
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "\d yayin_incelemesi"
```

Beklenen: `last_reminded_at` timestamp with time zone sütunu listelenir.

```powershell
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "\d push_registrations"
```

Beklenen: `client_id` integer PK, `token` text unique, `updated_at` timestamp.

### Adım 4: HTTP sözleşmeleri (canlı backend gerektirir)

Backend'i geçici ayağa kaldır (ayrı terminal):

```powershell
$base = "http://localhost:8000"

$env:DATABASE_URL = "postgresql+psycopg://dojo:dojo@localhost:5433/dojo"
uv run --project backend uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Başka terminalde eşleşmiş cihaz al (CLI bootstrap):

```powershell
uv run --project backend dojo-create-pairing-code
# dönen kodu kopyala, sonra:
Invoke-RestMethod -Method Post -Uri $base/api/pairing/validate -ContentType "application/json" -Body '{"code":"<KOD>","kind":"device","name":"Phone"}'
# dönen token değerini kopyala -> $token
```

Hatırlatma politikası:

```powershell
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Method Get -Uri $base/api/settings/reminders -Headers $headers
```

Beklenen: `interval_minutes:360, delivery_start:"08:00:00", delivery_end:"22:00:00", timezone:"Europe/Istanbul"`

```powershell
$body = @{ interval_minutes = 120; delivery_start = "08:00:00"; delivery_end = "20:00:00"; timezone = "Europe/Istanbul" } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri $base/api/settings/reminders -Headers $headers -ContentType "application/json" -Body $body
```

Beklenen: 200 ve aynı JSON geri döner.

```powershell
$bad = @{ interval_minutes = 0; delivery_start = "08:00:00"; delivery_end = "08:00:00"; timezone = "UTC" } | ConvertTo-Json
try { Invoke-RestMethod -Method Put -Uri $base/api/settings/reminders -Headers $headers -ContentType "application/json" -Body $bad } catch { $_.Exception.Response.StatusCode.value__ }
```

Beklenen: 422

FCM token kaydı:

```powershell
$tokBody = @{ token = "fcm-test-token-123" } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri $base/api/pairing/me/push-token -Headers $headers -ContentType "application/json" -Body $tokBody
```

Beklenen: `{"ok": true}`

```powershell
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT client_id, token FROM push_registrations;"
```

Beklenen: bir satır, `fcm-test-token-123`

Tarayıcı reddi:

```powershell
# tarayıcı eşleşmesi için ayrı kod üret ve çerez al:
$code2 = uv run --project backend dojo-create-pairing-code
# yukarıdaki validate'i browser kind ile çağırıp Set-Cookie al, sonra:
Invoke-RestMethod -Method Put -Uri $base/api/pairing/me/push-token -ContentType "application/json" -Body $tokBody -SessionVariable sess
# sess.Cookies üzerinden dojo_session ile tekrar dene -> 422
try { Invoke-RestMethod -Method Put -Uri $base/api/pairing/me/push-token -ContentType "application/json" -Body $tokBody -WebSession $sess } catch { $_.Exception.Response.StatusCode.value__ }
```

Beklenen: 422 `only device clients can register`

Silme:

```powershell
Invoke-RestMethod -Method Delete -Uri $base/api/pairing/me/push-token -Headers $headers
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT count(*) FROM push_registrations;"
```

Beklenen: `0`

Yetkisiz:

```powershell
try { Invoke-RestMethod -Method Get -Uri $base/api/settings/reminders } catch { $_.Exception.Response.StatusCode.value__ }
```

Beklenen: 401

### Adım 5: Worker ve kadans gözlemi

```powershell
docker compose -f ops/docker-compose.yml logs --tail 100 worker
```

Beklenen: `send_due_reminders failed` satırı yalnızca FCM hatasında görülür, worker döngüsü kesilmez.

DB'den kadans:

```powershell
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT id, status, last_reminded_at FROM yayin_incelemesi WHERE status='pending' ORDER BY id;"
```

Beklenen: gönderim sonrası `last_reminded_at` dolu; sessiz saatte (ör. `23:00` Europe/Istanbul) ve aralık dolmadan yeniden çağrıda ilerlemez.

Denetim:

```powershell
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT action, occurred_at, details FROM audit_events WHERE action LIKE 'notification.%' OR action LIKE 'push.%' OR action='reminders.policy_updated' ORDER BY id DESC LIMIT 20;"
```

Beklenen: `notification.sent` (delivered/invalid/transient sayıları), `notification.failed` (tüm çağrı hatası), `push.token_registered`/`push.token_removed`, `reminders.policy_updated`.

Transfer davranışı:

```powershell
# iki cihaz aynı token'ı sırayla kaydederse ikinci kazanır:
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT client_id, token FROM push_registrations ORDER BY client_id;"
```

Beklenen: token yalnızca son kaydeden cihazda kalır (eski satır silinir).

### Adım 6: Kod ve commit gezintisi

```powershell
git log --oneline -3
```

Beklenen:

```text
4281e5f feat(notifications): pending-review reminders and Android FCM (#16)
dd6d14d docs(design): specify review reminders (#16)
a651915 feat(review): approve, skip, reschedule with revision-aware CAS (#15)
```

```powershell
git diff dd6d14d...4281e5f --stat
```

Beklenen: 14 dosya — `model.py`, `ports.py`, `stubs.py`, `memory.py`, `db.py`, `fcm.py`, `publishing.py`, `conftest.py`, `0011_...py`, `routes/settings.py`, `routes/pairing.py`, `worker/main.py`, plan dokümanı.

```powershell
Get-Content docs/superpowers/specs/2026-08-24-pending-review-reminders-android-notifications-design.md | Select-Object -First 30
```

Beklenen: 7 karar, `ReminderPolicy`, `last_reminded_at`, toplu `Notifier`, worker sırası.

## 4. Bilinen Sınırlamalar

- `FCM_ENABLED` kapalıyken `StubNotifier` kullanılır; gerçek FCM için `FCM_ENABLED=true` ve `firebase_admin` Application Default Credentials gerekir, yoksa worker `RuntimeError` ile başlar.
- Geçersiz token toplu sonunda silinir; geçici hatada bir sonraki normal aralığa ertelenir, per-device outbox yok.
- `timezone` yalnızca `Europe/Istanbul` kabul eder; `delivery_start == delivery_end` reddedilir `422`.
- Yayın başarı/başarısızlık push'ları #18/#19'a bırakıldı; #16'nın son kriteri bu yüzden eksik kalır — tasarımda onaylı kapsam.
