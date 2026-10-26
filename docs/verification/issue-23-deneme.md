# Issue #23 — Şifreli yedekleme ve geri yükleme denemesi

Bu rehber yalnızca #23 değişikliklerini, mevcut `ops/tests/test_backup.py` ve
`ops/tests/test_backup_integration.py` testleriyle denemek içindir. Spec veya plan
dosyası gerekmez.

Komutları **Windows PowerShell'de, depo kökünde** sırayla çalıştır. Bilgisayarda
yalnızca Docker Desktop'ın Linux containers modunda çalışması gerekir. Python,
şifreleme araçları, gerçek PostgreSQL ve uygulama servisleri konteynerlerde çalışır.
İlk çalıştırma paket ve imaj indirdiğinden internet ve birkaç GB boş alan gerekir.

## 1. Docker'ı kontrol et

```powershell
docker info --format '{{.OSType}}'
```

Beklenen çıktı: `linux`. Bağlantı hatası varsa önce Docker Desktop'ı başlat.

## 2. Ayrı test ortamını başlat

> **Güvenlik:** Aşağıdaki konteyner, içinde ayrı Docker daemon'ı çalıştırmak için
> `--privileged` kullanır. Bunu yalnızca güvendiğin yerel geliştirme ortamında çalıştır.
> Ana makinenin Docker socket'i paylaşılmaz ve dışarıya port açılmaz. Depo salt okunur
> bağlanır; mevcut uygulama konteynerleri ve volume'ları test hedefi değildir.

```powershell
docker run -d --privileged --name issue23-lab --env DOCKER_TLS_CERTDIR= --mount "type=bind,source=$($PWD.Path),target=/source,readonly" docker:28-dind
```

İsim zaten kullanılıyorsa mevcut konteyneri silmeden önce sana ait bir önceki
deneme olduğunu doğrula; temizleme adımı dosyanın sonunda.

```powershell
docker exec issue23-lab sh -ec 'for i in $(seq 1 60); do if docker info >/dev/null 2>&1; then exit 0; fi; sleep 2; done; exit 1'
docker exec issue23-lab docker compose version
```

İlk komut daemon'ın hazır olmasını bekler. Hata verirse ilerleme:

```powershell
docker logs issue23-lab
```

## 3. Araçları ve kaynak kodunu hazırla

Şifreleme araçları yalnızca konteynere kurulur; Windows PATH'inde bulunmaları gerekmez.

```powershell
docker exec issue23-lab sh -ec 'apk add --no-cache python3 py3-pip age; python3 -m venv /opt/check; /opt/check/bin/pip install pytest cryptography'
```

Kaynakları konteynerin Linux dosya sistemine kopyala. Böylece dosya izinleri,
kilitleme ve geçici geri yükleme dizinleri Windows dosya sisteminden etkilenmez.
Aşağıdaki komut çalışma ağacını kullanır; commit atmak gerekmez. Yerel env dosyaları,
medya/veritabanı dizinleri ve Firebase kimlik bilgileri kopyalanmaz.

```powershell
docker exec issue23-lab sh -ec 'mkdir -p /work; tar -C /source --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=node_modules --exclude=dist --exclude=.env --exclude=.env.* -cf - pyproject.toml uv.lock dojo-core backend worker web ops/backup.py ops/deploy.py ops/tests ops/docker-compose.prod.yml ops/docker-compose.dedicated.yml ops/docker-compose.existing-proxy.yml ops/docker-compose.monitoring.yml ops/gateway | tar -C /work -xf -'
```

Her komuttan sonra `$LASTEXITCODE` değerini kontrol edebilirsin. `0` dışında sonuç
varsa sonraki adıma geçme.

## 4. Hızlı kontrolleri çalıştır

```powershell
docker exec --workdir /work --env REQUIRE_BACKUP_INTEGRATION=1 issue23-lab /opt/check/bin/python -m pytest ops/tests/test_backup.py -v
```

Bu dosya arşiv doğrulama, yanlış anahtar/bozuk şifreli veri, dosya yolu ve izin
sınırları, güvenlik yedeği zorunluluğu ve hata/kesinti davranışlarını kontrol eder.
Docker işlemleri bu testlerde taklittir; gerçek servis denemesi bir sonraki adımdır.
Beklenen: tüm testler `PASSED`, `failed` veya `skipped` yok.

## 5. Gerçek servis imajlarını oluştur

Komutlar test konteynerinin **içindeki** Docker daemon'ına gider. Ana Docker
ortamındaki aynı adlı imajlar kullanılmaz veya değiştirilmez.

```powershell
docker exec --workdir /work issue23-lab docker build -t dojo-backend-verify:issue23 -f backend/Dockerfile .
docker exec --workdir /work issue23-lab docker build -t dojo-worker-verify:issue23 -f worker/Dockerfile .
docker exec --workdir /work issue23-lab docker build -t dojo-gateway-verify:issue23 -f ops/gateway/Dockerfile .
docker exec issue23-lab docker pull postgres:18
```

Her build başarılı bitmeden ilerleme. Bu adım ilk çalıştırmada uzun sürebilir.

## 6. Gerçek yedekleme ve geri yüklemeyi dene

```powershell
docker exec --workdir /work --env REQUIRE_BACKUP_INTEGRATION=1 --env VERIFY_IMAGE_TAG=issue23 issue23-lab /opt/check/bin/python -m pytest ops/tests/test_backup_integration.py -v
```

Beklenen: **4 test `PASSED`**, `failed` veya `skipped` yok. Zorunlu entegrasyon
bayrağı, eksik araç/imaj nedeniyle testlerin sessizce atlanmasını engeller.

| Test | Denenen davranış |
| --- | --- |
| `test_existing_installation_roundtrip[False]` | Veritabanı, config ve medyayı tek şifreli arşive alır; üçünü değiştirir; güvenlik yedeği alarak orijinal verileri geri getirir. İki worker'ın tekrar çalıştığını doğrular. |
| `test_existing_installation_roundtrip[True]` | Aynı akışa sentetik Firebase kimlik bilgileri ve CRLF config dosyası ekler; bunların da geri geldiğini doğrular. Gerçek Firebase hesabı gerekmez. |
| `test_fresh_root_roundtrip` | Test kurulumunu kaldırır; arşivi yeni bir kurulum dizinine geri yükler; veritabanı, config ve sürüm bilgisini kontrol eder. |
| `test_restore_failure_keeps_writers_stopped` | Gerçek veri değişiminden sonra kasıtlı hata üretir; güvenlik yedeğinin oluştuğunu ve backend/worker'ın durmuş kaldığını doğrular. Testin `PASSED` olması beklenir. |

Medya kontrolü ikili dosyanın birebir geri geldiğini, boş dizinin korunduğunu ve
yedekten sonra eklenen dosyanın kaldırıldığını da kapsar. Testler gerçek CLI
modülünün `backup()`/`restore()` fonksiyonlarını çağırır; elle üretim CLI kurulumu
yapmaz. Rastgele `verifybackup...` projeleri ve sentetik veriler kullanılır;
test sonunda bu projeler kendi volume'larıyla kaldırılır. Arşivler geçici test
dizinlerindedir; bu akış kalıcı veya sunucu dışına aktarılmış bir yedek üretmez.

## 7. Gerekirse tek senaryoyu tekrar çalıştır

Örneğin yalnızca yeni dizine geri yükleme:

```powershell
docker exec --workdir /work --env REQUIRE_BACKUP_INTEGRATION=1 --env VERIFY_IMAGE_TAG=issue23 issue23-lab /opt/check/bin/python -m pytest ops/tests/test_backup_integration.py -k test_fresh_root_roundtrip -vv --tb=short
```

Beklenen: `1 passed, 3 deselected`. Kod değiştirdiysen önce 3. adımdaki kaynak
kopyalama komutunu, ardından 5. adımdaki build komutlarını tekrar çalıştır.

## 8. Yalnızca bu denemeyi temizle

> Bu komut `issue23-lab` konteynerini ve ona ait anonim volume'ları siler; içindeki
> test imajları, veriler ve geçici arşivler kaybolur. Yalnızca bu rehberle
> oluşturduğun test konteyneri için kullan.

```powershell
docker rm -f -v issue23-lab
```

Genel `prune` veya mevcut uygulamaya yönelik `compose down` çalıştırma.
