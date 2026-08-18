# Marka (Branding) ve Taslak Yapılandırması — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #11** (Branding and draft configuration) kapsamında yapılan
değişiklikleri özetler ve bunları adım adım deneyebilmen için PowerShell komutlarını
gösterir. Tüm komutlar PowerShell'dir; Python kodu içermez.

## 1. Değişiklik Özeti

### Amaç

`Dojo Paylaşım Paketi`'ndeki Reel'e uygulanacak marka bilgilerini yapılandırmayı ve bu
bilgilerin her pakete kopyalanıp paket bazında değiştirilebilmesini sağlar:

- **Marka varsayılanları (global)** — logo, isteğe bağlı intro/outro varlıkları ve süreleri,
  ve alt yazı (caption) şablonu. Kurulum genelinde tek yerden ayarlanır, ayar deposunda
  (`SettingsStore`) saklanır.
- **Taslağa kopyalama** — yeni bir aktif paket oluşturulurken global marka varsayılanları
  paketin manifest'ine kopyalanır.
- **Paket bazında geçersiz kılma (override)** — her paketin intro/outro'su ve alt yazısı
  global değerlere dokunmadan değiştirilebilir. Değişiklik `manifest.json` üzerinde saklanır;
  ayrıca `render_revision` temizlenir (render'ın yeniden üretilmesi gerektiği anlaşılır).
- **Logo zorunlu** — `publish` çağrısı, aktif paketin veya global logo ayarlanmadan
  `LogoNotConfigured` hatası verir. (Gerçek filigran işleme #12'dir.)
- **Onboarding kontrol listesi** — `DojoSetup.checklist()` artık `logo` ve `caption_template`
  maddelerini içerir; `is_ready` bu maddeler tamamlanmadan `True` olmaz.

### Yapılanlar (`development` branch, commit `608761d`)

| Alan | İçerik |
|---|---|
| `dojo-core/src/dojo/model.py` | `BrandingConfig` (frozen dataclass): `logo_asset`, `intro_asset`, `intro_duration`, `outro_asset`, `outro_duration`, `caption_template` |
| `dojo-core/src/dojo/exceptions.py` | `LogoNotConfigured(DojoError)` |
| `dojo-core/src/dojo/__init__.py` | Yeni dışa aktarımlar |
| `dojo-core/src/dojo/publishing.py` | `get/set_branding_defaults`, `_seed_draft_defaults`, `get_draft_branding`, `get_draft_caption`, `set_branding`, `set_caption`, `_assert_logo_configured`; `publish` logo koruması |
| `dojo-core/src/dojo/setup.py` | `checklist()` → `logo` + `caption_template` maddeleri |
| `backend/src/backend/routes/packages.py` | `GET/PUT /api/packages/active/caption`, `GET/PUT /api/packages/active/branding` |
| `backend/src/backend/routes/settings.py` (yeni) | `GET/PUT /api/settings/branding` (global varsayılanlar) |
| `backend/src/backend/cli.py` | `set-branding`, `set-caption-template` alt komutları |
| Testler | `test_branding.py` (yeni, 13), `test_setup.py`, `test_publishing.py`, `test_api.py`, `test_cli.py` |
| Doküman | Tasarım + plan dokümanları |

### Önemli tasarım kararları

- **Logo koruması taslağı önceliklendirir**: `_assert_logo_configured` önce aktif
  taslağın kendi `branding.logo_asset` değerine bakar; taslakta logo yoksa (`None`) global
  logoya düşer. Yani taslak global olmadan da kendi logosunu koyabilir.
- **Global değerler asla değişmez**: paket bazında `set_branding`/`set_caption` yalnızca
  o paketin manifest'ini etkiler; global ayarlara dokunmaz.
- **Alt yazı şablonu**: global şablondan taslağa kopyalanır, pakette serbestçe düzenlenir.
  Değiştirilebilir alan adları sabit bir kelime dağarcığına kilitlenmez (açık uçludur).
- **Veri manifest üzerinde**: yeni DB migration'ı YOK; marka/alt yazı dosya sistemindeki
  `manifest.json` içinde saklanır.
- **Render bayatlaması**: marka veya alt yazı değişince `render_revision` temizlenir.

### HTTP durum kodları

| Senaryo | Kod |
|---|---|
| Marka/alt yazı başarılı | `200` |
| Kimlik doğrulanmamış istek | `401` |
| Aktif paket yok | `404` |

## 2. Ön Hazırlık

1. **Docker'ı başlatın** (PostgreSQL için; CLI komutları gerçek DB ister).
2. **Bağımlılıkları yükleyin** (repo kökünden):
```powershell
uv sync
```

## 3. Test Adımları

### Adım 1: Dojo-core testleri (marka seam'i)

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_branding.py -v
```

Beklenen (**13 test geçer**):
- `test_*_defaults_*` — global varsayılanlar ayarlanıp okunur, audit `branding.defaults_updated`.
- `test_*_seed_*` — yeni pakete global değerler kopyalanır; şablon yoksa alt yazı boş kalır.
- `test_set_branding_*` — paket bazında marka override'ı global değerleri değiştirmez.
- `test_set_caption_*` — paket alt yazısı düzenlenir, global şablon aynı kalır.
- `test_*_render_revision_*` — düzenlemeler `render_revision`'ı temizler.

### Adım 2: Backend API testleri (rota sözleşmeleri)

```powershell
uv run --project backend pytest backend/tests/test_api.py -v -k "branding or caption"
```

Beklenen (**4 test geçer**):
- `test_*_require_auth` — marka/alt yazı rotaları kimlik doğrulamadan `401`.
- `test_branding_defaults_via_api` — global marka `200` ile okunur/yazılır.
- `test_caption_via_api_*` — taslak alt yazısı API'den set edilir, global değişmez.

### Adım 3: CLI testleri

```powershell
uv run --project backend pytest backend/tests/test_cli.py -v -k "branding or caption"
```

Beklenen (**2 test geçer**): `set-branding` ve `set-caption-template` komutları çalışır,
audit `cli` olarak işaretlenir.

### Adım 4: Tüm paketlerin tam takımları

```powershell
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
```

Beklenen: dojo-core **190 geçer, 2 atlanır**, backend **59 geçer**. (2 atlama
docker/ffmpeg gerekli işleme testleridir; onlar CI'da doğrulanır.)

### Adım 5: Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src/dojo dojo-core/tests/test_branding.py
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend ruff check backend/src/backend backend/tests
uv run --project backend mypy backend/src/backend
```

Beklenen: hepsi temiz.

## 4. Manuel Deneme (Uçtan Uca — CLI)

CLI komutları gerçek PostgreSQL'e bağlanır (`localhost:5433`, varsayılan
`postgresql+psycopg://dojo:dojo@localhost:5433/dojo`). DB hazırsa:

1. **Global marka varsayılanlarını ayarlayın** (logo + intro/outro):
```powershell
uv run --project backend dojo-settings set-branding --logo-asset "logo.png" --intro-asset "intro.mp4" --intro-duration 2.5 --outro-asset "outro.mp4" --outro-duration 1.5
```
Beklenen: `branding defaults saved`.

2. **Sadece logo ayarlayın** (diğerleri zaten set edildiyse korunur):
```powershell
uv run --project backend dojo-settings set-branding --logo-asset "logo.png"
```
Beklenen: `branding defaults saved`. (Not: komut ayar deposuna yazdığı için `--logo-asset`
vermeyip yalnız `--intro-asset` verirseniz diğer anahtarları etkilemez; her alt komut
yalnızca verdiğiniz değerleri günceller.)

3. **Alt yazı şablonunu ayarlayın**:
```powershell
uv run --project backend dojo-settings set-caption-template --text "Bugünün dojo anısı"
```
Beklenen: `caption template saved`.

## 5. Manuel Deneme (Uçtan Uca — API)

FastAPI uygulamasını başlatın, bir cihaz eşleştirip token alın, sonra:

1. **Değişkenleri kurun**:
```powershell
$base = "http://localhost:8000"
$token = "<pairing-token>"
$H = @{ Authorization = "Bearer $token" }
```

2. **Global marka varsayılanlarını görün**:
```powershell
Invoke-RestMethod -Method Get -Uri "$base/api/settings/branding" -Headers $H
```
   - CLI ile ayarladığınız `logo_asset`, `intro_asset`, `caption_template` vb. döner.

3. **Global marka varsayılanlarını güncelleyin**:
```powershell
$body = [System.Text.Encoding]::UTF8.GetBytes((@{ logo_asset = "logo.png"; caption_template = "Bugünün dojo anısı"; intro_asset = "intro.mp4"; intro_duration = 2.5; outro_asset = "outro.mp4"; outro_duration = 1.5 } | ConvertTo-Json))
Invoke-RestMethod -Method Put -Uri "$base/api/settings/branding" -Headers $H -ContentType "application/json" -Body $body
```
   - `200`; güncellenen varsayılanlar yankılanır.

4. **Aktif paket oluşturun** (varsa aynısını döndürür):
```powershell
Invoke-RestMethod -Method Get -Uri "$base/api/packages/active" -Headers $H
```

5. **Aktif paketin markasını görün** (global değerler kopyalanmış olmalı):
```powershell
Invoke-RestMethod -Method Get -Uri "$base/api/packages/active/branding" -Headers $H
```

6. **Aktif paketin alt yazısını görün** (şablon kopyalanmış olmalı):
```powershell
Invoke-RestMethod -Method Get -Uri "$base/api/packages/active/caption" -Headers $H
```

7. **Paket bazında alt yazıyı değiştirin** (global'e dokunmadan):
```powershell
$body = @{ caption = "Bu pakete özel yazı" } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$base/api/packages/active/caption" -Headers $H -ContentType "application/json" -Body $body
```
   - `200`; `caption` güncellenir. Ardından Adım 2'deki global `caption_template`'in
     değişmediğini teyit edin.

8. **Paket bazında markayı geçersiz kılın**:
```powershell
$body = @{ branding = @{ intro_asset = "ozel-intro.mp4" } } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$base/api/packages/active/branding" -Headers $H -ContentType "application/json" -Body $body
```
   - `200`; paket markası yalnız `intro_asset` için güncellenir, diğer alanlar korunur.

9. **Logo korumasını deneyin** (logo hiç ayarlanmadıysa `publish` reddeder):
```powershell
try { Invoke-RestMethod -Method Post -Uri "$base/api/packages/active/publish" -Headers $H }
catch { $_.Exception.Response.StatusCode.value__ }
```
   - Logo set edilmediyse `LogoNotConfigured` tetiklenir (publish henüz #18 kapsamında
     stub olduğu için tam davranış kod üzerinden doğrulanır).

## 6. Git Geçmişi

```powershell
git log --oneline -3
```

```text
608761d feat(dojo): branding and draft configuration (#11)
bd05be4 docs(spec): clarify set_trims rejects unknown/non-video ids (#10)
41eb8db feat(backend): montage order, trims, and status routes (#10)
```

## 7. Known Issues ve Sınırlamalar

- **Gerçek filigran yok**: `publish` yalnızca logo ayarlı olup olmadığını kontrol eder;
  logonun frame'lere basılması #12 kapsamındadır.
- **`publish` henüz stub**: gerçek yayın akışı #18'e bırakılmıştır; logo koruması bu
  stub'ın önünde durur.
- **Manifest yazımı atomik değildir**: `_write_manifest` doğrudan yazar; işlem ortasında
  çökme manifest'i bozabilir (tasarım kararı, out of scope).
- **Global varsayılanlar yalnız CLI/API**: şablon alanları, onboarding sırasında
  yapılandırma veya rehberli kurulumla da doldurulabilir; şu an tek kaynak CLI + API'dir.
- **Kapsam dışı**: Web UI (#26) ve Android (#32) bu ticket'ta yok. Değiştirilebilir
  şablon alan adları bilinçli olarak sabitlenmedi.