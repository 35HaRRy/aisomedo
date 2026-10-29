# Web medya yönetimi ve çoklu video bölümleri — Deneme rehberi (#29)

Bu rehber yapılan değişiklikleri özetler ve **önce tarayıcıda** denemenizi sağlar.
Arayüzde olmayan hazırlık/render işlemleri için yalnızca **PowerShell komutları**
verilir; Python veya SQL kodu yazmanız gerekmez. Komutların çalıştırdığı mevcut
CLI/test programları projenin kendi uygulamasıdır.

> **Yalnız ayrı deneme ortamında çalışın.** Medya yükleme, sıralama, seçim
> kaydetme ve ayar değişiklikleri sunucuda kalıcıdır. Gerçek dojo medyası veya
> üretim verisi kullanmayın. Instagram bağlamayın, yayın planını etkinleştirmeyin
> ve yayın onayı vermeyin. Bu rehber yayınlama, veritabanı silme veya arşivi
> zorla tamamlanmış gösterme komutu içermez.

## 1. Neler değişti?

| Değişiklik | Kullanıcıya etkisi |
| --- | --- |
| Güncel Paket medya listesi | Finalize olmuş fotoğraf/video ve montaj sırası görünür. |
| Paketten çıkar / Geri yükle | Original silinmeden medya montajdan çıkarılır; önceki bölümler ve konum korunur. |
| Sürükle / Yukarı / Aşağı | Montaj sırası sunucuya kaydedilir. |
| Çoklu retained bölüm | Bir videonun birkaç ayrı kısmı tutulur; aradaki kısımlar final render'a girmez. |
| Görsel timeline + hassas alanlar | Pointer/touch, klavye ve başlangıç/bitiş saniyeleriyle düzenleme yapılır. |
| Toplam süre ve sınır | Seçili video süresi, fotoğraflar ve etkin intro/outro kartları hesaba katılır. |
| Ortak bölüm taslağı | Birden fazla videonun taslağı birlikte kaydedilir; video değiştirmek taslağı silmez. |
| Gezinme kararı | Kaydedilmemiş bölümler için kaydet / at / vazgeç seçenekleri çıkar. |
| Eşzamanlılık koruması | Dış değişiklik ve belirsiz yazma sonucu görünür; bilinçsiz tekrar gönderim engellenir. |
| Tamamlanmış paketler | Salt okunur preview ve kimlik doğrulamalı original/processed/render indirmesi. |
| Render uyumu | Seçili bölümler kaynak zaman sırasıyla birleştirilir; originals değişmez. |

Son incelemede ayrıca dört hata düzeltildi: değişen render girdilerinin işi
`processing` durumunda bırakması, sayısal düzenlemeden sonra yanlış bölümün
kaldırılması, kendi işleminden sonraki yenilemenin dış değişikliği gizlemesi ve
belirsiz save sonrasında taslak atmanın yazma kilidini açması.

**Sınırlar:** Bu ekran final Reel render'ını başlatan veya yayın onayı veren bir
ekran değildir. Video editöründeki preview **kaynak/işlenmiş videodur**; seçili
bölümlerin kesintisiz final montaj preview'ı değildir. Bölüm kaydetmek yeni
dosya yüklemez ve otomatik render/yayın yapmaz.

## 2. Hazırlık ve güvenli ortam

Bu değişiklikleri içeren çalışan **ayrı test ortamınız** varsa bölüm 3'e geçin.
Yeni ortam için Docker Desktop (Linux containers), Node.js/npm ve PowerShell
gerekir. Yerel Python kurulumu aşağıdaki Compose/browser adımlarında gerekmez.

### 2.1. Doğru checkout ve portlar

Repo/worktree kökünde PowerShell açın; başka bilgisayarda yolu değiştirin:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo\.worktrees\issue-29-media'
git branch --show-current
docker info --format '{{.ServerVersion}}'
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 8000, 5434, 3100 } |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Dal bu çalışmada `feat/issue-29-media`; değişiklikler daha sonra başka dala
taşınmış olabilir. Eski checkout'tan backend/web çalıştırmayın. Burada web için
**3100** kullanılıyor; 3000'de başka uygulama bulunabilir. 8000/5434/3100 doluysa
başka projeyi kapatmak yerine ortamınızı ayırın veya zaten doğru test ortamının
çalıştığını doğrulayın. Vite API proxy'si yerel backend'in 8000 portunu kullanır.

**İlk kurulumda** host veri dizinlerinin boş olduğunu kontrol edin:

```powershell
foreach ($Path in 'ops/db-data', 'ops/media-data') {
    if ((Test-Path -LiteralPath $Path) -and
        (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1)) {
        throw "$Path dolu. Veriyi silmeyin; ayrı bir deneme checkout'u kullanın."
    }
}
```

Compose proje adını değiştirmek bu bind dizinlerini ayırmaz. Kendi test
ortamınızı yeniden açarken dizinlerin dolu olması normaldir; bu kontrol yalnız
ilk kurulum içindir.

### 2.2. Yerel ayarlar ve servisler

```powershell
if (-not (Test-Path -LiteralPath ops/.env)) {
    Copy-Item -LiteralPath ops/.env.example -Destination ops/.env
}
notepad ops/.env
```

Bu **test ortamına ait** dosyada:

- `POSTGRES_PASSWORD`: denemeye özel, boş olmayan parola.
- `COOKIE_SECURE=false`: yalnız bu yerel HTTP testinde; üretimde HTTPS/güvenli cookie korunur.
- `PUBLIC_BASE_URL=http://localhost:3100`
- `PUBLIC_HTTPS_ORIGIN=http://localhost:3100`
- `META_APP_ID` ve `META_APP_SECRET`: boş kalabilir; Instagram bağlantısı gerekmiyor.

Boş şifreleme anahtarı satırını mevcut anahtarı değiştirmeden doldurun:

```powershell
$EnvPath = (Resolve-Path -LiteralPath ops/.env).Path
$Content = [IO.File]::ReadAllText($EnvPath)
if ($Content -match '(?m)^META_TOKEN_ENCRYPTION_KEY=[ \t]*\r?$') {
    $Bytes = New-Object byte[] 32
    $Rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Rng.GetBytes($Bytes) } finally { $Rng.Dispose() }
    $Key = [Convert]::ToBase64String($Bytes).Replace('+', '-').Replace('/', '_')
    $Content = [regex]::Replace($Content, '(?m)^META_TOKEN_ENCRYPTION_KEY=[ \t]*\r?$', "META_TOKEN_ENCRYPTION_KEY=$Key")
    [IO.File]::WriteAllText($EnvPath, $Content, (New-Object Text.UTF8Encoding($false)))
    $Key = $null; $Bytes = $null; $Content = $null
}
```

Anahtarı, `.env`, pairing code veya cookie/token değerlerini paylaşmayın/Git'e eklemeyin.

```powershell
$ComposeArgs = @('--env-file', 'ops/.env', '-p', 'dojo-web-medya-deneme', '-f', 'ops/docker-compose.yml')
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose @ComposeArgs up -d --build db backend worker
docker compose @ComposeArgs ps
Invoke-RestMethod -Uri 'http://localhost:8000/health'
npm --prefix web ci
npm --prefix web run dev -- --host localhost --port 3100 --strictPort
```

Beklenen sağlık yanıtı `status: ok`. Vite terminali açık kalmalı.
Tarayıcı adresi **http://localhost:3100/#/package**; 8000 API portudur, web ekranı
değildir. `localhost` ve `127.0.0.1` arasında gidip gelmeyin: ayrı cookie/storage
kapsamlarıdır. Native komut hata verdiyse sonraki adıma geçmeden hatayı çözün.

Sonraki PowerShell komutları için aynı repo kökünde ikinci terminal açın ve
orada da `$ComposeArgs` satırını tekrar tanımlayın.

## 3. Eşleştirin ve test dosyalarını hazırlayın

İlk pairing code'u oluşturacak web düğmesi yoktur. İkinci terminalde:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
```

1. Tarayıcıda **Eşleştirme kodu** ve **Tarayıcı adı** alanlarını doldurun.
2. **Eşleştir** düğmesine basın.
3. Sihirbaz açılırsa ana gezinmeden **Güncel Paket**'e geçin. Bu deneme için
   Instagram bağlantısını veya kurulumun tümünü tamamlamanız gerekmez.
4. Yayın planını kapalı tutun; varsa **Ayarlar → Kurulumu aç** üzerinden kontrol edin.

Depoda gerçek kullanıcı içeriği olmayan, **30 saniyelik** sentetik MP4 vardır.
Yeni dosya adlarıyla iki kopyasını hazırlayın:

```powershell
$DemoDir = Join-Path $env:TEMP ('dojo-media-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $DemoDir | Out-Null
Copy-Item -LiteralPath web/e2e/fixtures/timeline.mp4 -Destination (Join-Path $DemoDir 'deneme-a.mp4')
Copy-Item -LiteralPath web/e2e/fixtures/timeline.mp4 -Destination (Join-Path $DemoDir 'Çalışma-B.MP4')
$DemoDir
```

Çıktıdaki dizini dosya seçicide açın. İsterseniz küçük bir test JPEG/PNG ekleyin.
Sentetik video tek renklidir; bölüm içerik farkını gözle izlemek için içinde
belirgin farklı sahneler olan kendi **kişisel veri içermeyen** test videonuzu
kullanabilirsiniz. Bu durumda sayısal süre beklentilerini kaynağa göre uyarlayın.

1. **Fotoğraf ve video seç** ile iki videoyu yükleyin.
2. **Pakete eklendi** sonucunu bekleyin. %100 veya **İşlem sırasına alındı** yeterli değildir.
3. **Aktif paket medyası** listesinde iki adı ve yaklaşık 30 saniyelik sürelerini görün.
4. Gerekirse **Paketi yenile**'ye basın. Worker 10 saniyelik aralıklarla kontrol eder;
   video işleme ve görünür tarayıcı yenilemesi daha uzun sürebilir.

İlk dosya farklı bir paket yaratabilir. Aynı adlı eski deneme dosyası varsa
çakışma akışına girmek yerine yeni ad kullanın; **üzerine yazma kalıcı silme**
işlemidir ve bu rehberin konusu değildir.

## 4. Tek videoda üç ayrı bölüm tutun — tarayıcı

1. `deneme-a.mp4` satırında **Bölümleri düzenle**'ye basın.
2. Native video kontrolleri, **Video zaman çizelgesi**, **Oynatma konumu** ve
   **Bölüm ekle** görünmeli. Başlangıçta: **Bölüm seçilmedi: videonun tamamı kullanılacak.**
3. Oynatma konumu 0 iken **Bölüm ekle**'ye basın; ilk bölüm yaklaşık `0–1` olur.
4. **1. bölüm başlangıcı (saniye)** = `0`, **bitişi** = `5` yapın.
5. Videoyu duraklatın. Video kontrolünü veya timeline'ın **boş alanına tıklamayı**
   kullanarak yaklaşık 10. saniyeye gidin; sürükleme yeni bölüm oluşturur.
   **Bölüm ekle**'ye basın; ikinci alanları `10` ve `15` yapın.
6. Yaklaşık 24. saniyeye gidip ekleyin; üçüncü alanları `24` ve `30` yapın.
7. **Yalnızca seçili bölümler kullanılacak.** ve **Kullanılacak süre: 16.00 s** beklenir.
8. **Bölümleri kaydet**'ye basın; **Bölümler kaydedildi.** görünmeli.
9. Sayfayı yenileyip editörü açın; aynı üç bölüm geri gelmeli.

Sayı alanlarında ondalık için şu anda **nokta** kullanın (`10.1` gibi).
Bölümler **tutulacak** içeriği belirtir; atılacak aralık değildir. Render sırası
`0–5`, ardından `10–15`, ardından `24–30` olur. Kaynak preview'ın native playback'i
bu boşlukları otomatik atlamaz; final render denemesi bölüm 12'dedir.

İki 30 saniyelik videodan yalnız A 16 saniyeye kısaldıysa toplam **46 saniye**;
bir varsayılan 3 saniyelik fotoğrafla **49 saniye** beklenir. Etkin kartlar veya
farklı fotoğraf süreleri varsa onları ayrıca ekleyin; ekrandaki limit esas alınır.

### Pointer, dokunma ve klavye

- Boş alanda sürükleme yeni bölüm yaratır; hassas alanlarla sonradan tam sınıra getirin.
- Bölüm kenarını sürüklemek başlangıç/bitişi değiştirir; komşu bölüme geçemez.
- Kenara Tab ile odaklanıp ok tuşuyla `0.1`, Shift+ok ile `1` saniye değiştirin.
- Home/End hareketini deneyin; testten sonra alanları yeniden yukarıdaki değerlere getirin.
- Telefonda/touch ekranda aynı boş-alan/kenar hareketini deneyin; medya sıra
  sürüklemesi yerine **Yukarı/Aşağı** alternatifini kullanabilirsiniz.

## 5. Geçersiz aralık ve tüm-videoya dönüş — tarayıcı

Önce mevcut geçerli bölümleri kaydedin.

1. Bir bitiş alanını boşaltın: uyarı görünmeli, **Bölümleri kaydet** kapalı olmalı.
   Başka videonun editörüne geçip geri gelin; boş giriş kaybolmamalı.
2. Geri `5` yazın; ardından ilk bölüm bitişini `12` yapın. `10–15` ile overlap
   olduğundan kaydetme yine kapalı olmalı. `5` ile düzeltin.
3. `start == end`, negatif başlangıç, 30'u aşan bitiş ve `0.01` saniyelik bölüm
   deneyin. Geçersiz değerler kayıt almamalı. Minimum bölüm **0.04 saniye**dir.
4. Her **Bölümü kaldır** düğmesini kullanıp son bölümü de kaldırın.
   **Videonun tamamı kullanılacak** durumuna dönmeli; bu videoyu tamamen atmak değildir.
5. Kaydederseniz A tekrar 30 saniye olur. Sonraki örnekler için bölüm 4'teki
   üç aralığı yeniden oluşturup kaydedin.

**Düzeltilen yanlış-kaldırma hatasını denemek için:** A'da yalnız `0–5` ve `10–15`
bırakın. Birinci satırın önce bitişini `25`, sonra başlangıcını `20` yapın.
Birinci satır şimdi `20–25`, ikinci satır `10–15` gösterir. **1. bölümü kaldır**
dediğinizde kalan satır `10–15` olmalıdır; yanlışlıkla `20–25` kalmamalıdır.
Kaydetmeyi deneyip sonucu yeniden açarak kontrol edin. Sonra A'nın üç bölümünü geri kurun.

## 6. Süre limitini deneyin — tarayıcı

A 16 ve B 30 saniyeyken iki yeni adla 30 saniyelik video daha hazırlayın:

```powershell
Copy-Item -LiteralPath web/e2e/fixtures/timeline.mp4 -Destination (Join-Path $DemoDir 'deneme-c.mp4')
Copy-Item -LiteralPath web/e2e/fixtures/timeline.mp4 -Destination (Join-Path $DemoDir 'deneme-d.mp4')
```

1. C ve D'yi dosya seçiciyle yükleyip finalize olmalarını bekleyin.
2. Kart/fotoğraf yoksa toplam `16 + 30 + 30 + 30 = 106` saniyedir.
   Varsayılan limit 90 ise aşım `16` saniyedir; kendi ekranınızdaki limite göre uyarlayın.
3. A'da küçük bir bölüm değişikliği yapın. Limit hâlâ aşılıyorsa kayıt düğmesi
   kapalı olmalı, **Sınırı aşan süreyi azaltın** bilgisi görünmelidir.
4. **Taslakları at** ile bu küçük değişikliği atın; D'yi **Paketten çıkar** ile
   montajdan çıkarın. Toplam tekrar limit içine düşmelidir.
5. C'yi de çıkararak ilk A/B senaryosuna dönün. Originals silinmez.

Yükleme/restoration paketi limit üstüne çıkarabilir; sunucu render/save için
uygunluğu ayrıca denetler. Sonuç hiçbir zaman sessiz kısaltılmış bir montaj olmamalı.
**Süre hesaplanamıyor** ise limit aşımıyla aynı durum değildir; kaynak süresi
bilinmeyen medyayı bu rehber için elle manifest değiştirerek üretmeyin.

## 7. Sıra, çıkarma ve geri yükleme — tarayıcı

1. A/B satırlarında **Yukarı/Aşağı** veya **Sürükle** ile sırayı değiştirin.
2. İşlem tamamlanınca F5 yapın; sıra aynı kalmalıdır. Sıra işlemi ayrı kaydedilir;
   ayrıca **Bölümleri kaydet** gerektirmez.
3. A'nın üç bölümünün kayıtlı olduğundan emin olun; **Paketten çıkar**'ya basın.
4. A **Paketten çıkarılmış medya** altında görünmeli; toplam süre azalmalıdır.
5. B'de `0–6` bölümü oluşturup **Bölümleri kaydet**'ye basın.
6. A için **Geri yükle**'ye basın. Önceki konumu ve `0–5 / 10–15 / 24–30`
   seçimi korunmalı; B `0–6` kalmalıdır.

Dirty bir videoyu çıkarırken karar penceresi gelir. **Vazgeç** çıkarmaz;
**Değişiklikleri at** yalnız o videonun taslağını atıp çıkarır, diğer videonun
taslağını korur; **Kaydet ve devam et** geçerli aggregate taslağı kaydeder.
Mevcut render varsa düzenleme sonrası **Render güncel değil** uyarısını izleyin.

## 8. Taslaklar ve gezinme — tarayıcı

1. A'da kayıtlı bir sınırı değiştirin; kaydetmeyin.
2. B'nin editörünü açıp bir sınır değiştirin; A'ya dönün. İki taslak da kalmalı;
   aynı anda yalnız bir video editörü açık olmalıdır.
3. **Ayarlar** veya **Tamamlanmış paketler**'e gitmek isteyin.
4. **Vazgeç** seçin: bulunduğunuz ekran ve taslaklar kalmalıdır.
5. Tekrar gezinip **Kaydet ve devam et** seçin: geçerliyse tüm video taslakları
   birlikte kaydedilip hedef ekran açılmalıdır.
6. Yeni değişiklik yapıp gezinmede **Değişiklikleri at** seçin: değişiklik kaydedilmemelidir.

Geçersiz taslakta **Kaydet ve devam et** kapalıdır. Sayfa kapatma/F5 browser'ın
kendi kaydedilmemiş-değişiklik uyarısını gösterebilir. **F5'ten sonra kaydedilmemiş
bölüm taslaklarının kurtarılması vaat edilmiyor**; bu koruma oturum içi gezinme ve
arka plan yenilemesidir. F5 ile yalnız kayıtlı durumu doğrulayın.

## 9. Başka sekme ve bağlantı kesintisi — tarayıcı

### 9.1. Başka sekmenin değişikliği

1. Aynı paired tarayıcıda aynı `#/package` adresini ikinci sekmede açın.
2. Birinci sekmede A'nın sınırını değiştirin, kaydetmeyin.
3. İkinci sekmede B'ye geçerli bir seçim kaydedin.
4. Birinciye dönüp görünür yenilemenin gelmesini bekleyin.
5. **Paket dışarıdan değişti. Taslaklar korunuyor...** uyarısı beklenir;
   A'nın yerel metni kaybolmamalı, yazma işlemleri kilitlenmelidir.
6. **Paketi yenile** ile sunucuyu bilinçli yeniden okuyun. Yerel taslağı gözden
   geçirip kaydedin veya **Taslakları at** ile sunucudaki seçimlere dönün.

Unrelated yenileme tek başına taslağı silmemelidir. Düzeltilen own-write yarışını
elle tam zamanlamak zor olabilir; bölüm 13'te hook regresyon komutu vardır.

### 9.2. Offline ve belirsiz save

1. Geçerli, kaydedilmemiş bir taslak bırakın; DevTools **Network → Offline** açın.
2. Offline algılandığında uyarı ve kapalı yazma düğmelerini kontrol edin;
   gerekirse sekmeden çıkıp geri dönün. Taslak metni kaybolmamalıdır.
3. Network'ü normale alın; **Paketi yenile** ile durumu okuyup taslağı kontrol edin.

Bu offline denemesi **sunucu kaydetti ama yanıt kayboldu** yarışını deterministik
üretmez. Böyle bir durumda **İşlemin sonucu doğrulanamadı** görünür. Tekrar save
göndermeyin. **Taslakları at** bile yazmayı açmamalı; başarılı açık yenileme gerekir.
Bu dört adımlı durum otomatik hook testinde özellikle doğrulanır.

## 10. Tamamlanmış paketler ve özel indirme — tarayıcı

1. Dirty draft varsa önce karar verin; **Tamamlanmış paketler**'e basın.
2. Gerçek test ortamında arşiv varsa **Tamamlanmış paket seç** ile birini seçin.
3. Available preview, caption ve **Orijinali indir / İşlenmiş dosyayı indir /
   Son Reel'i indir** bağlantılarını deneyin. `dosya mevcut değil` için indirme beklemeyin.
4. Bölüm kaydetme, çıkarma/geri yükleme ve dosya yükleme kontrolleri burada olmamalı.
5. **Aktif pakete dön**'e basın; aktif montaj arşivin içine taşınmamış olmalıdır.

İndirilen original'ın hash'ini elinizdeki yüklediğiniz aynı kaynakla karşılaştırabilirsiniz:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\test\kaynak.MP4'
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Users\kullanici\Downloads\indirilen.MP4'
```

Yolları değiştirin; original karşılaştırmasında hash eşit olmalıdır. Processed
dosya/render'ın kaynakla aynı bytes olması beklenmez.

**Arşiv yoksa:** **Henüz tamamlanmış paket yok.** doğru sonuçtur. Arşiv yalnız
doğrulanmış publication yaşam döngüsüyle oluşur; bunu test için SQL/manifest
değiştirerek veya gerçek Instagram paylaşımıyla zorlamayın. Bölüm 13'teki
mock API'li browser testi arşiv ekranını ayrı sentetik senaryoda açar; sizin
veritabanınıza arşiv eklemez.

**Yetkisiz erişim denemesi:** DevTools Network'ten test ortamındaki bir preview
veya download URL'sini alın; cookie/token içermeden yeni gizli pencerede açın.
Gizli pencereyi eşleştirmeyin. Yetkisiz response beklenir; dosya açılmamalıdır.
Eşleştirilmiş normal pencerenin çalışmaya devam ettiğini kontrol edin.

## 11. Arşive giderken yükleme kuyruğu korunur mu? — tarayıcı

Aktarımı fark edilecek kadar büyük, kişisel veri içermeyen farklı adlı bir MP4 kullanın.

1. DevTools Network'te yavaş profil seçip yüklemeyi başlatın.
2. **Yükleniyor** sırasında **Duraklat**'a basın; **Duraklatıldı** sonucunu bekleyin.
3. **Tamamlanmış paketler**'e geçip **Aktif pakete dön**'e dönün.
4. Aynı satır ve **Devam et** kalmalıdır; dosyayı yeniden seçmeniz gerekmemelidir.
5. Network hızını normale alıp devam edin. Upload aktif pakete finalize olmalı,
   görüntülediğiniz completed pakete eklenmemelidir.

Bu deneyde F5 yapmayın: F5 sonrası aynı original dosyayı yeniden seçmek mevcut
upload kurtarma davranışıdır, yeni galerinin yaptığı bir kayıp değildir.

## 12. Final render'ı görmek — yalnız PowerShell ile tetikleme

Web'de render başlatma düğmesi yok. Paired kullanıcı arayüzünde bölümleri
kaydedip montajı limit içine getirdikten sonra mevcut `dojo-render` CLI'ını kullanın.
Bu **render** denemesidir; yayın onayı veya Instagram paylaşımı değildir.

### 12.1. PowerShell'e ayrı test kimliği alın

Tarayıcının HttpOnly cookie'sini kopyalamayın. İkinci terminalde yeni tek kullanımlık code üretin:

```powershell
docker compose @ComposeArgs exec backend .venv/bin/dojo-create-pairing-code create-code
$Base = 'http://localhost:8000'
$Code = Read-Host 'Yeni Pairing code'
$PairBody = @{ code = $Code; kind = 'device'; name = 'PS Medya Denemesi' } | ConvertTo-Json
$Pair = Invoke-RestMethod -Method Post -Uri "$Base/api/pairing/validate" -ContentType 'application/json' -Body $PairBody
$Headers = @{ Authorization = "Bearer $($Pair.token)" }
$Code = $null; $PairBody = $null
Invoke-RestMethod -Uri "$Base/api/pairing/me" -Headers $Headers | Select-Object id, name, kind
```

Code tek kullanımlıdır; tarayıcıda kullandığınız code tekrar çalışmaz.
`$Pair`/`$Headers` değerlerini ekrana yazdırmayın veya dosyaya kaydetmeyin.

### 12.2. Logo kontrolü

Render için aktif paketin logosu gerekir. Daha önce logo ayarladıysanız:

```powershell
Invoke-RestMethod -Uri "$Base/api/packages/active/branding" -Headers $Headers
```

`logo_asset` boşsa yalnız test PNG/JPEG'ini upload edin ve **aktif paketin**
draft branding'ine ekleyin. Onboarding'de varsayılan logo değişikliği mevcut
paketin snapshot'ını otomatik değiştirmeyebilir; aşağıdaki işlem açıkça aktif paketi hedefler.

```powershell
$LogoPath = Read-Host 'Test logo PNG veya JPEG dosyasının tam yolu'
$Asset = Invoke-RestMethod -Method Post -Uri "$Base/api/settings/branding/assets" -Headers $Headers -ContentType 'application/octet-stream' -InFile $LogoPath
$Branding = Invoke-RestMethod -Uri "$Base/api/packages/active/branding" -Headers $Headers
$Branding | Add-Member -MemberType NoteProperty -Name logo_asset -Value $Asset.asset -Force
Invoke-RestMethod -Method Put -Uri "$Base/api/packages/active/branding" -Headers $Headers -ContentType 'application/json' -Body (@{ branding = $Branding } | ConvertTo-Json -Depth 10)
```

Diğer branding alanları korunur. Logo 10 MiB ve 4096 pixel/kenar sınırlarını
geçmeyen tek-frame PNG/JPEG olmalıdır. Bu işlem render'ı stale yapabilir.

### 12.3. Kuyruğa al ve dosyayı aç

Önce bütün tarayıcı taslaklarını kaydedin; CLI yalnız **sunucuda kayıtlı** seçimleri render eder.

```powershell
$Editor = Invoke-RestMethod -Uri "$Base/api/packages/active/editor" -Headers $Headers
$Editor.montage | Select-Object combined_duration, max_duration_seconds, duration_complete, over_limit
docker compose @ComposeArgs exec backend .venv/bin/dojo-render render-preview
docker compose @ComposeArgs logs --tail 60 worker
```

`stale: True` işi kuyruğa alma sonucudur; tamamlanma sonucu değildir. Worker
işlesin; render hata verirse aynı komutu sürekli yinelemeyin, log ve girdileri kontrol edin.

```powershell
$Editor = Invoke-RestMethod -Uri "$Base/api/packages/active/editor" -Headers $Headers
$Editor.render_stale
$ReelPath = Join-Path (Join-Path 'ops/media-data' $Editor.package.folder_name) 'render/reel.mp4'
Test-Path -LiteralPath $ReelPath
if ((-not $Editor.render_stale) -and (Test-Path -LiteralPath $ReelPath)) {
    Start-Process -FilePath (Resolve-Path -LiteralPath $ReelPath).Path
}
```

`render_stale` false ve dosya mevcut olmalı. Dosya host test media bind'ından
açılır; bu active render'ın web'de public download endpoint'i olduğu anlamına gelmez.
Önceki render dosyası hâlâ mevcut olsa bile stale true iken onu güncel sonuç saymayın.

Beklenen: kaynak zaman sıralı seçili bölümler, logo ve mevcut kartlar; toplam
süre kayıtlı montajla yaklaşık uyuşur. AAC/video frame sınırları küçük tolerans
yaratabilir. Tek-renk fixture'da kesilen sahneler gözle ayırt edilmez; süreyle
kontrol edin veya farklı sahneli test videosu kullanın.

## 13. Elle zor üretilecek regresyonlar — PowerShell test komutları

Bu bölüm yeni veri yazdırmadan mevcut testleri çalıştırır. Test altyapısı
gerektirir; Python **kodu** veya SQL çalıştırma metni içermez.

### 13.1. Gerçek masaüstü ve dokunmatik browser testi

Tarayıcıyı açarak testleri izleyebilirsiniz. Testler `/api/` yanıtlarını mock
eder; gerçek servis/deployment uçtan uca kanıtı değildir.

```powershell
npm --prefix web ci
Push-Location web
try {
    npx playwright install chromium
    $env:PLAYWRIGHT_PORT = '3100'
    npm run test:browser -- --headed --workers=1
} finally {
    Pop-Location
}
```

Playwright `http://127.0.0.1:3100` kullanır. Elle açtığınız `--host localhost`
Vite bu adresten erişilemiyorsa o Vite terminalinde Ctrl+C yapın; Playwright
kendi sunucusunu başlatsın. Portta başka projeyi çalışır bırakmayın.
Sunucu erişilebiliyorsa **bu checkout'un uygulaması olduğundan emin olun**;
`reuseExistingServer` açık olduğu için yanlış uygulamayı yeniden kullanmayın.
Testlerin API mock'u gerçek medyanızı değiştirmez. Browser kapanınca başarı
satırlarını kontrol edin; bu snapshot'ta 4 browser senaryosu geçmiştir.

Yalnız archive akışını tek desktop browser'da adım adım görmek için:

```powershell
$env:PLAYWRIGHT_PORT = '3100'
npm --prefix web run test:browser -- --project=desktop --grep 'media order' --debug
```

Playwright Inspector üzerinden adımları ilerletin. Sentetik completed paket,
Unicode attachment adı, unavailable render ve read-only kontrollerini görürsünüz.
Bu pencerenin gerçek test ortamındaki completed listesi olmadığını unutmayın.

### 13.2. Belirsiz yanıt / own-write / yanlış bölüm regresyonları

```powershell
npm --prefix web test -- src/packages/usePackageEditor.test.tsx src/packages/ActivePackagePanel.test.tsx src/packages/PackageEditorProvider.test.tsx
```

Beklenen: yanıtı kaybolan committed save, discard sonrası refresh kilidi,
reorder/remove/restore arkasındaki dış seçim değişikliği, numeric satır kaldırma
ve navigation kararları geçer. Gerçek deployment network kesintisi simülasyonu değildir.

### 13.3. Queued render uygunluğu ve gerçek FFmpeg

Host'ta `uv` ve projenin Python çalışma ortamı gerekir; komutlar yalnız mevcut test CLI'ını çağırır.

```powershell
uv sync --all-packages
uv run --project dojo-core pytest dojo-core/tests/test_render.py dojo-core/tests/test_render_selections.py -v
```

Docker açık olmalı. Changed-input testleri limit, eksik duration veya invalid
range nedeniyle render job'ın durable `failed` olmasını ve scheduler'ın
uygunsuz paketi tekrar kuyruğa koymamasını doğrular. FFmpeg transport testleri
sentetik kaynaklarla gerçek renderer'ı çalıştırır. `SKIPPED`, çalışmış/geçmiş
anlamına gelmez; Docker/native FFmpeg/platform atlamalarını ayrı okuyun.

## 14. Sorun giderme ve bilinen sınırlar

| Belirti | Kontrol |
| --- | --- |
| Yeni medya ekranı yok | Backend ve web aynı güncel checkout'tan mı başlatıldı? |
| Pairing sonrası yine giriş ekranı | localhost tutarlı mı; yalnız test HTTP için COOKIE_SECURE=false mı? |
| Upload kuyruğa alındı ama listede yok | Worker açık mı, medya doğrulaması başarıyla finalize oldu mu? |
| Kaydet kapalı | Dirty değişiklik var mı; invalid alan, limit, offline veya stale kilidi var mı? |
| Preview hata verdi | İşlenmiş artifact mevcut mu; **Önizlemeyi yeniden yükle** çalışıyor mu? |
| Render logo/süre hatası | Active draft logo, bilinen source duration ve toplam limit kontrol edildi mi? |
| History boş | Gerçek completed paket yoksa beklenen durum; SQL ile sahte arşiv üretmeyin. |
| Eski raw download linki açılmıyor | Ham medya artık paired erişim gerektirir; public raw URL beklemeyin. |

**Ertelenen küçük hata:** Milisaniyeye tam oturmayan duration/neighbor sınırında
timeline yuvarlaması invalid draft üretebilir. Server kaydetmeyi reddeder.
Hassas alanı legal source sınırına düzeltin; güvenlik validation'ını kaldırmayın.

11 kararın ve bu küçük bulgunun ayrıntılı takip kaydı:
[issue #29 takip notları](../verification/issue-29-follow-up-notes.md).
Tam doğrulama kaydı: [issue #29 verification](../verification/issue-29-web-media-management.md).
Mevcut Python lint/typecheck ve dependency audit bulguları ayrıca raporlanmıştır;
bu rehber bütün repository CI kontrollerinin temiz olduğunu iddia etmez.

## 15. Kısa kabul listesi

- [ ] A'nın üç seçimi reload sonrası `0–5 / 10–15 / 24–30` ve retained toplamı 16 saniye.
- [ ] Invalid/overlap/sub-frame giriş kaydedilmiyor; raw text video değiştirince korunuyor.
- [ ] Sayısal satır taşıdıktan sonra kaldırma, ekranda seçtiğim bölümü kaldırıyor.
- [ ] Sıra kalıcı; remove original'ı silmiyor; restore seçim ve konumu koruyor.
- [ ] Gezinti vazgeç/kaydet/at kararlarına uyuyor; birden çok draft tek save ile gidiyor.
- [ ] Dış değişiklik stale uyarısı veriyor; belirsiz yanıt açık refresh gerektiriyor.
- [ ] Archive salt okunur; available paired indirmeler çalışıyor; gizli pencere erişemiyor.
- [ ] Archive gezintisi pause edilmiş upload File/satırını kaybettirmiyor.
- [ ] CLI render sunucudaki seçimleri kullanıyor; stale dosya güncel diye sunulmuyor.
- [ ] Deneme gerçek Instagram paylaşımı, SQL müdahalesi veya veri silme gerektirmedi.
