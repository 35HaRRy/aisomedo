# Zamanlanmış ve manuel yayın: değişiklik özeti ve deneme rehberi (#40)

Bu rehber #40 kapsamında eklenenleri anlatır. Kullanıcıya görünen değişikliği
**tarayıcıda**, bütün servislerin birlikte çalışmasını ise **PowerShell üzerinden
başlatılan izole kabul testiyle** deneyebilirsiniz. Komut bloklarında Python veya
SQL kodu yoktur; `uv`, repodaki hazır çalıştırıcıyı gerekli yorumlayıcıyla açar.

> **Gerçek yayın uyarısı:** Kendi uygulamanızdaki **Onayla ve yayınla →
> Yayınlamayı onayla**, bağlı Instagram hesabında gerçek yayın başlatabilir.
> Canlı kurulumda deneme yapmayın. Gerçek Instagram'a hiçbir şey göndermeden son
> onayı da denemek için bölüm 4'teki izole testi kullanın.

## 1. Neler değişti?

| Değişiklik | Deneyebileceğiniz sonuç |
| --- | --- |
| Kontrol Paneli'nde **Manuel Yayın İncelemesi iste** | Düzenli planı değiştirmeden bir inceleme hazırlanmasını isteyebilirsiniz. Bu düğme tek başına Instagram'a yayın yapmaz. |
| **İncelemeye devam et** bağlantısı | Oluşan Yayın Zamanı üzerinden incelemeye geçebilirsiniz. |
| Tekrarlı istek koruması | İstek gönderilince düğme kapanır. Sonuç belirsizse otomatik yeniden gönderilmez; bekleyen işlemleri kontrol etmeniz istenir. |
| Üretim benzeri gerçek kabul ortamı | PostgreSQL, kalıcı dosya alanı, şema başlatıcısı, FastAPI, worker, FFmpeg ve derlenmiş web birlikte çalıştırılır. |
| İki uçtan uca senaryo | Bir zamanlanmış video yayını ve farklı gerçek medya kullanan bir manuel yayın doğrulanır. |
| Sahte Meta ve bildirim toplayıcısı | Gerçek Instagram/Firebase hesabı gerekmez; video gerçekten indirilir, yayın çağrıları ve bildirimler kaydedilir. |
| İçerik doğrulaması | İncelemedeki video ile Meta'nın indirdiği videonun SHA-256 özeti ve açıklaması karşılaştırılır. İki paketin çıktı özetlerinin farklı olması da zorunludur. |
| CI kapısı ve tanılama dosyaları | Kabul testi başarısızsa ops kontrolü geçmez. Boş, atlanmış veya yeniden denemeyle geçmiş testler başarı sayılmaz. |

Android uygulamasına bu işte yeni bir ekran veya düğme eklenmedi. Gerçek Android
bildirim teslimatı da bu kabul testinin kapsamı değildir: test, sentetik bir
cihazın bildirimlerini toplayıcıda doğrular.

## 2. Hangi yolu seçmeliyim?

- **Hazır ve ayrı bir deneme kurulumunuz varsa:** bölüm 3'te tarayıcıdan elle
  kontrol edin. Gerçek yayın istemiyorsanız son onay düğmesine basmayın.
- **Hiçbir gerçek hesaba bağlanmadan bütün akışı doğrulamak istiyorsanız:**
  doğrudan bölüm 4'e geçin. Önerilen güvenli yol budur.
- **GitHub Actions sonucunu görmek istiyorsanız:** bölüm 6'yı kullanın; önce
  değişikliklerin uzak depoya gönderilmiş olması gerekir.

**Önemli ayrım:** İzole kabul ortamı host portu açmaz. Kendi tarayıcınızdan veya
Android uygulamasından `dojo.acceptance.test` adresine bağlanamazsınız. Bu adres,
yalnız Docker ağı içindeki otomatik Chromium tarafından açılır. Test bittikten
sonra ekran görüntülerini kendi tarayıcınızda veya resim görüntüleyicinizde
inceleyebilirsiniz. Elle kullanılabilecek geçici bir test sunucusu eklenmedi.

## 3. Tarayıcıdan elle deneyin

Bu bölüm **zaten çalışan, bu değişiklikleri içeren ayrı deneme kurulumunuz**
içindir. Yeni sunucu kurmaz, mevcut veritabanını değiştiren bakım komutu çalıştırmaz.

### 3.1. Ön koşulları kontrol edin

1. Deneme uygulamanızın adresini tarayıcıda açın ve tarayıcıyı eşleştirin.
   Eşleştirme kodunu operatörden veya eşleştirilmiş cihazdan alın.
2. **Ayarlar → Kurulumu aç** üzerinden Instagram bağlantısı, Dojo Yayın Planı,
   logo, açıklama şablonu ve medya rızasının tamamlandığını kontrol edin.
   Gerekirse [kurulum rehberini](issue-26-web-onboarding-deneme-rehberi.md) izleyin.
3. **Kontrol Paneli**'nde worker'ın çalıştığını kontrol edin. Eksik kurulum veya
   çalışmayan worker varsa yalnız bu düğmeye basarak inceleme oluşturulmasını
   beklemeyin.
4. Başka bekleyen işlem varsa önce onu inceleyin. Yeni manuel istek düğmesi,
   bekleyen işlem varken veya tarayıcı çevrimdışıyken kapalıdır.

### 3.2. Manuel Yayın İncelemesi isteyin

1. **Güncel Paket** bölümünü açın. Önceki yayın sonrasında devam ediyorsanız
   tarayıcı sayfasını tamamen yenileyin; yalnız menü değiştirmek yeterli olmayabilir.
2. **Fotoğraf ve video seç** ile deneme medyası yükleyin. Dosyanın **Aktif paket
   medyası** içinde görünmesini bekleyin. Tamamlanan yükleme kuyruktan kaldırılır;
   kuyrukta kalıcı bir “Pakete eklendi” satırı aramayın.
3. **Kontrol Paneli**'ndeki sonraki düzenli **Yayın Zamanı**nı not edin.
4. **Manuel Yayın İncelemesi iste** düğmesine bir kez basın.
5. **İncelemeye devam et** bağlantısını açın. Worker'ın Reel'i hazırlamasını
   bekleyin. Hazır inceleme ayrıca panelde **İnceleme özeti** bağlantısıyla görünür.
6. **Yayın İncelemesi** ekranında paket adını, açıklamayı ve oynatılabilir Reel'i
   kontrol edin. Yalnız videoyu oynatmak yayın yapmaz.
7. İsterseniz **Onayla ve yayınla** ile ikinci onay metnini açıp **Vazgeç** ile
   geri dönün. Bu aşama tek başına yayınlamaz. Gerçek yayın istemiyorsanız
   **Yayınlamayı onayla** düğmesine basmayın.

**Beklenen:** Yeni inceleme oluşur; manuel istek düzenli planın sıklığını veya
sonraki düzenli zamanını kaydırmaz. Son onayı vermediyseniz paket tamamlanmış
sayılmaz ve inceleme bekleyen işlem olarak kalır. Sırf denemeyi bitirmek için
canlı veriyi atlamayın, ertelemeyin veya silmeyin; bunlar ayrı kalıcı işlemlerdir.

İstek sonucu doğrulanamazsa düğmeye tekrar tekrar basmayın. Paneli yenileyip
bekleyen işlemleri kontrol edin; önceki istek sunucuya ulaşmış olabilir.

### 3.3. Zamanlanmış incelemeyi gözlemleyin

1. Yalnız ayrı deneme ortamında **Ayarlar → Dojo Yayın Planı** bölümünü açın.
2. Gelecekteki bir pazartesi başlangıç tarihi ve **Europe/Istanbul** saati seçin.
   **Düzenli yayını etkinleştir** seçeneğini işaretleyip **Planı kaydet**'e basın.
   Plan iki haftada bir pazartesi işler; rastgele bir günü sırf testi hızlandırmak
   için seçmeyin.
3. Yayın Zamanı gelmeden Aktif Paket'e medya yükleyin ve doğrulamanın tamamlanmasını
   bekleyin. Bu senaryoyu önceki bekleyen manuel incelemeyle karıştırmayın; ayrı
   bir deneme durumu kullanın.
4. Zamanı geldiğinde worker'ın incelemeyi hazırlamasını bekleyip panelden açın.
5. 3.2'deki önizleme ve açıklama kontrollerini yapın. Gerçek yayın istemiyorsanız
   son onayı vermeyin.

**Beklenen:** Zamanın gelmesi incelemeyi hazırlar; kullanıcı son onayı vermeden
yayın tamamlanmaz. Gerçek zamanı beklemek istemiyorsanız bölüm 4'teki test kendi
yalıtılmış saatini ilerletir. Bilgisayarınızın veya sunucunun sistem saatini
değiştirmeyin.

## 4. Güvenli tam deneme — PowerShell

Bu yol gerçek PostgreSQL ve FFmpeg kullanır ama yalnız sahte Meta'ya yayın yapar.
Gerçek hesap, Firebase anahtarı, `ops/.env` düzenlemesi veya SQL işlemi gerekmez.

### 4.1. Araçları ve proje kökünü doğrulayın

Docker Desktop çalışıyor ve **Linux containers** modunda olmalı. `uv` kurulu
olmalı. İlk derleme için internet ve Docker imajlarına yetecek disk alanı gerekir.
Chromium ve Node test imajının içinde hazırlanır; bu tam test için host üzerinde
ayrıca Android SDK veya Node kurmanız gerekmez.

```powershell
Set-Location -LiteralPath 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
if (-not (Test-Path .\ops\acceptance\run.py)) { throw 'Proje kökü veya sürüm yanlış.' }
uv --version
if ($LASTEXITCODE -ne 0) { throw 'uv kullanılamıyor.' }
$DockerTuru = docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0 -or $DockerTuru -ne 'linux') { throw 'Docker Linux containers modunda çalışmalı.' }
docker compose version
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose kullanılamıyor.' }
```

Checkout'unuz farklı yerdeyse yalnız ilk satırdaki yolu değiştirin.

### 4.2. İki senaryoyu çalıştırın

```powershell
uv sync --all-packages --frozen
if ($LASTEXITCODE -ne 0) { throw 'Proje bağımlılıkları hazırlanamadı.' }

uv run --project backend .\ops\acceptance\run.py --image-tag rehber-issue40 --build --output .\artifacts\acceptance
if ($LASTEXITCODE -ne 0) { throw 'Kabul testi başarısız. Bölüm 5 ile son denemenin kayıtlarını inceleyin.' }
```

`--build`, uygulama imajlarını **bu checkout'taki koddan** üretir. İlk çalıştırma
uzun sürebilir. Aynı etiketle eski imaj kullanmamak için elle denemelerde bu
seçeneği koruyun. Docker'ın tüm önbelleğini veya volume'lerini temizlemeyin.

Çalıştırıcı otomatik olarak:

1. Rastgele `dojo-acceptance-*` adlı proje ve yeni test volume'leri oluşturur.
2. Geçici sertifikayla HTTPS'i açar; sertifika güveni yalnız test konteynerlerine
   kurulur, Windows sertifika deponuz değiştirilmez.
3. Tarayıcıyı ve sentetik bildirim alıcısını eşleştirip kurulumu tamamlar.
4. Zamanlanmış senaryoda video yükler, test saatini ilerletir, incelemeyi açar,
   oynatır ve onaylar.
5. Manuel senaryoda farklı bir PNG yükler, paneldeki manuel düğmeyle inceleme
   ister, oynatır ve onaylar.
6. İki videonun kendi incelemesiyle eşleşmesini, birbirinden farklı olmasını,
   bildirimleri, iki yayın kaydını ve iki tamamlanmış paket klasörünü doğrular.
7. Sonraki worker turunda yinelenen yayın olmadığını kontrol eder; kayıtları
   sakladıktan sonra yalnız kendi test servislerini ve volume'lerini temizler.

**Başarı ölçütü:** Komutun çıkış kodu sıfırdır. Bölüm 5'teki raporda **2 başarılı,
0 atlanmış, 0 beklenmeyen, 0 kararsız** test görülür. Yalnız klasör oluşması veya
bir ekran görüntüsünün bulunması testi başarılı saymaz. Eksik Docker/imaj/test
durumunda başarı yerine hata alınır.

## 5. Sonuçları PowerShell ve görüntüleyiciyle inceleyin

Komut, çalışmanın klasörünü **Acceptance evidence:** satırında yazar. Her deneme
ayrı alt klasöre kaydedilir. Aşağıdaki komutlar en son klasörü seçer; aynı anda
birden fazla deneme çalıştırdıysanız terminalde yazılan doğru klasörü kullanın.

```powershell
$Calisma = Get-ChildItem -LiteralPath .\artifacts\acceptance -Directory -Filter 'dojo-acceptance-*' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $Calisma) { throw 'Kabul testi çıktı klasörü bulunamadı.' }
$Calisma.FullName
Get-ChildItem -LiteralPath $Calisma.FullName

$Rapor = Get-Content -LiteralPath (Join-Path $Calisma.FullName 'report.json') -Raw | ConvertFrom-Json
$Rapor.stats | Format-List expected, skipped, unexpected, flaky, duration
```

Beklenen değerler `expected: 2`, `skipped: 0`, `unexpected: 0`, `flaky: 0`.
`duration` milisaniye cinsindendir. Bu JSON kontrolü tek başına temizliğin başarılı
olduğunu kanıtlamaz; çalıştırıcı çıkış kodunu da kontrol etmiş olmalısınız.

### 5.1. Yayın ve dosya kanıtları

```powershell
$Kanit = Get-Content -LiteralPath (Join-Path $Calisma.FullName 'evidence.json') -Raw | ConvertFrom-Json
$Kanit.containers | Format-Table id, bytes, sha256, caption -AutoSize
$Kanit.publications | Format-Table id, container_id -AutoSize
$Kanit.notifications | ConvertTo-Json -Depth 8
Get-Content -LiteralPath (Join-Path $Calisma.FullName 'filesystem.json') -Raw
```

**Beklenen:** İki container, iki yayın ve iki farklı SHA-256; iki paket için
inceleme ve yayın doğrulama bildirimleri; adları `-completed` ile biten iki
klasör. İnceleme–yayın eşitliğini otomatik test ayrıca kontrol eder.

### 5.2. Ekran görüntülerini açın

```powershell
Invoke-Item -LiteralPath (Join-Path $Calisma.FullName 'review-0-desktop.png')
Invoke-Item -LiteralPath (Join-Path $Calisma.FullName 'review-1-mobile.png')
```

`0` zamanlanmış, `1` manuel senaryodur. Her ikisinin de desktop/mobile görüntüsü
üretilir. Bunlar test anındaki inceleme ekranlarıdır; çalışan uygulamaya bağlantı
veya tek başına yayın başarı kanıtı değildir.

### 5.3. Hata varsa

```powershell
Get-ChildItem -LiteralPath $Calisma.FullName -Recurse -File |
    Select-Object FullName
$HataKaydi = Join-Path $Calisma.FullName 'command-failure.log'
if (Test-Path -LiteralPath $HataKaydi) { Get-Content -LiteralPath $HataKaydi -Tail 80 }
$ServisKaydi = Join-Path $Calisma.FullName 'compose.log'
if (Test-Path -LiteralPath $ServisKaydi) { Get-Content -LiteralPath $ServisKaydi -Tail 80 }
```

- İmaj derlemesinde hata olduysa tarayıcı raporu henüz oluşmamış olabilir.
- `report.json` veya `filesystem.json` yoksa bu sonucu başarı saymayın.
- Backend başlatılamadıysa `evidence.json` toplanamayabilir; bilinen küçük
  tanılama sınırıdır. Diğer kayıtları inceleyin.
- Çıktı **Cleanup failed for owned project** diyorsa o test projesi temizlenemedi.
  Paylaşılan verileri silen `docker system prune` veya genel volume silme
  komutları kullanmayın; hata mesajındaki tam proje adını operatörle paylaşın.
- `active package changed` alırsanız eski paket kimliğiyle gönderim engellenmiştir.
  Elle denemede sayfayı tamamen yenileyip güncel paketi kontrol edin; aynı isteği
  otomatik tekrar göndermeyin.

Trace dosyaları tarayıcı oturumu ve sentetik token içerebilir. Çıktı klasörünü
özel tanılama verisi olarak tutun; herkese açık paylaşmayın. Varsayılan çıktı
yolu Git tarafından dışlanır. Test ağı ve dosyaları gerçek kurulumun yedeği değildir.

## 6. GitHub Actions'ı tarayıcıdan kontrol edin

1. Değişiklikleri içeren dalın GitHub sayfasında **Actions → ci** çalışmasını açın.
   Yalnız yerelde commit varsa bu yeni kontrol henüz uzakta görünmez; bu rehber
   otomatik push veya canlı dağıtım başlatmaz.
2. **ops** işinde **Verify deployed scheduled and manual publication** adımını açın.
3. Başarılı çalışmanın **deployed-acceptance** artifact'ını indirin. İçindeki
   proje alt klasöründe bölüm 5'teki raporları inceleyin.
4. `required` sonucunu da kontrol edin. Kabul testinin geçmesi bütün CI işlerinin
   geçtiği anlamına gelmez; diğer zorunlu kontroller ayrıca başarılı olmalıdır.

## 7. Doğrulama sınırı ve önceki sonuç

2026-10-16 tarihindeki son yerel denemede iki gerçek akış geçti; iki farklı çıktı
özeti ve iki tamamlanmış paket doğrulandı. Bu geçmiş kayıt sizin checkout'unuzun
geçtiği anlamına gelmez; yukarıdaki komutu kendiniz çalıştırın.

Bu test gerçek Meta yetkilendirmesini, Firebase/Android cihaza teslimatı veya
internetten erişilebilir DNS/TLS kurulumunu kanıtlamaz. Ayrıntılı teknik sonuçlar,
inceleme kararları ve ilgisiz Windows CRLF test hatası
[doğrulama kaydında](../verification/issue-40-deployed-stack-acceptance.md) bulunur.
