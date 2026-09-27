# Yayın Hatası Kurtarma — Değişiklik Özeti ve Deneme Rehberi

Bu doküman issue #19 (publication failure recovery) kapsamında yapılan
değişiklikleri özetler ve tamamen PowerShell ile adım adım denemeni sağlar.

## Ne değişti

Kesin yayın-öncesi hata ile belirsiz sonuç artık ayrı yollardan gidiyor.
Container ID kaydedilmeden önceki kesin hatalar (`MetaPublishFailed`, auth,
şifreleme) paketi düzenlenebilir aktif duruma döndürüyor; Retry, Review, Skip
ve Reschedule bu pakette kullanılabiliyor. Container ID bir kez kaydedildikten
sonra her türlü yoklama hatası (timeout, ağ, auth) paketi `-publishing`
durumunda belirsiz bırakıyor — aktif'e dönüş yok, taze yayın yasak, kayıtlı
Meta kimlikleriyle yoklama sürüyor.

Publish POST artık tek seferlik: kayıt + dosya marker'ı göndermeden önce
kalıcılaşıyor, çökme/kayıp cevap/yinelenen çağrı ikinci POST üretemiyor.
`FINISHED` yalnızca yüklemenin hazır olduğu anlamına geliyor; paket
`-completed` olmuyor. Tamamlama yalnızca container `PUBLISHED` bildirdiğinde
yapılıyor, o da yeni container üretmeden. `ERROR`/`EXPIRED` bile publish
gönderildiyse aktif'e döndürmüyor (uzaktan Reel oluşmuş olabilir).

Durum cevabı artık `allowed_actions` taşıyor: `failed` pakette
retry/review/skip/reschedule, `-publishing`/belirsiz pakette yalnızca
reconcile. Onay, skip, reschedule, paket tamamlama ve yeni aktif paket
açma; `-publishing` varken 409 ile engelleniyor. `complete` yalnızca
Instagram-onaylı kayıtta çalışıyor; onaysız paket tamamlanamıyor.

Yeni endpoint'ler: `GET /api/reviews/pending`, `POST /api/reviews/{id}/approve`,
`POST /api/reviews/{id}/skip`, `POST /api/reviews/{id}/reschedule` ve
`POST /api/packages/active/publication/recover` (action: review/skip/reschedule).
Başarısız pakette `recover(skip)` onaysız 400, onaylı 200 dönüyor; sonrasında
retry ve complete 409 veriyor, `list_completed` boş kalıyor.

## Deneme adımları

Repo kökünde (`aisomedo`) PowerShell aç ve aşağıdaki adımları sırayla çalıştır.

### 1. Branch ve commit durumunu doğrula

```powershell
rtk git log --oneline -3
rtk git status --short
```

`0bec72f` commit'i en üstte görünmeli. `setup.py` ve `routes/setup.py`
değişiklikleri bu işin değil (önceki bekleyen iş); commit içinde değiller.

### 2. Commit içeriğini gözden geçir

```powershell
rtk git show --stat HEAD
```

15 dosya beklenir: `publishing.py`, `adapters/meta.py`, `testing.py`,
`routes/reviews.py` (yeni), `routes/publication.py`, `routes/packages.py`,
`main.py` ve ilgili test dosyaları.

### 3. Kurtarma testlerini çalıştır (TDD çekirdeği)

```powershell
uv run rtk pytest dojo-core/tests/test_publication.py -q
```

Beklenen: `17 passed`. Kanıtlananlar: geçici yoklama hatasında `-publishing`
korunur ve retry 409 yer; publish POST hatasında aynı container ile devam
edilir (yeni container yok); reconcile yoklama hatasında belirsiz kalır;
`failed` durum `allowed_actions` ile retry/review/skip/reschedule sunar;
skip ve auth-engelli paketler `list_completed` içinde görünmez.

### 4. API koruma testlerini çalıştır

```powershell
uv run rtk pytest backend/tests/test_publication_api.py backend/tests/test_api.py -q
```

Beklenen: hata yok. Kanıtlananlar: publishing sürerken retry ve publish 409;
reconcile yoklama hatasında endpoint 200 + `uncertain` + yalnızca reconcile
aksiyonu; kesin hatada `failed` + dört kurtarma aksiyonu; review endpoint'leri
çalışıyor; onaysız `complete` 409.

### 5. Worker ve Meta adapter testlerini çalıştır

```powershell
uv run rtk pytest worker/tests/test_worker.py dojo-core/tests/test_meta_publisher.py -q
```

Beklenen: hata yok. Worker yeniden başlasa bile kayıtlı container POST'u
tekrarlamıyor; `PUBLISHED` gelince tamamlıyor.

### 6. Tip denetimi

```powershell
uv run rtk mypy dojo-core/src backend/src worker/src
```

Beklenen: `No issues found`.

### 7. Tam paketi bir kez çalıştır

```powershell
uv run rtk pytest dojo-core/tests backend/tests worker/tests -q
```

Beklenen: `333 passed, 0 failed, 4 skipped` (4 skip, Docker gerektiren
render testleri).

### 8. Değişiklikleri issue ile eşleştir

```powershell
rtk git diff 1e1e50c...HEAD --stat
```

Kabul kriterleriyle karşılaştır: kesin hata aktif + kurtarma seçenekleri;
belirsiz/kabul-edilmiş-sonuç `-publishing` + yoklama + taze yayın yasağı;
belirsiz sonuçta ikinci harici yayın yok; onaysız paket tamamlanmış
görünmüyor.
