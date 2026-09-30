# #22 Üretim İzleme — Değişiklik Özeti ve Deneme Rehberi

Bu belge, issue #22 kapsamında eklenen izleme özelliklerini özetler ve her birini
**kendi elinizle deneyebileceğiniz** adımları verir.

Üretim yığını kurma ve günlük yorumlama ayrıntıları için operatör rehberine bakın:
[`production-monitoring.md`](production-monitoring.md).
Android'in alacağı mesaj biçimi için:
[`../contracts/operational-alerts.md`](../contracts/operational-alerts.md).

## 1. Ne değişti, özet

| # | Özellik | Nerede | Ne yapıyor |
|---|---|---|---|
| 1 | Backend hazır denetimi | `backend/src/backend/readiness.py`, `routes/health.py` | `/health` ucuz canlılık kontrolü olarak kaldı; yeni `/ready` veritabanını **sınırlı süreyle** yoklar |
| 2 | Worker sağlık kaydı | `worker/src/worker/health.py` | Worker ilerlemesini bir dosyaya yazar; boş (120sn) ve meşgul (3600sn) süre sınırları vardır |
| 3 | Web sağlık varlığı | `web/public/web-health.txt`, `ops/gateway/Caddyfile` | Derlenmiş web varlığını, API'den bağımsız olarak doğrular |
| 4 | Yapılandırılmış günlükler | `dojo-core/src/dojo/observability.py` | Her satır tek bir JSON; izinli alan listesi, sır/tok redaksiyonu |
| 5 | Disk olayı durumu | `dojo-core/src/dojo/monitoring_models.py`, migration `0015` | %15 altı olay açar, %20 üstü kurtarır; kalıcı, çift uyarı üretmez |
| 6 | Kalıcı uyarı teslimatı | `dojo-core/src/dojo/monitoring.py`, `adapters/fcm.py` | Kilitli kiralama, 60sn→3600sn geri çekilme, en az bir kez teslim |
| 7 | Arka plan toplayıcı | `worker/src/worker/monitoring.py` | 60sn'de disk örneklemesi; uzun render onu **baskılamaz** |
| 8 | Dağıtım bağlantısı | `ops/docker-compose.prod.yml`, `docker-compose.monitoring.yml` | Sağlık denetimleri, 3×10MiB günlük, salt okunur FCM sırrı |
| 9 | Doğrulanabilir dağıtım | `ops/verify-prod.sh`, `ops/verify-monitoring.sh` | Gerçek HTTP davranışını iddia eden iddiaları gerçekten çalıştırır |

**#22 hâlâ açık.** Android'e gerçek push ulaştırılması ve barındırılan HTTPS
denetiminin kurulması henüz doğrulanmadı — cihaz, VPS ve denetim hesabı yok.
Kanıt kaydı: [`../verification/issue-22-production-monitoring.md`](../verification/issue-22-production-monitoring.md).

---

## 2. Denemeler için hazırlık

Denemeler **üretim yığını** üzerinde yapılır, çünkü sağlık denetimleri ve
`/web-health.txt` yalnızca üretim yapılandırmasında etkindir. Geliştirme
yığınındaki 8000/5434 portları bu uçları sunmaz.

Önce kısayolları tanımlayın (aşağıdaki blok), sonra yığını kurun:

```powershell
P up -d --build
```

Bu, `ops/.env` içindeki `GATEWAY_HTTP_PORT` değerini kullanır; varsayılan
`9080`. Farklı bir port ayarladıysanız aşağıdaki adresi ona göre değiştirin.

Sonra tarayıcıda şu adrese gidin:

```
http://127.0.0.1:9080/
```

Burası, mevcut-vekil modunda **yalnızca loopback'e açılan** üretim gateway'idir
(ayrı alan adı modu §3.4'te anlatılıyor). Sağlıklıysa arayüz açılır; açılmazsa
`P ps` ile servislerin ayakta olduğunu kontrol edin.

> **Ön koşul: yığın bu dalın imajlarıyla kurulmuş olmalı.** `--build`
> eklemezseniz eski bir imaj çalışır ve §3.1'deki tablo yanlış görünür:
> `/ready` ve `/web-health.txt` adresleri uygulamanın HTML'ini döndürür,
> çünkü eski gateway bu yolları bilmez ve SPA yedeğine düşer. Doğrulamak için:
> ```powershell
> P exec -T gateway cat /etc/caddy/Caddyfile
> ```
> Bu çıktıda `/ready` ve `web-health.txt` geçmiyorsa `P up -d --build` ile
> yeniden kurun. Bu, §3.1'in amacı olan "yol yoksa 404, SPA değil" kuralının
> kendisidir.

### Kısayollar

Aşağıdaki üç fonksiyon **sır içermez**; yalnızca `ops/.env` dosyasını okurlar.
Rehberin geri kalanındaki tüm denemeler bunları kullanır. Terminale bir kez
yapıştırıp çalıştırın:

```powershell
# Üretim yığını, mevcut-vekil (loopback) modu — §3.1-§3.3, §4.1-§4.6
function P { docker compose --env-file ops/.env -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml @args }

# Üretim yığını, ayrı-alan-adı modu — §3.4
function P2 { docker compose --env-file ops/.env -f ops/docker-compose.prod.yml -f ops/docker-compose.dedicated.yml @args }

# Üretim yığını + izleme override'i (uyarılar) — §3.5
function P3 { docker compose --env-file ops/.env -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml -f ops/docker-compose.monitoring.yml @args }
```

`P3`'ü kullanmadan önce FCM kimlik bilgisi adımlarını tamamlayın
(operatör rehberi, §2): `FCM_PROJECT_ID` boşsa compose render hatası verir ve
hiçbir container ayağa kalkmaz.

---

## 3. Tarayıcıda denenebilenler

### 3.1 Sağlık uçları — dört adres, dört farklı yargı

Bu dört adresi **ayrı ayrı** açın. Farkları görmek denemenin kendisidir.

| Adres | Beklenen | Ne kanıtlar |
|---|---|---|
| `http://127.0.0.1:9080/health` | `{"status":"ok"}` | Backend ayakta. Veritabanı **kontrol edilmez** |
| `http://127.0.0.1:9080/ready` | `{"status":"ok"}` | Backend **ve veritabanı** birlikte ayakta |
| `http://127.0.0.1:9080/web-health.txt` | `dojo-web-ok` | Derlenmiş web varlığı ayakta — **API'den bağımsız** |
| `http://127.0.0.1:9080/bilinmeyen-yol` | Uygulama ekranı | SPA yedekleme çalışıyor (bu bir sağlık cevabı değildir) |

Son satır önemli: bilinmeyen bir yol uygulamayı gösterir, 404 değil. Bu yüzden
`/web-health.txt` **gerçek bir varlıktan** gelmelidir; SPA yedeği sağlıklı
sayılmaz. Bunu §3.3'te bozarak kanıtlarsınız.

### 3.2 Web sağlığı, API kapalıyken hâlâ cevap vermeli

Bu, en değerli tarayıcı denemesidir: iki katmanın **gerçekten bağımsız**
olduğunu gösterir.

1. Yığın ayaktayken `http://127.0.0.1:9080/web-health.txt` → `dojo-web-ok`
2. Yalnızca backend'i durdurun:
   ```powershell
   P stop backend
   ```
3. `http://127.0.0.1:9080/web-health.txt` → **hâlâ** `dojo-web-ok`
4. `http://127.0.0.1:9080/ready` → **hata** (502/503; canlılık değil, hazır değil)
5. `http://127.0.0.1:9080/health` → **yine hata** — bu beklenir, `/health` de
   backend'de yaşar
6. Backend'i geri getirin ve `/ready`'nin **yeniden yeşile dönmesini** görün:
   ```powershell
   P start backend
   ```

Beklenen: web varlığı API'den bağımsız, `/ready` toparlanır.

Bu bölüm, dal üzerinde şu şekilde doğrulanmıştır: backend durdurulduğunda
`/health` → 502, `/ready` → 502, `/web-health.txt` → hâlâ `dojo-web-ok`; backend
geri getirildiğinde `/ready` → `{"status":"ok"}`.

### 3.3 Sağlık varlığı kaybolursa 404, SPA değil

Gateway'in SPA yedeklemesi yanlışlıkla sağlık kontrolünü "geçirir" diye
kötüye kullanılmasını engeller:

```powershell
P exec -T gateway sh -c 'rm -f /srv/web-health.txt'
```

Sonra `http://127.0.0.1:9080/web-health.txt` adresini **yenileyin**. Beklenen:
404. Uygulama ekranı gelirse bu bir hata — SPA yedeği devreye girmiş demektir.

Dal üzerinde doğrulanmıştır: varlık silindikten sonra `/web-health.txt` → 404
(HTML değil), sonra `P up -d gateway` ile varlık geri gelir ve adres yine
`dojo-web-ok` döner.

Varlığı geri koyun (container yeniden başlayınca kendiliğinden döner):
```powershell
P up -d gateway
```

### 3.4 Ayrı alan adı modu (isteğe bağlı)

`ops/.env` içinde `DOMAIN` ve DNS hazırsa ayrı alan adı modunu da
deneyebilirsiniz:

```powershell
P2 config > $null; if ($?) { "render OK" } else { "render HATASI" }
P2 up -d
```

Bu modda Caddy `:80`'i TLS'e yönlendirir; tarayıcıda
`http://<DOMAIN>/web-health.txt` yazdığınızda HTTPS'e atlanmanız **normaldir**.
`/web-health.txt` yine de `dojo-web-ok` vermelidir. İnternete açık alan adı
kullanıyorsanız, bu adresi barındırılan denetim servisinize verin (§5).

### 3.5 Disk uyarısını tetiklemek

Bu deneme **eşiği değiştirerek** uyarıyı üretir; diskinizi doldurmanız gerekmez.
Uyarının kendisini **telefonda** görmek zorunlu değildir — sunucu tarafındaki
oluşumunu §4.2'deki komutla doğrulayabilirsiniz. Telefonla denemek için §6'daki
ön koşullar gerekir ve bunlar henüz sağlanmıyor.

1. `ops/.env` içine ekleyin:
   ```
   MONITORING_ENABLED=true
   MONITORING_DISK_LOW_PERCENT=99
   MONITORING_DISK_RECOVERY_PERCENT=100
   ```
2. Yığını izleme override'i ile yeniden kurun:
   ```powershell
   P3 up -d
   ```
   > `FCM_PROJECT_ID` ve `FCM_CREDENTIALS_FILE` **zorunludur**; ayarlamadan bu
   > komut render bile edilemez (bilerek böyle — projesiz FCM her gönderimi
   > düşürürdü).
3. 60 saniye sonra §4.2'deki komutla uyarının **oluştuğunu** doğrulayın:
   ```powershell
   P logs --tail 200 worker | Select-String "monitoring\."
   ```
4. Eşiği geri alın (`15` / `20`) ve yeniden başlatın; bu kez bir **kurtarma**
   uyarısı beklenir. Bu, çift uyarının *olay* başına bir, hedef başına bir
   olduğunu gösterir: tek bir dolu disk için iki hedef tanımlıysa iki `disk.low`
   ve iki `disk.recovered` görürsünüz — bu hata değildir.

---

## 4. PowerShell ile denenebilenler (Python/SQL yok)

Aşağıdaki komutların hiçbirinde Python veya SQL satırı yoktur.

### 4.1 Sağlık durumu ve günlükler

Üç container'ın sağlık durumunu tek tabloda görün:
```powershell
P ps --format "table {{.Service}}\t{{.State}}\t{{.Status}}"
```

Bir servis sağlıksız çıktıysa **kapalı olduğu anlamına gelmez** — Docker
`restart: unless-stopped` yalnızca **çöken** container'ı yeniden başlatır,
sağlıksız ama ayakta olanı başlatmaz. Bu yüzden duruşu ayrıca kontrol edin:
```powershell
P logs --tail 40 worker
```

Worker sağlık kaydının **içeriğini** görmek için:
```powershell
P exec -T worker cat /tmp/dojo-worker-health.json
```
Beklenen: `phase` (`idle` ya da `busy`) ve sabit bir son tarih. Uzun bir render
sırasında `busy` görürsünüz; 3600 saniyeyi aşmadığı sürece sağlıklıdır.

> **"No such file" diyorsa** worker bu özelliğin eklendiğinden **önceki** bir
> imajdan çalışıyor demektir. `P up -d --build` ile worker'ı yeniden kurun;
> dosya worker başlarken oluşturulur.

### 4.2 Disk uyarısını sunucu tarafında doğrulamak

Telefon yoksa uyarının **üretildiğini** yine de görebilirsiniz:
```powershell
P logs --tail 200 worker | Select-String "monitoring\."
```

Aradığınız olaylar:

| Olay | Ne zaman |
|---|---|
| `monitoring.disk_sample` | Her 60sn'de, hedef sağlıklıysa |
| `monitoring.disk_sample_failed` | Hedef yoksa/okunamıyorsa (900sn'de bir kez) |
| `monitoring.delivery` | Uyarı kabul edildiğinde |
| `monitoring.delivery_rejected` | Sağlayıcı reddettiğinde — **sessizce kaybolmaz** |
| `monitoring.overrun` | Bir tur çok uzun sürdü, kaç tur atlandı |

Son satır, bu dalın en sık sessizleşen hatasıdır: sağlayıcı hata döndürdüğünde
(eski hâliyle) hiçbir kayıt yazılmıyordu, kalıcı hata saatte bir kez sessizce
tekrar ediyordu. Artık `delivery_rejected` yazılır.

Disk alanını gerçekten görün:
```powershell
P exec -T worker df -h /media /
```
> `/media` **adlandırılmış bir volume**dır; container içinden bakınca
> `db-data` ve `caddy-data` ile **aynı** dosya sistemini raporlar. Yani
> "volume dolu" ile "host diski dolu" ayrımı bu ölçümle **yapılamaz** — bu
> yüzden host'ta ayrı bir dosya sistemi varsa §4.5'teki gibi ek hedef ekleyin.

### 4.3 Yapılandırılmış günlükler ve sır redaksiyonu

Her satırın tek bir JSON olduğunu doğrulayın:
```powershell
P logs --tail 5 backend
```

Bir sırrın günlüklere düşmediğini denetleyin. Sırrı **komut satırına
yazmayın**; depodaki yükleyici `ops/.env`'i okur ve değerleri ekrana basmaz:
```powershell
. .\ops\Load-Env.ps1
P logs --since 10m backend worker | Select-String -SimpleMatch $env:POSTGRES_PASSWORD
```
Çıktı **boş olmalıdır** — `Select-String` hiçbir eşleşme basmamalıdır. Doluysa
bir sır sızdı; durun ve `docs/contracts` sözleşmesine dönün. Aynı denemeyi
`SIGNED_URL_SECRET` ve FCM proje kimliği için de tekrarlayın.

Bir olayın hangi alanları taşıdığını görün:
```powershell
P logs --tail 200 worker | Select-String '"event":"job.outcome"' | Select-Object -First 3
```

### 4.4 Başarısız iş uyarısı

Yüklenebilir bir işin başarısız olması gerekir. Web arayüzünden yükleme
akışını tamamlayın (yükleme → iş başarısız). Ardından:
```powershell
P logs --tail 300 worker | Select-String '"event":"job.outcome"'
```
`status` alanında başarısız işi görürsünüz; kalıcı uyarı **aynı işlemde**
oluştuğu için, işin kaydı ile uyarının kaydı arasında çökme boşluğu yoktur.

### 4.5 Ek disk hedefi ekleme

Host'ta container'ın görmediği bir dosya sistemi varsa (örneğin Docker verisi
başka bir diskte), salt okunur bağlayıp adlandırın. `ops/.env`:
```
MONITORING_DISK_PATHS={"media":"/media","root":"/","hostdocker":"/host/docker"}
```
ve `ops/docker-compose.monitoring.yml` içine:
```yaml
    volumes:
      - /var/lib/docker:/host/docker:ro
```
> **Docker soketini asla bağlamayın.** `docker.sock` bağlanırsa izleme
> konteyneri host üzerinde root olur.

### 4.6 Kalıcı teslimatı sınamak (telefon olmadan)

Android gerektiren tek şey **alıcı**dır. Teslimatın kendisi sunucuda
doğrulanabilir — sağlayıcı çağrısının sonucunu günlükten izleyin:
```powershell
P logs --tail 400 worker | Select-String 'monitoring.delivery'
```
`status: accepted`, FCM'nin mesajı **kabul ettiğini** gösterir; telefonun
bildirimi **göstermesini** kanıtlamaz. Bu ayrım bilinçlidir ve `docs/contracts`
sözleşmesinde yazılıdır.

### 4.7 Tüm doğrulama betiklerini çalıştırmak

Önce ortamı ayarlayın, **sonra** betikleri çalıştırın (sıra önemlidir):
```powershell
$env:MSYS_NO_PATHCONV = "1"
$env:MSYS2_ARG_CONV_EXCL = "/etc/caddy"
& "C:\Program Files\Git\bin\bash.exe" ops/verify-prod.sh
& "C:\Program Files\Git\bin\bash.exe" ops/verify-monitoring.sh
```
`verify-monitoring.sh` beklenen tam olarak **`123 passed, 0 failed`** verir ve
bu, Windows altında Git Bash ile de doğrulanmıştır.

`verify-prod.sh` ise bu makinede **`20 passed, 2 failed`** verir. İki hata da
`config renders` adımındadır ve **ortam kaynaklıdır, kod hatası değildir**: Git
Bash `docker` komutunu Windows `docker.exe`'si yerine Docker'ın kendi shell
sarmalayıcısı üzerinden çağırır ve bu, betiğin geçici env dosyasını bulamaz.
Aynı iki compose render'ını elle, Windows yoluyla çalıştırdığınızda `exit 0`
verir. Betik bir **Linux host**ta çalıştığında bu adımlar sorunsuz geçer.

> **Windows uyarısı.** Bu betikler Linux'ta yazıldı. WSL'nin `bash` takma
> komutu `set -o pipefail` reddettiği için **Git Bash** kullanın ve yukarıdaki
> iki ortam değişkenini komutlardan **önce** yükleyin. Bunlar olmadan
> `/etc/caddy/Caddyfile` gibi Linux yolları yanlış çevrilir.
>
> Linux'ta `verify-prod.sh` tam sayım verektir. İlk çalıştırmada
> `config renders` hatası görürseniz bunu Linux'ta yeniden deneyin; hâlâ
> hata veriyorsa gerçek bir sorundur ve `ops/verify-prod.sh`'yi inceleyin.

---

## 5. Barındırılan HTTPS denetimi (elle kurulum)

Kod tarafı sağlayıcıdan bağımsızdır; hesabı **siz** açarsınız. İki denetim
kurulur:

| Denetim | Adres | Beklenen gövde |
|---|---|---|
| Web | `https://<DOMAIN>/web-health.txt` | tam olarak `dojo-web-ok` + satır sonu |
| API | `https://<DOMAIN>/ready` | `{"status":"ok"}` |

Kurulumda sağlayıcının şunları **gerçekten desteklediğini** doğrulayın:

1. **Gövde doğrulaması** — yalnızca HTTP 200'e bakmak yetmez. SPA yedeği
   200 döndürebilir. Gövde eşleştirme desteklenmiyorsa bu denetim işe yaramaz.
   Varlık `dojo-web-ok\n` şeklindedir: 11 karakter **ve** sonunda bir satır
   sonu. Sağlayıcı gövdeyi istemci tarafında kırparsa `dojo-web-ok` yazmanız
   yeterlidir; bu durumu kurulumda örnekleyerek sınayın.
2. **Sertifika doğrulaması** — açık olmalı.
3. **Aralık** — en fazla 5 dakika.
4. **Uyarı kanalı** — VPS'iniz çökse bile size ulaşabilen, **provider'ın kendi**
   kanalı olmalı. Kendi sunucunuza giden uyarı, sunucunuz çöktüğünde size
   hiçbir şey söylemez.

Sonra **kesinti denemesi** yapın: izlenen servisi kasten durdurun, provider'ın
uyarısını alın, geri getirin, kurtarma uyarısını alın. Bu, "izleme var"
iddiasının tek gerçek kanıtıdır — panelde bir denetim görüntülemek yetmez.

---

## 6. Android bildirimi (#32 ve #36 gerekir)

Telefonda uyarı görmek için Android uygulamasının **hazır olması gerekir**.
Bu iki issue **açık** ve uygulama şu an yalnızca bir yer tutucu ekran
(`MainActivity.kt`): eşleşme, FCM alıcısı ve bildirim izni henüz yok. Yani
sunucu tarafı doğru çalışsa bile bugün hiçbir telefon uyarı alamaz.

Eklendiğinde denenecekler (rehberin §4 bölümüne bakın):
- Arka planda bildirim görünüyor mu, tekrar gönderimde **değiştiriliyor** mu
- Türkçe başlık ve gövde doğru mu
- Bildirimde inceleme kimliği aranmıyor mu — uyarı türü kendi kimliğini taşır
- Geçici bir sağlayıcı hatasından sonra yeniden denendiğinde ulaşıyor mu

---

## 7. Kapanmadan önce bilinmesi gerekenler

- **CI kırmızı ve #22'yi hiç çalıştırmadı.** `.github/workflows/ci.yml`
  aynı lint komutlarını çalıştırıyor, ancak son koşu bu dalın her commit'inden
  önceydi. Önce push edip bir koşu kaydı alın.
- **Önceden var olan lint borcu** bu dalın dışında (#22 hiçbir yeni ihlal
  eklemiyor); ayrı bir iş olarak ele alınmalı.
- **Loglar sınırlıdır** (servis başına 3 × 10 MiB). Yoğun bir hata döngüsünde
  `monitoring.*` kayıtları yerini alıp gidebilir — bu yüzden aynı olayların
  900 saniyelik tekrar sınırı vardır.
- **Sırlar:** FCM kimlik dosyası yalnızca salt okunur Compose secret olarak
  gelir; `ops/.env` dışında hiçbir yere yazılmaz ve hiçbir komut onu basmaz.
