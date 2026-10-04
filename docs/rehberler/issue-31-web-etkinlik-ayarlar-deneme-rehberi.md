# Web Etkinlik ve Ayarlar — Değişiklik özeti ve deneme rehberi (#31)

Bu rehber `b49d097` commit'indeki değişiklikleri anlatır. Denemeler öncelikle
**tarayıcıda** yapılır. İlk eşleştirme kodunu veya rıza metnini oluşturmak gibi
arayüzde bulunmayan hazırlıklar için **PowerShell** komutları kullanılır.
Kod bloklarında Python veya SQL kodu yoktur.

> **Ayrı deneme ortamı kullanın.** Kaydedilen ayarlar aynı kuruluma bağlı bütün
> cihazları etkiler. Instagram bağlantısını değiştirmek ve yeni rıza sürümü
> oluşturmak gerçek sonuçları olan işlemlerdir. Bu rehber yayın onayı vermeyi,
> paket silmeyi veya veritabanını sıfırlamayı gerektirmez. Üretim ortamında sırf
> denemek için ayar değiştirmeyin. Gerçek veri veya hesap kullanmak istemiyorsanız
> doğrudan bölüm 10'daki sahte API'li tarayıcı testlerini çalıştırın.

## 1. Neler değişti?

| Değişiklik | Göreceğiniz sonuç |
| --- | --- |
| Düzenlenebilir Ayarlar | Düzenli yayın planı, logo, açıklama şablonu ve giriş/çıkış kartları artık Ayarlar ekranından kaydedilebilir. Kurulum sihirbazını yeniden açmak gerekmez. |
| Hatırlatma formu | Dakika cinsinden aralık ve bildirim gönderilebilecek saatler düzenlenebilir. Gece yarısını geçen pencere desteklenir. |
| Instagram bağlantısı | Hesap/durum gösterilir; OAuth veya kendi aldığınız token ile yeniden bağlanabilirsiniz. Hesap bağlı değilse bu açıkça belirtilir. |
| Rıza gösterimi | Ayarlar'da metin, sürüm ve kabul durumu görünür. Kabul işlemi burada yapılmaz; kurulum sihirbazında yapılır. |
| Kaydetme geri bildirimi | Başarılı kayıtta “Ayarlar kaydedildi.” görünür. Yeniden düzenleme başladığında eski başarı mesajı kalkar. |
| Taslak koruması | Başka bir sekme/cihazın değişikliği yazmakta olduğunuz formu ezmez. Sunucu değerlerini yüklemek sizin seçiminizdir. |
| Etkinlik açıklamaları | Mevcut son 20 olaylık akış kullanılır; marka, hatırlatma, rıza kabulü ve Instagram bağlantısı olaylarına Türkçe başlıklar eklendi. İşlemi yapan cihaz ve zaman görünür. |
| Hata ayrımı | Ayar yazıldıktan sonra kurulum durumunun yenilenmesi başarısız olursa başarılı kayıt yanlışlıkla başarısız gösterilmez; yenileme sorunu ayrıca bildirilir. |

Mevcut kurulum formları ve backend uçları yeniden kullanıldı; yeni bağımlılık
eklenmedi. Ayarlar'daki kart kaydı, sihirbazın “kartları atla” işlemini çalıştırmaz.
Ayarlar, Kontrol Paneli verisi alınamasa da kendi ayar uçlarından yüklenebilir;
bu, backend tamamen kapalıyken çalışacağı anlamına gelmez.

**Kapsam sınırı:** Bu değişiklik web push bildirimi eklemez. Hatırlatma ayarını
kaydetmek, tarayıcıya anında bildirim göndermez. Logo/kart/açıklama ayarları yeni
paketlerin varsayılanlarıdır; mevcut Aktif Paket'in kaydedilmiş marka/açıklama
görüntüsünü değiştirmek için kullanılmaz.

## 2. Deneme yolunu seçin

- **Çalışan, ayrı backend deneme ortamınız varsa:** bölümler 3–9 ile gerçek
  tarayıcı denemelerini yapın. Ayarlar'ı denemek için worker veya hazır Reel gerekmez.
- **Backend, Docker veya Instagram hesabı olmadan denemek istiyorsanız:** bölüm
  10'a geçin. PowerShell komutuyla açılan test tarayıcısı sahte API kullanır.
  Gerçek veritabanına/Instagram'a yazmaz. Bu yol gerçek sunucu kalıcılığını veya
  Meta entegrasyonunu değil, arayüz davranışını doğrular.

Bu rehber hazır backend'in güncel uygulama/veritabanı şemasıyla çalıştığını varsayar.
Sıfırdan ortam kurulumu için [kurulum rehberine](issue-26-web-onboarding-deneme-rehberi.md)
bakın; eski dal/worktree adresini değil **#31'i içeren mevcut checkout'u** kullanın.
Mevcut veritabanını yükseltmeniz gerekiyorsa [#30 rehberindeki yedek ve migration
uyarılarını](issue-30-web-yayin-incelemesi-deneme-rehberi.md#31-backend-worker-ve-web)
da okuyun. Yalnız image build etmek mevcut şemayı güncellemez. Compose proje adını
değiştirmek bind-mount veri dizinlerini kendiliğinden ayırmaz.

## 3. Arayüzü açın ve tarayıcıyı eşleştirin

### 3.1. Zaten çalışan web varsa

Mevcut web adresinde **Ayarlar** bağlantısını açın; adresin sonunda `#/settings`
olmalıdır. **Hatırlatmalar** ve düzenlenebilir formlar görünüyorsa bölüm 4'e geçin.
Yalnız eski özet görünüyorsa doğru checkout'u ve çalışan web sürecini kontrol edin.

### 3.2. Yalnız backend hazırsa — PowerShell

Repo kökünde PowerShell açın. Örnek yolu kendi checkout'unuza göre değiştirin:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
git log -1 --oneline
Invoke-RestMethod -Uri 'http://localhost:8000/health'
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -eq 4311 } |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Backend sağlık yanıtında `status: ok` beklenir; bu tek başına şema doğrulaması
değildir. **4311** doluysa başka boş port seçin; mevcut süreci zorla kapatmayın.

```powershell
npm --prefix web ci
if ($LASTEXITCODE -ne 0) { throw 'Web bağımlılıkları kurulamadı.' }
npm --prefix web run dev -- --host localhost --port 4311 --strictPort
```

Terminali açık bırakın. Tarayıcıda **http://localhost:4311/#/settings** açın.
Vite, API isteklerini `http://localhost:8000` adresindeki backend'e iletir.
8000 web arayüzü değildir. `localhost` ve `127.0.0.1` arasında geçiş yapmayın;
oturum çerezleri farklı adreslere aittir. Yerel HTTP denemesinde backend için
`COOKIE_SECURE=false` gerekir; üretimde HTTPS/güvenli çerez ayarlarını koruyun.

### 3.3. Eşleştirme gerekiyorsa — PowerShell + tarayıcı

Backend deneme ortamınız bu Compose dosyasıyla çalışıyorsa repo kökünde **ikinci
PowerShell penceresi** açıp kod üretin:

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-f', 'ops/docker-compose.yml')
docker compose @ComposeArgs exec -T backend .venv/bin/dojo-create-pairing-code create-code
```

Ortamınız özel Compose proje adı kullanıyorsa `$ComposeArgs` içine aynı `-p` ve
proje adını ekleyin. Başka backend kurulumunu hedeflemeyin. Backend'i Docker yerine
yerel proje komutlarıyla çalıştırıyorsanız, aynı deneme veritabanına bağlı mevcut
eşleştirme CLI'sini kullanın.

1. Çıktıdaki **Pairing code** değerini **Eşleştirme kodu** alanına yazın.
2. **Tarayıcı adı** alanına `Ayarlar deneme tarayıcısı` yazın.
3. **Eşleştir** düğmesine basın.
4. Gerekirse menüden **Ayarlar**'ı seçin veya aynı adresin sonuna `#/settings` yazın.

Kod tek kullanımlık ve süre sınırlıdır. Gizli pencere/başka tarayıcı için yeni kod
gerekir. Kod, oturum çerezi ve tokenları paylaşmayın. Eksik kurulum varsa Kontrol
Paneli sihirbaza yönlendirebilir; Ayarlar'ı doğrudan açıp formları deneyebilirsiniz.
Sadece bu denemeler için Instagram bağlantısını tamamlamanız şart değildir.

## 4. Düzenli yayın planını kaydedin — tarayıcı

Önce mevcut tarih, saat ve etkinlik durumunu not alın. Deneme boyunca düzenli
yayını kapalı tutun; böylece worker'ın düzenli Yayın Zamanı üretmesini önlersiniz.

1. **Dojo Yayın Planı** bölümünü bulun.
2. **İlk yayın tarihi** için bir Pazartesi seçin; örneğin takvimde gelecek Pazartesi.
3. **Yayın saati** alanına `13:30` yazın.
4. **Düzenli yayını etkinleştir** kutusunu boş bırakın.
5. **Planı kaydet** düğmesine basın.
6. Aynı bölümde **Ayarlar kaydedildi.** mesajını bekleyin.
7. Sayfayı F5 ile yenileyin; tarih, `13:30` ve kapalı durum korunmalıdır.
8. Tarihi bir Salı yapıp tekrar kaydetmeyi deneyin. **İlk yayın tarihi Pazartesi
   olmalı.** uyarısı görünmeli. F5 sonrasında son başarılı Pazartesi tarihi dönmelidir.

**Beklenen:** Plan her iki haftada bir Pazartesi kuralını kullanır; saat dilimi
`Europe/Istanbul`'dur. Geçerli ama kapalı plan, “tanımlanmamış plan” değildir.
Planı kaydetmek bir Yayın İncelemesi'ni onaylamaz veya anında Instagram'a yayın yapmaz.

## 5. Marka ayarlarını kaydedin — tarayıcı

Deneme için gerçek öğrenci fotoğrafı yerine küçük PNG/JPEG görseller kullanın.
Görseller tek kareli, en fazla **10 MiB** ve kenar başına **4096 piksel** olmalıdır.
Orijinal logo/kart dosyalarını geri yüklemek için elinizde bulundurun.

### 5.1. Logo

1. **Dojo logosu → Logo görseli** alanından bir PNG/JPEG seçin.
2. **Logoyu kaydet** düğmesine basın ve başarı mesajını bekleyin.
3. **Logo önizlemesi** görünmelidir.
4. F5 ile yenileyin; önizleme korunmalıdır. Dosya seçme alanının boşalması normaldir;
   kayıtlı görselin kaybolduğu anlamına gelmez.
5. İsterseniz PDF gibi desteklenmeyen bir dosya seçmeyi deneyin; dosya seçici izin
   veriyorsa PNG/JPEG uyarısı beklenir. Önceki kayıt değişmemelidir.

### 5.2. Açıklama şablonu

1. **Açıklama şablonu** alanına `Dojo denemesi — #dojo #deneme` yazın.
2. **Açıklamayı kaydet** düğmesine basın; başarı mesajını bekleyin.
3. F5 sonrasında metin aynı kalmalıdır.
4. Alanı boşaltıp kaydetmeyi deneyin. Tarayıcının zorunlu alan uyarısı veya form
   hatası çıkmalıdır; son başarılı metin değişmemelidir.

Bu deneme şablonun kaydını kontrol eder; özel değişken/yer tutucu desteği varsaymaz.
Güncel Paket'in mevcut açıklamasının değişmesini beklemeyin.

### 5.3. Giriş ve çıkış kartları

1. **Giriş ve çıkış kartları** bölümünde **Giriş görseli** seçin; süreyi `1.5`
   saniye yapın. Sayı alanı bölgesel ayara göre `1,5` gösterebilir.
2. **Çıkış görseli** seçin; süreyi `2` saniye yapın.
3. **Kartları kaydet** düğmesine basın.
4. F5 sonrasında iki önizleme ve süreler korunmalıdır.
5. **Çıkış kartını kaldır** düğmesine basın. Bu henüz yalnız taslaktır.
6. **Kartları kaydet**'e basın; F5 sonrasında çıkış kartı görünmemeli, giriş kartı
   korunmalıdır.

Süre boş bırakılırsa varsayılan fotoğraf süresi kullanılır. Pozitif olmayan süre
veya görsel olmadan süre tanımlama reddedilir. Ayarlar'da **Kartları değiştirmeden
devam et** düğmesi bulunmamalıdır; bu yalnız kurulum sihirbazının davranışıdır.

## 6. Hatırlatmaları ve doğrulamayı deneyin — tarayıcı

1. **Hatırlatmalar** bölümündeki mevcut değerleri not alın. Önceden değiştirilmemiş
   varsayılanlar: `360` dakika, başlangıç `08:00`, bitiş `22:00`.
2. **Hatırlatma aralığı (dakika)** alanını `120` yapın.
3. **Bildirim başlangıcı** `09:00`, **Bildirim bitişi** `21:00` olsun.
4. **Hatırlatmaları kaydet**'e basın; başarı mesajını bekleyip F5 yapın.
5. Üç değerin de korunduğunu kontrol edin.
6. Başlangıcı `22:00`, bitişi `08:00` yapıp kaydedin. Gece yarısını geçen bu pencere
   geçerlidir; F5 sonrasında aynı değerler dönmelidir.
7. İki saati de `08:00` yapıp kaydetmeyi deneyin. Farklı saat seçmeniz istenmeli;
   F5 sonrasında önceki `22:00`–`08:00` kaydı korunmalıdır.
8. Aralığı `0`, sonra `1.5` yapıp kaydetmeyi deneyin. Tarayıcı doğrulaması veya
   pozitif tam sayı uyarısı çıkmalıdır; sunucudaki son başarılı aralık değişmemelidir.
9. Geçerli bir kayıt sonrası alanı tekrar değiştirin. Önceki **Ayarlar kaydedildi.**
   mesajı kalkmalıdır; kaydedilmemiş yeni değer için başarı gösterilmemelidir.

Saatler **bildirim gönderilebilen pencereyi** belirtir; pencere dışı sessizdir.
`120`, iki saatlik hatırlatma aralığıdır; aralık alanının birimi saat değil dakikadır.
Bu deneme için gerçek bildirim beklemeyin: teslimat worker, bekleyen Yayın İncelemesi
ve bildirim altyapısına bağlıdır. Saat dilimi burada da `Europe/Istanbul` olarak sabittir.

## 7. Başka sekmenin değişikliğinde taslak koruması — tarayıcı

İki sekmede **aynı kurulumun** Ayarlar ekranını açın. Taslakların sekmeler arasında
paylaşılmaması normaldir; yalnız kaydedilen sunucu değerleri ortaktır.

1. **A sekmesinde** hatırlatma aralığını `60` yapın, **kaydetmeyin**.
2. **B sekmesinde** aralığı `90` yapıp kaydedin; başarı mesajını bekleyin.
3. A sekmesine dönün, birkaç saniye bekleyin. Sayfa odaklanınca veya görünürken
   yaklaşık beş saniyelik yenilemede **Başka bir cihaz ayarları değiştirdi.
   Taslağınız korunuyor.** mesajı görünmelidir.
4. A'nın alanı hâlâ `60` olmalıdır; `90` ile sessizce ezilmemelidir.
5. A'da **Sunucudaki değerleri yükle** düğmesine basın. Alan `90` olmalıdır.
6. A'da yeniden `60` taslağı bırakıp B'de `120` kaydedin. A'ya dönün; bu kez kendi
   `60` taslağınızı kaydedin. F5 sonrası `60` dönmelidir.

**Önemli:** Taslak koruması otomatik birleştirme veya çakışan kaydı engelleme değildir;
siz kaydetmeyi seçerseniz aynı formun sunucu değerlerini değiştirebilirsiniz. Bu
koruma canlı veri yenilenirken geçerlidir. F5, sayfa kapatma veya Ayarlar'dan başka
ekrana geçiş sonrasında kaydedilmemiş taslakların saklanacağını varsaymayın.

## 8. Instagram durumunu ve medya rızasını kontrol edin — tarayıcı

### 8.1. Instagram

1. **Instagram** bölümünü bulun. Bağlı hesap varsa kullanıcı adı ve **Bağlantı
   doğrulandı** veya **Yeniden bağlantı gerekli** görünmelidir. Hesap yoksa
   **Hesap bağlı değil** görünmelidir.
2. Yeniden bağlamayı yalnız test hesabınız varsa deneyin. **Instagram ile
   yetkilendir** düğmesine basın.
3. Yetkilendirme yeni pencerede açılmalıdır. Açılmazsa **Yetkilendirme sayfasını
   aç** bağlantısını kullanın. Ayarlar sekmesini kapatmayın.
4. Meta tarafında yetkilendirmeyi tamamlayıp Ayarlar'a dönün; dönen adaylardan
   **@... hesabını seç** düğmesiyle test hesabınızı seçin.
5. **Bağlantı doğrulandı** durumunu görün; F5 sonrasında aynı hesap görünmelidir.
6. Kontrol Paneli/Güncel Paket'te mevcut paket ve düzenli planın bu bağlantı
   işlemi nedeniyle değişmediğini kontrol edin.

Alternatif: Kendi aldığınız geçerli test tokenını maskeli **Instagram erişim tokenı**
alanına girip **Token ile bağlan**'a basın. Gönderilen token alanının boşalması
beklenir. Tokenı komut geçmişine, ekran görüntüsüne veya rehbere yapıştırmayın.
Mevcut hesap yeni bağlantı doğrulanana kadar korunur.

Meta uygulaması, şifreleme anahtarı ve OAuth callback yapılandırması eksikse gerçek
bağlantı tamamlanamaz. Yerel Vite'ı açmak bu hazırlıkları sağlamaz; bu durumda
[Instagram rehberine](yayin-yurutme-instagram-graph-api-rehberi.md) bakın veya bölüm
10'daki sahte bağlantı senaryosunu kullanın. Sırf hata üretmek için mevcut hesabın
tokenını iptal etmeyin.

### 8.2. Medya rızası

1. **Medya rızası** bölümünde metin ve **Rıza metni · Sürüm ...** bilgisini kontrol edin.
2. Kabul edilmişse **Rıza kaydedildi** ve tarih/saat görünmelidir.
3. Kabul edilmemişse **Bu sürüm için medya rızası henüz kaydedilmedi** mesajı
   görünmelidir. Ayarlar'da kabul kutusu ve **Rızayı kaydet** düğmesi olmamalıdır.
4. Kabulü gerçekten test etmek istiyorsanız **Kurulumu aç** bağlantısından
   sihirbaza geçin; **Medya rızası** adımını seçin, metni okuyup açıkça kabul edin.
5. Ayarlar'a dönün; kabul bilgisi görünmelidir. Kabul kurulum genelindedir;
   başka eşleştirilmiş cihaz da aynı sürümün kabulünü görür.

**Metin hiç yoksa**, rıza metninin henüz tanımlanmadığı mesajı görünür. İlk metin
oluşturmanın tarayıcı ekranı yoktur. Yalnız ayrı deneme ortamında PowerShell'de:

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-f', 'ops/docker-compose.yml')
$ConsentVersion = [int](Read-Host 'Boş deneme kurulumunda 1; mevcut metin varsa daha yüksek yeni sürüm')
if ($ConsentVersion -le 0) { throw 'Sürüm pozitif tam sayı olmalı.' }
$ConsentText = 'Deneme medya politikası. Yalnız izinli deneme medyası kullanılır.'
docker compose @ComposeArgs exec -T backend .venv/bin/dojo-consent set-policy --version $ConsentVersion --text $ConsentText
if ($LASTEXITCODE -ne 0) { throw 'Rıza metni kaydedilemedi.' }
```

Aynı Compose proje adı uyarısı burada da geçerlidir. Tarayıcıda **Tekrar dene**'ye
basın veya sayfayı yenileyin. Yeni sürüm **otomatik kabul edilmemelidir**.
Sürüm değiştirmek önceki sürümün kabulünü yeni metne taşımaz; sıradan ayar geri
alma işlemi değildir. Mevcut gerçek politikayı değiştirmek yerine bu senaryoyu
boş test kurulumunda deneyin.

## 9. Etkinlik akışını ve küçük ekranı deneyin — tarayıcı

### 9.1. Son işlemler

1. Menüden **Etkinlik**'i açın; adres sonunda `#/activity` olmalıdır.
2. Yukarıdaki başarılı kayıtlara karşılık **Yayın planı güncellendi**, **Marka
   ayarları güncellendi** ve **Hatırlatma ayarları güncellendi** başlıklarını arayın.
3. Instagram/rıza işlemlerini yaptıysanız **Instagram bağlantısı doğrulandı** ve
   **Medya rızası kaydedildi** kayıtlarını da kontrol edin.
4. Tarayıcı işlemlerinde eşleştirmede verdiğiniz cihaz adı ve zaman görünmelidir;
   CLI/worker işlemleri sistem olarak gösterilebilir.
5. Etkinlik sekmesini açık bırakın; başka sekmede hatırlatmayı farklı geçerli
   değerle kaydedin. Etkinlik'e dönüp birkaç saniye bekleyin; yeni kayıt görünmelidir.
6. Varsa **İnceleme özeti** bağlantısını açabilirsiniz; sırf bu rehber için inceleme
   oluşturmayın veya yayın onayı vermeyin.

En yeni kayıtlar üsttedir; ekran **son 20 olayı** gösterir. Bu değişiklik bütün
geçmiş için sayfalama eklemez. Olay yoksa boş durum mesajı normaldir; her form
değişikliği değil, başarılı sunucu işlemleri kayıt üretir.

### 9.2. Dar ekran ve klavye

1. Tarayıcı penceresini daraltın veya F12 ile cihaz görünümünü yaklaşık **390 px** yapın.
2. Ayarlar bölümleri tek sütuna geçmeli; alanlar/düğmeler erişilebilir olmalı ve
   sayfada yatay kaydırma gerekmemelidir.
3. Tab ile hatırlatma alanlarını ve kaydet düğmesini gezin; düğmede Enter ile
   geçerli bir kaydı gönderin.
4. Başarı mesajı görünmeli; klavye odağı kaydedilen bölümün başlığına dönmelidir.

## 10. Backend/Instagram olmadan güvenli tarayıcı testleri — PowerShell

Bu testler projenin mevcut tarayıcı testlerini çalıştırır; yeni test kodu yazmanız
gerekmez. Gerekenler Node.js/npm ve Playwright Chromium'dur. Docker, worker,
veritabanı, gerçek token veya eşleştirme kodu gerekmez. Sahte API yalnız testin
açtığı tarayıcı bağlamındadır; aynı adrese normal tarayıcıdan giderek bu sahte
ortama bağlanamazsınız.

Repo kökünde PowerShell açın:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
npm --prefix web ci
if ($LASTEXITCODE -ne 0) { throw 'Web bağımlılıkları kurulamadı.' }
Push-Location web
try {
    npx playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Chromium kurulamadı.' }
} finally {
    Pop-Location
}
```

Test için **4331** boş olmalıdır. Playwright Vite'ı kendisi başlatır; aynı portta
manuel sunucu açmayın. Dört denemeyi (iki masaüstü, iki mobil) çalıştırın:

```powershell
$OldPlaywrightPort = $env:PLAYWRIGHT_PORT
$env:PLAYWRIGHT_PORT = '4331'
try {
    npm --prefix web run test:browser -- e2e/activity-settings.spec.ts --workers=1
    if ($LASTEXITCODE -ne 0) { throw 'Etkinlik/Ayarlar tarayıcı testleri başarısız.' }
} finally {
    $env:PLAYWRIGHT_PORT = $OldPlaywrightPort
}
```

**Beklenen: `4 passed`.** Testler plan/açıklama/hatırlatma kalıcılığını sahte API
üzerinde yenilemeyle, kaydetme odağını, rıza gösterimini, Etkinlik'i, dar ekranı,
sunucu hatasında taslağın korunmasını ve sahte OAuth yeniden bağlantısını denetler.

Adımları açılan gerçek Chromium penceresinde izlemek için aynı testin masaüstü
sürümünü çalıştırın; işlemleri test otomatik yapar:

```powershell
$OldPlaywrightPort = $env:PLAYWRIGHT_PORT
$env:PLAYWRIGHT_PORT = '4331'
try {
    npm --prefix web run test:browser -- e2e/activity-settings.spec.ts --project=desktop --headed --workers=1
    if ($LASTEXITCODE -ne 0) { throw 'Görünür tarayıcı testleri başarısız.' }
} finally {
    $env:PLAYWRIGHT_PORT = $OldPlaywrightPort
}
```

**Beklenen: `2 passed`.** Daha yavaş, adım adım izlemek isterseniz aynı komutta
`--headed` yerine `--debug` kullanın; Playwright Inspector üzerinden adımları
ilerletin. Bitirince Inspector/tarayıcıyı kapatın veya terminalde Ctrl+C kullanın.

Logo/kart kaydı, boş hesap, geçersiz değerler, bekleyen rıza, eski başarı mesajının
temizlenmesi ve başarılı kayıt sonrası kurulum yenileme hatası için ek kontroller:

```powershell
npm --prefix web test -- src/components/SettingsSummary.test.tsx
if ($LASTEXITCODE -ne 0) { throw 'Ayarlar bileşen kontrolleri başarısız.' }
npm --prefix web run build
if ($LASTEXITCODE -ne 0) { throw 'Typecheck veya web build başarısız.' }
```

`b49d097` sürümünde bileşen dosyasında **14 test** bulunur. Bileşen kontrolleri
tarayıcı penceresi açmaz; tarayıcıda güvenle üretilemeyen hata koşullarını sahte
HTTP yanıtlarıyla sınar. İlk uygulama doğrulamasında yalnız bu commit'in dosyalarını
içeren web testlerinde **282** test, backend testlerinde **167** test ve bu dosyadaki
**4** tarayıcı testi geçti.
Bunlar geçmiş doğrulama sayılarıdır; güncel sonuç terminalinizdeki çıktıdır.

Tam tarayıcı suite'inde daha önceden bulunan paket-video oynatma zaman aşımı
`web/e2e/package-management.spec.ts` içinde de görüldü ve #31 öncesi sürümde
tekrarlandı. Bu rehberin odaklı komutu o dosyayı çalıştırmaz.

## 11. Son kontrol ve deneme ayarlarını geri alın

- [ ] Plan, logo, açıklama ve kart kayıtları F5 sonrasında korunuyor.
- [ ] Hatırlatma aralığı/penceresi korunuyor; geçersiz değerler kaydedilmiyor.
- [ ] Başka sekmenin kaydı taslağı ezmiyor; sunucu değerleri isteyerek yüklenebiliyor.
- [ ] Eski başarı mesajı yeni düzenleme için gösterilmiyor.
- [ ] Instagram durumu ve rıza sürümü/kabul durumu görünür.
- [ ] Ayarlar'dan rıza kabulü yapılmıyor; kabul için kurulum açılıyor.
- [ ] Etkinlik'te son işlemler, yapan cihaz ve zaman görünür.
- [ ] Dar ekranda ve klavyeyle kullanım mümkün.

Gerçek deneme sunucusunda değişiklik yaptıysanız önce not aldığınız plan,
hatırlatma ve açıklama değerlerini aynı formlardan geri kaydedin. Önceki logo/kart
dosyalarını gerekiyorsa yeniden yükleyin. Deneme için düzenli yayın kapalıysa
bilinçli olarak açmadığınız sürece kapalı bırakın. Geçmiş Etkinlik kayıtları geri
alma ile silinmez; yeni kayıtlar eklenir.

Rıza sürümünü düşürerek veya token/şifreleme anahtarını gelişigüzel değiştirerek
geri alma yapmayın. Instagram hesabını yalnız yetkili olduğunuz önceki hesaba
yeniden bağlayabilirsiniz. Sahte API'li testte bu temizlik gerekmez; durum yalnız
test belleğinde tutulur. Manuel Vite terminalini Ctrl+C ile kapatabilirsiniz;
veritabanı veya medya dizinlerini silmeniz gerekmez.
