# Web kontrol paneli — Değişiklik özeti ve deneme rehberi (#25)

Bu rehber, yeni web arayüzünü adım adım denemek içindir. Görsel kontroller
tarayıcıda yapılır. Arayüzde henüz düğmesi olmayan işlemler için PowerShell
kullanılır; aşağıdaki komutlarda Python veya SQL kodu yoktur.

> **Deneme ortamı kullanın.** Plan değiştirme, paket oluşturma, manuel yayın
> zamanı ekleme ve istemci iptali kalıcı değişikliklerdir. Gerçek dojo verileriyle
> çalışıyorsanız ilgili bölümleri uygulamayın. Bu rehber yayın onayı vermez ve
> Instagram'a paylaşım göndermeyi tarif etmez.

## 1. Neler değişti?

| Değişiklik | Kullanıcıya etkisi |
|---|---|
| Dört bölümlü web arayüzü | Kontrol Paneli, Güncel Paket, Etkinlik ve Ayarlar arasında gezinme |
| Tarayıcı eşleştirme formu | Tek kullanımlık kod ve tarayıcı adıyla giriş; hesap/parola gerekmez |
| Dashboard API'si | Paket, sonraki yayın zamanı, bekleyen işlemler ve servis durumları tek yanıtta |
| Canlı yenileme | Sayfa görünürken beş saniyede bir; sekmeye dönüşte ve bağlantı gelince hemen yenileme |
| Hata durumları | Bağlantı kesilince son bilgiler uyarıyla korunur; iptal edilen oturum temizlenir |
| Gerçek worker sağlık kaydı | API'nin çalışması, worker'ın çalıştığı anlamına gelmez; ikisi ayrı izlenir |
| Türkçe metin kataloğu | Menü, hata ve durum metinleri dışarıda tutulur; tarihler Türkiye saatinde gösterilir |
| Mobil düzen ve testler | Dar ekranda menü ve içerik yeniden düzenlenir; web davranış testleri CI'da çalışır |

**Bu sürümün sınırı:** Güncel Paket ve Ayarlar özet ekranlarıdır; Etkinlik son
20 kaydı gösterir. Medya yükleme, onay/atla/yeniden planla ve ayar düzenleme
formları bu iş kapsamında eklenmedi. Bu işlemler için aşağıda API komutları veya
mevcut ilgili rehberler kullanılır. “İnceleme özeti” bağlantısı yayın onayı değildir.

## 2. Hazırlık: yerel deneme ortamını başlatın

Gerekenler: Docker Desktop'ın Linux konteyner motoru açık olmalı; Node.js/npm
kurulu olmalı. PowerShell'i bu değişikliklerin bulunduğu **repo kökünde** açın.
Çalışma dalı `feat/issue-25-web`; ayrı çalışma dizini
`.worktrees/issue-25-web` olarak oluşturuldu. Komutları eski checkout'ta çalıştırırsanız
eski web ekranını görebilirsiniz.

```powershell
git branch --show-current
docker info --format '{{.ServerVersion}}'
if (-not (Test-Path ops/.env)) {
    Copy-Item ops/.env.example ops/.env
}
notepad ops/.env
```

`ops/.env` dosyasında şu değerleri kontrol edin:

- `POSTGRES_PASSWORD`: boş olmamalı; örnek parolayı üretimde kullanmayın.
- `COOKIE_SECURE=false`: yalnızca bu **yerel HTTP denemesi** için. Üretimde HTTPS
  ve `true` kullanın. HTTP'de Secure çerez tarayıcı tarafından gönderilmez.
- `WORKER_HEALTH_PATH=/run/dojo-worker/health.json`: eski `/tmp/...` değerini
  değiştirin. Worker ve backend aynı dosyayı görmelidir; backend salt okunur bağlar.

Mevcut `.env` dosyanızın üzerine kopyalama yapmayın. Veritabanı ve medya klasörleri
daha önce mevcutsa korunur; bu rehber bunları silmez.

```powershell
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose --env-file ops/.env -f ops/docker-compose.yml up -d --build db backend worker
docker compose --env-file ops/.env -f ops/docker-compose.yml ps
Invoke-RestMethod http://localhost:8000/health
npm --prefix web ci
npm --prefix web run dev
```

Son komut terminali meşgul tutar; açık bırakın. Diğer komutlar için yeni bir
PowerShell penceresi kullanın. Tarayıcıda Vite'ın yazdığı adresi açın; varsayılan
adres **http://localhost:3000**. Port doluysa terminaldeki farklı portu kullanın.
Backend `:8000` adresi web sayfasını sunmaz; arayüz için Vite adresini açmalısınız.

Beklenen: “Tarayıcıyı eşleştir” ekranı. Yükleme yerine bağlantı hatası görünürse
önce backend'in çalıştığını kontrol edin.

## 3. Tarayıcıyı eşleştirin

İlk kod üretiminin arayüzü yoktur. Yeni PowerShell penceresinde repo kökünden:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-create-pairing-code create-code
```

Çıktıdaki `Pairing code` değerini tarayıcıdaki **Eşleştirme kodu** alanına yazın.
**Tarayıcı adı** için `İstanbul Dojo Yönetim Bilgisayarı` yazın ve **Eşleştir**'e basın.

Beklenen:

1. Kontrol Paneli açılır.
2. Masaüstünde sol menü, dar ekranda üstte dört bağlantı görünür.
3. Sayfayı yenilediğinizde aynı tarayıcı yeniden kod istemez.
4. Kod tek kullanımlıktır. Ayrı bir gizli pencere açıp aynı kodu tekrar denerseniz
   “Kod geçersiz veya süresi dolmuş” uyarısı beklenir. Başka pencere için yeni kod üretin.

Çerez kontrolü, isterseniz tarayıcı geliştirici araçlarında **Application/Storage →
Cookies** bölümünden yapılır: `dojo_session` için `HttpOnly` işaretli olmalıdır.
Çerez değerini paylaşmayın. Konsola kod yapıştırmanız gerekmez.

## 4. Dört ekranı ve mevcut durumu kontrol edin

Tarayıcıdaki menüyü sırayla kullanın:

| Ekran | Beklenen |
|---|---|
| Kontrol Paneli | Bekleyen işlem; Dojo Paylaşım Paketi; Sonraki Yayın Zamanı; Instagram; Worker |
| Güncel Paket | Paketin adı, durumu ve oluşturulma zamanı; paket yoksa açıklayıcı boş durum |
| Etkinlik | Son kayıtlar, işlemi yapan istemci ve tarih; bilinmeyen olaylar teknik hata metni yerine genel Türkçe metin |
| Ayarlar | Bu tarayıcının adı, yayın planı ve bağlantı özetleri |

Yeni bir kurulumda “Henüz aktif paket yok”, “Planlanmış yayın yok” ve Instagram
için “Bağlı değil” normaldir. Dashboard'u açmak tek başına paket veya yayın işi
oluşturmaz. Worker sağlık dosyası yoksa “Durum bilinmiyor” görünür; bu, sağlıklı
olduğu iddiası değildir.

Tarayıcının geri/ileri düğmelerini ve bir bölüm açıkken sayfa yenilemeyi deneyin.
Adresler `#/dashboard`, `#/package`, `#/activity`, `#/settings` biçimindedir.

## 5. PowerShell için ayrı bir deneme oturumu açın

Sonraki veri değiştirme adımları için PowerShell'in kendi çerez oturumu gerekir.
Tarayıcı çerezlerini kopyalamayın. **Yeni** bir kod üretin, ardından:

```powershell
$Base = 'http://localhost:8000'
$Kod = Read-Host 'Yeni eşleştirme kodu'
$Giris = @{ code = $Kod; kind = 'browser'; name = 'PowerShell deneme istemcisi' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/validate" -ContentType 'application/json' -Body $Giris -SessionVariable DojoSession
Invoke-RestMethod -Uri "$Base/api/pairing/me" -WebSession $DojoSession
```

Beklenen: PowerShell istemcisinin kimliği döner. `$DojoSession` bu PowerShell
penceresinde tutulur. Aşağıdaki komutları aynı pencerede çalıştırın. Bu oturum ve
tarayıcı oturumu birbirinden bağımsızdır; ikisi de eşit yetkilidir.

## 6. Paket oluşturup tarayıcıda otomatik yenilemeyi görün

**Yalnızca deneme verisinde uygulayın.** Arayüzde paket oluşturma düğmesi henüz yok:

```powershell
Invoke-RestMethod -Uri "$Base/api/packages/active" -WebSession $DojoSession
```

Bu mevcut API, paket yoksa oluşturur; varsa mevcut paketi döndürür. Kontrol
Paneli'ni **görünür sekmede açık bırakın**, yenile düğmesine basmayın.
Normalde beş saniye ve istek süresi içinde paket adı görünmelidir. Güncel Paket
bölümünde aynı adın ve oluşturulma tarihinin yer aldığını kontrol edin.

## 7. Sonraki yayın zamanını deneyin

Bu adım yayın planını değiştirir. Önce mevcut planı bellekte saklayın:

```powershell
$EskiPlan = Invoke-RestMethod -Uri "$Base/api/settings/plan" -WebSession $DojoSession
$Pazartesi = (Get-Date).Date.AddDays(1)
while ($Pazartesi.DayOfWeek -ne [DayOfWeek]::Monday) {
    $Pazartesi = $Pazartesi.AddDays(1)
}
$YeniPlan = @{ anchor_date = $Pazartesi.ToString('yyyy-MM-dd'); anchor_time = '18:30:00'; enabled = $true } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$Base/api/settings/plan" -WebSession $DojoSession -ContentType 'application/json' -Body $YeniPlan
```

Tarayıcıda **Sonraki Yayın Zamanı**, seçilen pazartesiyi saat **18:30** olarak
göstermelidir. Ayarlar ekranında planın etkin olduğunu kontrol edin.
Takvim iki haftada bir, yani **14 gün** aralıklıdır; “15 gün” değildir.

Eski planın başlangıç tarihi ve saati doluysa geri almak için:

```powershell
if ($EskiPlan.anchor_date -and $EskiPlan.anchor_time) {
    $GeriAl = @{ anchor_date = $EskiPlan.anchor_date; anchor_time = $EskiPlan.anchor_time; enabled = $EskiPlan.enabled } | ConvertTo-Json
    Invoke-RestMethod -Method Put -Uri "$Base/api/settings/plan" -WebSession $DojoSession -ContentType 'application/json' -Body $GeriAl
}
```

Eski plan ayarlanmamışsa API boş başlangıç değerleri kabul etmez. Deneme planını
aynı başlangıç değerleriyle `enabled = $false` yapabilirsiniz; bu eski “hiç
ayarlanmamış” duruma birebir dönüş değildir. Üretim planı üzerinde deneme yapmayın.

## 8. Bekleyen işlemi ve başka cihazın değişikliğini görün

Deneme paketinde yeni manuel yayın zamanı oluşturun:

```powershell
Invoke-RestMethod -Method Post -Uri "$Base/api/settings/manual-publish" -WebSession $DojoSession
```

Bu komut **Instagram'a gönderim yapmaz**; inceleme gerektiren bir zaman oluşturur.
Mevcut bekleyen manuel zaman varsa `409` normaldir; tekrar tekrar çalıştırmayın.

Tarayıcıda bir sonraki yenilemede bekleyen işlem görünmelidir. Boş paket için
“Medya eklenmesi gerekiyor”, medya/render hazırlığı için “İnceleme hazırlanıyor”,
hazır render ve inceleme için “Yayın İncelemesi hazır” beklenir. Worker'ın kendi
çalışma aralığı, tarayıcının beş saniyelik yenileme aralığından ayrıdır.

**Başka istemciden çözümleme**, yalnızca gerçekten oluşmuş inceleme varsa denenir:

```powershell
$Bekleyen = Invoke-RestMethod -Uri "$Base/api/reviews/pending" -WebSession $DojoSession
$Bekleyen.reviews | Select-Object id, version, package_folder, status
```

Liste boşsa inceleme çözümleme adımını atlayın. Yalnızca bir due zaman oluşmuş
olması, her koşulda hazır inceleme oluştuğu anlamına gelmez. Hazır inceleme
oluşturmak için [Yayın İncelemesi rehberini](yayin-incelemesi-due-time-rehberi.md)
ve [render rehberini](immutable-reel-render-pipeline-rehberi.md) kullanabilirsiniz.

Deneme incelemesini **atlamak kalıcı bir karardır**: aynı paket korunur, ilgili
zaman çözülür. Yalnızca deneme incelemesini seçin; onay komutu kullanmayın:

```powershell
$IncelemeId = [int](Read-Host 'Atlanacak deneme incelemesinin id değeri')
$Inceleme = $Bekleyen.reviews | Where-Object { $_.id -eq $IncelemeId } | Select-Object -First 1
if ($null -eq $Inceleme) { throw 'Listede böyle bir inceleme yok; işlem yapılmadı.' }
$Atla = @{ version = $Inceleme.version; confirmed = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$Base/api/reviews/$IncelemeId/skip" -WebSession $DojoSession -ContentType 'application/json' -Body $Atla
```

Tarayıcıda işlem bir sonraki başarılı yenilemede kaybolmalıdır. İnceleme özeti
açıksa artık mevcut olmadığına dair Türkçe mesaj görünür. `409`, başka istemcinin
işlemi önce tamamlamış olabileceğini gösterir; listeyi yeniden alın.

## 9. Bağlantı kaybı ve sekmeye dönüş — tarayıcı

1. Dashboard'un başarıyla yüklendiğinden emin olun.
2. Geliştirici araçlarında **Network → Offline** seçin. **Disable cache** tek
   başına çevrimdışı yapmaz.
3. Sonraki başarısız istekte son bilgiler korunmalı ve güncel olmadığını belirten
   uyarı görünmelidir. İlk yükleme başarısızsa hayalî paket yerine hata/tekrar dene görünür.
4. Network ayarını **No throttling/Online** yapın; pencereye tekrar odaklanın.
5. Başarılı yenilemede uyarı kalkmalı ve bilgiler güncellenmelidir.
6. Başka sekmeye geçip geri dönün. Gizli sekmede düzenli istek gönderilmez;
   dönüşte yeni istek gönderilir. DevTools'ta `/api/dashboard` isteklerini filtreleyebilirsiniz.

Offline ayarının sadece geliştirici araçlarının bağlı olduğu sekmeyi etkilediğini
unutmayın. PowerShell istemcisinin bağlantısını kesmek gerekmez.

## 10. Worker sağlığını ayrı deneyin

**Yalnızca yerel deneme worker'ını durdurun.** Gerçek yayını işleyen serviste
uygulamayın:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml stop worker
Invoke-RestMethod "$Base/health"
```

Tarayıcıda Worker durumu artık sağlıklı kalmamalıdır. Düzgün kapanışta durduruldu
kaydıyla “Kontrol gerekiyor” beklenir. Ani duruşta son kaydın süresi dolana kadar
beklemek gerekebilir: varsayılan boşta sınırı 120, meşgul sınırı 3600 saniyedir.
Backend `/health` yanıtının hâlâ `ok` olması bu ayrımı gösterir.

Tekrar başlatın:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml start worker
```

Yeni sağlık kaydı yazıldıktan sonraki dashboard yenilemesinde “Çalışıyor” ve
“Hazır/İşleniyor” beklenir. “Durum bilinmiyor” kalıyorsa `.env` dosyasında ortak
sağlık yolunu ve konteyner bağlamalarını kontrol edin. Dosyayı elle üretmeyin.

## 11. Tarayıcı erişimini iptal edin

Bu adım hedef tarayıcıyı çıkışa zorlar. PowerShell oturumunu değil, tarayıcıda
girdiğiniz adı seçin. İptal geri alınmaz; tekrar giriş için yeni kod gerekir.

```powershell
$Istemciler = Invoke-RestMethod -Uri "$Base/api/pairing/clients" -WebSession $DojoSession
$Istemciler | Select-Object id, name, kind, revoked_at | Format-Table
$TarayiciId = [int](Read-Host 'İptal edilecek deneme tarayıcısının id değeri')
Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/clients/$TarayiciId/revoke" -WebSession $DojoSession
```

Tarayıcı görünürken bir sonraki korumalı istekte paket bilgileri temizlenmeli ve
“Tarayıcıyı eşleştir” ekranı açılmalıdır. Sayfayı elle yenilemeniz gerekmemelidir.

## 12. Mobil görünüm ve klavye kontrolü — tarayıcı

Geliştirici araçlarının cihaz görünümünde **320**, **390** ve **1280 px** genişlikleri
deneyin. Beklenen: yatay kaydırma yok; uzun isimler satır kırıyor; bütün menü
bağlantıları erişilebilir; dar ekranda içerikler alt alta geliyor.

`Tab` ile gezinip odak çizgisini, `Enter` ile bağlantı ve düğmeleri kontrol edin.
“İçeriğe geç” bağlantısı mevcut bölümü değiştirmeden ana içeriğe odaklanmalıdır.

## 13. Otomatik kontroller ve denemeyi durdurma

```powershell
npm --prefix web test
npm --prefix web run build
git status --short
```

Web testleri ve build başarılı bitmelidir. Vite terminalinde `Ctrl+C` kullanın.
Bu denemede başlattığınız konteynerleri verileri silmeden durdurmak için:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml stop
```

`down -v`, veritabanı silme veya klasör temizleme komutu bu rehberde yoktur.

## Doğrulama durumu ve bilinen sınırlar

Bu rehber hazırlanırken 21 web, 119 backend ve 140 worker testi geçti. Gerçek
HTTP uygulaması ve tarayıcıyla eşleştirme, HttpOnly çerez, due işlem yenilemesi,
erişim iptali ve üç ekran genişliği denendi. Docker'ın sonradan kapanması nedeniyle
tam PostgreSQL/Compose kabul testi tamamlanmadı. Son bağımsız incelemede worker
sağlık kaydının uç değerleri ve yavaş isteğe bağlı sağlık okumaları için düzeltme
gerektiren bulgular da bildirildi; henüz bütün işin tamamlandığı iddia edilmiyor.

Ayrıntılı test kaydı: [Issue #25 doğrulama notları](../verification/issue-25-web-dashboard.md).
