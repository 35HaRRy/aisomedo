# Meta Bağlantısı ve Bağlantı Sağlığı — Değişiklik Özeti ve Deneme Rehberi

Bu doküman issue #17 (Meta bağlantısı ve bağlantı sağlığı) kapsamında yapılan değişiklikleri özetler ve tamamen PowerShell ile adım adım denemeni sağlar.

## Ne Değişti?

- **Yeni facade `DojoMetaConnection`** (`dojo-core/src/dojo/meta_connection.py`): OAuth başlatma, callback tamamlama, aday Instagram Professional hesap keşfi, açık hesap seçimi, şifrelenmiş token saklama, durum ve `maintain()` (7 gün önce yenileme, günde bir doğrulama).
- **Yeni model ve sabitler** (`dojo-core/src/dojo/model.py`): `MetaCandidate`, `MetaConnectionStatus`, `MetaOAuthAttempt`, sağlık değerleri `not_connected | healthy | refresh_due | reconnect_required`.
- **Yeni istisnalar** (`dojo-core/src/dojo/exceptions.py`): `MetaConnectionError`, `MetaOAuthStateInvalid`, `MetaOAuthFailed`, `MetaAccountInvalid`, `MetaReturnUriInvalid`, `MetaTokenEncryptionError`.
- **Yeni portlar** (`dojo-core/src/dojo/ports.py`): `MetaConnectionStore`, `MetaOAuthProvider`, `TokenCipher`.
- **Şifreleme adaptörü** (`dojo-core/src/dojo/adapters/meta.py`): `FernetCipher` (zorunlu `META_TOKEN_ENCRYPTION_KEY` ile doğrulanmış şifreleme), `StubMetaOAuthProvider` ve iskelet `HttpMetaOAuthProvider`.
- **Bellek ve Postgres depoları** (`dojo-core/src/dojo/adapters/memory.py`, `dojo-core/src/dojo/adapters/db.py`): singleton `meta_connections` (id=1), `meta_oauth_attempts` (hashlenmiş state, tek kullanımlık, 10 dk TTL).
- **Migration** `migrations/versions/0012_meta_connection.py` (alembic head).
- **FastAPI katmanı** (`backend/src/backend/routes/meta.py`, `backend/src/backend/deps.py`, `backend/src/backend/main.py`): `POST /api/meta/oauth/start`, `GET /api/meta/oauth/callback` (herkese açık, state ile kimlik doğrulama), `GET /api/meta/oauth/attempts/{id}`, `POST …/select`, `GET /api/meta/status`. `return_uri` yalnızca `META_ALLOWED_RETURN_URIS` allowlist içindeyse kabul edilir.
- **Worker** (`worker/src/worker/main.py`): her tick başında `meta.maintain()`; hata yayını durdurmaz, paket/plan durumunu değiştirmez.
- **Onboarding** (`dojo-core/src/dojo/setup.py`): `instagram` kontrol listesi öğesi eklendi; `healthy` veya `refresh_due` iken tamamlandı sayılır, `not_connected`/`reconnect_required` iken tamamlanmadı.
- **Bağımlılık** `dojo-core/pyproject.toml`: `cryptography>=42`.

## Davranış Kuralları

- Tek aktif bağlantı; yeniden bağlanma başarısız olursa eski bağlantı korunur (atomik değişim yalnızca `select` başarılı olunca).
- Token hiçbir istemci yanıtında, logda veya audit detayında yer almaz; yalnızca `FernetCipher` ile şifrelenmiş hali saklanır.
- `state` SHA-256 ile saklanır, başlatan client'a bağlıdır, tek kullanımlıktır, 10 dakika geçerlidir.
- Yenileme penceresi 7 gün; günlük uzak doğrulama en fazla bir kez çalışır; geçici ağ hatası sağlığı `reconnect_required` yapmaz, kalıcı hata yapar.
- `META_TOKEN_ENCRYPTION_KEY` eksikse `DojoMetaConnection` ayağa kalkmaz (fail-closed).

## Gereksinimler

- `uv` (Python 3.12)
- Docker (tam test süiti ve compose stack için)
- Postgres: compose ile `5434` portunda yayınlanır.
- `META_TOKEN_ENCRYPTION_KEY` (Fernet, 32 byte base64url) — yoksa backend/worker başlamaz.

## Meta'da Gerekli Değerleri Alma — URL ve İşlem Adımları

Aşağıdaki tüm URL'ler `https://developers.facebook.com` ve bağlı `https://business.facebook.com` üzerindedir. Her adım sonunda hangi ortam değişkenini elde ettiğini yazar.

### 0. Ön Koşullar (Bir Kez)

```powershell
Start-Process "https://www.facebook.com/pages/create"
Start-Process "https://www.instagram.com/accounts/create/"
```

- Bir **Facebook Page** oluştur (örn. `Dojo Page`). URL: `https://www.facebook.com/pages/create` → Kategori, isim, oluştur.
- Bir **Instagram Professional** hesabı oluştur ve **Facebook Page ile bağla**: Instagram mobil uygulama → Profil → Menü → Ayarlar → Hesap → Profesyonel hesaba geç → Business, sonra Facebook Page seç. Alternatif: `https://business.facebook.com/settings/instagram-accounts` → `Add` → Instagram hesabını bağla.
- Instagram hesabın `Professional` ve Page'e bağlı değilse Graph keşfi boş döner.

### 1. Meta Developer Hesabı ve Uygulama Oluştur

```powershell
Start-Process "https://developers.facebook.com/apps/create/"
```

- `https://developers.facebook.com/` → sağ üst `My Apps` → `Create App` → **Business** türü seç (Instagram Graph sadece Business/Other destekler).
- `App Name`: `Dojo Publishing` (örnek), `App Contact Email` gir → `Create App`.
- Sonuçta elde edilenler:
  - `META_APP_ID` → `https://developers.facebook.com/apps/<APP_ID>/settings/basic/` sayfasındaki **App ID**
  - `META_APP_SECRET` → aynı sayfada `Show` ile görünen **App secret** ( `App secret` alanını göster, kopyala)

Güvenlik notu: `App secret` asla istemciye gönderilmez, sadece backend/worker ortam değişkeninde tutulur.

### 2. Facebook Login Ürününü Ekle

```powershell
Start-Process "https://developers.facebook.com/apps/"
```

- Uygulama Dashboard → `Add Product` → `Facebook Login` → `Set Up` → platform olarak **Web** seç.
- Sol menü → `Facebook Login` → `Settings`:
  - **Valid OAuth Redirect URIs** alanına tam olarak backend callback'ini ekle:

```
http://localhost:8000/api/meta/oauth/callback
```

  Prod için ek satıra `https://<senin-domainin>/api/meta/oauth/callback` ekle. URL birebir eşleşmeli; aksi halde `exchange_code` 400 döner.
  - `Save Changes` → bu değer **`META_REDIRECT_URI`** olur.

### 3. Instagram Graph / Instagram Ürününü Ekle

```powershell
Start-Process "https://developers.facebook.com/apps/"
```

- Dashboard → `Add Product` → `Instagram` veya `Instagram Graph API` → `Set Up`.
- Sol menü → `Instagram` → `Basic Display` değil, **Graph API** yolunu kullan (Professional hesaplar için).
- Gerekli izinler (Facebook Login → Permissions):
  - `instagram_basic`
  - `instagram_content_publish`
  - `pages_show_list`
  - `pages_read_engagement`
  - (Ekip için gerekirse `business_management`)

  İzinleri ekle: `App Review` → `Permissions and Features` → ilgili izinlerde `Request` → gelişmiş erişim istemeden önce **Test Users** ile dene.

  Bu izin listesi **`META_OAUTH_SCOPE`** değeridir (gerekmedikçe varsayılanı değiştirme):

```
instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement
```

### 4. Test Kullanıcıları ve Roller

```powershell
Start-Process "https://developers.facebook.com/apps/<APP_ID>/roles/roles/"
```

- `Roles` → `Test Users` → `Add` → Page'e ve Instagram hesabına erişimi olan bir test kullanıcısı oluştur; veya kendi hesabını `Roles` → `App Roles` altında `Admin/Developer` olarak ekle.
- Test kullanıcısı ile `https://www.facebook.com/<PAGE>` ve Instagram bağlantısını doğrula.

### 5. App Mode ve Versiyon

- `Settings` → `Basic` → **App Mode**: geliştirme sırasında `In Development` yeterlidir; prod'da `Live` yapmadan önce `App Review` gerekir.
- **Graph API Version**: `META_GRAPH_VERSION` (ör. `v19.0`) → uygulamanın `Settings` → `Advanced` → `Upgrade API Version` alanından görülür. Kod varsayılanı `v19.0`, değiştirmek istersen:

```powershell
$env:META_GRAPH_VERSION = "v20.0"
```

### 6. Ortam Değişkenlerini Toplu Ayarlama

Artık elindeki değerleri PowerShell'de ayarla:

```powershell
$env:META_APP_ID = "BURAYA_APP_ID_YAZ"
$env:META_APP_SECRET = "BURAYA_APP_SECRET_YAZ"
$env:META_REDIRECT_URI = "http://localhost:8000/api/meta/oauth/callback"
$env:META_GRAPH_VERSION = "v19.0"
$env:META_ALLOWED_RETURN_URIS = "http://localhost:3000/callback,dojo://callback"
# Şifreleme anahtarı (aşağıdaki komutla üret)
$env:META_TOKEN_ENCRYPTION_KEY = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# İsteğe bağlı: scope'u özelleştir
$env:META_OAUTH_SCOPE = "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement"
```

Kalıcılaştırma için `ops\.env` dosyasına ekle (PowerShell satır sonu sorunundan kaçınmak için tek satır):

```powershell
Set-Content -Path "ops\.env" -Value @"
POSTGRES_PASSWORD=dojo
META_APP_ID=$env:META_APP_ID
META_APP_SECRET=$env:META_APP_SECRET
META_REDIRECT_URI=$env:META_REDIRECT_URI
META_GRAPH_VERSION=$env:META_GRAPH_VERSION
META_ALLOWED_RETURN_URIS=$env:META_ALLOWED_RETURN_URIS
META_TOKEN_ENCRYPTION_KEY=$env:META_TOKEN_ENCRYPTION_KEY
META_OAUTH_SCOPE=$env:META_OAUTH_SCOPE
"@
Get-Content ops\.env
```

### 7. Değerleri Doğrulama (Tarayıcı ile Hızlı Kontrol)

- App ayarlarını aç:

```powershell
Start-Process "https://developers.facebook.com/apps/$env:META_APP_ID/settings/basic/"
Start-Process "https://developers.facebook.com/apps/$env:META_APP_ID/fb-login/settings/"
Start-Process "https://developers.facebook.com/apps/$env:META_APP_ID/instagram/basic-display/"
```

- Beklenen:
  - `App ID` ve `App secret` dolu.
  - `Valid OAuth Redirect URIs` içinde `META_REDIRECT_URI` birebir var.
  - `Instagram Graph API` ürünü ekli.
  - Page ↔ Instagram bağlantısı `https://business.facebook.com/settings/instagram-accounts` içinde görünüyor.

### 8. Canlı Domain İçin Ek Adım

Prod domain eklerken:

```powershell
Start-Process "https://developers.facebook.com/apps/$env:META_APP_ID/settings/basic/"
```

- `App Domains` → `senin-domainin.com` ekle.
- `Facebook Login` → `Valid OAuth Redirect URIs` → `https://senin-domainin.com/api/meta/oauth/callback` ekle.
- `META_REDIRECT_URI` ve `META_ALLOWED_RETURN_URIS` prod değerleriyle yeniden başlat.

### 9. Hangi Değer Hangi URL/Kod Yerine Geçer — Özet Tablo

| Ortam Değişkeni | Nereden Alınır (URL) | Ne İşe Yarar |
|---|---|---|
| `META_APP_ID` | `https://developers.facebook.com/apps/<APP_ID>/settings/basic/` → **App ID** | OAuth `client_id`, Graph çağrılarında `app_id` |
| `META_APP_SECRET` | Aynı sayfa → **App secret** → `Show` | `exchange_code` ve `refresh_token` sunucu tarafı doğrulaması |
| `META_REDIRECT_URI` | `Facebook Login` → `Settings` → **Valid OAuth Redirect URIs** | Meta'nın kodu geri göndereceği adres (`/api/meta/oauth/callback`) |
| `META_GRAPH_VERSION` | `Settings` → `Advanced` → API Version | Graph isteklerinin versiyon öneki (`v19.0`) |
| `META_ALLOWED_RETURN_URIS` | Senin belirlediğin web/Android callback allowlist | `POST /oauth/start` içindeki `return_uri` doğrulaması |
| `META_TOKEN_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | Uzun ömürlü token'ı `FernetCipher` ile şifreleme |
| `META_OAUTH_SCOPE` | `App Review` → `Permissions` listesi | `build_auth_url` içindeki `scope` parametresi |

Hazır olduktan sonra `### 1. Anahtarı Üret…` adımına dönüp stack'i başlatabilirsin.

## Adım Adım Deneme (PowerShell)

Tüm örnekler `C:\Users\35.HaRRy\Desktop\Projects\aisomedo` kökünden çalıştırılır. `curl` yerine `Invoke-RestMethod`/`Invoke-WebRequest` kullanılır.

### 1. Anahtarı Üret ve Ortam Değişkenlerini Ayarla

```powershell
Test-Path -LiteralPath "ops\.env"
if (-not $?) { Set-Content -Path "ops\.env" -Value "POSTGRES_PASSWORD=dojo" }
$env:META_TOKEN_ENCRYPTION_KEY = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:META_APP_ID = "dev_app_id"
$env:META_APP_SECRET = "dev_secret"
$env:META_REDIRECT_URI = "http://localhost:8000/api/meta/oauth/callback"
$env:META_ALLOWED_RETURN_URIS = "http://localhost:3000/callback,dojo://callback"
$env:META_GRAPH_VERSION = "v19.0"
$env:META_TOKEN_ENCRYPTION_KEY
```

Kalıcı yapmak için `ops\.env` içine de yaz:

```powershell
Add-Content -Path "ops\.env" -Value ("META_TOKEN_ENCRYPTION_KEY=" + $env:META_TOKEN_ENCRYPTION_KEY)
```

### 2. Tip Kontrolü ve Bellek Tabanlı Testler

```powershell
uv run --project dojo-core mypy dojo-core/src/dojo --ignore-missing-imports
uv run --project backend mypy backend/src/backend --ignore-missing-imports
uv run --project worker mypy worker/src/worker --ignore-missing-imports
uv run --project dojo-core pytest dojo-core/tests/test_pairing.py dojo-core/tests/test_setup.py -v
uv run --project backend pytest backend/tests/test_api.py -v
```

Beklenen: tüm kontroller ve testler yeşil.

### 3. Stack'i Ayağa Kaldır

```powershell
docker compose -f ops/docker-compose.yml up --build -d
Start-Sleep -Seconds 5
docker ps
```

Sadece veritabanı + backend'i yerelde çalıştırmak istersen:

```powershell
docker compose -f ops/docker-compose.yml up -d db
uv run --project backend uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 4. Bootstrap Pairing Kodu Üret

```powershell
uv run --project backend dojo-create-pairing-code create-code
```

Çıktıdaki 8 haneli `CODE` değerini not et.

### 5. Tarayıcı Pairing Yap ve Token Al

```powershell
$CODE = "BURAYA_KODU_YAZ"
$pairBody = @{ code = $CODE; kind = "device"; name = "TestDevice" } | ConvertTo-Json
$pairResp = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/pairing/validate" -ContentType "application/json" -Body $pairBody
$TOKEN = $pairResp.token
$TOKEN
$headers = @{ Authorization = "Bearer $TOKEN" }
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/pairing/me" -Headers $headers | Format-List
```

### 6. Bağlantı Durumunu Gör (Henüz Bağlı Değil)

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/status" -Headers $headers | ConvertTo-Json -Depth 5
# health = not_connected beklenir
```

### 7. OAuth Başlat (Allowlist İçindeki return_uri ile)

```powershell
$startBody = @{ return_uri = "http://localhost:3000/callback" } | ConvertTo-Json
$start = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/meta/oauth/start" -Headers $headers -ContentType "application/json" -Body $startBody
$start | ConvertTo-Json -Depth 5
$authUrl = $start.auth_url
$attemptId = $start.attempt_id
$authUrl
$attemptId
```

Allowlist dışı URI deneyince 422 döner:

```powershell
$badBody = @{ return_uri = "https://evil.example/cb" } | ConvertTo-Json
try { Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/meta/oauth/start" -Headers $headers -ContentType "application/json" -Body $badBody } catch { $_.Exception.Response.StatusCode.Value__ }
# 422 beklenir
```

`return_uri` göndermeden de başlatabilirsin:

```powershell
$start2 = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/meta/oauth/start" -Headers $headers -ContentType "application/json" -Body "{}"
$start2.auth_url
```

### 8. Callback Çağrısı (Stub Sağlayıcı ile)

`auth_url` içindeki `state` parametresini al:

```powershell
Add-Type -AssemblyName System.Web
$uri = [System.Uri]$authUrl
$q = [System.Web.HttpUtility]::ParseQueryString($uri.Query)
$state = $q["state"]
$state
# Stub sağlayıcıda code değeri doğrulanmaz; herhangi bir string kabul edilir
$callbackUri = "http://localhost:8000/api/meta/oauth/callback?state=$state&code=code123"
# Allowlist kullanıldıysa callback 302 redirect döner; redirect'i takip etme
try {
  $cb = Invoke-WebRequest -Uri $callbackUri -MaximumRedirection 0 -ErrorAction Stop
} catch {
  $_.Exception.Response.Headers.Location
}
```

`return_uri` yoksa JSON döner:

```powershell
$uri2 = [System.Uri]$start2.auth_url
$q2 = [System.Web.HttpUtility]::ParseQueryString($uri2.Query)
$state2 = $q2["state"]
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/oauth/callback?state=$state2&code=code123" | ConvertTo-Json
```

### 9. Aday Hesapları Listele

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/oauth/attempts/$attemptId" -Headers $headers | ConvertTo-Json -Depth 5
# candidates içinde ig_user_id, ig_username, page_id, page_name görünür; token görünmez
```

Başka client ile denersen 404:

```powershell
# ikinci bir client oluşturup onun token'ı ile aynı attemptId'yi sorgula -> 404
```

### 10. Hesap Seç ve Bağlantıyı Aktif Et

```powershell
$cands = (Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/oauth/attempts/$attemptId" -Headers $headers).candidates
$chosen = $cands[0].ig_user_id
$selectBody = @{ ig_user_id = $chosen } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/meta/oauth/attempts/$attemptId/select" -Headers $headers -ContentType "application/json" -Body $selectBody | ConvertTo-Json -Depth 5
# health = healthy
```

Geçersiz aday seçimi 422:

```powershell
$badSelect = @{ ig_user_id = "does_not_exist" } | ConvertTo-Json
try { Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/meta/oauth/attempts/$attemptId/select" -Headers $headers -ContentType "application/json" -Body $badSelect } catch { $_.Exception.Response.StatusCode.Value__ }
# 422
```

### 11. Durumu Tekrar Gör (Bağlı)

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/status" -Headers $headers | ConvertTo-Json -Depth 5
# health = healthy, ig_username ve page_name dolu, expires_at dolu, token yok
```

### 12. State Tek Kullanım ve TTL Kontrolü

Aynı state ile callback'i tekrar çağır:

```powershell
try { Invoke-RestMethod -Method Get -Uri $callbackUri } catch { $_.Exception.Response.StatusCode.Value__ }
# 400 beklenir (state already consumed)
```

Sahte state:

```powershell
try { Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/oauth/callback?state=fake123&code=code123" } catch { $_.Exception.Response.StatusCode.Value__ }
# 400
```

### 13. Yeniden Bağlanma Atomik Kalır (Eski Bağlantı Korunur)

Yeni bir OAuth başlat, başarısız bir code ile callback yap, durumun değişmediğini doğrula:

```powershell
$start3 = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/meta/oauth/start" -Headers $headers -ContentType "application/json" -Body $startBody
$q3 = [System.Web.HttpUtility]::ParseQueryString(([System.Uri]$start3.auth_url).Query)
$state3 = $q3["state"]
# Stub'ta bad_code özel olarak reddedilir
try { Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/oauth/callback?state=$state3&code=bad_code" } catch { $_.Exception.Response.StatusCode.Value__ }
# 502 beklenir
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/status" -Headers $headers | Select-Object health, ig_username
# health hala healthy, eski bağlantı korunmuş
```

### 14. Onboarding Kontrol Listesi (Instagram Öğesi)

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/setup" -Headers $headers | ConvertTo-Json -Depth 5
# instagram öğesi complete = true görülmeli (healthy iken)
```

### 15. Korumasız ve Yetkisiz Erişim

```powershell
try { Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/meta/status" } catch { $_.Exception.Response.StatusCode.Value__ }
# 401
try { Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/meta/oauth/start" -ContentType "application/json" -Body "{}" } catch { $_.Exception.Response.StatusCode.Value__ }
# 401
```

### 16. Temizlik

```powershell
docker compose -f ops/docker-compose.yml down
Remove-Item Env:META_TOKEN_ENCRYPTION_KEY -ErrorAction SilentlyContinue
```

## Bilinen Sınırlar

- `HttpMetaOAuthProvider` iskelettir; canlı Meta Graph çağrıları stub ile simüle edilir, gerçek ağ doğrulaması yapılmaz.
- `build_meta` iki yerde (backend ve worker) çoğullanmıştır; tek bir fabrika modülüne taşınabilir.
- Sağlık `Enum` yerine `str` sabitleriyle tutulur; `Data Clumps` (`upsert_active` 10 parametre) ve `Feature Envy` (`meta._store.get_meta_attempt`) kokularına sahiptir.
- Worker `maintain()` geçici hatayı `"transient"/"timeout"/"network"` alt dizesine göre ayırır.
