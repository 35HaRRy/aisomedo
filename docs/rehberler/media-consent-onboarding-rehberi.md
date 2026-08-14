# Media-consent ve İlk Kurulum (Onboarding) — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #5** (Media-consent policy and guided first-run onboarding)
kapsamında yapılan değişiklikleri özetler ve bunları adım adım deneyebilmen için
komutları gösterir.

## 1. Değişiklik Özeti

### Amaç
Kurulum genelinde tek bir medya-onay (consent) politikası tanımlanabilir, her
politika sürümü için **kurulum genelinde bir kez** onay alınır, yeni eşleşen
cihazlar bu onayı devralır. Ayrıca ilk kurulum için türetilmiş bir **kontrol
listesi** (checklist) ve `is_ready` kapısı (gate) sunulur.

### Yapılanlar (6 commit, `development` branch)

| Commit | İçerik |
|---|---|
| `d7447ed` | **Depolama katmanı** — `ConsentPolicy`, `ConsentAcceptance`, `SetupItem` modelleri; `SetupStore` portu; `ConsentError`/`ConsentPolicyDowngrade`/`NoConsentPolicy` istisnaları; alembic migration `0003_setup` (`consent_policies` + `consent_acceptances` tabloları); `InMemoryStore` + `PostgresStore` yöntemleri; testler |
| `377c23f` | **Önceden var olan regresyon düzeltmesi** — `InMemoryStore.list_recent` sıralaması (issue #5 dışındaki `bfad4c0` commit'inin bozduğu 2 testi yeşile çevirdi) |
| `aeb2c66` | **FK eklendi** — `consent_acceptances.policy_version → consent_policies.version` (tasarım dokümanı gerektirdi; plan brief'i atlamıştı) |
| `b007167` | **`DojoSetup` facade'ı** — `set_policy` (downgrade reddi + audit), `accept_current_policy` (idempotent, `NoConsentPolicy`), `current_acceptance`, `checklist`, `checklist_item`, `is_ready`; `dojo` paketinden dışa aktarımlar |
| `0907e7b` | **API** — `GET /api/setup`, `GET /api/setup/consent`, `POST /api/setup/consent/accept`; `deps.build_setup`, `app.state.setup`; 5 yeni sözleşme testi |
| `641a041` | **CLI** — `dojo-consent set-policy --version N --text "..."` konsol scripti |

### Önemli tasarım kararları
- Onay, **sürüm başına tek satır** (kurulum genelinde), müşteri başına satır yok.
- `record_acceptance` **idempotent**: aynı sürüm için tekrar → `False`, tek satır, tek audit event.
- Checklist **depolanmaz, türetilir**: `pairing` ⟺ eşleşmiş/revoke edilmemiş cihaz var; `consent` ⟺ mevcut sürüm onaylanmış.
- Audit event'leri: `consent.policy_updated` (actor = istek yapan), `consent.accepted` (actor = cihaz id).
- Kapsam: dojo-core + backend API + CLI **sadece**. Web UI (#26) ve Android (#32) bu ticket'ta yok.

---

## 2. Test Rehberi

### Ön koşullar
- Python 3.12 + `uv` kurulu (`uv --version`)
- Postgres testleri için **Docker** çalışıyor olmalı (testcontainers)
- Komutlar repo kökünden (`C:\Users\35.HaRRy\Desktop\Projects\aisomedo`) çalıştırılır

### Adım 1 — Tüm testleri çalıştır

```powershell
# dojo-core (domain katmanı) — 71 test
uv run --project dojo-core pytest dojo-core/tests -q

# backend (API + CLI) — 23 test
uv run --project backend pytest backend/tests -q
```

Beklenen çıktı: **71 passed** ve **23 passed**.

### Adım 2 — Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
uv run --project backend ruff check backend/src backend/tests

# (Bu ortamda `uv run ... mypy` Windows App Control tarafından engelleniyor;
#  uvx ile çalıştır.)
uvx mypy dojo-core/src/dojo
uvx mypy backend/src/backend
```

Beklenen çıktı: `All checks passed!` ve `Success: no issues found in N source files`.

### Adım 3 — CLI'yi elle dene

```powershell
# Yardım / alt komutlar
uv run --project backend dojo-consent --help

# Gerçek Postgres (Docker) gerekir. Postgres ayağa kaldırıldıysa:
uv run --project backend dojo-consent set-policy --version 1 --text "Medya paylasimina izin veriyorum."
```

Çıktı: `Consent policy v1 saved`.

### Adım 4 — API'yi canlı dene (ops/docker-compose ile)

```powershell
# 1) Postgres + backend ayağa kaldır
docker compose -f ops/docker-compose.yml up -d --build backend

# 2) Politika tanımla
uv run --project backend dojo-consent set-policy --version 1 --text "Medya onay metni"
```

Ardından `curl` ile:

```bash
# Politika + onay durumu (önce 404 beklenir: henüz politika yok)
curl -i http://localhost:8000/api/setup/consent

# Eşleşme (pairing) ile cihaz al — mevcut /api/pairing akışını kullan
# GET /api/setup -> {"checklist": [...], "ready": false}
curl http://localhost:8000/api/setup
```

> Not: `/api/setup` yolları eşleşmiş bir cihaz (bearer token veya tarayıcı
> oturumu) gerektirir; `get_current_client` arkasındalar. Token'sız istekler
> **401** döner. Tam akış en iyi otomasyon testlerinde görülür (Adım 5).

### Adım 5 — Otomasyonla tam akış doğrulama (önerilen)

Sözleşme testleri, API davranışını gerçek Postgres olmadan `InMemoryStore`
üzerinden uçtan uca doğrular:

```powershell
uv run --project backend pytest backend/tests/test_api.py -q -v
```

Şu senaryoları kapsar:
- Auth yok → 401 (`test_setup_routes_require_auth`)
- Politika yokken checklist eksik görünür (`test_setup_without_policy_shows_incomplete`)
- Politika yokken `GET/POST /api/setup/consent` → 404 (`test_consent_404_until_policy_configured`)
- Cihaz onaylar, `accepted_at` aynı kalır (idempotent), setup ready olur (`test_device_accepts_consent_and_setup_becomes_ready`)
- Tarayıcı oturumu onaylar (`test_browser_session_accepts_consent`)

Domain katmanı için:

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_setup.py -v
uv run --project dojo-core pytest dojo-core/tests/test_store_setup.py -v
```

### Adım 6 — Migration'ı doğrula

`test_db_adapter.py` içindeki alembic testi, `0003_setup` migration'ının
`0002_pairing`'den sonra zincirlendiğini ve her iki tabloyu gerçek Postgres'te
oluşturduğunu doğrular:

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py -q -v
```

---

## 3. Notlar ve bilinen eksikler (review bulguları)

Standartlar ekseni bulguları (düzeltilmesi önerilen):
- `routes/setup.py:58` `SetupItemOut(**vars(item))` — `vars()` kullanımı
  API şemasını dataclass alan adlarına bağlar; `routes/activity.py`'deki gibi
  açık eşleme önerilir (hard bulgu).
- `NoConsentPolicy("consent acceptance lost")` iki farklı durum için
  kullanılıyor; ayrı bir istisna önerilir.
- `SetupStore.get_policy` yalnızca testlerde kullanılıyor (spekülatif).

Spec ekseni bulguları:
- CLI ile tanımlanan politikanın API'den görünürlüğünü kanıtlayan bir
  uçtan uca test yok (tasarım dokümanı Test bölümü).

## 4. İlgili dokümanlar

- Tasarım: `docs/superpowers/specs/2026-08-12-media-consent-and-first-run-onboarding-design.md`
- Plan: `docs/superpowers/plans/2026-08-12-media-consent-and-first-run-onboarding.md`
- SDD ilerleme kaydı: `.superpowers/sdd/progress.md`
- Issue: #5 (kapatma, /code-review sonrası ayrıca yapılır — açık bırakıldı)
