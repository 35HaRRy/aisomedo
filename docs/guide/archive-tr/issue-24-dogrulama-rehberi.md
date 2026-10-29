# Rehber: OpenAPI sözleşmesi ve istemci sürüm denetimi doğrulama (#24)

Bu rehber, #24 ile gelen değişiklikleri özetler ve her kabul kriterini
denemen için adım adım tarif eder. Tarayıcıda yapılabilen her şey tarayıcıda;
geri kalanı `Invoke-RestMethod` PowerShell komutlarıyla (Python/SQL yok).

## 1. Ne değişti?

- **Sözleşme tek kaynak:** `backend/openapi.json` FastAPI'den üretilir ve
  repoda commitlidir (`backend/scripts/export_openapi.py`).
- **Üretilmiş istemciler:** Aynı sözleşmeden TypeScript
  (`web/src/api/openapi.ts`) ve Kotlin
  (`android/.../api/GeneratedApi.kt`) istemcileri üretilir
  (`backend/scripts/generate_clients.py`). CI, yeniden üretip fark bulursa
  (`git diff --exit-code`) kırmızıya döner.
- **Sürüm politikası:** `backend/src/backend/versions.py`. Sunucu güncel (N)
  ve bir önceki (N-1) Android sürümünü destekler. Ayarlar:
  `ANDROID_CURRENT_VERSION_CODE`, `ANDROID_MIN_VERSION_CODE` (varsayılan
  `max(1, current-1)`), `ANDROID_UPDATE_URL` (imzalı APK'nin HTTPS adresi).
- **Herkese açık uç:** `GET /api/compat` → `api_version`,
  `android_min_version_code`, `android_current_version_code`, `update_url`.
- **Güncelleme kapısı:** `ClientVersionMiddleware`
  (`backend/src/backend/main.py`). `Bearer` taşıyan `/api/*` isteklerinde
  `X-Android-Version-Code` başlığı yoksa/geçersizse/eskiyse `426` ve
  `{"detail":"update_required","update_url":...}` döner. Tarayıcı
  çerez seansları asla engellenmez; `/api/compat`, `/health`, `/ready` ve
  Meta OAuth geri aramaları muaftır.
- **Android:** `MainActivity` açılışta `/api/compat` sorar; kurulu sürüm
  minimumun altındaysa indirme düğmeli bloklayan güncelleme ekranı gösterir.
  `ApiConfig.deviceHeaders()` sonraki API çağrıları için sürüm başlığını üretir.
- **Web:** `ContractBanner` üretilmiş `CONTRACT_VERSION` ile sunucunun
  `api_version` değerini karşılaştırır; uyumsuzsa "sayfayı yenile" bandı gösterir.

## 2. Hazırlık (bir kez)

PowerShell'i repo kökünde aç (`C:\...\aisomedo`):

```powershell
Copy-Item ops/.env.example ops/.env
Add-Content ops/.env "ANDROID_CURRENT_VERSION_CODE=5"
Add-Content ops/.env "ANDROID_UPDATE_URL=https://example.com/dojo-latest.apk"
docker compose --env-file ops/.env -f ops/docker-compose.yml up -d --build db backend
docker compose --env-file ops/.env -f ops/docker-compose.yml ps
```

(`ops/.env` zaten varsa ilk satırı atla; `ANDROID_` satırları yoksa ekle.)
`backend` servisi `healthy` olana kadar bekle; bu kurulumda güncel sürüm 5,
desteklenen minimum 4 demektir.

## 3. Adım: minimum sürümü tarayıcıda gör

Tarayıcıda aç:

```text
http://localhost:8000/api/compat
```

Beklenen (biçimli) yanıt:

```json
{
  "android_current_version_code": 5,
  "android_min_version_code": 4,
  "api_version": "0.1.0",
  "update_url": "https://example.com/dojo-latest.apk"
}
```

Kabul kriteri "minimum sürüm API ile açık" — işte bu.

## 4. Adım: sağlık uçları muaftır (tarayıcı)

```text
http://localhost:8000/health
```

`{"status":"ok"}` döner. Güncel olmayan bir istemci bile bu uca ve
`/api/compat` ucuna ulaşabilir; kapı sadece sürümlü API çağrılarını tutar.

## 5. Adım: güncel istemci kapıdan geçer (PowerShell)

Sürüm 5 (`N`) ile istek at. Kimlik sahte olsa bile kapıdan geçip kimlik
denetimine takılmalı (`401`, `426` değil):

```powershell
try {
  Invoke-RestMethod http://localhost:8000/api/packages/active -Headers @{Authorization="Bearer deneme"; "X-Android-Version-Code"="5"}
} catch {
  $_.Exception.Response.StatusCode.value__
}
try {
  Invoke-RestMethod http://localhost:8000/api/packages/active -Headers @{Authorization="Bearer deneme"; "X-Android-Version-Code"="4"}
} catch {
  $_.Exception.Response.StatusCode.value__
}
```

İkisi de `401` vermeli (sürüm 4 = N-1, hâlâ destekleniyor).

## 6. Adım: eski istemci güncelleme yanıtı alır (PowerShell)

```powershell
try {
  Invoke-RestMethod http://localhost:8000/api/packages/active -Headers @{Authorization="Bearer deneme"; "X-Android-Version-Code"="2"}
} catch {
  $_.Exception.Response.StatusCode.value__
  $_.ErrorDetails.Message
}
```

Beklenen kod + gövde:

```text
426
{"detail":"update_required","update_url":"https://example.com/dojo-latest.apk"}
```

Kabul kriteri "uyumsuz istemci engellenir + güncelleme istenir" — işte bu.
Kimlik sahteyken bile `426` dönmesi özellikle doğrudur: sürüm kapısı kimlik
denetiminden önce çalışır, böylece eski istemci güncelleme adresini her
koşulda öğrenir.

## 7. Adım: başlıksız eski istemci de engellenir (PowerShell)

```powershell
try {
  Invoke-RestMethod http://localhost:8000/api/packages/active -Headers @{Authorization="Bearer deneme"}
} catch {
  $_.Exception.Response.StatusCode.value__
}
```

`426` beklenir. Başlığı hiç göndermeyen (güncellememiş) istemci
sessizce geçemez.

## 8. Adım: web bandı (tarayıcı)

Ayrı bir PowerShell'de:

```powershell
npm --prefix web install
npm --prefix web run dev
```

Tarayıcıda `npm`'in yazdığı adresi aç (genelde `http://localhost:5173`).
"Dojo Yayıncılık" başlığı görünür ve **güncelleme bandı görünmez** — bu,
üretilmiş `CONTRACT_VERSION` ile sunucunun `api_version` değerinin eşleştiği
anlamına gelir. Bant yalnızca sözleşme değişip web istemcisi yenilenmediğinde
çıkar.

## 9. Adım: drift koruması (salt okunur)

CI'daki `contract` işi (`.github/workflows/ci.yml`) sözleşmeyi ve istemcileri
yeniden üretip `git diff --exit-code` ile farkta başarısız olur; ayrıca
`backend/tests/test_contract.py` koşar. Yerel karşılıkları:

```powershell
git status --short
```

Temiz çıktı = commitli sözleşme ve istemciler güncel üretimi yansıtıyor.
(Yeniden üretim betikleri Python çalıştırır; bu rehberin "komutlarda Python
yok" kuralı için CI'ı kaynak kabul et.)

## 10. Temizlik

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml down
```

## Kabul kriteri eşleşmesi

- [x] Kotlin + TypeScript istemciler OpenAPI'den üretiliyor; drift CI'ı kırıyor → Adım 2, 9
- [x] Minimum desteklenen sürüm API ile açık → Adım 3
- [x] Uyumsuz istemci engellenip güncelleme ekranına yönlendiriliyor → Adım 6, 7 (sunucu tarafı); Android ekranı `assembleDebug` ile derleme-doğrulamalı
