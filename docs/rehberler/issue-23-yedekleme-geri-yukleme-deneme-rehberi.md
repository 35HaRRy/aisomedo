# Manuel şifreli yedekleme ve geri yükleme: durum ve deneme rehberi (#23)

## 1. Şu ana kadar ne değişti?

**Henüz yedekleme/geri yükleme özelliği uygulanmadı.** Bu aşamada tasarım belgesi
ve uygulama planı hazırlandı. Tasarım kullanıcı tarafından onaylandı; planın
incelenmesi ve uygulama yönteminin seçilmesi bekleniyor.

| Dosya | İçerik |
| --- | --- |
| `docs/superpowers/specs/2026-10-14-manual-encrypted-backup-restore-design.md` | Onaylanan kapsam, şifreleme, güvenlik, bakım kesintisi ve kurtarma kuralları |
| `docs/superpowers/plans/2026-10-14-manual-encrypted-backup-restore.md` | Kodlama görevleri, testler, CI ve doğrulama adımları |
| Bu rehber | Mevcut belgeleri kontrol etme; uygulama tamamlandığında güvenli deneme yolu |

Tasarım belgesi `3a20eed` commit'inde eklendi. Bu commit yalnız dokümantasyon
değişikliğidir; çalışan uygulamaya özellik, ekran veya yedekleme komutu eklemez.

Planlanan özellik: PostgreSQL, üretim ayarları ve gerekli kimlik bilgileri,
geçerli sürüm paketi ve tüm medyanın tek `age` şifreli arşivde saklanması.
Yedekleme kısa bakım kesintisi gerektirir. Mevcut verinin geri yüklemeyle
değiştirilmesi açık onay ve önce şifreli güvenlik yedeği gerektirir.
Zamanlanmış yedek, uygulama ekranı veya otomatik buluta gönderim yoktur.

## 2. Şimdi deneyebileceğiniz kontroller — PowerShell

PowerShell'i proje kökünde açın. Aşağıdaki komutlar veri değiştirmez,
servis durdurmaz; Python veya SQL kodu içermez.

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
indirme veya geri yükleme düğmesi eklenmeyecek. Şu anda uygulamada bu çalışma
nedeniyle yeni davranış beklemeyin.

Belgeler GitHub'a gönderildikten sonra tarayıcıda ilgili dalın dosya listesinden
spec ve planı okuyabilirsiniz. Yerel commit'lerin GitHub'da görünmesi için ayrıca
gönderim gerekir; bu rehber gönderim veya dağıtım yaptırmaz.

## 4. Uygulama tamamlandıktan sonra kullanılacak güvenli deneme

**Bu bölüm gelecek deneme sırasıdır; şu anda uygulanmış veya çalıştırılmış değildir.**
İlgili test dosyaları eklenmeden bu komutları çalıştırmayın.

### 4.1. Sentetik güvenlik testleri

Kod tamamlandıktan sonra PowerShell'de:

```powershell
if (-not (Test-Path 'ops/tests/test_backup.py')) {
    throw 'Yedekleme testleri henüz uygulanmadı.'
}
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

Linux, Docker/Compose, `age` ve doğrulama imajları gereklidir. Windows'ta
PowerShell üzerinden WSL kullanılabilir; Docker Desktop WSL entegrasyonu ve
WSL içindeki test ortamı ayrıca hazırlanmalıdır. Tam kurulum adımları uygulama
tamamlandığında `docs/ops/backup.md` belgesinde yer alacaktır.

Mevcut proje kökü WSL tarafından erişilebiliyorsa, ön koşullar hazırlandıktan sonra:

```powershell
wsl -- env REQUIRE_BACKUP_INTEGRATION=1 uv run --project backend pytest ops/tests/test_backup_integration.py -v
if ($LASTEXITCODE -ne 0) { throw 'Linux kurtarma doğrulaması başarısız.' }
```

**Beklenen:** Gerekli ön koşullar yoksa test başarısız olur; sessizce atlanmaz.
Testler geçici Docker proje adları ve sahte kimlik bilgileriyle çalışır;
orijinal verileri geri getirir, yedekten sonra eklenen medya dosyalarını kaldırır
ve uygulama sağlığını kontrol eder. Üretim ortamını hedeflememelidir.

### 4.3. İsteğe bağlı tarayıcı/Android gözlemi

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
- Tasarım/plan hazırlanmış olması #23'ün tamamlandığı anlamına gelmez.
- Bu aşamada şifreli yedek ve geri yükleme testleri çalıştırılmadı; kod henüz yok.
- Uygulama sonrasında gerçek sonuçlar `docs/verification/issue-23-backup-restore.md`
  altında kaydedilecek; rehber de mevcut komutlarla güncellenecek.
