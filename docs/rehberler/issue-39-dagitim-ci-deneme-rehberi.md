# Dağıtım, güvenli güncelleme ve CI: değişiklik özeti ve deneme rehberi (#39)

Bu rehber imzalı Android APK dağıtımını, otomatik kontrolleri ve güvenli sunucu
güncellemesini denemek içindir. Öncelik tarayıcı ve Android uygulamasıdır.
Ekrandan yapılamayan kontroller PowerShell komutlarıyla çalıştırılır; Python
veya SQL kodu yazmanız gerekmez. `uv` mevcut testleri çalıştırırken gerekli
yorumlayıcıyı kullanır; Python içermeyen bir çalışma ortamı vaat edilmez.

> **Yerel denemeyi canlı dağıtımdan ayırın.** Testlerde yalnız sentetik medya
> kullanın. Gerçek Instagram hesabıyla yayın başlatmayın. `main` dalına gönderim
> canlı dağıtımı, `android-v*` etiketi APK yayınını tetikleyebilir. Bunları yalnız
> açık yayın kararı ve operatör hazırlığı sonrasında yapın. Gerçek ortamda servis
> durdurma, volume silme veya yedek geri yükleme komutu bu rehberde yoktur.

## 1. Neler değişti?

| Değişiklik | Deneyebileceğiniz sonuç |
| --- | --- |
| Tam CI akışı | Android, backend/core/worker, web, tarayıcı, ops, API sözleşmesi ve gerçek FFmpeg kontrolleri |
| Tek birleşik kontrol | `required`, kendisine bağlı kontrollerden biri başarısız, iptal veya atlanmışsa başarısız olur |
| API uyumluluk kapısı | Eski istemcileri bozan sözleşme değişiklikleri ve üretilmiş istemci dosyası sapmaları reddedilir |
| İmzalı APK yayını | `android-v<versionName>` etiketinden `aisomedo.apk` ve SHA-256 dosyası GitHub Releases'e eklenir |
| Güvensiz imzaya kapalı davranış | Eksik imza girdileri derlemeyi durdurur; debug sertifikalı APK yayınlanmaz |
| Değişmez sunucu sürümleri | Kontrolleri geçen `main` gönderimi üç GHCR imajı ve tam digest içeren dağıtım paketi üretir |
| Güvenli güncelleme | PostgreSQL yedeği, ayrı veritabanında migration provası ve sağlık kontrolü yapılır |
| Hata sonrası geri dönüş | Başarısız güncellemede önceki uygulama imajları geri getirilir; canlı veritabanı otomatik geri yüklenmez |
| Kalıcı veri koruması | Volume kimlikleri ve servis bağlantıları korunur; beklenmedik depolama değişikliği reddedilir |
| Kesinti temizliği | Yarım kalan migration başlatıcısı ve yalnız ona ait veritabanı oturumları temizlenir |
| Sıralı, doğrulanmış SSH dağıtımı | Çalışan dağıtım iptal edilmez; eski `main` işleri atlanır; sunucu anahtarı uyuşmazlığı reddedilir |

Yeni bir web/Android dağıtım yönetimi ekranı eklenmedi. Uygulamadaki gözlem,
kurulumun ve kayıtların güncelleme sonrasında çalışmaya devam etmesidir.
Snapshot, migration ve rollback ayrıntıları Actions/test çıktısından izlenir.

**Durum sınırı:** Kodun hazır olması GitHub kurallarının, gerçek imza anahtarının
veya VPS bağlantısının kurulmuş olduğu anlamına gelmez. Bu çalışma bunları
otomatik yapılandırmadı. Değişiklikler uzak depoya gönderilmediyse yeni workflow
henüz GitHub arayüzünde görünmez.

## 2. Hangi sırayla deneyebilirim?

1. Canlı ortama dokunmadan başlamak için §3'teki yerel kontrolleri çalıştırın.
2. Docker Desktop varsa §4'te gerçek yedek/migration/rollback senaryolarını deneyin.
3. Dal GitHub'a gönderildiyse §5'te CI işlerini tarayıcıdan inceleyin.
4. Hazır bir imzalı Release varsa §6'da APK'yı indirip Android'de açın.
5. Operatör kurulumu tamamlandıysa §7'de dağıtım sonrası uygulamayı kontrol edin.

§3–4 gerçek imza anahtarı, SSH erişimi veya GitHub secret gerektirmez.
§5–7'nin uzaktaki kabul kontrolleri için ilgili GitHub/VPS hazırlığı gerekir.

## 3. Hızlı yerel kontroller — PowerShell

### 3.1. Proje kökünü açın

PowerShell'i bu değişiklikleri içeren checkout/worktree kökünde açın. Örneğin
bu çalışma için `.worktrees/issue-39`. Kökü doğrulayın:

```powershell
Get-Location
Test-Path .github/workflows/ci.yml
Test-Path ops/tests/test_deploy.py
uv --version
```

İki dosya kontrolü `True` olmalı. `uv` kurulu olmalı ve paket indirmek için
internet erişimi bulunmalı. Komut bulunamıyorsa önce `uv` kurulumunu tamamlayın.

### 3.2. Dağıtım ve workflow güvenlik kontrollerini çalıştırın

```powershell
uv sync --all-packages --frozen
if ($LASTEXITCODE -ne 0) { throw 'Bağımlılıklar hazırlanamadı.' }

uv run --project backend pytest ops/tests/test_deploy.py ops/tests/test_workflows.py -v
if ($LASTEXITCODE -ne 0) { throw 'Dağıtım/workflow kontrolü başarısız.' }
```

**Beklenen:** Testler geçer. Yedek → prova → canlı migration → sağlık sırası,
hata/iptal sonrası geri dönüş, saklanan sürüm kaydı, depolama kimliği, geçersiz
adresler ve SSH girdileri kontrol edilir. Workflow testleri `required` için
başarı/hata/iptal/atlanma sonuçlarını da dener. Bunlar sentetik kontrollerdir;
GitHub'da birleşmenin gerçekten engellendiğini tek başına kanıtlamaz.

Windows'ta Linux kilit testi atlanır; symlink izni yoksa symlink testi de
atlanabilir. Bu iki kontrolün Windows'ta atlanması, Linux CI'de çalıştıklarının
yerine geçmez. Çıktıdaki `skipped` nedenlerini ayrıca okuyun.

### 3.3. Eski istemci uyumluluğunu kontrol edin

```powershell
uv run --project backend pytest backend/tests/test_openapi_compat.py backend/tests/test_contract.py -v
if ($LASTEXITCODE -ne 0) { throw 'API uyumluluk kontrolü başarısız.' }
```

**Beklenen:** Geçerli eklemeler kabul edilir; alan silme, istek kısıtını daraltma,
yanıt tipini bozma ve kimlik doğrulama tanımı değişiklikleri reddedilir.
Anlaşılamayan bazı şema birleşimleri güvenli tarafta kalıp reddedilir.
Bu kapı migration'ın iş anlamındaki uyumluluğunun insan incelemesi yerine geçmez.

### 3.4. Android imza korumasını gerçek derlemeyle deneyin — isteğe bağlı

Java 25, `JAVA_HOME`, Android SDK 35/build-tools 35.0.0 ve Android SDK yolunun
Gradle tarafından bulunması gerekir. Bu adım gerçek yayın anahtarı kullanmaz;
test kendi geçici sentetik anahtarını üretir.

```powershell
$OncekiImzaTesti = $env:RUN_ANDROID_SIGNING_TESTS
try {
    $env:RUN_ANDROID_SIGNING_TESTS = '1'
    uv run --project backend pytest ops/tests/test_android_signing.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Android imza kontrolü başarısız.' }
}
finally {
    if ($null -eq $OncekiImzaTesti) {
        Remove-Item Env:RUN_ANDROID_SIGNING_TESTS -ErrorAction SilentlyContinue
    } else {
        $env:RUN_ANDROID_SIGNING_TESTS = $OncekiImzaTesti
    }
}
```

**Beklenen:** İki test geçer: imza bilgisi yokken release reddedilir, sentetik
release imzası doğrulanır ve debug derlemesi release secret gerektirmez.
`skipped` sonucu bu denemenin yapılmadığı anlamına gelir; başarı saymayın.
Sentetik APK'yı gerçek dağıtım veya mevcut uygulamanın güncellemesi için kullanmayın.

## 4. Gerçek yedek, migration ve rollback — PowerShell + Docker Desktop

Bu bölüm isteğe bağlıdır; aynı senaryolar CI'nin `ops` işinde de çalışır.
Docker Desktop **Linux containers** modunda, çalışır durumda olmalı.
İlk imaj derlemeleri uzun sürebilir; yeterli disk/RAM ve internet gerekir.

> Yalnız kendi yerel/test Docker daemon'ınızda çalıştırın. Docker context'iniz
> üretim sunucusuna bağlı olmamalı. Testler `verifydeploy...` adlı geçici projeler
> oluşturup yalnız kendi kaynaklarını temizler; `dojo-prod` ve `ops/.env`
> kullanılmaz. Docker socket erişimi daemon üzerinde yönetici yetkisi verir;
> yalnız güvendiğiniz bu checkout ile çalışın.

### 4.1. Docker hedefini doğrulayın ve test imajlarını derleyin

```powershell
docker context show
docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker çalışmıyor.' }
```

Context'in yerel Docker Desktop olduğunu kendiniz doğrulayın; işletim sistemi
çıktısı `linux` olmalı. Uzak/üretim context varsa burada durun.

```powershell
docker build -t dojo-backend-verify:issue39 -f backend/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Backend test imajı hazırlanamadı.' }
docker build -t dojo-worker-verify:issue39 -f worker/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Worker test imajı hazırlanamadı.' }
docker build -t dojo-gateway-verify:issue39 -f ops/gateway/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw 'Gateway test imajı hazırlanamadı.' }
```

### 4.2. Linux test çalıştırıcısını başlatın

Windows'ta entegrasyon testini doğrudan çalıştırmak Linux gereksinimi nedeniyle
atlanabilir. Aşağıdaki geçici container bu sorunu çözer. Proje salt okunur
bağlanır; test ortamı ve önbellek container'ın geçici alanında tutulur.

```powershell
$Repo = (Get-Location).Path
$Runner = 'issue39-rehber-' + [guid]::NewGuid().ToString('N').Substring(0, 8)

docker create --name $Runner --workdir /workspace --mount "type=bind,source=$Repo,target=/workspace,readonly" --mount 'type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock' --env UV_PROJECT_ENVIRONMENT=/tmp/issue39-venv --env UV_CACHE_DIR=/tmp/uv-cache --env REQUIRE_DEPLOY_INTEGRATION=1 --env VERIFY_IMAGE_TAG=issue39 --entrypoint sleep docker:29-cli infinity
if ($LASTEXITCODE -ne 0) { throw 'Linux test çalıştırıcısı oluşturulamadı.' }

try {
    docker start $Runner
    if ($LASTEXITCODE -ne 0) { throw 'Test çalıştırıcısı başlamadı.' }
    docker exec $Runner apk add --no-cache python3 py3-pip ca-certificates
    if ($LASTEXITCODE -ne 0) { throw 'Test araçları yüklenemedi.' }
    docker exec $Runner pip install --break-system-packages uv
    if ($LASTEXITCODE -ne 0) { throw 'uv yüklenemedi.' }
    docker exec $Runner uv sync --all-packages --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Linux test bağımlılıkları hazırlanamadı.' }
    docker exec $Runner uv run --project backend pytest ops/tests/test_deploy_integration.py -v -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Gerçek dağıtım entegrasyonu başarısız.' }
}
finally {
    docker rm -f $Runner
}
```

Son komut yalnız bu blokta adı üretilmiş test çalıştırıcısını kaldırır; test
imajlarını silmez. Test zorla kesilirse kalan `verifydeploy...` kaynaklarını
inceleyin; geniş kapsamlı `docker system prune` veya volume silme kullanmayın.

### 4.3. Sonuçları okuyun

**Beklenen:** Sekiz test geçer, hiçbiri atlanmaz. Parametre adları şunları gösterir:

| Senaryo | Testin doğruladığı sonuç |
| --- | --- |
| `health` | Aday backend sağlıksız kalır; önceki uygulama imajı geri gelir |
| `preflight` | Kopya veritabanındaki migration provası başarısız olur; canlı migration başlamaz |
| `interruption` | Migration sırasında kesinti olur; başlatıcı ve ona ait DB oturumları temizlenir, açık işlem geri alınır |
| `none` | Başarılı sürüm geçişi kaydedilir |
| Proxy/monitoring kombinasyonları | İki proxy modu ve monitoring açık/kapalı Compose ayarları render edilir |

İlk dört senaryoda gerçek PostgreSQL dump'ı oluşturulur, ayrı veritabanına
okunabildiği doğrulanır; veritabanı kaydı ve medya dosyası korunur. Hata
senaryolarında önceki başarılı sürüm kaydı korunur. Saklanan dump tekrar okunur.

**Kanıt sınırı:** Bu yerel testte dış GHCR erişimi yerel imajlara eşlenir ve
kamusal HTTPS kontrolü yerine test sınırı kullanılır. Gerçek registry kimliği,
SSH, DNS ve TLS doğrulanmış sayılmaz. Rollback canlı DB'yi eski snapshot'a
döndürmez; yedek geri yükleme ayrı operatör kararıdır.

## 5. CI ve birleşme engeli — GitHub'ı tarayıcıdan kullanın

### 5.1. Kontrolleri inceleyin

1. GitHub'da depo → **Actions → ci** açın; bu değişiklikleri içeren koşuyu seçin.
2. `android`, `backend`, `web`, `ops`, `contract`, `ffmpeg` işlerini açın.
3. `ops` içinde **Verify real deployment rollback** adımını açın: §4'teki
   senaryoların geçtiğini doğrulayın.
4. `android` içinde imza koruması ve debug derleme/test/lint adımlarını inceleyin.
   Instrumentation APK'sı derlenir; burada cihaz üzerinde instrumentation
   testlerinin çalıştırıldığı iddia edilmez.
5. `web` içinde birim testleri, build ve tarayıcı testlerini inceleyin.
6. `contract` içinde sözleşme/istemci sapması ve geriye uyumluluk adımları geçmeli.
7. `ffmpeg` içinde gerçek medya fixture'ları atlanmadan çalışmalı.
8. En son `required` yeşil olmalı. Alt işlerden biri hata/iptal/atlanma sonucu
   verirse bu kontrol yeşil olmamalı.

PR veya `main` dışı dal koşusunda `publish`/`deploy` atlanması normaldir; bu
işler `required` bağımlılıkları değildir. Mevcut bazı diğer testlerin atlanması
mümkündür; bunu bütün testlerin çalıştığı şeklinde raporlamayın.

### 5.2. Birleşmenin gerçekten engellendiğini deneyin

Yönetici yetkisi gerekir. **Workflow dosyası tek başına birleşmeyi engellemez.**

1. **Settings → Rules → Rulesets** veya mevcut branch protection ekranını açın.
2. `main` için kontrol zorunluluğunu etkinleştirin; ilk hosted koşuda görünen
   birleşik `required` kontrolünü seçin (arayüzde `ci / required` görünebilir).
   Bypass yetkilerini sınırlayın; merge queue kullanılıyorsa onu da kapsayın.
3. Yeni workflow henüz `main` üzerinde yoksa önce onun kontrollü entegrasyonunu
   tamamlayın. Sonraki deneme yalnız hazırlanan korumalı dal üzerinde anlamlıdır.
4. Tarayıcıdan `main` üzerindeki `backend/openapi.json` dosyasını açıp kalemle
   düzenleyin. `"title": "AcceptanceIn"` değerini `"title": "DenemeAcceptanceIn"`
   yapın. **Yeni bir deneme dalına** kaydedin; doğrudan `main` üzerine kaydetmeyin.
5. Deneme dalından `main` hedefine PR açın. Bu kasıtlı üretilmiş-dosya sapmasıdır;
   `contract` ve ardından `required` başarısız olmalı. İmza/SSH secret gerekmez.
6. PR'de checks ayrıntılarını ve başarısız kontrol nedeniyle birleşme engelini
   görün. Bypass kullanmayın; bu PR'yi hiçbir zaman birleştirmeyin.
7. Deneme PR'sini kapatın. Gerçek değişikliklerin olduğu normal PR'de `required`
   başarılı olmalı; diğer repo kuralları da karşılanıyorsa birleşme açılır.

Başarısız PR yine de birleştirilebiliyorsa kural/hedef dal/kontrol adı veya bypass
izinleri yanlıştır. Yerel workflow testi bunu düzeltemez.

## 6. İmzalı APK — tarayıcı ve Android

### 6.1. Mevcut bir Release'i deneyin

1. GitHub → **Releases** açın; `android-v...` etiketli doğrulanmış yayını seçin.
2. Assets altında `aisomedo.apk` ve `aisomedo.apk.sha256` bulunmalı.
3. **Actions → android-release** koşusunda imzalı derleme, imza doğrulama ve
   yayın adımlarının geçtiğini görün. Başarısız koşuyu yayın kanıtı saymayın.
4. İki dosyayı bilgisayarda aynı klasöre indirin. PowerShell'de o klasöre geçip:

```powershell
$Gercek = (Get-FileHash .\aisomedo.apk -Algorithm SHA256).Hash.ToLowerInvariant()
$Beklenen = ((Get-Content .\aisomedo.apk.sha256 -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
if ($Gercek -ne $Beklenen) { throw 'APK sağlama toplamı uyuşmuyor; kurmayın.' }
'APK SHA-256 eşleşti.'
```

Hash eşleşmesi indirme bütünlüğünü gösterir; tek başına imza sahibinin kimliğini
kanıtlamaz. Android SDK kuruluysa release sertifikasını ayrıca inceleyebilirsiniz:

```powershell
# Android SDK'nız ANDROID_HOME ile tanımlıysa:
$ApkSigner = Join-Path $env:ANDROID_HOME 'build-tools\35.0.0\apksigner.bat'
& $ApkSigner verify --verbose --print-certs .\aisomedo.apk
if ($LASTEXITCODE -ne 0) { throw 'APK imzası doğrulanamadı.' }
```

Sertifika debug olmamalı; SHA-256 sertifika parmak izini operatörün güvenilir
kaydına karşılaştırın. Aynı kaynaktan indirilen checksum güvenilir kaydın yerini tutmaz.

5. Android 10/API 29 veya üstü deneme cihazında aynı Release'in APK'sını indirin.
   Gerekirse yalnız indirme için kullandığınız tarayıcı/dosya yöneticisine
   **Bu kaynaktan yüklemeye izin ver** izni verin; kurulumdan sonra kapatın.
6. APK'yı kurup açın. HTTPS deneme sunucusunu seçin, deneme koduyla eşleştirin.
   **Kontrol Paneli**, **Paket**, **Ayarlar** açılmalı. Ayrıntılı eşleştirme için
   [Android kabuk rehberi](issue-32-android-kabuk-deneme-rehberi.md) kullanılabilir.
7. Aynı release anahtarıyla imzalı, daha yüksek `versionCode` içeren sonraki APK
   varsa mevcut kurulumun üzerine yükleyin. Cihazı/eşleştirmeyi yeniden kontrol edin.

Debug veya farklı anahtarla imzalı kurulumun üstüne release yüklemek başarısız
olabilir; anahtarı değiştirmeyin. Gerekirse ayrı deneme cihazı kullanın.
Uygulamayı kaldırmak yerel eşleştirmeyi/verileri silebilir. Eski sürüm kodlu APK
normal güncelleme olarak yüklenmez. İkinci uygun APK yoksa güncelleme denemesi
yapılmış sayılmaz.

Özel depoda indirme GitHub oturumu ister. Uygulamadan anonim indirme için
operatörün erişilebilir HTTPS dağıtım adresi gerekir; depoyu otomatik public yapmayın.

### 6.2. Henüz Release yoksa — yalnız gerçek yayın kararıyla

Önce `android-release` environment'ı ve `ANDROID_KEYSTORE_BASE64`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`
secret'ları hazırlanmalı. Anahtarın şifreli çevrimdışı yedeği tutulmalı;
anahtarı veya base64 içeriğini Git'e/komut geçmişine koymayın.

1. Her yayın için `android/app/build.gradle.kts` içinde `versionCode` artırılmış,
   `versionName` seçilmiş ve bu değişiklik CI geçerek `main` üzerine alınmış olmalı.
2. Actions'ta ilgili `main` commit'inin kontrollerinin geçtiğini doğrulayın.
3. PowerShell'de aşağıdaki komutları yalnız o yayını gerçekten oluşturmak için
   çalıştırın. Etiket adı `versionName` ile aynı olmalı:

```powershell
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'main alınamadı.' }
$MainSha = git rev-parse origin/main
git show "${MainSha}:android/app/build.gradle.kts" | Select-String 'versionCode|versionName'
$Surum = Read-Host 'Doğruladığınız versionName (örnek: 0.1.1)'
$Etiket = "android-v$Surum"
git tag -a $Etiket $MainSha -m "Android $Surum"
if ($LASTEXITCODE -ne 0) { throw 'Etiket oluşturulamadı; mevcut etiketi değiştirmeyin.' }
git push origin $Etiket
if ($LASTEXITCODE -ne 0) { throw 'Etiket gönderilemedi.' }
```

4. **Actions → android-release** koşusunu ve sonra §6.1'i takip edin.

Eksik secret, debug anahtarı, yanlış sürüm veya `main` geçmişinde olmayan commit
yayını durdurmalı. Yarım kalmış draft varsa operatör yalnız ilgili draft'ı
incelemeli; yayınlanmış Release/etiketi zorla değiştirmeyin.

## 7. Otomatik dağıtım sonrası kontrol — tarayıcı/Android, gerekirse PowerShell

### 7.1. Ön koşulları kontrol edin

Bu bölüm operatörün hazırladığı ayrı kabul ortamında yapılmalı. Linux VPS,
Docker Compose, Python 3.12+, HTTPS/DNS, GHCR okuma erişimi ve sağlıklı kaydedilmiş
başlangıç sürümü gerekir. `production` environment'ında şu girdiler bulunmalı:

- Variables: `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`, `DEPLOY_ROOT`,
  `DEPLOY_MODE`, `DEPLOY_ORIGIN`, `DEPLOY_MONITORING`.
- Secrets: `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`.

Sunucu anahtarını bağımsız güvenilir kanaldan doğrulayın. Host-key kontrolünü
kapatmayın. Ayrıntılı hazırlık: [dağıtım runbook'u](../ops/deployment.md).
Hazırlık yoksa bu bölümü atlayıp eksik olarak kaydedin; sahte başarı raporlamayın.

### 7.2. Güncellemeden önce uygulama kayıtlarını not edin

1. Kabul ortamında tarayıcı ve Android'i eşleştirin.
2. Kontrol Paneli/Paket ekranındaki mevcut deneme paketini ve durumunu not edin.
3. Ayarlar/kurulumda mevcut sentetik logo, açıklama şablonu ve kapalı yayın planını
   kontrol edin. Hiç kayıt yoksa koruma denemesi için ayrı deneme ortamında bu
   kayıtları oluşturun; gerçek öğrenci medyası veya Instagram yayını kullanmayın.
4. Sadece okuma yapacağınız sonraki karşılaştırma için ekran görüntüsü alın;
   secret veya eşleştirme kodlarını görüntüye dahil etmeyin.

### 7.3. Onaylı `main` güncellemesini izleyin

1. Onaylanmış PR birleştirildiğinde **Actions → ci** içinde o `main` koşusunu açın.
   Sırf deneme için canlı `main` üzerine değişiklik göndermeyin.
2. `required` başarılı olduktan sonra `publish` başlamalı. Üç imaj yayımlanır;
   koşunun Artifacts alanında `release-<tam-commit-sha>` bulunmalı.
3. Artifaktı indirip `release.json`/`images.json` dosyalarını metin olarak açın.
   İmajlar `@sha256:...` ile sabitlenmiş olmalı; gerçek `.env`, APK imza anahtarı
   ve SSH secret içermemeli.
4. `deploy` işini açın. Sürüm eski bir `main` commit'iyse **Main advanced;
   leaving newer release in charge** mesajıyla aktarım atlanabilir; bu eski
   commit'in dağıtıldığı anlamına gelmez. En yeni uygun koşuyu izleyin.
5. Gerçek dağıtım işi geçmeli. Güncellemede kısa kesinti mümkündür;
   sıfır kesinti vaat edilmez.

### 7.4. Tarayıcı ve Android'de sonucu deneyin

1. Tarayıcıda kabul ortamının `https://ADRES/ready` yolunu açın: JSON
   `{"status":"ok"}` dönmeli; uygulamanın HTML giriş sayfası dönmemeli.
2. `https://ADRES/web-health.txt` açın: web sağlık dosyası HTTP 200 dönmeli.
3. Ana sayfayı açıp tam yenileyin; Kontrol Paneli/Paket/Ayarlar açılmalı.
4. Önceki paket, logo, açıklama ve kapalı planla karşılaştırın; kayıtlar korunmalı.
5. Android'i yeniden açıp **Yenile** yapın. Aynı sunucu ve iptal edilmemiş eşleştirme
   çalışmalı; paket/ayarlar tarayıcıyla tutarlı olmalı.

Android sürüm politikasını backend dağıtımı kendiliğinden artırmaz. Yeni APK'nın
güncelleme uyarısı için operatör ayrıca `ANDROID_CURRENT_VERSION_CODE` ve
`ANDROID_UPDATE_URL` değerlerini yayımlanan APK'ya göre ayarlamalıdır.

İsterseniz sağlık yanıtlarını PowerShell'den okuyun:

```powershell
$Origin = 'https://dojo-deneme.example.com' # Gerçek kabul ortamınızla değiştirin.
Invoke-RestMethod "$Origin/ready"
(Invoke-WebRequest "$Origin/web-health.txt" -UseBasicParsing).StatusCode
```

### 7.5. Snapshot ve sürüm kaydını okuyun — isteğe bağlı, salt okunur SSH

Uygulama snapshot listesini göstermez. SSH istemcisi ve operatörün doğruladığı
known_hosts kaydı varsa yalnız okuma için şu PowerShell komutlarını kullanın:

```powershell
$DeployHost = 'vps-deneme.example.com'
$DeployUser = 'deploy'
$DeployPort = 22
$DeployRoot = '/srv/aisomedo'
$Target = "$DeployUser@$DeployHost"
ssh -o StrictHostKeyChecking=yes -p $DeployPort $Target "cat '$DeployRoot/current.json'"
if ($LASTEXITCODE -ne 0) { throw 'Sürüm kaydı okunamadı.' }
ssh -o StrictHostKeyChecking=yes -p $DeployPort $Target "ls -lt '$DeployRoot/snapshots'"
if ($LASTEXITCODE -ne 0) { throw 'Snapshot listesi okunamadı.' }
```

`current.json` son doğrulanmış başarılı commit'i göstermeli; yeni dağıtımın
öncesine ait `.dump` dosyası bulunmalı. Snapshot içeriğini GitHub'a yüklemeyin.
Dosya varlığı tek başına geri yüklenebilirlik kanıtı değildir; gerçek okuma
denemesi §4'te ve CI entegrasyonunda yapılır.

### 7.6. Hatalı sağlık sonrası geri dönüşü nasıl doğrularım?

Güvenli, otomatik tekrar §4'tür. Gerçek SSH/TLS sınırında kontrollü hata denemesi
yalnız operatörün ayrı kabul ortamında, gözden geçirilmiş aday sürümle yapılmalı.
Bu rehber canlı ortamı bozacak bir hata enjeksiyonu komutu vermez.

Kontrollü denemede beklenenler:

- Aday sürüm sağlık doğrulaması geçmez; Actions dağıtım işi başarısız görünür.
  Başarılı rollback, başarısız dağıtım işini yeşile çevirmez.
- Önceki uygulama imajları tekrar sağlıklıdır; `current.json` önceki commit'te kalır.
- Tarayıcı/Android'de §7.4 tekrar çalışır, not edilen DB/medya kayıtları korunur.
- Dağıtım öncesi snapshot saklanır; canlı DB otomatik eski snapshot'a çevrilmez.
- Rollback de başarısızsa operatör müdahalesi gerekir; bunu düzelmiş saymayın.

## 8. Sonuçları kaydedin

- [ ] Yerel dağıtım/workflow ve API uyumluluk testleri geçti.
- [ ] Gerçek Docker senaryoları sekiz testle, atlanmadan geçti.
- [ ] Android sentetik imza/debug kontrolleri iki testle geçti veya araç eksikliği kaydedildi.
- [ ] Hosted `ci / required` başarılı koşusunun bağlantısı kaydedildi.
- [ ] Başarısız kontrolün birleşmeyi engellediği deneme PR'si kaydedildi ve kapatıldı.
- [ ] Gerçek imzalı Release, APK/hash, güvenilir sertifika kaydı ve Android kurulumu doğrulandı.
- [ ] Gerçek SSH dağıtımı, commit, snapshot ve uygulama kayıtlarının korunması doğrulandı.
- [ ] Ayrı kabul ortamındaki kontrollü başarısız sağlık/rollback kanıtı kaydedildi.

Eksik operatör hazırlığı nedeniyle yapılamayanları açıkça **yapılmadı** olarak
işaretleyin. Yerel testlerin geçmesi tek başına #39'un gerçek dağıtım kabulünün
tamamlandığını göstermez.

İlgili ayrıntılar: [APK yayın runbook'u](../ops/releases.md),
[dağıtım runbook'u](../ops/deployment.md),
[onaylı tasarım](../superpowers/specs/2026-10-06-distribution-deployment-ci-design.md).
