# Canlı durum (SSE) ve güvenli eşzamanlı düzenleme — deneme rehberi

Bu rehber, `feat/live-state-sse` dalındaki çalışmanın ne yaptığını ve web
tarayıcısı ile Android uygulamasında adım adım nasıl deneneceğini anlatır.
Arayüzde kolay tekrarlanamayan kontroller için PowerShell komutları ayrı
bölümdedir. Bu rehberdeki PowerShell bloklarında Python veya SQL komutu yoktur.

Güncelleme: 2026-10-22. Dal: `feat/live-state-sse`.

## 1. Ne değişti?

Önceki davranış, web ve Android istemcilerinin canlı veriyi düzenli aralıklarla
sorgulamasına dayanıyordu. Yeni davranış olay güdümlüdür:

- İstemci ön plandayken `/api/events` üzerinden tek bir SSE bağlantısı açar.
  Bu bağlantı `ready`, `change`, `resync` ve `heartbeat` olaylarını taşır.
- Veri değişikliği olduğunda istemci yalnızca etkilenen kaynakların HTTP
  anlık görüntüsünü yeniden okur. Periyodik anket, yedek anket veya arka plan
  veri çekme yoktur.
- Web'de dashboard yalnızca kontrol paneli/paket sayfasında, editor yalnızca
  paket sayfasında izlenir. Setup ilk açılışta, ardından kurulum/ayarlar
  ekranında okunur. Gizlenen editörün taslağı korunur; dönüşte güncel veriyle
  uzlaştırılır. Yinelenen yenilemeler birleştirilir; kayıt sonrası doğrulama korunur.
- Worker, değişmeyen gelecekteki Yayın Zamanı kaydını artık silip yeniden
  oluşturmaz; boşta turlar gereksiz `dashboard/publication` bildirimi üretmez.
- SSE bağlantısı koptuğunda istemci düzenlemeyi ve tüm değişiklik isteklerini
  kilitler. Taslak ekranda ve cihazda korunur; bağlantı geri gelince düzenleme
  yeniden açılır.
- Sunucu, durum değişikliğini, içerik revizyonunu, kalıcı olayı ve PostgreSQL
  bildirimini aynı işlemde yazar. Bildirimler işlem başına birleştirilir;
  istemci aynı değişiklik için gereksiz yenileme yapmaz.
- Anlık görüntüler sürüm bilgisi taşır. İstemci, gördüğü sürümden daha eski
  bir yanıtı veya geç gelen bir okumayı uygulamaz.
- Düzenlemeler grup grup birleştirilir. Farklı videolardaki bağımsız
  değişiklikler birlikte yaşayabilir. Aynı videonun bölümleri tek bir çakışma
  grubudur; bir bölümün başlangıcı ile bitişi ayrı ayrı birleştirilmez.
- Bir grupta çakışma varsa gönderilen toplu isteğin tamamı reddedilir; kısmi
  yazma olmaz. Kullanıcı yerel veya sunucu sürümünü seçmeden kayıt açılmaz.
- Web taslakları IndexedDB'de atomik karşılaştır-ve-yaz ile saklanır. Tarayıcı
  sekmesi yenilense veya kapansa da taslak korunur. Taslak, canlı bağlantı
  hazır olup anlık görüntü başarıyla okunana kadar salt okunurdur.
- Android taslakları uygulama içi depoda, sunucu + eşleştirme + paket kapsamında
  atomik olarak saklanır. Uygulama arka plana atıldığında canlı bağlantı durur;
  ön plana dönünce yeniden kurulur. Yeni bir arka plan bildirim türü eklenmedi.
- Render işi paket kilidi dışında çalışır; geç tamamlanan sonuç hazır bir
  çıktının yerini alamaz. Temizlik sürerken render tamamlanabilir; geç gelen
  sonuç silinmiş kaydı veya dosyayı geri getiremez.
- Eski tekil değişiklik uçları, tırnaklı
  `If-Match: "paket-kimliği:içerik-revizyonu"` başlığı ister. Toplu düzenleme
  isteği kendi başlangıç sürümünü taşır.

Bu çalışma bir veri taşıma, geri doldurma veya kesme planı içermez. PostgreSQL
tek doğruluk kaynağıdır; `manifest.json` ondan türetilir.

## 2. Görünür davranış sözleşmesi

| Gereksinim | Denemede görülmesi gereken |
| --- | --- |
| 2–10 etkin istemci | İki tarayıcı ve bir Android istemci aynı anda açık kalabilir. |
| Periyodik canlı veri sorgusu yok | Boşta beklerken ağ sekmesinde yalnızca açık SSE isteği ve 15 saniyelik `heartbeat` olayları görünür. |
| Bağımsız düzenlemeler birleşir | Ayrı videolarda yapılan iki kayıt birbirini ezmeden korunur. |
| Aynı grupta çakışma | Aynı videonun bölümleri aynı anda değişirse çakışma bölümü açılır ve kayıt kilitlenir. |
| Çakışmada toplu ret | Çakışan grup varken gönderim kabul edilmez; sunucuda kısmi değişiklik oluşmaz. |
| Kopmada düzenleme kapalı | Bağlantı kesilince alanlar ve kayıt düğmeleri devre dışı kalır; taslak korunur. |
| Taslak dayanıklılığı | Sekme kapanıp açıldığında veya uygulama sonlandırılıp yeniden açıldığında taslak geri gelir. |
| Taslak güvenliği | Geri yüklenen taslak, canlı bağlantı ve anlık görüntü hazır olmadan düzenlenemez. |
| Yalnızca ön plan | Web sekmesi görünürken ve Android uygulaması ön plandayken canlı bağlantı kurulur; yeni arka plan izleme yoktur. |

Normal bağlantı kurma ve senkronizasyon bildirimleri gösterilmez; güncel veri
doğrulanana kadar düzenleme/kayıt kilidi korunur. Web'de gerçek hata durumlarında
şu metinler görünür:

- `Güncel veriler doğrulanamadı. Düzenleme ve kayıt kapalı; yeniden deneyin.`
- `Canlı bağlantı kesildi. Taslağınız ekranda korunuyor; yeniden bağlanılana kadar düzenleme ve kayıt kapalı.`
- `Eşleştirme artık geçerli değil. Yeniden eşleştirin.`

Web'deki `Canlı · değişiklikler anında eşitlenir` ve `Son güncelleme` satırı,
kapladığı boşlukla birlikte kaldırıldı. Gerçek bağlantı veya veri doğrulama
hatasında `Canlı bağlantıyı yeniden dene` düğmesi bulunur.

## 3. Bu ortamda doğrulama durumu

2026-10-22 itibarıyla Docker kullanılabilir; güncel doğrulama durumu:

- Web: 346 birim testi ve üretim derlemesi geçti. Tarayıcı testlerinde 31 geçti,
  1 atlandı; bu koşu son iki yarış durumu düzeltmesinden önceydi.
- Core: 810 geçti, 4 atlandı; backend: 244 geçti; worker: 141 geçti.
  Gerçek PostgreSQL ve iki API süreci + worker çapraz süreç testi de çalıştı.
- Yerel backend ve Vite üzerinden 65 saniyelik canlı ölçümde sürekli SSE
  kopması görülmedi. Tekrarlayan `change` olaylarının scheduler kaydını
  yeniden oluşturmasından kaynaklandığı doğrulandı; düzeltme regresyon testleriyle geçti.
- İzole TLS/ağ geçidi kabul testi çalıştırılamadı.
- Android bu son değişikliklerde yeniden test edilmedi; önceki JVM durumu
  bölüm 14.3'tedir. Enstrümantasyon testleri derlendi ancak cihaz olmadığı için çalışmadı.

Rehberdeki tüm elle deneme adımlarının çalıştırıldığı anlamına gelmez.
Scheduler düzeltmesi çalışan Docker imajlarına henüz uygulanmadı; bölüm 4'teki
yeniden derleme gereklidir. Önceki ayrıntılı doğrulama kaydı:
[`docs/verification/live-state-sse.md`](../verification/live-state-sse.md).

## 4. Hazırlık: yerel ortamı başlatın

Gerekenler:

- Docker Desktop'ın Linux konteyner motoru açık olmalı.
- Node.js ve npm kurulu olmalı.
- PowerShell, bu değişikliklerin bulunduğu **repo kökünde** açılmalı.

Önce dalı ve Docker'ı doğrulayın:

```powershell
git branch --show-current
docker info --format '{{.ServerVersion}}'
```

Beklenen: `feat/live-state-sse` ve bir Docker sunucu sürümü. Docker bağlantısı
kurulamıyorsa Docker Desktop'ı açıp Linux motorunun çalıştığını kontrol edin.

Ortam dosyasını yalnızca yoksa oluşturun:

```powershell
if (-not (Test-Path ops/.env)) {
    Copy-Item ops/.env.example ops/.env
}
notepad ops/.env
```

`ops/.env` içinde en az şunları kontrol edin:

- `POSTGRES_PASSWORD`: boş olmamalı. Örnek parolayı üretimde kullanmayın.
- `COOKIE_SECURE=false`: yalnızca bu yerel HTTP denemesi için. Üretimde HTTPS
  ve `true` kullanın. HTTP üzerinden Secure çerez gönderilmez.
- `WORKER_HEALTH_PATH=/run/dojo-worker/health.json`: worker ve backend aynı
  dosyayı görmeli. Mevcut `.env` dosyanızın üzerine kopyalama yapmayın.

Veri klasörleri ve yığın:

```powershell
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose --env-file ops/.env -f ops/docker-compose.yml up -d --build db backend worker
docker compose --env-file ops/.env -f ops/docker-compose.yml ps
Invoke-RestMethod http://localhost:8000/health
```

Beklenen: `db`, `backend` ve `worker` çalışıyor; `/health` yanıt veriyor.
Backend `:8000`, PostgreSQL `:5434` üzerindedir.
Kaynak değişikliklerinin mevcut konteynerlere geçmesi için yukarıdaki `--build`
gereklidir; yalnızca `restart` backend/worker kodunu güncellemez.

Web bağımlılıklarını kurun ve geliştirme sunucusunu başlatın:

```powershell
npm --prefix web ci
npm --prefix web run dev
```

Son komut terminali meşgul tutar; açık bırakın. Diğer komutlar için yeni bir
PowerShell penceresi kullanın. Tarayıcıda Vite'ın yazdığı adresi açın; varsayılan
adres **http://localhost:3000**. Backend `:8000` adresi web sayfasını sunmaz.

## 5. Tarayıcıyı eşleştirin

İlk eşleştirme kodunun arayüzü yoktur. Yeni bir PowerShell penceresinde repo
kökünden:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-create-pairing-code create-code
```

Çıktıdaki `Pairing code` değerini tarayıcıdaki **Eşleştirme kodu** alanına yazın.
**Tarayıcı adı** için `İstanbul Dojo Yönetim Bilgisayarı` gibi tanınabilir bir ad
girin ve **Eşleştir**'e basın.

Beklenen:

1. Kontrol Paneli açılır.
2. Normal bağlantı/senkronizasyon bildirimi veya canlı durum üst satırı görünmez.
3. Sayfa yenilemesi gerekmeden veriler yüklenir.

İkinci bir tarayıcı profili veya gizli pencereyle çakışma denemesi için yeni bir
kod üretip aynı adımları tekrarlayın. Her kod tek kullanımlıktır ve süresi
dolabilir.

## 6. Canlı bağlantıyı doğrulayın

Tarayıcıda:

1. Kontrol Paneli'ni açın; canlı durum üst satırı artık gösterilmez.
2. `F12` ile geliştirici araçlarını açın.
3. **Network** sekmesinde `events` filtresini yazın.
4. Açık kalan `events` isteğini seçin. Yanıt türü
   `text/event-stream`, önbellek başlığı `no-store` olmalı.
5. **EventStream** görünümünde önce `ready`, sonra değişiklik yokken yaklaşık 15 saniyede bir
   `heartbeat` olayını görün.

Yaklaşık iki dakika sayfaya dokunmadan bekleyin. Ağ listesinde yeni
`/api/dashboard`, `/api/setup`, `/api/packages/active/editor` veya `/api/activity` istekleri
birikmemelidir. Tek açık istek `events` olmalıdır. `heartbeat` bir veri sorgusu
değildir; yalnızca taşıma katmanının canlılık kontrolüdür.

Geliştirme modunda StrictMode nedeniyle açılışta iki `events` isteğinden birinin
hemen iptal olması normaldir; sürekli yeniden bağlantı değildir. `change` olayları
da bağlantıyı canlı tutar; trafik varken ayrıca 15 saniyede bir heartbeat beklemeyin.
**Etkinlik/Ayarlar** ekranında dashboard/editor GET'i olmamalı; **Güncel Paket**
ekranına dönünce editor yeniden okunmalı, taslak kaybolmamalıdır.

Aynı anda 2–10 istemci kullanabilirsiniz. İkinci tarayıcıda bir değişiklik
yapıldığında ilk tarayıcı sayfa yenilemeden güncellenmelidir.

Sekmeyi arka plana alıp geri dönün: SSE yeniden kurulur ve güncel veriler
okunur; normal dönüşte bildirim görünmez. Doğrulama bitene kadar düzenleme/kayıt
kapalıdır. Bu, periyodik sorgu değil, sekmeye dönüşle tetiklenen kurtarmadır.

## 7. Deneme verisi oluşturun

**Güncel Paket** sayfasına gidin. Henüz paket yoksa:

1. **Fotoğraf ve video seç** düğmesiyle en az iki kısa video yükleyin.
   İki ayrı video, bağımsız birleştirme ile aynı-video çakışmasını ayırt etmeyi
   kolaylaştırır.
2. Yükleme durumu **Pakete eklendi** olana kadar bekleyin.
3. İlk videonun kalem simgesine basın. Ekran okuyucu bu düğmeyi
   `... bölümlerini düzenle` olarak duyurur.
4. `1. bölüm başlangıcı (saniye)` ve `1. bölüm bitişi (saniye)` alanlarına
   geçerli değerler girin; örneğin `0` ve `3`.
5. **Bölümleri kaydet** düğmesine basın.

Beklenen: `Bölümler kaydedildi.` mesajı görünür ve
`Kaydedilmemiş bölüm veya süre değişiklikleri var.` metni kaybolur. Kayıt
sonrası sayfa yenilemeye gerek yoktur; diğer açık istemciler değişikliği
otomatik alır.

`Bölüm ekle` düğmesi, oynatma konumunda en az bir karelik boş alan varsa yeni
bir bölüm ekler. Bölümler çakışamaz, video dışına çıkamaz ve en az 0,04 saniye
sürmelidir.

## 8. Bağımsız düzenlemeleri birleştirin

İki ayrı tarayıcı profili veya normal + gizli pencere açın; ikisini de ayrı
kodlarla eşleştirin. İkisinde de **Güncel Paket** sayfasını açın.

1. A penceresinde birinci videonun bitişini `4`, B penceresinde ikinci videonun
   bitişini `5` yapın. İkisinde de **kaydetmeyin**.
2. A penceresinde **Bölümleri kaydet**'e basın. `Bölümler kaydedildi.` mesajını
   bekleyin. B penceresi bu değişikliği otomatik almalı; B'nin ikinci videodaki
   kaydedilmemiş taslağı korunmalıdır.
3. B penceresinde **Bölümleri kaydet**'e basın. A penceresi B'nin kaydını sayfa
   yenilemeden almalıdır.
4. İki videoyu da yeniden açıp değerleri kontrol edin.

Beklenen: iki video da kendi değerini korur; hiçbir taraf diğerinin değişikliğini
ezmez. Yalnızca değişen gruplar gönderilir. Bir videonun bölüm seçimi (veya
"tüm video" seçimi) tek grup olduğu için aynı videodaki farklı bölümler ayrı
ayrı birleşmez.

## 9. Aynı videoda çakışmayı deneyin

İki eşleştirilmiş tarayıcı penceresinde de aynı videonun düzenleyicisini açın.

1. B penceresinde bitiş değerini `6` yapın; **kaydetmeyin**.
2. A penceresinde aynı videonun bitişini `5` yapıp kaydedin.
3. B penceresinde canlı yenileme geldiğinde `Çakışan taslak` bölümü ve
   `video:... çakışması` alanı görünmelidir. **Bölümleri kaydet** devre dışıdır.
4. İki seçenekten birini kullanın:
   - **Sunucudaki değişikliği kullan**: yerel taslak sunucu sürümüyle değiştirilir.
   - **Benim değişikliğimi kullan**: sunucu temel sürümü güncellenir; yerel
     değer korunur ve kayıt yeniden açılır.
5. **Sunucudaki değişikliği kullan** seçeneğinde kayıt gerekmez; yerel taslak
   sunucu değerine döner. **Benim değişikliğimi kullan** seçeneğinde kaydedin.
   İki pencereyi yeniden kontrol edin.

Beklenen: aynı videoda iki bağımsız sürüm sessizce birleşmez. Sunucu, çakışan
grubu içeren toplu isteği `409` ile reddeder ve **hiçbir grubu** yazmaz. Bu
toplu ret davranışı arayüzde kayıt düğmesi kilitlenerek, otomatik testte ise
doğrudan HTTP yanıtıyla doğrulanır.

`Paket dışarıdan değişti. Taslaklar korunuyor; yazmadan önce yenileyin veya
değişiklikleri atın.` mesajı görürseniz önce **Paketi yenile**'yi kullanın.
`İşlemin sonucu doğrulanamadı...` mesajı, isteğin sunucuda uygulanıp
uygulanmadığının bilinmediği anlamına gelir; yeniden göndermeden önce paketi
yenileyin.

## 10. Taslağın yenileme ve kapanmaya dayanmasını deneyin

1. Bir videonun düzenleyicisinde bitiş değerini geçici olarak `4.` yapın.
   Bu geçersiz bir değerdir; kayıt engellenir.
2. `Kaydedilmemiş bölüm veya süre değişiklikleri var.` metnini ve taslak
   depolama hatası **olmadığını** kontrol edin.
3. Sayfayı `F5` ile yenileyin.
4. İlk anda rutin bağlantı/senkronizasyon bildirimi görünmez. Taslak değeri
   ekranda kalır ancak alanlar ve düğmeler devre dışıdır.
5. Canlı bağlantı kurulup anlık görüntü okunduktan sonra alan yeniden
   düzenlenebilir olur; `4.` değeri hâlâ oradadır.
6. Sekmeyi tamamen kapatın. Yeniden `http://localhost:3000` açın,
   **Güncel Paket** ve aynı videonun düzenleyicisine gidin. Taslak geri gelir.
7. Değeri `4` yapıp kaydedin. `Bölümler kaydedildi.` mesajını görün.

Taslak kapsamı bilinçlidir: aynı kaynak + istemci + paket için saklanır. Farklı
tarayıcı profili, gizli pencere, `localhost` yerine `127.0.0.1` kullanımı veya
site verilerinin temizlenmesi taslağı görünmez yapar. Bu bir hata değildir.

Aşağıdaki mesajlardan biri görünürse kaydetmeyin; önce belirtilen işlemi yapın:

- `Taslak bu cihaza kaydedilemedi...`: tarayıcı depolaması kullanılamıyor.
  **Taslak kaydını yeniden dene**'ye basın. Sekmeyi kapatmak son değişiklikleri
  kaybettirebilir.
- `Bu cihazdaki taslak okunamadı...`: bozuk kayıt sunucuya gönderilmez.
- `Taslak başka bir sekmede değişti...`: iki sekme aynı taslağı aynı anda
  yazmaya çalıştı. Bu sekmedeki değişiklikler korunur; diğer sekmeyi kapatıp
  yeniden deneyin. Atomik karşılaştır-ve-yaz testi bunu doğrular.

## 11. Bağlantı kopunca düzenlemenin kilitlendiğini görün

Backend'i durdurun:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml stop backend
```

Beklenen:

1. En geç yaklaşık 45 saniye içinde
   `Canlı bağlantı kesildi. Taslağınız ekranda korunuyor; yeniden bağlanılana
   kadar düzenleme ve kayıt kapalı.` mesajı görünür.
2. **Canlı bağlantıyı yeniden dene** düğmesi görünür.
3. Bölüm alanları, sürükleme, yükleme ve kayıt düğmeleri devre dışıdır.
   Gezinme bağlantıları çalışmaya devam eder.
4. Ekrandaki taslak silinmez.

Backend'i yeniden başlatın:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml start backend
```

Beklenen: istemci yaklaşık 1–30 saniye içinde (rastgele gecikmeyle) yeniden
bağlanır, güncel anlık görüntü sessizce okunur ve
düzenleme yeniden açılır. Taslak korunmuştur. Otomatik gelmezse
**Canlı bağlantıyı yeniden dene**'ye basın.

Yalnızca worker'ı durdurmak SSE bağlantısını kesmez; kopma denemesi için
backend'i durdurun.

## 12. Erişim iptalini deneyin (isteğe bağlı)

Bu adım hedef tarayıcıyı çıkışa zorlar. Aynı PowerShell penceresinde kalın;
`$DojoSession` yalnızca o pencerede geçerlidir. Önce yönetici oturumu için yeni
bir kod üretin ve PowerShell'i tarayıcı istemcisi olarak eşleştirin:

```powershell
$Base = 'http://localhost:8000'
$Kod = ((docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-create-pairing-code create-code | Select-String 'Pairing code').ToString() -split ':', 2)[1].Trim()
$Govde = @{ code = $Kod; kind = 'browser'; name = 'PowerShell yönetici oturumu' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/validate" -ContentType 'application/json' -Body $Govde -SessionVariable DojoSession
$Istemciler = Invoke-RestMethod -Uri "$Base/api/pairing/clients" -WebSession $DojoSession
$Istemciler | Select-Object id, name, kind, revoked_at | Format-Table
$HedefId = [int](Read-Host 'İptal edilecek tarayıcının id değeri')
Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/clients/$HedefId/revoke" -WebSession $DojoSession
```

Hedef tarayıcıda bir sonraki korumalı istekte veya akış olayında oturum
geçersiz olur. Beklenen: `Eşleştirme artık geçerli değil. Yeniden eşleştirin.`
ve eşleştirme ekranı. Taslaklar cihazda silinmez; ancak yeniden eşleştirme yeni
bir istemci kimliği oluşturduğu için eski taslak yeni oturumda görünmez. Taslağı
açıkça silmek için tarayıcı site verilerini veya Android'de sunucu değiştirme
işlemini kullanın.

## 13. Android uygulamasında deneyin

Gerekenler: Android Studio ve Android SDK, bir emülatör veya USB hata ayıklaması
açık fiziksel cihaz. Backend ve web yığını yukarıdaki gibi çalışıyor olmalıdır.

### 13.1 Hata ayıklama APK'sını kurun

```powershell
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:Path = "$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\emulator;$env:Path"
adb devices
& android/gradlew.bat -p android :app:assembleDebug
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

Beklenen: `adb devices` en az bir cihaz listeler ve `assembleDebug` başarılı olur.
`No connected devices!` görürseniz emülatörü Android Studio'nun Device
Manager'ından başlatın veya cihazda USB hata ayıklamasına izin verin.

Gradle yanlış Java'yı bulursa Android Studio'nun JDK'sını ayarlayın:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
```

### 13.2 Sunucu adresini girin

- **Emülatör:** `http://10.0.2.2:8000` (emülatörden bilgisayardaki backend).
- **USB fiziksel cihaz:** önce port yönlendirmesi yapın, sonra
  `http://127.0.0.1:8000` girin:

```powershell
adb reverse tcp:8000 tcp:8000
```

Hata ayıklama derlemesi yerel HTTP'ye izin verir. Yayın (release) derlemesi
HTTPS ister. Yerel deneme için mutlaka hata ayıklama APK'sını kullanın.

### 13.3 Cihazı eşleştirin

1. Uygulamada **Sunucu adresi** alanına yukarıdaki adresi yazın ve **Bağlan**'a
   basın.
2. Yeni bir PowerShell penceresinde eşleştirme kodu üretin:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-create-pairing-code create-code
```

3. Kodu uygulamadaki **Eşleştirme kodu** alanına girin ve **Eşleştir**'e basın.
4. **Paket** sekmesinde **Aktif Paket**'i açın.

### 13.4 Ön plan canlı bağlantısı

1. Bir videoda **Video bölümlerini düzenle**'ye basın.
2. `1. bölüm` başlangıç/bitiş değerlerini değiştirin.
3. **Video bölümlerini kaydet**'e basın; `Kaydedilmiş montaj gösteriliyor.`
   mesajını görün.
4. Web tarayıcısında başka bir videoyu değiştirin. Android uygulaması ön planda
   ve canlıyken bu değişikliği sayfa yenilemeden almalıdır.
5. Normal bağlantı/senkronizasyonda `Sunucu henüz doğrulanmadı...` uyarısı
   görünmemelidir. Gerçek bağlantı veya veri okuma hatasında uyarı ve **Yenile**
   korunur; `Çevrimdışı...` uyarısı ağ yokken gösterilir.

### 13.5 Arka plan davranışı

1. Android'de Home veya son uygulamalar düğmesiyle uygulamayı arka plana atın.
2. Birkaç saniye bekleyip uygulamaya dönün.
3. Dönüşte canlı bağlantı yeniden kurulur. Normal bağlantı/senkronizasyon uyarısı
   görünmez; bağlantı ve güncel veri doğrulanana kadar düzenleme/kayıt devre dışıdır.

Bu çalışma yeni bir arka plan bildirimi veya arka plan veri çekme eklemez.
Mevcut inceleme/yayın bildirimleri değişmemiştir.

Canlı bağlantının durması, başlamış dosya aktarımını durdurmaz: Android mevcut
sistem yükleme işleriyle arka planda devam eder; sistem/ağ kısıtları etkileyebilir.
Web'de sekme gizlenince aktarım iptal edilmez, ancak tarayıcının askıya alması veya
sekmenin kapanması aktarımı kesebilir; yeniden açınca aynı dosyayı seçmek
gerekebilir. Sunucuda kuyruğa alınmış işleme/render işleri istemciden bağımsızdır.
Bu arka plan yükleme davranışları değiştirilmedi; cihazda yeniden doğrulanmadı.

### 13.6 Taslağın uygulama kapanmasına dayanması

1. Düzenleyicide geçersiz veya yarım bir değer bırakın; örneğin bitiş `4.`.
2. `Taslak bu cihaza kaydedilemedi...` uyarısı **olmadığını** kontrol edin.
3. Düzenleyiciyi kapatmadan uygulamayı son uygulamalardan kaydırarak kapatın
   veya zorla durdurun.
4. Uygulamayı yeniden açın, **Paket → Aktif Paket** ve aynı videonun
   düzenleyicisine gidin.
5. Taslak geri gelmeli; canlı bağlantı ve güncel anlık görüntü hazır olana kadar
   salt okunur kalmalıdır. Ardından değeri düzeltip kaydedin.

Taslaklar sunucu + eşleştirme bağlamı + paket kapsamında saklanır. Sunucu
değiştirme veya uygulama verilerini temizleme taslakları siler; normal kapanma
silmez.

### 13.7 Android'de çakışma

1. Android'de bir videoda değişiklik yapıp kaydetmeyin.
2. Aynı videoyu web'de başka bir istemciden değiştirip kaydedin.
3. Android'e dönün. `... için çakışan değişiklikler` bölümü açılmalı;
   **Benim değişikliğimi kullan** ve **Sunucudaki değişikliği kullan** düğmeleri
   görünmelidir.
4. Bir sürüm seçmeden kayıt yapılamaz. Seçimden sonra kayıt tek toplu istekle
   gönderilir; kısmi yazma olmaz.

## 14. PowerShell otomatik kontrolleri

Aşağıdaki komutlar arayüzde tek tek denemek yerine deterministik kapsamı
çalıştırır. Komutlar repo kökünden çalıştırılmalıdır. Bu bloklarda Python veya
SQL komutu yoktur.

### 14.1 Web birim testleri ve derleme

```powershell
npm --prefix web test -- --maxWorkers=2
npm --prefix web run build
```

Son koşuda 346 test geçti; derleme ve TypeScript kontrolü başarılı oldu.
Varsayılan paralellikte iki test zaman aşımına düştü; ayrı tekrarda ve yukarıdaki
düşük paralellikli tam koşuda geçti. Test sayısı değişebilir.

### 14.2 Tarayıcı uçtan uca testleri

İlk çalıştırmada tarayıcı yoksa bir kez kurun:

```powershell
npm --prefix web exec -- playwright install chromium
```

Tüm tarayıcı paketi:

```powershell
npm --prefix web run test:browser
```

Bu dalda son çalıştırmada 31 test geçti; mobil yerel sürükleme testi kasıtlı
olarak atlandı (1 skipped). Atlama bir hata değildir.

Yalnızca canlı durum senaryoları:

```powershell
npm --prefix web run test:browser -- live-state.spec.ts
```

Beklenen: masaüstü ve mobil projelerde toplam 8 test geçer. Bu dosya şunları
kapsar:

- Eksik/geçersiz girişin gerçek IndexedDB ile yenilemeden sonra korunması.
- Taslak geri yüklendiğinde canlı bağlantı + anlık görüntü hazır olana kadar
  salt okunur kalması.
- İki sekmenin eşzamanlı taslak yazmasında birinin atomik olarak reddedilmesi.
- İki ayrı profilde farklı videoların birleşmesi ve aynı videoda çakışmanın
  toplu isteği reddetmesi.

Bu testler gerçek Fetch akışı ve IndexedDB kullanır; PostgreSQL veya ters vekil
sunucu doğruluğu kanıtı değildir.

### 14.3 Android JVM testleri, lint ve APK

```powershell
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
& android/gradlew.bat -p android :app:testDebugUnitTest
& android/gradlew.bat -p android :app:lintDebug
& android/gradlew.bat -p android :app:assembleDebug
```

Son Android tam JVM koşusunda 279 testten 278'i geçti;
`notificationVersionOrPackageMismatchCannotAuthorizeAnotherReview` başarısız oldu.
Bu test ayrı tekrarda geçti; yeni uyarı testleri ve canlı koordinatörle birlikte
10 odaklı test ve `lintDebug` geçti. `assembleDebug` önceki doğrulamada başarılıydı.
JVM testleri parçalı UTF-8/CRLF akışlarını, eksik çerçeveleri,
socket iptalini, yalnızca heartbeat ile çalışmayı, ön plan kabulünü ve taslak
dosyası dayanıklılığını kapsar.

### 14.4 Cihaz gerektiren Android testleri

Bağlı cihaz/emülatör varsa:

```powershell
adb devices
& android/gradlew.bat -p android :app:connectedDebugAndroidTest "-Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.LiveStateTest"
& android/gradlew.bat -p android :app:connectedDebugAndroidTest "-Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.MediaEditorPanelTest"
```

Bu komutlar bu ortamda **çalıştırılmadı**; cihaz yoktu. Test APK'ları derlendi,
ancak çalışma zamanı kanıtı yoktur.

### 14.5 SSE akışını ham olarak doğrulayın

Bu betik cihaz istemcisi olarak eşleşir ve bearer token ile akışı açar. Akışı bir
PowerShell penceresinde açık bırakın; başka bir pencerede tarayıcıdan kayıt yapın.

```powershell
$Base = 'http://localhost:8000'
$Kod = ((docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-create-pairing-code create-code | Select-String 'Pairing code').ToString() -split ':', 2)[1].Trim()
$Govde = @{ code = $Kod; kind = 'device'; name = 'PowerShell SSE denemesi' } | ConvertTo-Json
$Cevap = Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/validate" -ContentType 'application/json' -Body $Govde
if (-not $Cevap.token) { throw 'Bearer token alınamadı; kind=device olmalı.' }
curl.exe -sS -N --max-time 60 -H "Authorization: Bearer $($Cevap.token)" "$Base/api/events"
```

Beklenen çıktı sırası:

```text
event: ready
data: {"protocol": 1}

event: heartbeat
data: {}
```

Akış açıkken tarayıcıda bir bölüm kaydedin. Aynı terminalde kısa süre içinde
`event: change` ve sürüm listesi görünmelidir. `--max-time 60` süresi dolunca
`curl` hata kodu 28 ile çıkar; bu normaldir, akışı kapatmak için kullanılır.
`event: resync` görürseniz istemci anlık görüntüyü baştan doğrular; bu, dinleyici
kaybı veya kaçırılmış olay durumunda beklenen davranıştır.

### 14.6 Yetkisiz SSE isteğini doğrulayın

```powershell
curl.exe -i http://localhost:8000/api/events
```

Beklenen: `401 Unauthorized`. Kimlik taşımayan hiçbir akış açılmaz.

### 14.7 Docker ile gerçek yığın kontrolleri

Tam yığın kabul testi ve iki API süreci + worker + PostgreSQL çapraz süreç testi
bu rehberin PowerShell bloklarında yer almaz; proje test çalıştırıcısı
gerektirirler. PostgreSQL ve çapraz süreç testleri artık geçti; izole TLS/ağ geçidi
kabul testi henüz çalıştırılmadı. Önceki komutlar ve doğrulama kaydı
[`docs/verification/live-state-sse.md`](../verification/live-state-sse.md)
dosyasındadır; güncel koşu özeti bölüm 3'tedir.

## 15. Sorun giderme

| Belirti | Kontrol |
| --- | --- |
| `docker info` başarısız | Docker Desktop ve Linux konteyner motorunu başlatın. |
| `/health` yanıt vermiyor | `docker compose ... ps` ve `docker compose ... logs backend`. |
| SSE isteği `503 live subscription unavailable` | PostgreSQL dinleyicisi hazır değil. Birkaç saniye sonra yeniden deneyin; sürerse backend günlüklerini ve veritabanı bağlantısını kontrol edin. |
| Canlı rozet veya son güncelleme satırı yok | Beklenen davranış; satır kaldırıldı. Canlı bağlantıyı Network → `/api/events` üzerinden doğrulayın. |
| Açılışta iki `events`, biri iptal | Geliştirme StrictMode kontrolü; tek açık bağlantı kalıyorsa normaldir. |
| Boşta yaklaşık 10 saniyede bir `change` ve dashboard GET'i | Eski worker imajı aynı gelecek Yayın Zamanı kaydını yeniden oluşturuyor olabilir. Bölüm 4'teki `--build` ile backend/worker'ı güncelleyin. |
| Kopma hemen görünmüyor | Kalp atışı zaman aşımı 45 saniyedir; bu süreye kadar bekleme normaldir. |
| Yeniden bağlanmıyor | **Canlı bağlantıyı yeniden dene**'ye basın; backend'in çalıştığını ve SSE isteğinin 200 döndüğünü kontrol edin. |
| Kaydet düğmesi kapalı | Canlı durum, çakışma, geçersiz alan, süre sınırı veya depolama hatası olabilir. Düğmenin altındaki durum metnini okuyun. |
| `Çakışan taslak` var | **Benim değişikliğimi kullan** veya **Sunucudaki değişikliği kullan** seçin; seçmeden kayıt açılmaz. |
| Taslak görünmüyor | Aynı origin, tarayıcı profili ve istemci kimliği mi? Gizli pencere/site verisi temizliği taslağı siler. Yeniden eşleştirme yeni kimlik oluşturur. |
| Android `Sunucu henüz doğrulanmadı` | Gerçek bağlantı veya veri okuma hatasını kontrol edin; normal senkronizasyonda bu uyarı gizlidir. **Yenile**'ye basın; emülatörde `10.0.2.2`, fiziksel cihazda `adb reverse` kullanın. |
| Android `No connected devices!` | Emülatörü başlatın veya USB hata ayıklamasını yetkilendirin. |
| Android yerel HTTP'yi reddediyor | Hata ayıklama APK'sı kullandığınızdan emin olun; release HTTPS ister. |
| Android'de eski taslak yok | Sunucu değiştirildiyse veya yeniden eşleştirildiyse eski bağlam taslağı görünmez; bu bilinçli kapsam davranışıdır. |

## 16. Sınırlar ve kaynaklar

- Bu dalda birleştirme veya gönderme yapılmadı. Dal
  `feat/live-state-sse`, son commit `bbfbd38`.
- Gerçek PostgreSQL ve iki API süreci + worker testleri geçti; izole TLS/ağ geçidi
  kabul testi henüz çalıştırılmadı. Canlı ölçüm scheduler düzeltmesinden önceydi.
- Android cihaz/emülatör yoktu: enstrümantasyon testleri derlendi, çalıştırılmadı.
- Tarayıcı uçtan uca testleri gerçek Fetch akışı ve IndexedDB kullanır; ancak
  veritabanı ve ters vekil davranışını kanıtlamaz.
- Veri taşıma, geri doldurma veya kesme planı yoktur. PostgreSQL tek doğruluk
  kaynağıdır.
- Üretimde HTTPS ve `COOKIE_SECURE=true` kullanılmalıdır.

Ayrıntılı kanıt, engelli kontroller ve yeniden üretme komutları:

- [`docs/verification/live-state-sse.md`](../verification/live-state-sse.md)
- [`docs/superpowers/specs/2026-10-20-live-state-sse-design.md`](../superpowers/specs/2026-10-20-live-state-sse-design.md)
- [`docs/superpowers/plans/2026-10-20-live-state-sse.md`](../superpowers/plans/2026-10-20-live-state-sse.md)
- [`web/e2e/live-state.spec.ts`](../../web/e2e/live-state.spec.ts)
- [`backend/tests/test_live_integration.py`](../../backend/tests/test_live_integration.py)
- [`android/app/src/main/java/com/dojo/aisomedo/live/LiveCoordinator.kt`](../../android/app/src/main/java/com/dojo/aisomedo/live/LiveCoordinator.kt)
- [`android/app/src/main/java/com/dojo/aisomedo/editor/DraftStore.kt`](../../android/app/src/main/java/com/dojo/aisomedo/editor/DraftStore.kt)
