# Dağıtım ve Tek-Scheduler Rehberi (Issue #21)

Bu rehber `feat/issue-21-deployment` dalındaki değişiklikleri özetler ve adım adım
denemeyi tarif eder. Tüm deneme adımları ya tarayıcıda ya da yalnız PowerShell
komutlarıyla yapılır; python ve SQL kodu gerekmez.

## Neler değişti

**Üretim dağıtımı (yeni dosyalar):**

- `ops/docker-compose.prod.yml` — bağımsız üretim tabanı: `db`, `init`, `backend`,
  `worker`, `gateway` servisleri. `db` ve `backend` dışarıya port açmaz. Veriler
  isimli volume'larda durur (`db-data`, `media-data`, `caddy-data`).
- `ops/docker-compose.dedicated.yml` — tek alan adı modu: Caddy 80/443 portlarını
  alır, TLS sertifikasını kendisi üretir ve yeniler.
- `ops/docker-compose.existing-proxy.yml` — mevcut ters-vekil modu: ağ geçidi yalnız
  `127.0.0.1:9080` adresinden düz HTTP sunar, TLS'yi üst vekil üstlenir.
- `ops/gateway/Dockerfile` + `ops/gateway/Caddyfile` — derlenmiş web önyüzü ile
  Caddy'yi tek imajda birleştirir. `/api/*`, `/pub/*`, `/health` aynen backend'e
  gider; geri kalan her yol SPA'ya düşer (`index.html`). Medya volume'u bağlı değildir.
- `ops/verify-prod.sh` — 48 denetimli doğrulama betiği (config, imaj derleme, Caddy
  geçerliliği, veri kalıcılığı).
- `docs/ops/deployment.md` — operatör belgesi (kurulum, iki mod, ortam tablosu,
  sağlık denetimi, volume ömrü).

**Tek-scheduler liderliği (davranış):**

- `dojo-core/src/dojo/scheduler.py` (yeni) — her zamanlama turunda PostgreSQL
  advisory kilidi deneyen liderlik kapsamı. Kilidi alamayan worker o turda iş
  üretmez ama hazır işleri işlemeye devam eder.
- `dojo-core/src/dojo/adapters/db.py` — düzenli vade ve aktif render için kısmi
  benzersiz indexler; `create_job_once` / `create_review_once` yarış-güvenli
  ekleme (çift kayıt + çift denetim kaydı engellenir).
- `dojo-core/migrations/versions/0014_emission_idempotency.py` + `dojo-core/src/dojo/schema.py`
  (`python -m dojo.schema`) — serileştirilmiş şema başlatıcı; çakışan satırları
  silmeden raporlayan uçuş-öncesi denetim içerir.
- `worker/src/worker/main.py` — sınıflı tick: üretim liderlik altında, iş çalıştırma
  atomsal hak talebiyle eşzamanlı, tekil işlemler (mutabakat, hatırlatma, bakım)
  yalnızca liderde; SIGTERM sınırlı kapanış; `SKIP_CREATE_ALL=1` ile üretim DDL kapalı.
- `backend/src/backend/proxy.py` (yeni) — tek ASGI güven katmanı: yönlendirme
  başlıkları yalnız `TRUSTED_PROXIES` içinden gelirse sayılır. Açık köken
  (`PUBLIC_HTTPS_ORIGIN`) backend VE worker imza/OAuth üreticilerine bağlandı.

## Gerekenler

- Docker Desktop çalışır durumda.
- Repo kökü: `C:\Users\35.HaRRy\Desktop\Projects\aisomedo` (aşağıdaki komutlar
  PowerShell'de bu dizinden çalıştırılır).

## Deneme A — tarayıcıda (yerel, mevcut-vekil modu)

Gerçek alan adı ve TLS gerekmez; ağ geçidi `http://localhost:9080` adresinden
düz HTTP sunar.

**1. Deneme ortam dosyası oluştur:**

`ops/.env.deneme` adında dosya aç, içine şunları yaz:

```text
POSTGRES_PASSWORD=deneme-sifresi-123
POSTGRES_DB=dojo
POSTGRES_USER=dojo
DOMAIN=localhost
PUBLIC_BASE_URL=http://localhost:9080
SIGNED_URL_SECRET=deneme-imza-sirri-1234567890
COOKIE_SECURE=false
GATEWAY_HTTP_PORT=9080
TRUSTED_PROXIES=private_ranges
META_APP_ID=
META_APP_SECRET=
META_REDIRECT_URI=
META_GRAPH_VERSION=v26.0
META_ALLOWED_RETURN_URIS=
META_TOKEN_ENCRYPTION_KEY=
META_OAUTH_SCOPE=instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement
MEDIA_ROOT=
WORKER_INTERVAL_SECONDS=30
```

**2. Yığını başlat (ilk seferde imaj derler, birkaç dakika sürer):**

```powershell
docker compose --env-file ops/.env.deneme -p dojo-deneme -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml up -d --build
```

**3. Tarayıcıda sırayla aç ve beklenen sonucu gör:**

| Adres | Beklenen sonuç | Ne kanıtlar |
|---|---|---|
| `http://localhost:9080/` | "Dojo Yayıncılık" başlıklı sayfa (200) | Önyüz sunuluyor |
| `http://localhost:9080/health` | `{"status":"ok"}` (200) | Backend sağlıklı, ağ geçidi iletiyor |
| `http://localhost:9080/api/packages/active` | `{"detail":"unauthorized"}` (401) | API aynen iletiliyor, SPA'ya düşmüyor |
| `http://localhost:9080/pairing` | Önyüz sayfası (200) | Derin bağlantı SPA'ya düşüyor |
| `http://localhost:9080/pub/kotu-jeton` | İmza hatası JSON (404) | İmzalı-dosya yolu SPA'ya düşmüyor |

**4. (İsteğe bağlı) Çift worker:** iki worker aynı anda çalışsa bile zamanlayıcı
tek lider seçer. PowerShell'de ölçekle, `ps` çıktısında `worker-1` ve `worker-2`
görünür; loglarda `ERROR` satırı olmaz:

```powershell
docker compose --env-file ops/.env.deneme -p dojo-deneme -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml up -d --scale worker=2 --no-recreate
```

**5. Kapat (veriler `dojo-deneme_*` volume'larında kalır):**

```powershell
docker compose --env-file ops/.env.deneme -p dojo-deneme -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml down
```

Deneme verisini tamamen silmek için sonuna `-v` ekle. Gerçek kurulumda proje adı
`dojo-prod` sabittir; başka isim altında başlatmak boş volume'larla yeni kurulum
sayılır.

## Deneme B — yalnız PowerShell (tarayıcısız)

Aynı yığın ayaktayken (Deneme A adım 2), her tarayıcı denetiminin karşılığı:

```powershell
(Invoke-WebRequest -Uri http://localhost:9080/health -UseBasicParsing).Content
try { Invoke-WebRequest -Uri http://localhost:9080/api/packages/active -UseBasicParsing } catch { $_.Exception.Response.StatusCode.value__; $_.ErrorDetails.Message }
(Invoke-WebRequest -Uri http://localhost:9080/ -UseBasicParsing).StatusCode
(Invoke-WebRequest -Uri http://localhost:9080/pairing -UseBasicParsing).StatusCode
try { Invoke-WebRequest -Uri http://localhost:9080/pub/kotu-jeton -UseBasicParsing } catch { $_.Exception.Response.StatusCode.value__; $_.ErrorDetails.Message }
```

Servis sağlığı ve loglar:

```powershell
docker compose --env-file ops/.env.deneme -p dojo-deneme -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml ps
docker compose --env-file ops/.env.deneme -p dojo-deneme -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml logs worker --tail 5 --no-log-prefix
```

Config doğrulama (sır basmadan sözdizimi denetimi):

```powershell
docker compose --env-file ops/.env.deneme -p dojo-deneme -f ops/docker-compose.prod.yml -f ops/docker-compose.dedicated.yml config --quiet
docker compose --env-file ops/.env.deneme -p dojo-deneme -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml config --quiet
```

## Notlar

- Gerçek `https` sertifika üretimi yalnız alan adı + DNS + erişilebilir VPS ile
  denenir; yerel denemede TLS devre dışıdır, bu beklenen durumdur.
- Üretimde `COOKIE_SECURE=true` ve `https` köken zorunludur; operatör yazım
  hatasında servis açıkça hata verip açılmaz (sessiz `http` dönüşü yok).
- `init` servisi şemayı bir kez kurar; backend/worker `SKIP_CREATE_ALL=1` ile
  başlar. `down` sonrası `up` veri kaybetmez; volume adları `dojo-prod_*`
  önekiyle sabittir.
