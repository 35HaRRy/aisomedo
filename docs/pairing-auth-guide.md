# Pairing & Equal-Privilege Auth — Değişiklik Özeti ve Deneme Rehberi

Bu doküman issue #3 (pairing ve eşit yetkili oturum açma) kapsamında yapılan
değişiklikleri özetler ve adım adım denemeni sağlar.

## Ne Değişti?

- **DojoPairing facadesi** (`dojo-core/src/dojo/pairing.py`): tek kullanımlık
  onay kodu üretme/doğrulama, cihaz ve tarayıcı oturumları, liste/iptal.
- **Yeni model, portlar, adaptörler** (`model.py`, `ports.py`,
  `adapters/secrets.py`, `adapters/memory.py`, `adapters/db.py`):
  `PairingCode`, `Client`, SHA-256 hashleme, `PostgresStore`/`InMemoryStore`.
- **Migration** `migrations/versions/0002_pairing.py` (alembic head).
- **FastAPI katmanı** (`backend/src/backend/routes/pairing.py`, `deps.py`,
  `main.py`): `/api/pairing/*` rotaları, `get_current_client` bağımlılığı,
  `/health` ve `POST /api/pairing/validate` hariç tüm `/api` korunuyor.
- **Per-IP throttle**: `POST /api/pairing/validate` üzerinde 10 istek/dakika.
- **CLI**: `dojo-create-pairing-code create-code` ile bootstrap kodu üretme
  (actor = `"cli"`).
- **Eşit yetki**: rol yok; her doğrulanmış client kod üretebilir, client
  listeleyebilir/iptal edebilir, iş rotalarını kullanabilir.
- **Güvenlik**: ham kod/token asla saklanmaz (yalnızca SHA-256 hash);
  tarayıcı oturumu HttpOnly+Secure+SameSite=Lax cookie; 10 dk TTL, tek kullanım;
  iptal anında devreye girer; tarayıcı oturumu 30 gün boşta kalırsa düşer.

## Gereksinimler

- `uv` (Python 3.12)
- Docker (tam test süiti ve compose stack için)
- Postgres: compose ile 5433 portunda yayınlanır; kod varsayılanları
  `localhost:5433` (bkz. `ops/docker-compose.yml`).

## Adım Adım Deneme

### 1. Testleri Çalıştır

```bash
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
```

Lint + tip kontrolü:

```bash
uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend ruff check backend/src backend/tests
uv run --project backend mypy backend/src/backend
```

Beklenen: tüm testler yeşil, hiçbir lint/mypy bulgusu yok.

### 2. Stack'i Ayağa Kaldır

```bash
# ops/.env içinde POSTGRES_PASSWORD tanımla (zorunlu)
echo "POSTGRES_PASSWORD=dojo" > ops/.env
docker compose -f ops/docker-compose.yml up --build -d
```

Not: Yalnızca veritabanını çalıştırmak istersen:

```bash
docker compose -f ops/docker-compose.yml up -d db
# host üzerinde çalıştır:
uv run --project backend uvicorn backend.main:app --port 8000
```

### 3. Bootstrap Onay Kodu Üret (CLI)

```bash
uv run --project backend python -m backend.cli create-code
```

Alternatif (konsol script'i): `uv run --project backend dojo-create-pairing-code create-code`

Çıktıda 8 haneli kod ve son kullanma zamanı görünür. İlk client'ı doğrulamak
için bu kod gerekli (actor = `"cli"`).

### 4. Cihaz Pairing (Bearer Token)

```bash
CODE="C1HK2P3T"  # yukarıdaki kodu yaz
curl -s -X POST http://localhost:8000/api/pairing/validate \
  -H "Content-Type: application/json" \
  -d "{\"code\":\"$CODE\",\"kind\":\"device\",\"name\":\"Phone\"}"
```

Yanıtta `token` döner. Token ile korumalı rotalara eriş:

```bash
TOKEN="..."
curl -s http://localhost:8000/api/pairing/me -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:8000/api/packages/active -H "Authorization: Bearer $TOKEN"
```

### 5. Tarayıcı Pairing (Cookie)

```bash
curl -s -c cookies.txt -b cookies.txt -X POST http://localhost:8000/api/pairing/validate \
  -H "Content-Type: application/json" \
  -d "{\"code\":\"$CODE\",\"kind\":\"browser\",\"name\":\"Browser\"}"
```

Cookie `cookies.txt` içine yazılır; sonraki isteklerde kullanılır:

```bash
curl -s -b cookies.txt http://localhost:8000/api/pairing/me
```

### 6. Kodu Tekrar Kullan — Tek Kullanım

Aynı kodla ikinci bir validate 401 döner:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/pairing/validate \
  -H "Content-Type: application/json" \
  -d "{\"code\":\"$CODE\",\"kind\":\"device\",\"name\":\"X\"}"
# → 401
```

### 7. Client Listele ve İptal Et

```bash
curl -s http://localhost:8000/api/pairing/clients -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:8000/api/pairing/clients/2/revoke -H "Authorization: Bearer $TOKEN"
# iptal edilen client'ın bir sonraki isteği 401 döner
```

### 8. Yeni Kod Üret (Kimliği Doğrulanmış)

```bash
curl -s -X POST http://localhost:8000/api/pairing/codes -H "Authorization: Bearer $TOKEN"
# → {code, expires_at, ttl_seconds}
```

### 9. Throttle

Ardışık 10 başarısız validate sonrası 11. istek 429 döner:

```bash
for i in $(seq 1 11); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/pairing/validate \
    -H "Content-Type: application/json" -d '{"code":"aaaaaaaa","kind":"device","name":"X"}'
done
# 401 x10, 429
```

Not: throttle bellekte (in-memory) ve IP başına; backend yeniden başlatılınca sıfırlanır.

### 10. Temizlik

```bash
docker compose -f ops/docker-compose.yml down
```

## Bilinen Sınırlar (Minor)

- Throttle, IP başına hafıza listesi biriktirir (uzun ömürlü süreçlerde IP
  sayısı arttıkça büyür).
- İptalde eşzamanlı (TOCTOU) çift audit kaydı ihtimali vardır.
- Geçersiz `Authorization: Bearer` başlığı varsa, geçerli cookie varsa o kullanılır.
