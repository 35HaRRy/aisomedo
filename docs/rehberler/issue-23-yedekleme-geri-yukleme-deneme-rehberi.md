# Issue #23 — PowerShell ve Docker ile yedekleme/geri yükleme denemesi

Yalnız #23 için yapılan değişiklikleri deneyin: veritabanı, yapılandırma ve
medyanın tek şifreli arşive alınması; bunların geri yüklenmesi; güvenlik yedeği,
bozuk arşiv ve kesinti kontrolleri. Spec/plan dosyası okumanız gerekmez.

**Windows PowerShell + yerel Docker Desktop, Linux containers modunda** yeterli.
WSL veya bilgisayarda kurulu şifreleme aracı gerekmez. Python/SQL kaynak kodu
yazmayacaksınız; gerekli test araçları container içinde çalışır.

> **Güvenlik:** Gerçek kurtarma testinin container'ına Docker socket'i bağlanır.
> Bu, Docker motorunu yönetme yetkisidir; güvenlik izolasyonu değildir. Yalnız
> kendi yerel geliştirme Docker'ınızda ve güvendiğiniz depo koduyla çalıştırın.
> Uzak/üretim Docker context'i kullanmayın. Kurumsal politika socket erişimini
> engelliyorsa güvenliği kapatmayın; yetkili test ortamı kullanın.

Tüm adımları **aynı PowerShell penceresinde**, sırayla çalıştırın. İlk imaj
hazırlama internet/disk alanı gerektirir ve yavaş bağlantıda uzun sürebilir.
Mevcut uygulama container'ları yeniden başlatılmaz. Testlerde gerçek Instagram
hesabı, Firebase projesi veya üretim verisi kullanılmaz.

## 1. Docker ve proje kökünü kontrol edin

```powershell
Set-Location 'C:\Users\35.HaRRy\Desktop\Projects\aisomedo'
$Repo = (Get-Location).Path
if (-not (Test-Path 'ops/tests/test_backup_integration.py')) {
    throw 'Proje kökünde değilsiniz veya issue #23 değişiklikleri yok.'
}
$Engine = docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop çalışmıyor veya erişim yok.' }
if ($Engine.Trim() -ne 'linux') { throw 'Linux containers moduna geçin.' }
$ContextName = docker context show
if ($LASTEXITCODE -ne 0) { throw 'Docker context okunamadı.' }
$Context = docker context inspect $ContextName | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Docker context bilgisi okunamadı.' }
if (-not $Context[0].Endpoints.docker.Host.StartsWith('npipe://')) {
    throw 'Bu Windows rehberi yalnız yerel Docker Desktop içindir; uzak motorda çalıştırmayın.'
}
```

**Beklenen:** Hata yok; `linux` motoru ve yerel named-pipe bağlantısı.

## 2. Test imajlarını hazırlayın

Dockerfile metni yalnız container hazırlığını tarif eder; Python/SQL kaynak
kodu içermez. Geçici dosya oluşturulur, gerekli iki test bağımlılığı içeride kurulur.

```powershell
$Setup = Join-Path $env:TEMP ('aisomedo-issue23-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Setup -ErrorAction Stop | Out-Null
$Dockerfile = Join-Path $Setup 'Dockerfile'
$Runner = 'dojo-issue23-guide-tests:local'
@'
FROM docker:cli AS docker
FROM python:3.12.14-slim
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins
RUN apt-get update && apt-get install -y --no-install-recommends age \
    && rm -rf /var/lib/apt/lists/* \
    && pip install pytest==9.1.1 cryptography==50.0.0
WORKDIR /work
'@ | Set-Content -LiteralPath $Dockerfile -Encoding ASCII
docker build -t $Runner -f $Dockerfile $Setup
if ($LASTEXITCODE -ne 0) { throw 'Test çalıştırıcı imajı hazırlanamadı.' }
docker build -t dojo-backend-verify:issue23 -f backend/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Backend test imajı hazırlanamadı.' }
docker build -t dojo-worker-verify:issue23 -f worker/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Worker test imajı hazırlanamadı.' }
docker build -t dojo-gateway-verify:issue23 -f ops/gateway/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Gateway test imajı hazırlanamadı.' }
docker pull postgres:18
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL test imajı indirilemedi.' }
```

**Beklenen:** Tüm build/pull işlemleri başarılı. Yalnız test imajları hazırlanır.
Sonraki denemelerde aynı kaynaklar için Docker cache kullanılabilir.

## 3. Hızlı güvenlik testlerini çalıştırın

Depo salt okunur bağlanır. Bu adım Docker socket'ini paylaşmaz.

```powershell
docker run --rm --mount "type=bind,src=$Repo,dst=/work,readonly" `
    -e REQUIRE_BACKUP_INTEGRATION=1 $Runner `
    pytest -p no:cacheprovider ops/tests/test_backup.py -v
if ($LASTEXITCODE -ne 0) { throw 'Issue #23 güvenlik testleri başarısız.' }
```

**Beklenen: 61 passed**, `failed`/`skipped` yok. Yanlış anahtar, değiştirilmiş
ve kesilmiş arşiv, güvensiz dosya yolları, yanlış root, mevcut özel adlı volume,
CRLF/BOM ayarları, güvenlik yedeği zorunluluğu ve kesinti davranışı denenir.

Gerçek veritabanı kurtarması için sonraki adımı da yapın.

## 4. Gerçek şifreli yedek ve geri yükleme

Önce yalnız bu denemeye ait rastgele bir veri volume'ü oluşturun:

```powershell
$TestVolume = 'issue23-guide-data-' + [guid]::NewGuid().ToString('N')
docker volume create --label 'aisomedo.issue23.guide=1' $TestVolume
if ($LASTEXITCODE -ne 0) { throw 'Geçici test veri alanı oluşturulamadı.' }
$VolumeInfo = docker volume inspect $TestVolume | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Test volume bilgisi okunamadı.' }
$DataPath = $VolumeInfo[0].Mountpoint
```

`$DataPath` Docker motorunun Linux yoludur, Windows klasörü değildir. İçeriği
test container'ına **aynı yolda** bağlayın: Compose'un kimlik dosyası gibi
bind-mount kaynaklarını Docker motorunun da bulabilmesi için bu gereklidir.

```powershell
docker run --rm --mount "type=bind,src=$Repo,dst=/work,readonly" `
    --mount 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock' `
    --mount "type=volume,src=$TestVolume,dst=$DataPath" `
    -e REQUIRE_BACKUP_INTEGRATION=1 -e VERIFY_IMAGE_TAG=issue23 $Runner `
    pytest -p no:cacheprovider ops/tests/test_backup_integration.py -v `
    --basetemp "$DataPath/integration"
if ($LASTEXITCODE -ne 0) { throw 'Gerçek kurtarma testi başarısız; çıktıyı inceleyin.' }
```

**Beklenen: 4 passed**, `failed`/`skipped` yok:

| Senaryo | Gerçekten yapılan kontrol |
| --- | --- |
| Mevcut kurulum | DB, ayar ve medya yedeklenir; değiştirilir; güvenlik yedeği alınıp orijinal değerler geri getirilir; iki worker korunur |
| Firebase/CRLF | Sentetik kimlik dosyası ve CRLF ayarları da byte düzeyinde geri gelir; yalnız kimlik dosyasının host yolu değiştirilir |
| Boş hedef | Testin eski kaynakları kaldırılır; arşiv yeni kurulum dizininde açılır; DB, config ve medya geri yüklenir |
| Değiştirme sonrası hata | Gerçek veri değiştirmeden sonra hata oluşturulur; backend/worker durmuş, şifreli güvenlik yedeği mevcut kalır |

İkili medya birebir karşılaştırılır; boş dizin korunur ve yedekten sonra eklenen
dosya kaldırılır. Testler rastgele `verifybackup...` projeleri ve sahte kimlik
bilgileri kullanır; kendi uygulama kaynaklarını sonunda temizler. `dojo-prod`
hedeflenmez. Arşivler ve test anahtarları §5'e kadar `$TestVolume` içinde kalır.

### 4.1. Yedek dosyalarını yerinde açıp inceleyin

§5'te temizlemeden önce arşivleri listeleyip mevcut kurulum senaryosunun
yedeğini seçin. Volume Windows Gezgini'nde açılmaz; içeriğine container üzerinden
bakılır. Kaynak volume salt okunur bağlanır, şifreli dosyalar değiştirilmez.

```powershell
$Archives = @(docker run --rm --mount "type=volume,src=$TestVolume,dst=$DataPath,readonly" `
    $Runner find "$DataPath/integration" -type f -name 'backup.age')
if ($LASTEXITCODE -ne 0) { throw 'Test arşivleri listelenemedi.' }
$Archives
$Archive = $Archives | Where-Object { $_ -match '/test_existing_installation_' } | Select-Object -First 1
if (-not $Archive) { throw 'Mevcut kurulum senaryosunun yedeği bulunamadı.' }
$CasePath = $Archive.Substring(0, $Archive.LastIndexOf('/'))
$CasePath
```

Seçilen klasördeki `identity.txt`, yalnız o testin anahtarıdır. Aşağıdaki komut
`backup.age` ve `safety.age` dosyalarını bu anahtarla açar. Açık içerik yalnız
geçici inceleme container'ında tutulur; container kapanınca kaldırılır. DB dump'ını
okumak için başlatılan PostgreSQL aracı ağsızdır, veritabanı sunucusu başlatmaz.
Docker socket yetkisi için baştaki güvenlik uyarısı burada da geçerlidir.

```powershell
$Inspect = @'
set -eu
umask 077
for name in backup safety; do
    printf '\n=== %s.age ===\n' "$name"
    age --decrypt --identity "$1/identity.txt" --output "/tmp/$name.tar" "$1/$name.age"
    tar -tf "/tmp/$name.tar"
    printf '\n--- manifest ---\n'
    tar -xOf "/tmp/$name.tar" manifest.json
    printf '\n--- test ayari ---\n'
    tar -xOf "/tmp/$name.tar" config/production.env | grep '^SIGNED_URL_SECRET='
    printf '\n--- medya baytlari ---\n'
    tar -xOf "/tmp/$name.tar" media/branding/nested/binary | od -An -tx1
    tar -xOf "/tmp/$name.tar" database.dump > /tmp/database.dump
    printf '\n--- DB test kaydi (SQL dokumu; calistirilmaz) ---\n'
    docker run --rm -i --network none --read-only postgres:18 \
        pg_restore --data-only --table=recovery_sentinel --file=- < /tmp/database.dump
done
'@
# Windows PowerShell'in iç tırnakları değiştirmemesi için komut metnini taşıyın.
# Base64 burada şifreleme değildir; yalnız komut metni taşınır, yedek/anahtar değil.
$InspectBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Inspect.Replace("`r", '')))
docker run --rm --mount "type=volume,src=$TestVolume,dst=$DataPath,readonly" `
    --mount 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock' `
    $Runner sh -ec 'echo $1 | base64 -d | sh -es -- $2' inspect $InspectBase64 $CasePath
if ($LASTEXITCODE -ne 0) { throw 'Arşiv içeriği incelenemedi; sonraki adıma geçmeyin.' }
```

**Beklenen:**

| İçerik | `backup.age` | `safety.age` |
| --- | --- | --- |
| DB SQL dökümündeki test satırı | `original-database` | `changed-database` |
| `SIGNED_URL_SECRET` | `original-setting` | `changed-setting` |
| `media/branding/nested/binary` (hex) | `00 ff 6f 72 69 67 69 6e 61 6c` | `63 68 61 6e 67 65 64` |
| Dosya listesinde `media/extra` | Yok | Var |

İki arşivde de `database.dump`, `config/production.env`, `current.json`,
`release/`, `manifest.json` ve `media/branding/empty` bulunmalı. Manifestte DB
tablo/satır sayıları, şema sürümü, dosya boyutları ve SHA-256 değerleri görülebilir.
Güvenlik yedeğinin farklı olması beklenir: geri yüklemeden **hemen önceki,
değiştirilmiş** durumu korur; asıl yedeğin kopyası değildir.

> Bunlar sentetik test verileridir. Bu görüntüleme komutlarını gerçek yedeklere
> uygulamak sırları ve kişisel verileri terminale/loglara çıkarabilir. Gerçek
> anahtarları veya açık arşiv içeriğini paylaşmayın. Başarılı listeleme tek başına
> geri yükleme kanıtı değildir; canlı kontrol aşağıdadır.

### 4.2. Geri yüklemenin sonucunu çalışan ortamda görün

Normal testler sonunda uygulama container'ları ve uygulama volume'leri temizlenir.
Bu yüzden §4.1'de kalan dosyalar canlı DB'yi göstermez. Aşağıdaki **isteğe bağlı**
tekrar, tek senaryoyu debugger ile durdurur; uygulama açıkken salt okunur sorgular
çalıştırabilirsiniz. Kaynak kodu değiştirme veya yeni Python/SQL dosyası yazma
gerekmez. Aynı PowerShell penceresinde çalıştırın:

```powershell
docker run --rm -it --mount "type=bind,src=$Repo,dst=/work,readonly" `
    --mount 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock' `
    --mount "type=volume,src=$TestVolume,dst=$DataPath" `
    -e REQUIRE_BACKUP_INTEGRATION=1 -e VERIFY_IMAGE_TAG=issue23 $Runner `
    pytest -p no:cacheprovider -s --trace `
    'ops/tests/test_backup_integration.py::test_existing_installation_roundtrip[False]' `
    --basetemp "$DataPath/interactive"
if ($LASTEXITCODE -ne 0) { throw 'Etkileşimli kurtarma kontrolü tamamlanamadı.' }
```

`--basetemp` her çalıştırmada yalnız `$DataPath/interactive` içeriğini yeniden
oluşturur; §4'teki `integration` arşivlerine dokunmaz. `(Pdb)` istemi geldiğinde
komutları **PowerShell'e değil bu isteme**, satır satır girin:

```text
b /work/ops/tests/test_backup_integration.py:137
b /work/ops/tests/test_backup_integration.py:140
c
```

Bu satırlar mevcut testte sırasıyla `cli.restore(...)` çağrısı ve
`value = cli.query(restored, ...)` satırıdır. Test dosyası değişmişse önce satır
numaralarını buna göre güncelleyin. İlk duruşta geri yükleme henüz başlamamıştır:

```text
p cli.query(info, "SELECT value FROM recovery_sentinel").decode().strip()
p 'SIGNED_URL_SECRET=changed-setting' in (root / 'config/production.env').read_text()
p original(['docker', 'exec', info['containers']['backend'][0], 'cat', '/media/branding/nested/binary'])
c
```

**Beklenen:** Sırayla `'changed-database'`, `True`, `b'changed'`.
`c` geri yüklemeyi çalıştırır ve ikinci breakpoint'te durur. Şimdi çalışan
veritabanını, diskteki ayarı ve uygulamanın kullandığı medya volume'ünü okuyun:

```text
p cli.query(restored, "SELECT value FROM recovery_sentinel").decode().strip()
p 'SIGNED_URL_SECRET=original-setting' in (root / 'config/production.env').read_text()
p restored['worker_count']
p original(['docker', 'exec', restored['containers']['backend'][0], 'cat', '/media/branding/nested/binary'])
p json.loads(cli.volume_helper(restored, cli.MEDIA_INVENTORY))['media/branding/empty']
p 'media/extra' in json.loads(cli.volume_helper(restored, cli.MEDIA_INVENTORY))
p original(restored['command'] + ['ps']).decode()
```

**Beklenen:** Sırayla `'original-database'`, `True`, `2`, `b'\x00\xfforiginal'`,
`{'type': 'directory'}`, `False`; son çıktıda DB/backend/gateway ve iki worker
çalışıyor olmalı. `ps` çıktısı `p` nedeniyle tırnaklı ve `\n` içerebilir.
Bu, yalnız arşivdeki metni değil, geri yüklenen gerçek veriyi okur. Başarılı
`restore()` ayrıca DB metadata/medya checksum kontrollerini ve servis sağlık
kontrollerini tamamlamış olmalıdır.

İnceleme bitince `(Pdb)` istemine **`c`** yazın. Kalan test assertion'ları da
çalışmalı, sonuç **1 passed** olmalı ve test kendi uygulama kaynaklarını
temizlemelidir. Terminali/container'ı zorla kapatmayın; temizleme yarıda kalabilir.
§4.1'i bu tekrarın arşivleriyle yapmak isterseniz `$CasePath` değerini `(Pdb)`
istemindeki `p str(tmp_path)` çıktısına ayarlayın; sonra §5'e geçin.

## 5. Yalnız bu denemenin artıklarını temizleyin

```powershell
$VolumeInfo = docker volume inspect $TestVolume | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $VolumeInfo[0].Labels.'aisomedo.issue23.guide' -ne '1') {
    throw 'Test volume etiketi doğrulanamadı; silme yapılmadı.'
}
docker volume rm $TestVolume
if ($LASTEXITCODE -ne 0) { throw 'Test volume kullanımda; zorla silmeyin.' }
Remove-Item -LiteralPath $Dockerfile -ErrorAction Stop
Remove-Item -LiteralPath $Setup -ErrorAction Stop
```

Yalnız kaydettiğiniz rastgele test volume'ü ve tek geçici Dockerfile silinir;
test imajları cache için kalır. `docker system prune`, genel volume silme veya
canlı ortamda `docker compose down -v` çalıştırmayın.

## Tarayıcı/Android hakkında

Yedekleme ekranı eklenmedi. Test ortamı sonunda kapandığından ona uygulamadan
bağlanmanız beklenmez. Ayrıca açık tutulmuş, üretim dışı bir kurulumunuz varsa
restore sonrasında tarayıcıyı yenileyerek veya Android'de çevrimiçi eşitleyerek
eski paket/medya/ayarları gözlemleyebilirsiniz. Şifrelemeyi ekran değil, yukarıdaki
gerçek kurtarma testleri doğrular. Gerçek Instagram hesabı bağlamayın.

GitHub'da bu değişiklikleri içeren bir CI koşusu varsa tarayıcıdan **Actions →
ci → ops → Verify real encrypted recovery** adımındaki dört sonucu da okuyabilirsiniz.
Bu rehber gönderim, yayın veya üretim geri yüklemesi yapmaz.

## Hata alırsanız

- Docker erişimi/motoru: Docker Desktop ve Linux containers modunu kontrol edin.
- Socket mount engeli: kurumsal politika izin vermeyebilir; güvenliği kapatmayın.
- İmaj bulunamıyor: §2'de üç `dojo-*-verify:issue23` imajını hazırlayın.
- Kimlik dosyası/bind-mount hatası: `$DataPath` ve aynı-yol mount'unu değiştirmeyin.
- Disk yetersiz: Docker Desktop disk alanını kontrol edin; üretim volume'lerini silmeyin.
- `skipped` veya `failed`: çıktı gerçek kurtarmanın doğrulandığı anlamına gelmez.

## Doğrulama

İlk sürümdeki 7 PowerShell bloğu aynı bilgisayarda sırayla çalıştırıldı: imaj hazırlama
başarılı, **61 güvenlik + 4 gerçek kurtarma testi geçti**, atlanan test yok.
Şifreli arşivler listelendi ve yalnız denemenin veri volume'ü/geçici Dockerfile'ı
temizlendi. Host üzerinde WSL veya şifreleme CLI'si çalıştırılmadı.

§4.1 ve §4.2 sonradan eklenen sağlama adımlarıdır; yukarıdaki ilk sürümün
çalıştırma kaydı bu ek komutların da denendiği anlamına gelmez.
