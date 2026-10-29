# Web kurulum sihirbazı — Değişiklik özeti ve deneme rehberi (#26)

Bu rehber, yapılan değişiklikleri tarayıcıda adım adım denemeniz içindir.
Tarayıcıda yönetim ekranı bulunmayan işlemler için PowerShell komutları verilir.
Komutlarda Python veya SQL kodu bulunmaz; mevcut uygulama komutları ve HTTP
istekleri kullanılır.

> **Deneme ortamı kullanın.** Plan, Instagram bağlantısı, logo, açıklama ve rıza
> değişiklikleri kalıcıdır ve aynı kurulumu kullanan bütün cihazları etkiler.
> Gerçek dojo kurulumunda sırf denemek için rıza sürümü oluşturmayın veya bağlantı
> değiştirmeyin. Bu rehber yayın onayı vermeyi ya da Instagram'a gönderi paylaşmayı
> gerektirmez. Veritabanı ve medya dosyaları silinmez.

## 1. Neler değişti?

| Değişiklik | Tarayıcıda göreceğiniz sonuç |
| --- | --- |
| Yedi adımlı kurulum | Eşleştirme, Instagram, yayın planı, rıza, logo, açıklama ve isteğe bağlı kartlar |
| Kaldığı yerden devam | Eksik kurulum ilk açılışta görünür; kaydedilen adımlar yenilemede korunur |
| Ayarlar içinden yeniden açma | **Ayarlar → Kurulumu aç** bağlantısı |
| Manuel Instagram tokenı | Kendi aldığınız tokenı maskeli alana girip bağlantıyı doğrulayabilirsiniz |
| OAuth hesap seçimi | Yetkilendirme yeni pencerede açılır; dönen hesaplardan birini siz seçersiniz |
| Sürüme bağlı rıza | Okuduğunuz sürüm kabul edilir; değişen metin otomatik kabul edilmez |
| Ortak kurulum durumu | Bir cihazın kaydı diğer eşleştirilmiş cihazlarda görünür |
| Form içinden yapılandırma | Plan, logo, açıklama ve kartları sihirbazda kaydedebilirsiniz |
| Bağımsız görsel yükleme | Logo/kart yüklemek için aktif medya paketi gerekmez |
| Kısmi ayar kaydı | Bir alanı kaydetmek diğer alanları veya mevcut paket görüntülerini değiştirmez |
| Taslak koruması | Başka cihazın değişikliği yazmakta olduğunuz formu ezmez; açıkça yeniden yükleyebilirsiniz |
| Hazırlık kontrolü | Zorunlu adımlar backend tarafından doğrulanır; kartlar hazır olmayı engellemez |

**İki ayrı kavram:** Planın tanımlanmış olması ile düzenli yayının etkin olması
aynı şey değildir. Geçerli bir Pazartesi tarihi ve saat, plan kapalı olsa bile
kurulum adımını tamamlar. Düzenli zamanlama ayrıca etkin plan ve hazır kurulum
gerektirir. Kurulumu bitirmek tek başına yayın onayı değildir.

## 2. Hazırlık ve güvenli başlatma

### 2.1. Doğru çalışma dizinini açın

Bu değişiklikler `feat/issue-26-onboarding` dalındadır. PowerShell'i değişikliklerin
bulunduğu repo/worktree kökünde açın. Bu oturumda kullanılan dizin:

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo\.worktrees\issue-26-onboarding'
git branch --show-current
$env:COMPOSE_PROJECT_NAME = 'dojo-onboarding-deneme'
```

Başka bilgisayarda ilk satırı kendi repo dizininizle değiştirin. Eski checkout'ta
çalıştırırsanız yeni sihirbaz yerine eski ekranı görebilirsiniz.
Compose proje adı burada özellikle denemeye ayrılır. Bu ad konteynerleri ayırır,
ancak mevcut `ops/db-data` içeriğini veya dolu host portlarını ayırmaz. Gerçekten
boş deneme dizinleri kullanın; dolu port için çalışan gerçek ortamı durdurmayın.

Gerekenler: Docker Desktop'ın Linux konteyner motoru açık olmalı; Node.js/npm
kurulu olmalı. Aşağıdaki Docker yolu için bilgisayarda Python kurulması gerekmez.
`8000`, `5434` ve web portu başka uygulama tarafından kullanılmamalıdır.

### 2.2. Yerel yapılandırmayı hazırlayın

```powershell
docker info --format '{{.ServerVersion}}'
if (-not (Test-Path -LiteralPath ops/.env)) {
    Copy-Item -LiteralPath ops/.env.example -Destination ops/.env
}
notepad ops/.env
```

Not Defteri'nde şu alanları kontrol edip kaydedin:

- `POSTGRES_PASSWORD`: boş bırakmayın. Yerel deneme için harf/rakam içeren farklı
  bir parola seçin. Daha önce kullanılan veritabanının parolasını gelişigüzel değiştirmeyin.
- `COOKIE_SECURE=false`: yalnızca bu yerel HTTP denemesi için; üretimde HTTPS ve
  `true` kullanılmalıdır.
- `PUBLIC_BASE_URL=http://localhost:3000` ve
  `PUBLIC_HTTPS_ORIGIN=http://localhost:3000`: yalnızca yerel kurulum için.
- `META_TOKEN_ENCRYPTION_KEY`: boşsa aşağıdaki komutla oluşturun. Mevcut, çalışan
  kurulumun anahtarını değiştirmeyin; önceki tokenların okunmasını bozabilirsiniz.

Boş şifreleme anahtarını Python kullanmadan oluşturmak için:

```powershell
$EnvPath = (Resolve-Path -LiteralPath ops/.env).Path
$Content = [System.IO.File]::ReadAllText($EnvPath)
if ($Content -match '(?m)^META_TOKEN_ENCRYPTION_KEY=[ \t]*\r?$') {
    $Bytes = New-Object byte[] 32
    $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Rng.GetBytes($Bytes) } finally { $Rng.Dispose() }
    $Key = [Convert]::ToBase64String($Bytes).Replace('+', '-').Replace('/', '_')
    $Content = [regex]::Replace($Content, '(?m)^META_TOKEN_ENCRYPTION_KEY=[ \t]*\r?$', "META_TOKEN_ENCRYPTION_KEY=$Key")
    [System.IO.File]::WriteAllText($EnvPath, $Content, (New-Object System.Text.UTF8Encoding($false)))
    $Key = $null
    $Content = $null
    $Bytes = $null
    Write-Host 'Boş şifreleme anahtarı oluşturuldu; ekrana yazdırılmadı.'
} else {
    Write-Host 'Boş anahtar satırı bulunmadı. Mevcut değer değiştirilmedi.'
}
```

Bu anahtar yerel `.env` dosyasında kalır; paylaşmayın veya Git'e eklemeyin.
Backend ve worker kullanıldığında aynı anahtarı kullanmalıdır.

### 2.3. Veritabanı ve backend'i başlatın

Sihirbazı denemek için worker gerekmez. Aşağıda özellikle worker başlatılmıyor;
Kontrol Paneli'nde worker'ın çalışmıyor görünmesi bu denemede normaldir.

```powershell
New-Item -ItemType Directory -Force -Path ops/db-data, ops/media-data | Out-Null
docker compose --env-file ops/.env -f ops/docker-compose.yml up -d --build db backend
docker compose --env-file ops/.env -f ops/docker-compose.yml ps
Invoke-RestMethod -Uri 'http://localhost:8000/health'
```

Beklenen: backend ve db çalışır; sağlık yanıtında `status` değeri `ok` olur.
Bu komutlar mevcut `ops/db-data` ve `ops/media-data` içeriklerini kullanır.
Aynı kurulumda zaten çalışan worker varsa yeni bir çalışma dizinine geçmek onu
durdurmaz; gerçekten ayrı deneme ortamı kullandığınızdan emin olun.

### 2.4. Web arayüzünü başlatın

```powershell
npm --prefix web ci
npm --prefix web run dev
```

Terminali açık bırakın. Tarayıcıda Vite'ın yazdığı adresi açın; varsayılan
**http://localhost:3000**. Port doluysa terminaldeki adresi kullanın.
`http://localhost:8000` backend adresidir, web sayfası değildir.

Sonraki komutlar için **aynı repo kökünde ikinci bir PowerShell penceresi** açın.
Bu yeni pencerede de aynı proje adını ayarlayın; aksi halde Docker komutları başka
kurulumu hedefleyebilir:

```powershell
$env:COMPOSE_PROJECT_NAME = 'dojo-onboarding-deneme'
```

## 3. Tarayıcıyı eşleştirin

İlk eşleştirme kodunu üreten bir web ekranı yoktur. PowerShell'de:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-create-pairing-code create-code
```

1. Çıktıdaki **Pairing code** değerini tarayıcıdaki **Eşleştirme kodu** alanına yazın.
2. **Tarayıcı adı** olarak `Rehber Tarayıcısı 1` yazın.
3. **Eşleştir** düğmesine basın.

Beklenen: eksik kurulum varsa `#/onboarding` açılır. Yedi adım ve
tamamlandı/bekliyor/isteğe bağlı durumları görünür. Eşleştirme zaten tamamlanmıştır;
ilk eksik zorunlu adım seçilir. Kurulum önceden tamamlanmışsa Kontrol Paneli
açılması normaldir; **Ayarlar → Kurulumu aç** ile sihirbazı açın.

Kod tek kullanımlık ve süre sınırlıdır. Yeni tarayıcı/gizli pencere için yeni kod
üretin. Oturum çerezini veya kodu başkalarıyla paylaşmayın.

## 4. Instagram erişim tokenını tarayıcıdan tanımlayın

Üstteki adımlardan **Instagram bağlantısı** düğmesini seçin.

### 4.1. Önce hatalı giriş davranışını deneyin

1. **Instagram erişim tokenı** alanına gerçek sır olmayan `deneme-gecersiz-token` yazın.
2. Alanın maskeli olduğunu kontrol edin.
3. **Token ile bağlan** düğmesine basın.

Beklenen: alan gönderimden sonra temizlenir. Sunucu ve Instagram erişimi uygunsa
geçersiz token/izin uyarısı görünür. Sunucu yapılandırılmamışsa veya sağlayıcıya
ulaşılamıyorsa bunun yerine ilgili yapılandırma/servis hatası görünür; bu da
geçersiz girişin başarılı bağlantı sayılmadığını gösterir. Önceden bağlı hesabınız
varsa başarısız doğrulama onu değiştirmemelidir.

### 4.2. Kendi aldığınız geçerli tokenı deneyin

1. Instagram Login akışı için alınmış, uygun izinlere sahip Business/Creator
   hesabınızın tokenını aynı alana girin. Token edinme ön koşulları için
   [Instagram token bağlantısı rehberine](instagram-token-baglantisi-rehberi.md) bakın.
2. **Token ile bağlan** düğmesine basın.
3. İşlem sürerken ikinci kez gönderemediğinizi ve alanın temizlendiğini kontrol edin.
4. İşlem başarılıysa Instagram adımı tamamlanır ve sıradaki eksik adıma geçilir.
5. Hesap adını görmek için yeniden **Instagram bağlantısı** adımını seçin.

Beklenen: doğrulanan `@kullanıcı_adı` görünür. Token arayüzde tekrar gösterilmez;
uygulama tarafından localStorage/sessionStorage'a veya sayfa URL'sine kaydedilmez.

> Tokenı PowerShell komutuna, URL'ye, ekran görüntüsüne veya sohbet mesajına
> yapıştırmayın. Geliştirici araçlarının Network bölümünde istek gövdesini görmek
> mümkündür; gerçek token kullanılan HAR kayıtlarını dışa aktarmayın/paylaşmayın.

Geçerli tokenınız yoksa bu adımı başarıyla tamamlamış saymayın. Diğer formları
üstteki adım düğmeleriyle ayrı ayrı deneyebilirsiniz; genel hazır durumu eksik kalır.

### 4.3. OAuth seçeneğinin sınırı

**Instagram ile yetkilendir** yeni pencere açar. Pencere engellenirse
**Yetkilendirme sayfasını aç** bağlantısı kullanılabilir. Yetkilendirme sonucunda
aday hesaplar geldiğinde **@… hesabını seç** düğmesiyle açıkça seçim yapılır;
yeni seçim doğrulanana kadar mevcut bağlantı korunur.

Ancak mevcut backend kurucusu OAuth tarafında `StubMetaOAuthProvider` kullanıyor.
Yerel örnek yapılandırmayı gerçek Meta OAuth entegrasyonu gibi değerlendirmeyin;
bu değişiklik tam bir canlı OAuth sağlayıcısı eklemiyor. OAuth ekranı/hesap seçimi
otomatik fixture testleriyle doğrulandı. Gerçek bağlantıyı denemek için bu rehberdeki
manuel token yolunu kullanın.

## 5. Yayın planını yapılandırın — yayın kapalı kalsın

**Dojo Yayın Planı** adımını seçin.

1. **İlk yayın tarihi** için Pazartesi olan `2026-10-05` seçin.
2. **Yayın saati** için `10:00` seçin.
3. **Düzenli yayını etkinleştir** kutusunu **işaretlemeyin**.
4. **Planı kaydet** düğmesine basın.

Beklenen: tarih/saat kaydedilir; plan adımı tamamlanır. Saat dilimi
`Europe/Istanbul`, düzen iki haftada bir Pazartesi'dir. Plan kapalı kalır.
Örnek tarih geçmişte olsa bile yapılandırma denemesi için geçerlidir; bu rehberde
planı etkinleştirmeyin.

Negatif kontrol: aynı adımda `2026-10-06` (Salı) seçip kaydetmeyi deneyin.
Pazartesi gerektiğini söyleyen hata beklenir. Başarılı eski kayıt korunur.
Alanı tekrar Pazartesi yapıp kaydedin.

Diğer adımlar eksikse kayıttan sonra sihirbaz o eksik adıma dönebilir; üstteki
adım düğmeleriyle istediğiniz forma geri dönmeniz mümkündür.

## 6. Rıza metnini oluşturun ve tarayıcıda kabul edin

### 6.1. Yönetici metni oluşturur — PowerShell

**Medya rızası** ekranı mevcut metni gösterir; metin oluşturma ekranı yoktur.
Yalnızca yeni deneme veritabanında ilk sürümü oluşturmak için:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-consent set-policy --version 1 --text 'DENEME METNI v1: Bu ortamda medya rizasi ekranini test ediyorum. Hukuki metin degildir.'
```

Mevcut kurulumda önce tarayıcıdaki sürüme bakın. Daha yüksek sürüm varsa `1`
kullanmayın; gerçek metni aynı sürüm altında değiştirmeyin. Gerçek kullanımın
metnini yetkili kişi belirlemelidir; örnek metin hukuki öneri değildir.

### 6.2. Tarayıcıda kabul edin

1. **Medya rızası** adımını açın veya sekmeden ayrılıp geri dönün.
2. Sürüm numarası ve metni okuyun.
3. Başlangıçta onay kutusunun boş, **Rızayı kaydet** düğmesinin kapalı olduğunu kontrol edin.
4. Okudum/rıza veriyorum kutusunu işaretleyin.
5. **Rızayı kaydet** düğmesine basın.
6. Adım değişirse yeniden **Medya rızası** düğmesini seçin.

Beklenen: **Rıza kaydedildi** ve kabul tarihi görünür. Sayfayı yenileyince aynı
sürüm için tekrar onay istenmez. Kabul bu tarayıcıya özel değil, kurulum geneline aittir.

### 6.3. Yeni sürüm tekrar onay ister

Yalnızca deneme ortamında, mevcut sürüm `1` ise:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-consent set-policy --version 2 --text 'DENEME METNI v2: Metin degisti; yeniden acik onay gerekiyor.'
```

Tarayıcıdaki rıza adımına dönün. Beklenen: sürüm `2` ve yeni metin görünür;
önceki kabul yeni sürümü kabul etmiş sayılmaz. Kutu yeniden boş olmalıdır.
Yeni metni okuyup açıkça kabul edin.

**Tam 409 kontrolü** tarayıcıdaki canlı yenilemeyle yarışmaya çalışmak yerine
aşağıdaki PowerShell kontrolüyle deterministik yapılabilir; geliştirici konsoluna
kod yapıştırmanız gerekmez (bölüm 11.2).

## 7. Logo ve açıklama şablonunu kaydedin

### 7.1. Logo

1. **Dojo logosu** adımını seçin.
2. **Logo görseli** alanından kendi deneme PNG/JPEG dosyanızı seçin.
3. **Logoyu kaydet** düğmesine basın.
4. Yeniden aynı adımı açın; **Logo tanımlı** ve yeni yüklenen logo önizlemesini kontrol edin.

Sınırlar: **tek kare PNG/JPEG**, en fazla **10 MiB**, her kenarı en fazla
**4096 piksel**. Şeffaf PNG desteklenir. Aktif paket oluşturmanız gerekmez.
Eski sunucu tanımlı logo referansı için önizleme olmayabilir; bu tek başına hata değildir.

Negatif kontroller:

- SVG/GIF dosyasını seçmeyi deneyin; PNG/JPEG uyarısı beklenir. Dosya seçicide
  görünmüyorsa “Tüm dosyalar” filtresini kullanabilirsiniz.
- 10 MiB üstü dosya seçerseniz boyut uyarısı beklenir.
- Uzun kenarı 4097 piksel olan bir PNG/JPEG yüklemeyi denerseniz sunucu reddetmelidir.
- Dosya uzantısını `.png` yapmak geçersiz içeriği geçerli görsele dönüştürmez.

Başarısız yükleme/kayıt, önceki logoyu değiştirmemelidir. Sadece yüklenmiş ama ayara
atanamamış dosya kalabilir; kaydetme hatasını başarılı kurulum saymayın.

### 7.2. Açıklama

1. **Açıklama şablonu** adımını seçin.
2. `Dojo deneme açıklaması — antrenman anıları` yazın.
3. **Açıklamayı kaydet** düğmesine basın.
4. Yeniden açın; yazdığınız metin korunmalıdır.
5. Sadece boşluk yazarak kaydetmeyi deneyin; boş olamaz uyarısı beklenir.
6. Geçerli metni geri yazıp kaydedin.

Beklenen: açıklama kaydı logoyu veya kartları silmez. Yeni paketlerin başlangıç
ayarlarını değiştirir; mevcut paketlerin kopyalanmış ayarları ve hazır renderları
geriye dönük değiştirilmez.

## 8. İsteğe bağlı kartları deneyin

**İsteğe bağlı kartlar** adımında iki yol vardır:

### A. Değiştirmeden devam et

**Kartları değiştirmeden devam et** düğmesine basın.

Beklenen: kart adımı incelenmiş sayılır. Var olan giriş/çıkış kartları silinmez.
Kartların eksik olması genel hazır durumunu zaten engellemez.

### B. Kart yapılandır

1. **Giriş görseli** için PNG/JPEG seçin.
2. **Giriş süresi (saniye)** alanına `1.5` girin. Tarayıcı yerelleştirmesine göre
   ondalık ayırıcı virgül olabilir.
3. İsterseniz çıkış görseli ve süresini de tanımlayın.
4. **Kartları kaydet** düğmesine basın.
5. Yeniden açıp kayıtları kontrol edin.

Süre pozitif ve sonlu olmalıdır; `0` veya negatif sayı reddedilir. Süre boşsa
varsayılan fotoğraf süresi kullanılır. Görsel olmadan süre tanımlamayın.

Silme denemesi: **Giriş kartını kaldır**, ardından **Kartları kaydet**.
Beklenen: giriş görseli ve süresi temizlenir; logo/açıklama/çıkış kartı korunur.
**Kaldır** düğmesi taslağı değiştirir; kalıcı işlem için kaydetmeniz gerekir.

> Bilinen küçük sorun: geçerli kart dosyası seçtikten sonra geçersiz ikinci dosya
> seçerseniz ilk dosya taslakta kalabilir. Böyle bir hatadan sonra kaydetmeyin;
> adımı terk edip yeniden açın ve istediğiniz dosyayı tekrar seçin.

## 9. Bitirme, yeniden açma ve kaldığı yerden devam

1. Zorunlu adımlar tamamsa **Kurulum tamamlandı** başlığını kontrol edin.
2. **Kurulumu bitir** ile Kontrol Paneli'ne dönün.
3. **Ayarlar → Kurulumu aç** ile tekrar açın.
4. Sayfayı yenileyin; kaydedilen ayarlar ve rıza korunmalıdır.

Yarım bırakma kontrolü: herhangi bir adımda **Kuruluma sonra devam et** seçin.
Kontrol Paneli'nde kalabilmelisiniz; arka plan yenilemeleri sizi sürekli sihirbaza
geri atmamalıdır. Yeniden açınca eksik zorunlu adım seçilir.

**Kaydedilmemiş form değerleri** kalıcı değildir. Sayfa yenileme veya adım değiştirme
taslağı kaybedebilir; kaldığı yerden devam, sunucuya başarıyla kaydedilmiş ayarlar
içindir. Gerçek tokenınız yoksa Instagram eksik kalır ve tamamlandı ekranı beklenmez.

## 10. İki tarayıcıyla ortak durum ve taslak koruması

1. Yeni bir eşleştirme kodu üretin (bölüm 3).
2. Ayrı tarayıcı profili/gizli pencere açıp `Rehber Tarayıcısı 2` adıyla eşleştirin.
3. İkinci pencerede **Medya rızası** adımını açın.
4. İlk pencerede kabul edilmiş aynı sürüm için ikinci pencerede de kabul tarihi
   görünmeli; tekrar kabul gerekmez.
5. İkinci pencerede **Açıklama şablonu** alanına `Kaydedilmemiş taslak` yazın;
   henüz kaydetmeyin.
6. İlk pencerede aynı şablonu başka geçerli metne değiştirip kaydedin.
7. İkinci pencereye dönün; foreground yenilemesini bekleyin.

Beklenen: ikinci penceredeki taslak ezilmez. Başka cihazın değişikliği için uyarı
ve **Sunucudaki değerleri yükle** düğmesi çıkar. Düğmeye basınca taslak yerine
sunucudaki son değer alınır. Logo/kart referansı değişiklikleri de bu kontrole dahildir.

Yerel dosya seçimi de taslaktır; yeniden yükleme onu temizler. Taslak korunuyor
olması değişiklik birleştirme veya kayıt çatışmasını otomatik engelleme garantisi değildir.

## 11. Tarayıcıda ekranı olmayan kontroller — yalnız PowerShell

### 11.1. PowerShell için ayrı çerezli oturum açın

Tarayıcı çerezini kopyalamayın. Bölüm 3'teki komutla yeni bir kod üretin, sonra:

```powershell
$BaseUrl = 'http://localhost:8000'
$PairCode = Read-Host 'Yeni, tek kullanımlık eşleştirme kodu'
$PairBody = @{ code = $PairCode; kind = 'browser'; name = 'Rehber PowerShell' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/pairing/validate" -ContentType 'application/json' -Body $PairBody -SessionVariable DojoSession | Out-Null
$PairCode = $null
$PairBody = $null
Invoke-RestMethod -Uri "$BaseUrl/api/setup" -WebSession $DojoSession | ConvertTo-Json -Depth 5
```

Beklenen: `ready` ve yedi maddelik `checklist` görünür. Cookie PowerShell oturumunda
tutulur; tarayıcıdan veya SQL'den kimlik bilgisi alınmaz. Uzak backend kullanırsanız
`$BaseUrl` HTTPS olmalıdır; HTTP örneği sadece yerel makine içindir.

### 11.2. Eski rıza sürümünün 409 ile reddedilmesi

11.1'deki oturumu açık tutun. Önce mevcut sürümü okuyun:

```powershell
$OldPolicy = Invoke-RestMethod -Uri "$BaseUrl/api/setup/consent" -WebSession $DojoSession
$OldVersion = [int]$OldPolicy.version
$NewVersion = $OldVersion + 1
docker compose --env-file ops/.env -f ops/docker-compose.yml exec backend .venv/bin/dojo-consent set-policy --version $NewVersion --text 'DENEME: Yeni surum; onceki kabul yeterli degil.'
$OldAcceptance = @{ version = $OldVersion } | ConvertTo-Json
try {
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/setup/consent/accept" -WebSession $DojoSession -ContentType 'application/json' -Body $OldAcceptance | Out-Null
    Write-Host 'BEKLENMEYEN: Eski sürüm kabul edildi.'
} catch {
    if ($null -ne $_.Exception.Response) {
        Write-Host "HTTP $([int]$_.Exception.Response.StatusCode) (beklenen: 409)"
    } else {
        Write-Host 'HTTP yanıtı alınamadı; önce bağlantıyı kontrol edin.'
    }
}
Invoke-RestMethod -Uri "$BaseUrl/api/setup/consent" -WebSession $DojoSession | Select-Object version, accepted_at
```

Beklenen: `409`; yeni sürümün `accepted_at` değeri boş. Tarayıcıya dönün,
yenilenen metni okuyup açıkça kabul edin. Bu komut yeni sürüm oluşturduğu için
**yalnız deneme ortamında** kullanılmalıdır. `$BaseUrl` ile Docker CLI'ın aynı
kurulumu hedeflediğinden emin olun; uzak backend için yerel Docker komutu kullanmayın.

### 11.3. Oturum iptalini deneyin

PowerShell oturumu ile istemcileri listeleyin:

```powershell
Invoke-RestMethod -Uri "$BaseUrl/api/pairing/clients" -WebSession $DojoSession |
    Select-Object id, name, kind, revoked_at | Format-Table
```

Listeden **yalnız iptal edeceğiniz deneme tarayıcısının** kimliğini bulun.
PowerShell istemcisini veya gerçek bir kullanıcının cihazını seçmeyin.

```powershell
$TargetId = Read-Host 'İptal edilecek deneme tarayıcısının id değeri'
$Confirm = Read-Host "İstemci $TargetId iptal edilecek. Onay için EVET yazın"
if ($Confirm -eq 'EVET') {
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/pairing/clients/$TargetId/revoke" -WebSession $DojoSession
}
```

İlgili tarayıcıya dönün. Beklenen: korumalı yenileme 401 aldığında eşleştirme
ekranına dönülür; korumalı form/veri gösterilmeye devam edilmez. Bu istemciyi
yeniden kullanmak için yeni kodla eşleştirme gerekir.

### 11.4. Web formu yerine mevcut token betiğini kullanma

Tarayıcıdan token tanımlayamıyorsanız repo kökünde:

```powershell
.\ops\connect-instagram.ps1 -BaseUrl 'http://localhost:8000'
```

Betik Dojo uygulama kimliği ile Instagram tokenını ayrı, gizli girişlerle ister.
Detaylar: [Instagram token bağlantısı rehberi](instagram-token-baglantisi-rehberi.md).
Bu alternatif bir bağlantı yoludur; web formunun çalıştığını kanıtlamaz.

## 12. Mobil, klavye ve bağlantı hatası kontrolleri

- Tarayıcı geliştirici araçlarının cihaz görünümünde genişliği sırayla
  **320**, **390**, **1280** piksel yapın. Yatay taşma olmamalı; adımlar ve formlar
  okunabilmelidir.
- `Tab`/`Shift+Tab` ile adım düğmeleri ve form alanlarını gezin. Odak görünür
  olmalı; `Space` ile onay kutusu değişmeli, `Enter` ile düğme çalışmalıdır.
- Adım değişince odak yeni başlığa taşınmalıdır.
- Geliştirici araçlarında ağ durumunu geçici **Offline** yapın. Son kayıtlı
  bilgiler hata uyarısıyla korunmalıdır; başarı gibi sunulmamalıdır. **Online**
  yapıp sekmeye dönün veya **Tekrar dene** kullanın.
- Gerçek token kullanırken ağ kayıtlarını paylaşmayın. Bu kontroller için
  geliştirici konsolunda JavaScript çalıştırmanız gerekmez.

## 13. Sık görülen sorunlar ve denemenin sınırları

| Durum | Ne kontrol edilmeli? |
| --- | --- |
| Eski Ayarlar özeti var, sihirbaz yok | Doğru dal/worktree ve onun web sunucusu çalışıyor mu? |
| Eşleştirme sonrası yeniden kod isteniyor | Yerel HTTP için `COOKIE_SECURE=false` mı? Backend yeniden oluşturuldu mu? |
| Token ekranında yapılandırma hatası | `META_TOKEN_ENCRYPTION_KEY` dolu/geçerli mi; backend yeni `.env` ile başlatıldı mı? |
| Geçersiz token/izin hatası | Instagram Login token türü, hesap ve gerekli izinler uygun mu? |
| Servise ulaşılamadı | Backend internet/Instagram erişimi ve sağlayıcı durumu; önceki bağlantı korunmalı |
| Rıza metni yok | Yönetici CLI ile metin oluşturdu mu; CLI ve tarayıcı aynı veritabanını mı kullanıyor? |
| Genel tamamlandı görünmüyor | Instagram dahil bütün zorunlu adımlar gerçekten tamam mı? Kartlar zorunlu değil |
| Worker çalışmıyor görünüyor | Bu rehber worker'ı başlatmıyor; sihirbaz denemesi için normal |
| Kart dosyası reddedildi | Eski seçimin taslakta kalma ihtimali nedeniyle adımı kapatıp yeniden açın |
| `refresh_due` için yeniden bağlan yazıyor | Bilinen metin tutarsızlığı; backend bu sağlık durumunu hazır kabul ediyor |

Bu rehber onboarding'i denetler, gerçek Instagram yayını veya tam canlı OAuth
entegrasyonu garantisi vermez. Otomatik doğrulama sırasında core **583**, backend
**129**, worker **140**, web **70** test geçti; web build/typecheck geçti.
Host FFmpeg olmadığı için iki mevcut medya testi, Windows symlink yetkisi
olmadığı için bir güvenlik testi atlandı. Mevcut lint/core mypy borcu ayrıca
raporlandı; atlanan testler başarılı sayılmadı.

Detaylı kanıt ve ekran görüntüleri:
[issue #26 doğrulama kaydı](../verification/issue-26-web-onboarding.md).

Denemeyi bitirirken web terminalinde `Ctrl+C` kullanın. Yalnız bu rehber için
başlattığınız backend/db servislerini durdurmak isterseniz:

```powershell
docker compose --env-file ops/.env -f ops/docker-compose.yml stop backend db
```

Bu işlem veri silmez; ancak aynı servisleri kullanan başka oturumları da keser.
Ortak/üretim ortamında uygulamayın. Temizlik amacıyla `down -v` veya veri klasörü
silme komutları kullanmayın.
