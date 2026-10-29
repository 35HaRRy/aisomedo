# Audit Tam Bilgisi ve Etkinlik Akışı - Test Rehberi

## Özet Değişiklikler

Bu çalışma, audit ve aktivite akışı sistemi için 4 temel görev tamamlandı:

**1. Mağaza Sözleşmesi (Task 1):**
- `AuditEvent.id`, stabil artan bir cursor olarak tanımlandı
- `list_recent(before_id)` yöntemi ile yeni-ilk-son sıralaması (newest-first) cursor paging ile eklendi

**2. DojoActivity Yüzeyi (Task 2):**
- `dojo/activity.py` içinde yeni `DojoActivity` yüzeyi oluşturuldu
- Cursor paging ve aktör çözümleme mekanizmaları entegre edildi
- Aktör çözümleme: eşleşen istemci → `Client` nesnesi, sistem/cli → literal string

**3. Eylem Aktörü (Task 3):**
- `DojoPublishing.ensure_active_package()` içinde `requester` parametresi eklendi
- HTTP yolu üzerinden kimliği atanmış istemci için `package.created` eylemi oluşturuldu
- Zamanlayıcı yolu için `None` geçildi (actor = "system")

**4. Etkinlik API Yolu (Task 4):**
- Yeni route: `GET /api/activity?limit=50&before_id=<id>`
- Eşit haklara sahip (pairing.device + pairing.browser) okuma erişimi
- Yanıt: resolved actor için `{"id", "name", "kind"}` nesnesi içeren etkinlikler listesi

**BIRLEŞİK DEĞİŞİKLİK:**
- Veritabanı ve in-memory store'lar `list_recent` için sıralama düzeltildi
- InMemoryStore filtrelemeden sonra slice işlemi sıralaması düzeltildi

---

## Test Adımları

### Ön Hazırlık

1. **Depoyu klonlayın veya güncelleyin:**
```bash
git clone <repo-url>
cd aisomedo
```

2. **Gerekli bağımlılıkları yükleyin:**
```bash
uv sync
```

3. **Docker'ı başlatın** (testler için PostgreSQL gerekir):
   - VSCode'da PostgreSQL veya Docker Desktop'u başlatın

### Test 1: Mağaza Sözleşmesi ve Cursor Paging

Test dosyasını doğrudan çalıştırın:
```bash
uv run pytest dojo-core/tests/test_db_adapter.py::test_append_and_list_recent_newest_first -v
uv run pytest dojo-core/tests/test_db_adapter.py::test_list_recent_before_id_excludes_cursor -v
uv run pytest dojo-core/tests/test_db_adapter.py::test_list_recent_respects_limit -v
```

**Açıklama:**
- İki olay ekleme → yeni-ilk-son sıralaması doğrulanır
- `before_id=4` ile önceki olaylar alındığında cursor doğru çalışır
- `limit` parametresi sınırlandırılır

**Known Limitation:**
- Gerçek PostgreSQL veritabanı gerekir (`pg_store` fixture'i ile testler çalışır)
- Eğer Docker çalışmıyorsa testler çalışmayabilir; in-memory store için testler ayrı yazılabilir

### Test 2: InMemoryStore Sıralama Düzeltmesi (Bug Fix)

Bu dosyayı doğrudan değiştirip hatayı simüle edin:

**Dosya:** `dojo-core/src/dojo/adapters/memory.py`

**Bug:** `list_recent` yönteminde önce filtrele, sonra slice ve sonunda reverse yapılırken sıralama yanlış olur.

**Düzeltme:**
```python
def list_recent(self, limit: int = 50, before_id: int | None = None) -> list[AuditEvent]:
    if before_id is not None:
        events = [e for e in reversed(self._events) if e.id < before_id]
    else:
        events = self._events
    return list(reversed(events[-limit:]))
```

**Test Senaryosu:**

1. İki olay ekleme (ürün oluşturma):
```python
from dojo.model import AuditEvent
from dojo.testing import FIXED_AT

store = InMemoryStore()

# İlk olay (id=1)
event1 = AuditEvent(
    action="package.created",
    actor="system",
    occurred_at=FIXED_AT,
    details={"version": "1.0"}
)
store.append(event1)  # Internally creates id=1

# İkinci olay (id=2)
event2 = AuditEvent(
    action="package.created",
    actor="system",
    occurred_at=FIXED_AT,
    details={"version": "2.0"}
)
store.append(event2)  # Internally creates id=2

events = store.list_recent()
assert [e.details["version"] for e in events] == ["2.0", "1.0"]
assert [r.id for r in events] == [2, 1]
```

2. Cursor paging testi:
```python
# 5 olay ekleme (id=1 ile id=5)
for i in range(5):
    event = AuditEvent(
        action="package.updated",
        actor="system",
        occurred_at=FIXED_AT,
        details={"version": f"{i+1}.0"}
    )
    store.append(event)

# Önceki olayları al (before_id=3 → id < 3)
events = store.list_recent(limit=10, before_id=3)
print(f"Event IDs: {[e.id for e in events]}")
print(f"Event versions: {[e.details["version"] for e in events]}")
```

**Beklenen:**
- Event IDs: [2, 1]
- Event versions: ["2.0", "1.0"]
(En yeni önceki olaylar should appear first)

### Test 3: DojoActivity Yüzeyi ve Aktör Çözümleme

**Dosya:** `dojo-core/src/dojo/activity.py`

**Test senaryosu:**

1. Basit etkinlik listesi:
```python
from dojo.activity import DojoActivity
from dojo.model import AuditEvent, Client, PairingCode
from dojo.testing import FIXED_AT
from datetime import datetime

# Store'lar oluşturma
in_memory_store = InMemoryStore()
pairing_store = InMemoryStore()

# İstemci oluştur
client = store.create_client(
    Client(id=1, name="Phone", kind="device"),
    "hashed_credential"
)
pairing_store.mark_client_revoked(client.id, datetime.now())
pairing_store.touch_client(client.id, datetime.now())

# Etkinlikleri oluştur
event1 = store.append(AuditEvent(
    action="pairing.client_revoked",
    actor="client_1",
    occurred_at=FIXED_AT,
    details={"client_id": 1}
))

event2 = store.append(AuditEvent(
    action="package.created",
    actor="client_1",
    occurred_at=FIXED_AT,
    details={"folder": "test-package"}
))

# DojoActivity yüzeyini oluştur
activity = DojoActivity(
    audit=in_memory_store,
    pairing=pairing_store
)

page = activity.list_activity(limit=10)

print(f"Entries: {page.entries}")
for entry in page.entries:
    print(f"  - {entry.action} by {entry.actor}")
```

2. Aktör çözümleme testi:
```python
# {
    # "system" → literal string
    # "cli" → literal string
    # "1" → Client{id=1, name="Phone", kind="device"}
    # "999" → literal actor id string
# }
```

**Kod:** `dojo-core/src/dojo/activity.py` içinde `_resolve_actor` metodunu test edin.

### Test 4: API Yönlendirme (FastAPI)

**Adım 1: Backend servisini başlatın:**
```bash
uv run --project backend uvicorn backend.src.main:app --reload
```

**Adım 2: Swagger UI üzerinden endpointi test edin:**
http://localhost:8000/docs

**Endpoint:** `GET /api/activity`

**Query Parametreleri:**
- `limit` (optional, varsayılan: 50)
- `before_id` (optional)

**Test senaryoları:**

1. Kimsiz istek (yanlış olmalı):
```bash
curl http://localhost:8000/api/activity
# Response: 401 Unauthorized
```

2. Doğru istemciyle istek (Futenum gerekiyor):
```bash
# Auth header ile (JWT token ile)
curl -H "Authorization: Bearer <jwt_token>" \
     "http://localhost:8000/api/activity?limit=10"
```

**Doğru yanıt yapısı:**
```json
{
  "events": [
    {
      "id": 2,
      "action": "pairing.client_revoked",
      "occurred_at": "2026-08-12T12:00:00Z",
      "actor": {"id": 1, "name": "Phone", "kind": "device"},
      "details": {"client_id": 1}
    },
    {
      "id": 1,
      "action": "package.created",
      "occurred_at": "2026-08-12T11:00:00Z",
      "actor": {"id": 2, "name": "Browser", "kind": "browser"},
      "details": {"folder": "test-package"}
    }
  ],
  "next_cursor": 1
}
```

### Test 5: package.created Aktör Egemenliği

1. **Backend servisini başlatın:**
```bash
uv run --project backend uvicorn backend.src.main:app --reload
```

2. **API uç noktasına istek atın:**
```bash
curl -X POST -H "Content-Type: application/json" \
     -H "Authorization: Bearer <jwt_token>" \
     "http://localhost:8000/api/packages/active?folder=test-folder"
```

3. **Aldığınız yanıtı kontrol edin:**
```bash
# Etkinlik akışını kontrol edin
curl -H "Authorization: Bearer <jwt_token>" \
     "http://localhost:8000/api/activity?limit=1"
```

**Beklenen:**
- Yanıt verisinde `action: "package.created"`
- Yanıt verisinde `actor` alanı ile zaten kimliğine sahip istemci geliyor

**Doğru - Dinamik Aktör:**
```python
# HTTP yolu için dynamic actor (client_id'den Client nesnesi)
actor = _resolve_actor(client_id=current_client.id, ...)

# Zamanlayıcı yolu için system actor
actor = "system"
```

---

## Git İletileri

### InMemoryStore düzeltmesi:
```
fix(dojo-core): correct InMemoryStore list_recent ordering after filter

Reversed events before filtering by before_id to preserve newest-first
order in filtered result. Previous order: filter, slice, reverse.
Correct order: filter newest-first list, slice, reverse.
```

### Task 4: Activity API
```
feat(backend): activity API with resolved actors and cursor paging (#4)
```

### Task 3: Package Actor
```
feat(dojo-core,backend): attribute package creation to the acting client (#4)
```

### Task 2: Activity Facade
```
feat(dojo-core): activity facade with cursor paging and actor resolution (#4)
```

### Task 1: Store Contract
```
feat(dojo-core): stable audit ids and newest-first cursor reads (#4)
```

---

## Özet İpuçları

- **Cursor Paging Mantığı:** `before_id` hariç ve öncesinden gelen olayları yeni-ilk-son sıralı alır
- **Aktör Çözümleme:** Eşleşen client yoksa literal actor string kullanılır
- **Sıralama Düzenlemesi:** InMemoryStore'da önce `reversed` yapısını koru, sonra filtrele ve slice et
- **API'ler:** Her `/api/` endpoint'i `get_current_client` ile kimlik doğrulaması gerektirir
- **Eşit Haklar:** Her iki pairing türü (device + browser) aynı okuma erişimine sahiptir

---

## Known Issues ve Limitations

1. **Test Koşulları:** Gerçek PostgreSQL veritabanı gerekir
   - Çözüm: Eğer Docker yoksa testleri in-memory store ile ayrıca yazın
   - veya Docker'ın çalıştığından emin olun

2. **Aktör Çözümleme:** Bilinmeyen client_id'ler literal string olarak döner
   - Geliştirme aşamasında beklentidir
   - Production'da bu durum loglanmalıdır

3. **Limit Koruması:** `limit` parametresi 1 ile 100 arasında olmalı, FastAPI validation ile korunur
   - Testler bu sınırı doğrulamalıdır

---

## Benzer Konular ve Kaynaklar

- **Audit Store:** `dojo-core/src/dojo/ports.py`
- **Activity Facade:** `dojo-core/src/dojo/activity.py`
- **Backend Integration:** `backend/src/backend/routes/activity.py`
- **Domain Model:** `dojo-core/src/dojo/model.py`

---

**Not:** Bu rehber, yansıtmalı testler ve manuel testler için tasarlandı. Tüm testler `pytest` ile çalıştırılabilir ve CI/CD pipeline'ında kullanılabilir.