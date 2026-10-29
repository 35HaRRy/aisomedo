# Yayın İncelemesi — Vadesi Gelen Zamandan Oluşturma — Değişiklik Özeti ve Test Rehberi

Bu doküman, **issue #14** (Yayin Incelemesi creation from a due time) kapsamında yapılan
değişiklikleri özetler ve bunları adım adım deneyebilmen için PowerShell komutlarını
gösterir. Tüm komutlar PowerShell'dir; Python kodu içermez.

## 1. Değişiklik Özeti

### Amaç

Bir vade zamanı (`Yayın Zamanı`) gelince, aktif paket revizyonuna bağlı **kalıcı bir
`Yayın İncelemesi`** oluşturur. Kilit noktalar:

- **İdempotent** — aynı revizyon için en fazla **bir** inceleme oluşur; zamanlayıcı
  yeniden çalıştırılsa da, süreç yeniden başlasa da ek inceleme üretilmez (AC1).
- **Render tamamlanınca oluşur** — inceleme yalnızca bir render gerçekten tamamlandığında
  ortaya çıkar (yani her zaman işlenmiş bir çıktıya bağlıdır).
- **Boş paket** — vade gelince aktif paket boşsa inceleme **oluşturulmaz**, zaman satırı
  `pending` kalır; kullanıcıya Yükle / Atla / Yeniden Zamanla seçenekleri kalır (AC2).
  Sonradan medya yüklenirse aynı paket üzerinde render → inceleme akışı devam eder,
  ikinci bir aktif paket açılmaz.
- **Geç onay için hazır** — inceleme zamanın kendisine değil oluşuma bağlı kalıcıdır;
  zaman geçse de yeni klasör veya yeni inceleme açılmaz (AC3).
- **Kalıcılık** — incelemeler yeni `yayin_incelemesi` tablosunda saklanır (migration
  `0008`). Benzersiz kısıt `(occurrence_id, revision_digest)` idempotens güvencesini sağlar.

### Yapılanlar (`development` branch, 2 commit)

| Commit | İçerik |
|---|---|
| `f8dd0ff` | **Tasarım dokümanı** — `docs/superpowers/specs/2026-08-20-yayin-incelemesi-from-due-time-design.md` |
| `5c18618` | **Uygulama** — `YayinIncelemesi` modeli + `ReviewStore` portu + migration `0008` + `InMemoryStore`/`PostgresStore` uygulamaları + `evaluate_due_work`/`_create_review_if_due` + `test_review.py` + DB testleri |

### Önemli tasarım kararları

- **İnceleme, render tamamlanma kancasına bağlanır**: `_create_review_if_due`, `_render_job`
  sonunda ve zaten taze olan paketler için `evaluate_due_work` içinde çağrılır.
- **İdempotens anahtarı**: `(occurrence_id, revision_digest)`. İçerik düzenlenirse revizyon
  değişir, aynı oluşum için yeni bir inceleme doğar; eski revizyon değişmeden kalır.
- **Boş paket → inceleme yok**: vade satırı `pending` kalır; çözümleme (#15) kapsamındadır.
- **Çözümleme kapsam dışı**: onayla / atla / yeniden zamanla (`status` şu an hep
  `pending`) #15'e aittir.
- **Yeni API rotası yok**: inceleme gösterimi #25, çözümleme #15, bildirim #16'dır. Bu
  yüzden doğrulama test takımı ve doğrudan DB sorgusu ile yapılır.
- **Render işi tekilleştirilmez**: kuyrukta bekleyen bir render varken yeniden çalıştırma
  ikinci bir render işi sıralayabilir; inceleme idempotens'i yine de korunur (AC1).

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

### Adım 1: İnceleme (seam) testleri

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_review.py -v
```

Beklenen (**7 test geçer**):

- `test_due_occurrence_creates_one_durable_review` — render tamamlanınca tam bir inceleme
  oluşur, `review.created` denetim kaydı yazılır.
- `test_reviews_idempotent_across_rerun_and_restart` — aynı depoyu paylaşan yeniden
  çalıştırma ve "yeniden başlatma" ek inceleme üretmez, yeniden render da sıralamaz.
- `test_fresh_render_creates_review_without_rerender` — paket önceden render edilmişse
  inceleme doğrudan oluşur, gereksiz render yapılmaz.
- `test_review_snapshots_caption` — inceleme, paket başlığının (caption) anlık görüntüsünü
  taşır.
- `test_empty_package_at_due_creates_no_review_and_stays_pending` — boş pakette inceleme
  yok, oluşum `pending` kalır.
- `test_upload_after_empty_due_reviews_same_package` — boş vadeden sonra medya yüklenince
  aynı paket üzerinde inceleme oluşur; ikinci aktif paket açılmaz.
- `test_review_is_durable_after_time_passes` — zaman geçse de inceleme kalıcıdır, yeni
  klasör/inceleme açılmaz.

### Adım 2: Depo (DB) testleri

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py -v -k review
```

Beklenen (**3 test geçer**, gerçek Postgres üzerinde):

- `test_review_create_get_by_occurrence_and_pending` — kayıt + `(oluşum, revizyon)` ile
  okuma + bekleyen listesi.
- `test_review_unique_occurrence_revision` — aynı `(oluşum, revizyon)` ikinci kez
  eklenemez (benzersiz kısıt).
- `test_review_different_revision_allowed` — farklı revizyon aynı oluşuma eklenebilir.

> Not: DB testleri testcontainers ile geçici bir Postgres açar; Docker gerekir.

### Adım 3: Migration doğrulaması

```powershell
uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py::test_alembic_upgrade_head_creates_schema -v
```

Beklenen (**1 test geçer**): `0008_yayin_incelemesi` de dahil tüm migration'lar
`head`'e kadar uygulanır, `yayin_incelemesi` tablosu oluşur.

### Adım 4: Tüm paketlerin tam takımları

```powershell
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
uv run --project worker pytest worker/tests -v
```

Beklenen: toplam **300 geçer, 2 atlanır** (atlama docker/ffmpeg gerektiren işleme
testleridir; CI'da doğrulanır).

### Adım 5: Lint ve tip kontrolü

```powershell
uv run --project dojo-core ruff check dojo-core/src/dojo dojo-core/tests/test_review.py dojo-core/tests/test_db_adapter.py
uv run --project dojo-core mypy dojo-core/src/dojo
```

Beklenen: hepsi temiz. (`mypy` doğrudan engellenirse `uvx mypy dojo-core/src/dojo` ile
deneyin.)

## 4. Manuel Deneme (Worker + DB)

Yeni API rotası olmadığı için uçtan uca doğrulama worker döngüsü ve doğrudan DB
sorgusu ile yapılır. Yığın ayağa kalktıktan sonra:

1. **Aktif pakete medya yükleyip render aldırın** (Android/web istemcisinden ya da mevcut
   test akışlarıyla). Sonra worker'ın birkaç tur atmasına izin verin:
```powershell
docker compose -f ops/docker-compose.yml logs -f --tail=50 worker
```
   - Worker her turda `evaluate_due_work` çağırır; vadesi gelen bir `Yayın Zamanı` varsa
     ve paket boş değilse render tetiklenir, render tamamlanınca inceleme oluşur.

2. **Oluşumları ve incelemeleri Postgres'ten görüntüleyin**:
```powershell
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT * FROM yayin_zamani ORDER BY id;"
docker exec -i $(docker compose -f ops/docker-compose.yml ps -q db) psql -U dojo -d dojo -c "SELECT * FROM yayin_incelemesi ORDER BY id;"
```
   - `yayin_incelemesi` tablosunda `status='pending'` satırlar beklenir.
   - Aynı `(occurrence_id, revision_digest)` ikilisiyle ikinci satır oluşmaz (idempotens).

3. **İdempotens'i deneyin** — worker'ın birkaç tur daha çalışmasına izin verin ve aynı
   sorguyu tekrarlayın; inceleme sayısı değişmemelidir.

4. **Boş paket durumunu deneyin** — aktif paket boşken vadesi gelen bir zaman bırakıp
   yukarıdaki sorguyu çalıştırın; `yayin_incelemesi` boş kalır, `yayin_zamani`'da satır
   `pending` olarak durur.

## 5. Git Geçmişi

```powershell
git log --oneline -2
```

```text
5c18618 feat(dojo-core): durable yayin incelemesi from a due time (#14)
f8dd0ff docs(design): yayin incelemesi creation from a due time (#14)
```

## 6. Known Issues ve Sınırlamalar

- **İnceleme çözümlemesi burada yok**: `status` her zaman `pending`'dir. Onayla / atla /
  yeniden zamanla ve çok cihazlı atomicite **#15** kapsamındadır.
- **İnceleme gösterimi API'si yok**: istemciye dönük inceleme görünümü **#25**, bildirim
  ve hatırlatmalar **#16** kapsamındadır.
- **Boş paket inceleme oluşturmaz**: vade satırı `pending` kalır; kullanıcıya seçenek
  sunma ve çözümleme #15/#16'ya aittir.
- **`yayin_incelemesi.occurrence_id` bir FK değildir**: `yayin_zamani`/`uploads`/`jobs`
  ile aynı sade-Integer kalıbını izler; veritabanı düzeyinde ilişki zorlanmaz.
- **Render işi tekilleştirilmez**: kuyrukta bekleyen render varken yeniden çalıştırma
  ikinci bir render sıralayabilir; inceleme idempotens'i yine korunur (tasarım kararı 7).