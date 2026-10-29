# Instagram Token Bağlantısı — Değişiklik Özeti ve Deneme Rehberi

Meta panelinden alınan Instagram Login token ile OAuth ekranlarını geçmeden bağlantı kurma özelliği. Instagram hesap ID ve kullanıcı adı otomatik bulunur. Mevcut Facebook OAuth akışı korunur.

## Ne Değişti?

- **Yeni endpoint** `POST /api/meta/instagram/token`: Dojo kimliği zorunlu, gövdede Instagram access token alır, hesabı doğrular, tokenı şifreli saklar, bağlantı durumunu döner.
- **Yeni provider** `HttpInstagramTokenProvider`: hesap keşfi ve izin kontrolü yalnızca `graph.instagram.com` üzerinden yapılır, token Authorization başlığıyla değil `access_token` query-string parametresi ile taşınır.
- **Bağlantı türü** `connection_type`: `facebook_login` veya `instagram_login` olarak saklanır, yeniden başlatmalarda korunur. Eski kayıtlar `facebook_login` sayılır.
- **Migration** `0013_instagram_login`: sayfa alanları ve token bitiş tarihi nullable olur, `connection_type` kolonu eklenir. Eski bağlantılar korunur.
- **Eşzamanlılık koruması**: bakım (worker) eski okuduğu sonuçla yeni bağlantıyı ezemez, eski worker sonucu yok sayılır.
- **PowerShell betiği** `ops/connect-instagram.ps1`: Dojo kimliği ile Instagram tokenını ayrı alır, gizli giriş sorar, yalnızca durum alanlarını yazdırır.
- **Süre kuralı**: ilk kayıtta `expires_at` boştur, bu "süresiz" değil "bilinmiyor" demektir. İlk uzak kontrol kayıttan en az 24 saat sonra yapılır, yenilemenin döndürdüğü süre gerçek bitiş tarihine çevrilir.
- **Hata kuralı**: doğrulama başarısızsa eski aktif bağlantı korunur.

## Ön Koşullar

- Meta panelindeki Instagram API / Instagram Login bölümünden alınmış uzun ömürlü Instagram User access token. Business veya Creator hesabı gerekir.
- Tokenda `instagram_business_basic` ve `instagram_business_content_publish` izinleri olmalı.
- Dojo Bearer token veya tek kullanımlık eşleştirme kodu.
- Backend ve worker aynı veritabanını ve aynı `META_TOKEN_ENCRYPTION_KEY` değerini kullanmalı.

## Adım 0 — Kaynak Kodu Güncelle

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
git pull
```

## Adım 1 — Veritabanını Güncelle

Backend ve worker durukken çalıştır. Hedef veritabanı `dojo-core/alembic.ini` içindeki adrestir.

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
$env:DATABASE_URL = 'postgresql+psycopg://dojo:dojo@localhost:5434/dojo'
uv run --directory dojo-core alembic upgrade head
uv run --directory dojo-core alembic current
```

Beklenen: `current` çıktısında `0013_instagram_login` görünür.

## Adım 2 — Backend ve Workerı Yeniden Başlat

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
docker compose --env-file ops/.env -f ops/docker-compose.yml up db -d
powershell -File ops/run-backend.ps1
```

Worker ayrı bir terminalde çalışıyorsa onu da durdurup başlat.

## Adım 3 — Instagram Tokenını Bağla

Her iki kimlik de gizli giriş olarak sorulur, ekrana yazılmaz.

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
.\ops\connect-instagram.ps1
```

Beklenen: `health` = `healthy`, `connection_type` = `instagram_login`, `ig_user_id` dolu, `page_id` boş, `expires_at` boş (ilk kayıtta normal).

## Adım 4 — Uzak Backend veya Eşleştirme Kodu ile Bağla

```powershell
.\ops\connect-instagram.ps1 -BaseUrl 'https://dojo.example.com'
```

```powershell
.\ops\connect-instagram.ps1 -PairingCode '<DOJO_ESLESTIRME_KODU>'
```

Eşleştirme kodu mevcut kod üretme komutuyla oluşturulur, tek kullanımlıktır.

## Adım 5 — Bağlantı Durumunu Sorgula

Betik dışı kontrol için `GET /api/meta/status` kullanılır. Beklenen: 3. adımdaki değerlerle aynı `ig_user_id` ve `connection_type`.

```powershell
$appToken = Read-Host 'Dojo application Bearer token' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($appToken)
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
Invoke-RestMethod -Uri 'http://localhost:8000/api/meta/status' -Headers @{Authorization = "Bearer $plain"} | ConvertTo-Json -Depth 5
$plain = $null
```

## Adım 6 — Hatalı Tokenın Eski Bağlantıyı Bozmadığını Dene

Bilerek yanlış bir token gönder, ardından durumu tekrar sorgula.

```powershell
$app = Read-Host 'Dojo application Bearer token' -AsSecureString
$bad = Read-Host 'Yanlis Instagram token denemesi' -AsSecureString
.\ops\connect-instagram.ps1 -AppToken $app -InstagramToken $bad
```

Beklenen: bağlantı hatası mesajı, eski `ig_user_id` durum sorgusunda aynen durur.

## Adım 7 — Otomatik Testleri Çalıştır

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
uv run --all-packages --group dev pytest dojo-core/tests/test_instagram_connection.py dojo-core/tests/test_meta_store.py backend/tests/test_meta_token_api.py backend/tests/test_instagram_powershell.py -q
```

Beklenen: `25 passed`.

```powershell
uv run --all-packages --group dev pytest backend/tests/test_api.py worker/tests/test_worker.py dojo-core/tests/test_setup.py -q
```

Beklenen: `75 passed`.

## Sonuç Kodları

| Kod | Anlamı |
| --- | ------ |
| 200 | Bağlantı kaydedildi, durum döndü |
| 401 | Dojo kimliği eksik veya geçersiz |
| 422 | Token boş, bozuk, geçersiz veya Instagram izni eksik |
| 502 | Instagram API veya ağ sorunu, sonra tekrar dene |

## Güvenlik Notları

- Instagram tokenını chat, e-posta veya komut geçmişine yapıştırma, yalnızca gizli girişle ver.
- Token yanıtlarda, hata mesajlarında ve kayıtlarda açık görünmez, yalnızca şifreli saklanır.
- `BaseUrl` uzak adreste `https` olmalı, `http` yalnızca yerel makineye izinli.
- Kısa ömürlü (1 saatlik) tokenla değil, panelden alınan uzun ömürlü tokenla bağlan.

## Kaynaklar

- Instagram Login başlangıç: `https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started/`
- Token yenileme: `https://developers.facebook.com/documentation/instagram-platform/reference/refresh_access_token/`
