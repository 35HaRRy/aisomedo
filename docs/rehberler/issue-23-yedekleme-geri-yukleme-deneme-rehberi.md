# Manuel şifreli yedekleme ve geri yükleme: durum ve deneme rehberi (#23)

## 1. Şu ana kadar ne değişti?

`ops/backup.py` altında manuel şifreli yedekleme ve geri yükleme CLI'si eklendi.
Web/Android yedekleme ekranı eklenmedi. Canlı sunucuda yedekleme veya geri yükleme
yapılmadı; aşağıdaki denemeler yalnız sentetik ve geçici test kaynaklarını kullanır.

| Dosya | İçerik |
| --- | --- |
| `docs/superpowers/specs/2026-10-14-manual-encrypted-backup-restore-design.md` | Onaylanan kapsam, şifreleme, güvenlik, bakım kesintisi ve kurtarma kuralları |
| `docs/superpowers/plans/2026-10-14-manual-encrypted-backup-restore.md` | Kodlama görevleri, testler, CI ve doğrulama adımları |
| Bu rehber | Güvenli PowerShell/WSL testleri ve tarayıcı/Android gözlemleri |
| `ops/backup.py` | Veritabanı, yapılandırma ve tüm medyanın tek şifreli arşivde saklanması/geri yüklenmesi |
| `ops/tests/test_backup.py` | Yanlış anahtar, bozuk arşiv, güvensiz yollar, kesinti ve güvenlik yedeği kontrolleri |
| `ops/tests/test_backup_integration.py` | Gerçek PostgreSQL/medya kurtarma; mevcut ve boş hedef; hata sonrası servislerin kapalı kalması |
| `docs/ops/backup.md` | Linux operatör komutları, anahtar saklama ve kurtarma sınırları |

Tasarım belgesi `3a20eed` commit'inde eklendi. Bu commit yalnız dokümantasyon
değişikliğidir; çalışan uygulamaya özellik, ekran veya yedekleme komutu eklemez.

Eklenen özellik: PostgreSQL, üretim ayarları ve gerekli kimlik bilgileri,
geçerli sürüm paketi ve tüm medyanın tek `age` şifreli arşivde saklanması.
Yedekleme kısa bakım kesintisi gerektirir. Mevcut verinin geri yüklemeyle
değiştirilmesi açık onay ve önce şifreli güvenlik yedeği gerektirir.
Zamanlanmış yedek, uygulama ekranı veya otomatik buluta gönderim yoktur.
Boş hedefte mevcut özel adlı volume de korunur; dış/bind-backed depolama ve
shell'den gelen Compose ayarları reddedilir. Yeniden başlatma sırasında gelen
sinyalde de eski servisleri toparlama girişimi yapılır.
Yanlış kurulum yolu ilgisiz klasörün izinlerini değiştirmez. Windows CRLF/BOM
ayar dosyaları korunur; Firebase için yalnız host-path ayarı değiştirilir.

## 2. Şimdi deneyebileceğiniz kontroller — PowerShell

PowerShell'i proje kökünde açın. Bu bölümdeki komutlar veri değiştirmez,
servis durdurmaz; Python veya SQL kodu içermez. §4 testleri kendi geçici
Docker kaynaklarını oluşturup temizler; üretim ortamına dokunmaz.

### 2.1. Belgelerin varlığını kontrol edin

```powershell
$Spec = 'docs/superpowers/specs/2026-10-14-manual-encrypted-backup-restore-design.md'
$Plan = 'docs/superpowers/plans/2026-10-14-manual-encrypted-backup-restore.md'
Get-Location
Test-Path $Spec
Test-Path $Plan
```

**Beklenen:** İki dosya kontrolü de `True`. `False` ise doğru checkout'ta
olduğunuzu kontrol edin; bu belgeler uzak depoya henüz gönderilmiş olmayabilir.

### 2.2. Değişiklik kapsamını inceleyin

```powershell
git show --stat --oneline 3a20eed
if ($LASTEXITCODE -ne 0) { throw 'Tasarım commit bilgisi okunamadı.' }
git status --short
```

**Beklenen:** Tasarım commit'inde yalnız tasarım belgesi listelenir. İkinci
komut mevcut yerel değişiklikleri gösterir; boş çıktı temiz çalışma ağacıdır.
Sonradan eklenen plan/rehber bu ilk commit'in içinde değildir.

### 2.3. Tasarım ve planı okuyun

```powershell
Get-Content -Encoding UTF8 $Spec
Get-Content -Encoding UTF8 $Plan
```

Özellikle şunları kontrol edin:

1. Yedek veritabanı, ayarlar/kimlik bilgileri ve tüm medyayı kapsıyor mu?
2. Özel şifre çözme anahtarı arşiv dışında ve sunucudan bağımsız saklanıyor mu?
3. Geri yükleme öncesi doğrulama ve mevcut veriler için güvenlik yedeği zorunlu mu?
4. Yarım kalan geri yüklemede uygulama servisleri kapalı tutuluyor mu?
5. Gerçek kurtarma testleri yalnız geçici, üretim dışı kaynaklarda mı çalışıyor?

**Bu kontrol, çalışan yedek veya başarılı geri yükleme kanıtı değildir.**

## 3. Tarayıcı veya Android'de neden doğrudan denenemiyor?

Bu özellik sunucu operatörü için manuel CLI olarak tasarlandı. Yedek alma,
indirme veya geri yükleme düğmesi yoktur. Ekran üzerinden yalnız geri yüklenen
test ortamının eski verileri tekrar gösterdiği gözlemlenebilir.

Belgeler GitHub'a gönderildikten sonra tarayıcıda ilgili dalın dosya listesinden
spec ve planı okuyabilirsiniz. Yerel commit'lerin GitHub'da görünmesi için ayrıca
gönderim gerekir; bu rehber gönderim veya dağıtım yaptırmaz.

## 4. Güvenli deneme — PowerShell

Önce §4.1'i, Linux ortamı hazırsa §4.2'yi çalıştırın. Testlerin içinde mevcut
kod çalışır; komutlara Python veya SQL kaynak kodu yapıştırmanız gerekmez.

### 4.1. Sentetik güvenlik testleri

`uv` ve `age` kurulu, `age-keygen` PATH üzerinde olmalıdır:

```powershell
if (-not (Test-Path 'ops/tests/test_backup.py')) {
    throw 'Doğru checkout altında değilsiniz.'
}
uv --version
if ($LASTEXITCODE -ne 0) { throw 'uv kurulumu gerekli.' }
age --version
if ($LASTEXITCODE -ne 0) { throw 'age kurulumu gerekli.' }
Get-Command age-keygen -ErrorAction Stop
uv sync --all-packages --frozen
if ($LASTEXITCODE -ne 0) { throw 'Test bağımlılıkları hazırlanamadı.' }
uv run --project backend pytest ops/tests/test_backup.py -v
if ($LASTEXITCODE -ne 0) { throw 'Yedekleme güvenlik testleri başarısız.' }
```

`uv` mevcut test kodunu çalıştırır; siz Python/SQL kodu yazmazsınız. Bu,
Python yorumlayıcısı gerekmeyeceği anlamına gelmez. `uv` ve gerçek şifreleme
kontrolleri için `age` kurulumu gerekir. Linux'a özgü kontroller Windows'ta
atlanabilir; `skipped` çıktısı başarılı Linux doğrulaması sayılmaz.

### 4.2. Gerçek veritabanı ve medya kurtarma testi

Linux, Docker/Compose, `age`, Linux `uv` ve doğrulama imajları gereklidir.
Windows'ta PowerShell üzerinden WSL kullanılabilir. Örnekte `Ubuntu` kullanılır;
dağıtım adınızı değiştirin. Docker Desktop'ın bu dağıtım için WSL entegrasyonu
açık olmalıdır. Komut bulunamazsa önce ilgili Linux aracının kurulumunu tamamlayın.
Linux ve Windows sanal ortamlarını karıştırmamak için ayrı Linux ortamı kullanılır.

Ön koşulları kontrol edin:

```powershell
wsl -d Ubuntu -- docker info
if ($LASTEXITCODE -ne 0) { throw 'WSL Docker erişimi gerekli; Docker Desktop WSL entegrasyonunu kontrol edin.' }
wsl -d Ubuntu -- age --version
if ($LASTEXITCODE -ne 0) { throw 'WSL içinde age kurulumu gerekli.' }
wsl -d Ubuntu -- uv --version
if ($LASTEXITCODE -ne 0) { throw 'WSL içinde uv kurulumu gerekli.' }
```

Üretim imajlarından ayrı test imajlarını hazırlayın:

```powershell
$LinuxEnv = '/var/tmp/aisomedo-issue23-venv'
wsl -d Ubuntu -- env "UV_PROJECT_ENVIRONMENT=$LinuxEnv" uv sync --all-packages --frozen
if ($LASTEXITCODE -ne 0) { throw 'Linux test bağımlılıkları hazırlanamadı.' }
wsl -d Ubuntu -- docker build -t dojo-backend-verify:issue23 -f backend/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Backend test imajı hazırlanamadı.' }
wsl -d Ubuntu -- docker build -t dojo-worker-verify:issue23 -f worker/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Worker test imajı hazırlanamadı.' }
wsl -d Ubuntu -- docker build -t dojo-gateway-verify:issue23 -f ops/gateway/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Gateway test imajı hazırlanamadı.' }
```

Gerçek kurtarma testlerini çalıştırın:

```powershell
wsl -d Ubuntu -- env "UV_PROJECT_ENVIRONMENT=$LinuxEnv" REQUIRE_BACKUP_INTEGRATION=1 VERIFY_IMAGE_TAG=issue23 uv run --project backend pytest ops/tests/test_backup_integration.py -v
if ($LASTEXITCODE -ne 0) { throw 'Linux kurtarma doğrulaması başarısız.' }
```

**Beklenen:** Gerekli ön koşullar yoksa test başarısız olur; sessizce atlanmaz.
Testler geçici Docker proje adları ve sahte kimlik bilgileriyle çalışır;
orijinal verileri geri getirir, yedekten sonra eklenen medya dosyalarını kaldırır
ve uygulama sağlığını kontrol eder. Üretim ortamını hedeflememelidir.

Mevcut hedef için iki worker örneği ve isteğe bağlı Firebase kimlik dosyası;
boş hedef için sıfırdan kurtarma; değiştirme sonrası hata için servislerin
kapalı kalması ayrı senaryolardır. Uygulamanın başlangıç klasör onarımıyla
çakışmamak için sentetik iç içe medya `branding` altında oluşturulur.

### 4.3. Tarayıcıda CI sonucunu inceleme

Değişiklikleri içeren dal GitHub'a gönderilmişse:

1. GitHub deposunda **Actions → ci** sayfasını açın.
2. Bu değişiklikleri içeren commit'in koşusunu seçin; eski koşu yeni kodu doğrulamaz.
3. **ops → Verify real encrypted recovery** adımını açın.
4. Mevcut hedef, Firebase dosyası, boş hedef ve hata senaryolarının geçtiğini kontrol edin.
5. **required** işinin başarılı olduğunu doğrulayın. Başarısız/atlanmış sonuç başarı sayılmaz.

Bu rehber dalı göndermeyi, üretime dağıtımı veya workflow başlatmayı otomatik yapmaz.
Yalnız yerel commit varsa GitHub'da yeni koşu beklemeyin.

### 4.4. İsteğe bağlı tarayıcı/Android gözlemi

Otomatik testler geçici ortamı temizleyebilir; bu ortamın açık kalacağını varsaymayın.
Operatör ayrıca yalıtılmış ve açık tutulmuş bir test kurulumu hazırlarsa:

1. Gerçek Instagram hesabı ve bildirim hedefi bağlamadan test hesabıyla giriş yapın.
2. Sentetik medya içeren paketin sırasını, açıklamasını ve önizlemesini kaydedin.
3. Operatörün test ortamında yedek alıp bu verileri değiştirmesini sağlayın.
4. Yedek geri yüklendikten sonra tarayıcıyı yenileyin. Android'de çevrimdışı
   önbelleğe güvenmeyin; çevrimiçi eşitleme sonrası sunucudan gelen veriyi kontrol edin.
5. İlk durumun geri geldiğini ve yedekten sonra eklenen medyanın bulunmadığını doğrulayın.

Ekran gözlemi şifrelemeyi veya tüm dosyaların bütünlüğünü kanıtlamaz; gerçek
kurtarma testleri ve doğrulama raporu esas kanıttır.

## 5. Güvenlik sınırı ve mevcut doğrulama durumu

- Canlı sunucuda geri yükleme, servis durdurma veya volume silme denemesi yapmayın.
- Özel `age` anahtarını, üretim ayarlarını ve şifresiz yedeği Git'e eklemeyin.
- Yalnız güvendiğiniz kaynaktan gelen arşivi geri yükleyin. Şifreleme, arşivi
  oluşturan kişinin kimliğini kanıtlamaz; veritabanı dökümleri çalıştırılabilir işlemler içerir.
- Gerçek sonuçlar ve ortam sınırları `docs/verification/issue-23-backup-restore.md`
  altında kaydedilir. Yerel test başarısı üretimde geri yükleme yapıldığı anlamına gelmez.
