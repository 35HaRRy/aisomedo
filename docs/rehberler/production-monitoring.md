# Produtım İzleme — Operatör Rehberi

Bu rehber, dağıtılmış izleme yığının operatör tarafını anlatır: container sağlık
denetimleri, sınırlı JSON günlükler, FCM uyarılı disk izleme ve barındırılan
HTTPS denetimleri.

Bir Android cihazının tükettiği her şeyi değiştirmeden önce istemci mesaj
sözleşmesini okuyun:
[`docs/contracts/operational-alerts.md`](../contracts/operational-alerts.md).

## 1. Neler etkin, hangi dosya etkinleştiriyor

İzleme dağıtım başına isteğe bağlıdır. Taban üretim dosyası her servis için
sağlık denetimini ve sınırlı günlükleri açar, başka hiçbir şeyi değil: hiçbir
uyarı gönderilmez, hiçbir kimlik bilgisi okunmaz ve CI bu dosyayı yalnızca
`ops/.env.example` ile çizebilir.

| Katman | Etkinleştiren | Ne yapar |
|---|---|---|
| Container sağlık denetimleri | `ops/docker-compose.prod.yml` (her zaman) | backend `/ready`, worker sağlık CLI, gateway web-health varlığı |
| Sınırlı JSON günlükler | `ops/docker-compose.prod.yml` (her zaman) | servis başına 3 × 10 MiB `json-file`; sır taşımayan erişim günlükleri |
| Disk izleme + FCM uyarıları | `ops/docker-compose.monitoring.yml` (isteğe bağlı) | 60sn'de disk örnekleme, kalıcı uyarılar, gerçek push teslimi |

Yığını taban + tam olarak bir vekil modu ile, uyarı istediğinizde izleme
override'i ile ayağa kaldırın:

```bash
# Ayrı alan adı + operasyonel uyarılar
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml \
  -f ops/docker-compose.dedicated.yml \
  -f ops/docker-compose.monitoring.yml up -d --build

# Mevcut vekil + operasyonel uyarılar
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml \
  -f ops/docker-compose.existing-proxy.yml \
  -f ops/docker-compose.monitoring.yml up -d --build
```

Son `-f`'yi yok sayarsanız uyarısız çalışır. Vekil modu her iki durumda da
değişmez: izleme override'i yalnızca worker'a dokunur.

## 2. Ayarlar ve varsayılanlar

Tüm ayarlar `ops/.env` içindedir. Boş bırakmak varsayılandır; bu yüzden hiçbir
şeyi değiştirmeyen bir dağıtım da çalışan bir yapılandırma elde eder.

| Değişken | Varsayılan | Anlamı |
|---|---|---|
| `FCM_CREDENTIALS_FILE` | **izleme override'i ile zorunlu** | Firebase servis-hesabı JSON'unun mutlak host yolu. `/run/secrets/firebase-credentials.json` adresine salt okunur bağlanır |
| `FCM_PROJECT_ID` | — (işlevsel olarak `GOOGLE_CLOUD_PROJECT` de okunur, **ama Compose render'ı için yetmez**) | Firebase projesi. İzleme override'i ile **zorunlu**: FCM proje adresine göre çalışır ve projesini bilemeyen bir dağıtım başlangıçta başarısız olur (§2) |
| `MONITORING_INTERVAL_SECONDS` | `60` | Disk örnekleme aralığı |
| `MONITORING_DISK_LOW_PERCENT` | `15` | Bu boş oranın altında düşük alan olayı açılır |
| `MONITORING_DISK_RECOVERY_PERCENT` | `20` | Bu boş oranında ve üstünde kurtarılır |
| `MONITORING_DISK_PATHS` | `{"media":"/media","root":"/"}` | Adlandırılmış disk hedefleri, ad → **mutlak** container içi yol |
| `WORKER_HEALTH_IDLE_SECONDS` | `120` | Worker boş döngüsünde en fazla kayıt yaşı |
| `WORKER_HEALTH_BUSY_SECONDS` | `3600` | Worker meşgul en fazla yaş |
| `WORKER_HEALTH_PATH` | `/tmp/dojo-worker-health.json` | Container yerel sağlık kaydı |

Son üçü de `ops/docker-compose.prod.yml` içinde `${…}` ile geçirilir; dosyada
sabit yazılı değildir, bu yüzden `.env`'deki değer gerçekten container'a gider.
Varsayılanlar compose dosyasındadır, yani `.env` bu üçünü hiç içermese de
dağıtım aynı değerleri alır. `WORKER_HEALTH_PATH` yazılabilir bir container içi
yol olmalıdır: sağlık denetimi CLI'ı yol argümanı almadan bu kaydı çözer.

İki eşik bilinçli olarak eşit değildir: kurtarma işareti düşük işaretinin
üstündedir, böylece eşik civarında salınan bir dosya sistemi akış kazanması
yerine bir açılış ve bir kurtarma uyarısı üretir. Geçersiz bir değer
(`low >= recovery`, sayı olmayan, göreli hedef yolu) toplayıcıyı hiçbir şey
bildiremeyen bir durumda başlatmak yerine `monitoring.config_invalid` kaydıyla
worker başlangıcını başarısız kılar.

### FCM kimlik bilgisi kurulumu

1. Firebase konsolu → Proje ayarları → Servis hesapları → Yeni özel anahtar
   oluştur. JSON'u indirin.
2. Depo dışında, deploy eden kullanıcıya ait ve dünya tarafından okunabilir
   olmayacak şekilde host'a taşıyın:
   ```bash
   sudo install -m 600 -o dojo -g dojo ~/firebase-adminsdk.json /etc/dojo/firebase-credentials.json
   ```
3. Firebase konsolundan **proje kimliğini** not edin. Proje Ayarları → Genel →
   Proje kimliği (`…appspot.com` ya da `…firebaseio.com` söyleyen `project_id`
   alanı). Bu, `FCM_PROJECT_ID` olacak; servis hesabı JSON'unda da aynı
   `project_id` bulunur, ikisi aynı olmalıdır.
4. `ops/.env` içine **ikisini de** yazın — ikisi de zorunludur:
   ```
   FCM_CREDENTIALS_FILE=/etc/dojo/firebase-credentials.json
   FCM_PROJECT_ID=dojo-uretim-projesi
   ```
   `FCM_PROJECT_ID` boş bırakılırsa `ops/docker-compose.monitoring.yml` bu
   dosyayı `:?` ile koruduğu için **render** başarısız olur
   (`set FCM_PROJECT_ID in .env to the Firebase project id`) ve hiçbir container
   ayağa kalkmaz. Bu, kasıtlıdır: projesiz bir FCM her gönderimi ya
   sağlayıcı hatasıyla düşürür ya da kimlik dosyasının adı ne projeye
   işaret ediyorsa oraya gönderir.
5. Worker'ı `up -d` ile ayağa kaldırın.

`GOOGLE_CLOUD_PROJECT` **kodda** `FCM_PROJECT_ID` yerine geçer
(`worker/tests/test_fcm_wiring.py`), ama bu override'da tek başına işe
yaramaz: Compose yalnızca `FCM_PROJECT_ID`'yi kendi ortamına geçirir ve onu
`:?` ile korur, `GOOGLE_CLOUD_PROJECT`'ü okumaz. İkisini birden ayarlamak
sorun değil, ama `GOOGLE_CLOUD_PROJECT` yazıp `FCM_PROJECT_ID`'yi
atlamak render hatası üretir.

JSON dosyası asla depoya kopyalanmaz, asla bir ortam değişkenine konmaz ve
buradaki hiçbir betik tarafından yazdırılmaz. Container'a yalnızca Compose
secret olarak ulaşır; bu salt okunurdur ve `docker inspect` çıktısında
görünmez.

İki şeyi ayırmak gerekir, çünkü ikisi de aynı anda başlangıçta olmuyor:
**proje kimliği başlangıçta doğrulanır, kimlik dosyası ilk gönderimde çözülür.**

**Proje kimliği başlangıçta doğrulanır.** FCM proje adresine göre çalışır:
`FCM_ENABLED=true` iken `FCM_PROJECT_ID` (ya da `GOOGLE_CLOUD_PROJECT`) çözülemez
se worker ayakta kalmaz, `fcm.notifier_unavailable` kaydı yazar ve süreç hata ile
çıkar. Aksi halde her gönderim ya sağlayıcı hatasıyla düşer ya da kimlik
dosyasının adı ne projeye işaret ediyorsa oraya gider; ikisi de "kuralım çalışıyor
sanıp" asıl kaybedilen şey operasyonel uyarıdır. Boş bir `FCM_PROJECT_ID`
yapılandırılmamış sayılır — sır temizledikten sonra kalan o boş satır tipik
hatadır.

**Kimlik dosyası başlangıçta doğrulanmaz.** Firebase SDK'sı Application Default
Credentials'i tembel çözer, dolayısıyla eksik, bozuk ya da servis hesabı olmayan
bir dosya worker'ı **başlatmaz**; worker sorunsuz ayağa kalkar ve hata ilk
gönderimde, tipli bir `DefaultCredentialsError` olarak ortaya çıkar. Bu bilinçli
bir seçim değil, SDK'nın davranışıdır. Operasyonel olarak doğru olan da budur:
uyarı bekleyen durumda kalır, hiçbir şey "gönderildi" sayılmaz ve
`monitoring.delivery_send_failed` kaydı yazılır. Bu davranış
`ops/verify-monitoring.sh` içinde doğrulanır.

`monitoring.notifier_missing` kaydını gören bir worker ise üçüncü, ayrı bir
arıza: izleme `FCM_ENABLED` kapalıyken açılmıştır ve bu bilinçli olarak
başlangıçta reddedilir, çünkü hiç gönderilmeyen kalıcı uyarılar, hiç olmamış
uyarılardan ayırt edilemez.

## 3. Sağlık denetimleri

| Servis | Denetim | Kademe | Başarısızlık anlamı |
|---|---|---|---|
| `backend` | `GET /ready` (sınırlı DB bağlantısı) | 15sn aralık, 5sn zaman aşımı, 3 deneme, 30sn başlangıç süresi | API PostgreSQL'e ulaşamıyor. `/health` ucuz canlılık rotası olarak kalır ve üretimde o denetlenmez |
| `worker` | `python -m worker.health` | aynı | Eksik, bozuk, yabancı önyük veya bayat ilerleme kaydı. Meşgul süresi içindeki bir render sağlıklı kalır; takılan render değil |
| `gateway` | `GET http://127.0.0.1:8081/web-health.txt` | aynı | Derlenmiş web varlığı sunulmuyor. Bilinçli olarak herkese açık site değil, döngü dinleyicisi |

Üçünün de sağlıklı olduğu kanıtı `docker compose … ps` çıktısında üç `healthy`
satırıdır; bu, canlı kanıt olarak
[`docs/verification/issue-22-production-monitoring.md`](../verification/issue-22-production-monitoring.md)
içindeki `health_backend_status` / `health_worker_status` /
`health_gateway_status` alanlarına yazılır.

```bash
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.<mode>.yml ps
```

### Sağlıksız container otomatik yeniden başlatılmaz

Docker'ın `unhealthy` durumu **yalnızca tanılayıcıdır**. `restart:
unless-stopped`, süreç çıkışına tepki verir, sağlık durumuna değil; bu yüzden
çalışmaya devam eden sağlıksız bir container çalışmaya devam eder ve kendi
başına hiçbir uyarı gitmez. Bu bilinçlidir: devam eden bir render, bir sağlık
hükmüyle öldürülmemelidir. Kurtarma operatör eylemidir.

Sırayla teşhis:

```bash
# 1. Hangi denetim, ne zamandan beri
docker inspect --format '{{.State.Health.Status}} {{json .State.Health.Log}}' \
  dojo-prod-worker-1 | head -c 2000

# 2. O servisin yapılandırılmış günlükleri
docker logs --since 30m dojo-prod-worker-1

# 3. backend sağlıksız → sorun veritabanı mı?
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.<mode>.yml logs --tail 50 db
docker exec dojo-prod-db-1 pg_isready -U dojo -d dojo

# 4. worker sağlıksız → sağlık kaydı ne diyor?
docker exec dojo-prod-worker-1 cat /tmp/dojo-worker-health.json

# 5. gateway sağlıksız → derlenmiş varlık mevcut mu?
docker exec dojo-prod-gateway-1 ls -l /srv/web-health.txt
```

Sonra müdahale edin:

- `worker` boş denetim hatası → tick döngüsü durdu. `restart worker`; tekrarlarsa
  neden için `worker.tick_failed` kayıtlarını okuyun.
- `worker` sağlık denetimi, kayıt **yazılamadığı** için sağlıksızsa (kayıt
  eksik ya da bayat) `worker.health_state_unwritable` kaydına bakın: bu tek
  kayıt, sağlık kaydının neden yazılamadığını söyler ve disk/`/tmp` basıncının
  kendisidir. Sağlık kaydının yazılamaz duruma düşmesi, `monitoring.*` ve
  `job.outcome` kayıtlarının da okunması gereken bir kesintidir: önce diski
  açın, `monitoring.disk_sample_failed` kayıtlarını okuyun.
- `worker` meşgul hatası → bir render `WORKER_HEALTH_BUSY_SECONDS` ötesine
  takıldı. İşi kontrol edin, bitirilemeyecekse `restart worker`. Uçuş halindeki
  render sınırı 120sn'lik `stop_grace_period`'dur, yani yeniden başlatma en
  geç 120 saniyede bitirir.
- `backend` hatası → önce veritabanını geri getirin; `/ready` 200 dönmeye başlayınca
  denetim kendiliğinden toparlanır. Backend'i önce yeniden başlatmayın: aynı
  belirtiyi verir ve teşhisi kaybedersiniz.
- `gateway` hatası → eksik varlık bir yönlendirme değil derleme sorunudur:
  `--build` ile yeniden derleyin. `/web-health.txt` eksik varlığı çalışan
  varlıktan ayırt edilebilir kılmak için 404 döner, SPA'ya düşmez.

## 4. Günlükler

Backend ve worker stdout'a satır başına bir JSON nesnesi yazar; `timestamp`
(UTC), `level`, `service`, `event` ve küçük bir tanımlayıcı izin listesi taşır.
Mesaj metni ve argümanları hiçbir zaman serileştirilmez, bu yüzden eski bir
`logger.warning("token=%s", token)` çağrısı sızdıramaz; istisnalar yalnızca
sınıf adı ve yığın çerçevelerini katkılar.

Gateway'in erişim günlükleri de JSON'dur ve tam istek URI'si ile tüm istek
başlıkları kaldırılmıştır — maskelenmiş değil. Alan düzeyinde silme sözleşmenin
tamamıdır, çünkü bilinen sorgu parametresi adlarını maskelemek yalnızca biri
düşünülmüş olanları kapsar.

**Yanıt tarafı silinmez, Caddy'nin kendi maskelemesine bırakılmıştır.** Caddy her
erişim kaydında `resp_headers` yazar, yani eşleştirme sırasında API'nin
verdiği oturum çerezi loglanabilir bir alandır. Bu alan ancak Caddy'nin
kimlik başlıklarını `REDACTED` ile değiştirmesi sayesinde güvenlidir. Bu
gateway imajında sabitlenmiş bir Caddy sürümüyle derlenir
(`ops/gateway/Dockerfile`) ve `ops/verify-monitoring.sh` Faz I'de, API
stand-in'inin verdiği `Set-Cookie` değerinin logda **hiç** görünmediğini ve
`resp_headers` alanının gerçekten yazıldığını (yani denetimin boş yere geçmediğini)
doğrular.

```bash
# Yapılandırılmış: jq ile filtrelenebilir
docker logs --since 1h dojo-prod-worker-1 | jq -c 'select(.event=="job.outcome")'
docker logs --since 1h dojo-prod-backend-1 | jq -c 'select(.level=="ERROR")'

# İzleme geçişleri ve teslim sonuçları
docker logs --since 1h dojo-prod-worker-1 | jq -c 'select(.event|startswith("monitoring."))'

# Gateway erişim günlüğü: yalnızca metot/durum/süre
docker logs dojo-prod-gateway-1 | jq -c 'select(.msg=="handled request") | {method:.request.method, status, duration}'

# Sağlık yazma hataları
docker logs --since 1h dojo-prod-worker-1 | jq -c 'select(.event=="worker.health_write_failed")'
```

### İşe yarayan olaylar

| Olay | Anlamı |
|---|---|
| `monitoring.enabled` | Toplayıcı başladı; hedef sayısı ve aralık |
| `monitoring.disk_sample` | Bir okuma kaydedildi; `status` hedef adıdır |
| `monitoring.disk_sample_failed` | Bir hedef okunamadı; `status` `<hedef>:missing` (yol yok), `<hedef>:unreadable` (okuma hatası) ya da `<hedef>:rejected` (örnek kaydedilmedi). Olay durumu korunur: örneklenemeyen hedef asla kurtarma kanıtı değildir |
| `monitoring.overrun` | Bir toplama turu aralığı aştı; `status` atlanan tur sayısını taşır |
| `monitoring.delivery` | Uyarılar sağlayıcı tarafından kabul edildi (görüntülendiğinin kanıtı değil) |
| `monitoring.delivery_send_failed` | Bir gönderim **istisna** fırlattı; uyarı bekliyor ve yeniden denenecek |
| `monitoring.delivery_rejected` | Sağlayıcı gönderimi **sonuç olarak** kabul etmedi (istisna değil, bu yüzden başka hiçbir kayıt üretmezdi). `status` kalıcı sonucu ve nedeni birlikte taşır: `retry:provider_error`, `invalid:invalid_registration`, `retry:unreported`. Uyarı `PENDING` kalır ve geri çekilmeyle yeniden denenir |
| `monitoring.notifier_missing` | İzleme FCM olmadan açıldı; başlangıç reddedildi |
| `monitoring.config_invalid` | Etkin bir ayar geçersiz; başlangıç reddedildi |
| `monitoring.shutdown_incomplete` | Toplayıcı sınırlı birleşmeyi aştı, `status="alive"` |
| `job.outcome` | Bir çalıştırma bitti; yalnızca `job_id` ve `status` |
| `worker.health_write_failed` | Sağlık kaydı yazılamadı; denetim sağlıksız bildirecek |
| `worker.health_state_unwritable` | Sağlık kaydının yazılamadığı süreç boyunca **bir kez**: izleme bozuldu, denetim sağlıksız bildirecek |

### Sınırlandırılmış gürültü: hangi olay ne sıklıkta yazılır

Aşağıdaki üç olay kalıcı bir durumun tekrarıdır, ayrı ayrı olaylar değildir;
bu yüzden sınırlanmışlardır. Sınırlar **kayıt sayısını** korur, görünürlüğü
değil: bir olay susturulmaz, sadece tekrar etmez.

| Olay | Sınır | Neden |
|---|---|---|
| `worker.health_write_failed` | Faz başına ilk hata tam olarak, sonra en fazla **15 dakikada bir** | `/tmp` dolu ya da salt okunur olduğunda — tam olarak #22'nin aradığı koşul — her yazma iki kez ve tick başına başarısız olur: sınırsızken saatte ~17 000 kayıt, 3 × 10 MiB'lik günlük bütçesinin tamamını bu tek çağrı yerine döndürür ve `monitoring.*` ile `job.outcome` kayıtlarını yok eder |
| `monitoring.disk_sample_failed` | Hedef başına ilk hata tam olarak, sonra en fazla **15 dakikada bir** | Var olmayan bir hedef her turda başarısız olur; sınırsız iki uyarı dakika başına, hedef başına, sonsuza kadar |
| `monitoring.delivery_rejected` | Uyarı başına ilk kayıt, sonra en fazla **15 dakikada bir** | Sağlayıcı hatası geri çekilmeyle saatte bir yinelenir; alıcı sayısı büyükse bu, olayın kendisi kadar gürültülü olur |

`worker.health_state_unwritable` süreç başına **bir kez** yazılır, çünkü bir
durumun kendisidir: sağlık kaydının yazılamadığı ve denetimin sağlıksız
bildireceği. Disk hedefi ya da teslim yeniden çalışıyorsa ilgili kayıt kendi
sınırından sonra yeniden yazılır.

### Günlük saklama

Her üretim servisi Docker'ın `json-file` sürücüsünü `max-size: 10m` ve
`max-file: "3"` ile kullanır: servis başına yaklaşık 30 MiB, döndürülür ve
asla sınırsız büyümez. Günlük sürücüsü `json-file` olmayan bir container host
disksini doldurabilir; bu disk de disk izlemenin baktığı dosya sistemlerinden
biridir (aşağıya bakın).

## 5. Disk izleme ve dosya sistemi kapsamı

Bu, yanlış yapılması en kolay kısım; bu yüzden açıkça söyleniyor.

**Varsayılan `{"media":"/media","root":"/"}` hedefleri medya volume'unu
ölçmez.** `media-data` Docker'ın **adlandırılmış volume'u**, yani `/media`
container içinde Docker veri kökünün içindeki bir dizine bağlı bir mount
noktasıdır. Bu yüzden `shutil.disk_usage("/media")` volume'u değil, volume'un
yaşadığı dosya sistemini raporlar. "Volume dolu" ile "üzerinde durduğu disk
dolu" durumlarını birbirinden ayırt edemez, hiçbir başka container içi yol da
edemez.

Standart tek disklı bir Linux host'ta verilerin fiilen durduğu yerler:

| Ne | Host yolu | Varsayılanla kapsanıyor mu? |
|---|---|---|
| PostgreSQL verisi (`db-data`) | `/var/lib/docker/volumes/dojo-prod_db-data` | Evet, Docker veri kökü container köküyle aynı dosya sistemindeyse |
| Medya (`media-data`) | `/var/lib/docker/volumes/dojo-prod_media-data` | Evet, yukarıdakiyle aynı dosya sistemi |
| Caddy durumu (`caddy-data`) | `/var/lib/docker/volumes/dojo-prod_caddy-data` | Evet, yukarıdakiyle aynı dosya sistemi |
| Container günlükleri (`json-file`) | `/var/lib/docker/containers/…` | Evet, yukarıdakiyle aynı dosya sistemi |
| Worker kök dosya sistemi | container overlay | Evet (`root`) |

Gerçek yerleşimi varsaymayın, host'ta doğrulayın:

```bash
docker volume inspect dojo-prod_db-data dojo-prod_media-data dojo-prod_caddy-data \
  --format '{{.Name}} -> {{.Mountpoint}}'
docker info --format '{{.DockerRootDir}}'
```

Bunların hepsi tek bir dosya sistemine düşüyorsa varsayılanlar yeterlidir.
**Varsayılanlardan host geneli kapsama iddiasında bulunmayın**: ayrı bir
`/var/lib/docker`, ayrı bir `/var/log`, bağlanmış bir uygulama veri diski ya da
başka herhangi bir dosya sistemi onlara görünmez.

### Tek disk, iki uyarı: bu bir hata değil

Varsayılan iki hedef (`media` ve `root`) normalde **aynı** fiziksel diski
gösterir. Bu yüzden bu disk %15'in altına düştüğünde telefonunuzda **iki**
`disk.low` uyarısı gelir: önce "media hedefinde boş alan oranı düşük", hemen
ardından "root hedefinde boş alan oranı düşük". Kurtarma da iki tane olur:
iki `disk.recovered`. Bunlar iki ayrı ve kalıcı olaydır (`media` ve `root`
kendi olayını açar), ayrı ayrı kurtarılırlar; aynı `alert_id` iki kez
üretilmez çünkü olay başına tek açılış ve tek kurtarma uyarısı vardır.

Bu bir çift sayım ya da yapılandırma hatası **değildir**; her hedef kendi
etiketiyle ayrı bir sözleşmedir ve bu, "volume dolu" ile "üzerinde durduğu disk
dolu" ayrımının bilinçli sonucudur. Aynı fiziksel diski iki kez saymak
istemiyorsanız `MONITORING_DISK_PATHS` içinde yalnızca `root` bırakın.

### Varsayılanların kaçırdığı bir dosya sistemini kapsama

O dosya sisteminden **salt okunur** bir dizin bağlayın ve adını kendi hedefi
olarak verin. Bir örneklemeye salt okunur bir dizin yeter; onunla hiçbir şeyi
değiştiremezsiniz. Docker soketini asla bağlamayın: kök eşdeğeri bir yetenektir
ve disk izlemenin onu tutmasına hiçbir gerekçe yoktur.

Örneğin `ops/docker-compose.monitoring-disk.yml` adlı ek bir override oluşturun:

```yaml
services:
  worker:
    volumes:
      - /var/lib/docker:/host/docker:ro        # veri kökü ayrı bir dosya sistemiyse
      - /var/log:/host/var-log:ro             # ayrı bir /var/log dosya sistemi
    environment:
      MONITORING_DISK_PATHS: >-
        {"media":"/media","root":"/","docker-root":"/host/docker","host-var-log":"/host/var-log"}
```

`MONITORING_DISK_PATHS` varsayılan çiftin **yerini** alır, bu yüzden
dağıtımın hâlâ istediği her hedefi tekrarlamalıdır. Yollar mutlak olmalıdır:
göreli bir yol worker'ın çalışma dizinine göre çözülür, kimsenin seçmediği bir
dosya sistemini tanımlar ve örneklemek yerine başlangıcı başarısız kılar.
Hedef adları uyarı gövdelerinde göründüğü için operatörün okuyabildiği adlar
kullanın.

```bash
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.<mode>.yml \
  -f ops/docker-compose.monitoring.yml \
  -f ops/docker-compose.monitoring-disk.yml up -d worker
```

### Eşikler ve ilk etkinleştirme davranışı

- Bir olay boş alan `MONITORING_DISK_LOW_PERCENT` altındayken **açılır** ve
  boş alan `MONITORING_DISK_RECOVERY_PERCENT` üstündeyken ya da eşitken
  **kurtarılır**. Olay başına tek açılış ve tek kurtarma uyarısı, örnek
  başına bir tane değil.
- Başarısız bir örnek `monitoring.disk_sample_failed` kaydı üretir ve hiçbir
  şeyi değiştirmez. Asla kurtarma olarak okunmaz. `status` alanı **neden**
  olduğunu söyler: `<hedef>:missing` yolun var olmadığı anlamına gelir ve bu
  operatör eylemi ister — §5'te tarif edilen bind mount'lardan biri eksik ya da
  yazılmış. `<hedef>:unreadable` yalnızca okumanın başarısız olduğudur, disk
  hâlâ izleniyor demektir. Ayrım logdadır çünkü mesaj metni hiçbir zaman
  serileştirilmez.
- Olay durumu kalıcıdır: yeniden başlatma hâlâ açık bir olay için yeniden
  uyarı üretmez ve bayat bir örnek sahte bir kurtarma gösteremez.

**İlk etkinleştirme mevcut hataları bir kez dahil eder.** İzleme ilk kez
açıldığında, daha önce başarısız olmuş her iş, haftalar önce olmuş olsa bile
tek bir `job.failed` uyarısı üretir. Bu bilinçlidir — aksi halde etkinleştirmeden
sonraki ilk gerçek olay ile tarih arasındaki fark görünmez olurdu — ama ilk
etkinleştirmenin bir küme üretebileceği anlamına gelir. Bekleyin ve bu kümeyi
yeni bir kesinti olarak okumayın. Sonraki taramalar yeniden uyarı üretmez ve aynı
işin sonraki başarısız tekrarı kendi uyarısını üretir.

### Yeniden deneme semantiği

Geçici bir gönderim hatası üstel geri çekilmeyle yeniden denenir: 60sn,
120sn, 240sn, … 3600sn'de sınırlanır. Teslim **en az bir kez** gerçekleşir,
yani aynı uyarı birden fazla gelebilir; bildirim etiketi (`alert_id`) yineleneni
ilk olanın yerine geçirir. Kabul edilen yanıt, sağlayıcının mesajı kabul ettiği
anlamına gelir, bir cihazın gösterdiği anlamına değil.

Kabul edilmeyen her deneme logda görünür: istisna fırlatırsa
`monitoring.delivery_send_failed`, sağlayıcı hata **sonucu** döndürürse
`monitoring.delivery_rejected` (`status` alanında `retry:provider_error` ya da
`invalid:invalid_registration`). İkinci yol daha önce hiçbir kayıt bırakmıyordu:
uyarı var olur, saatte bir yeniden denenir ve log "hiçbir şey olmadı" gibi
görünürdü. `monitoring.delivery` yalnızca **kabul** edilen gönderimler için
yazılır; sıfır teslimle geçen bir turda görülmemesi normaldir, yoksa
`monitoring.delivery_rejected` kaydına bakın.

## 6. Barındırılan HTTPS izleme

Uygulama tarafı denetimler, üzerinde çalıştıkları makinenin kesintisini
bildiremez; bu yüzden iki harici denetim gerekir. HTTPS yoklaması ve sertifika
doğrulaması olan barındırılan bir sağlayıcı kullanın, aralık beş dakika veya
daha kısa olsun.

| Denetim | URL | Beklenen | Neden ayrı |
|---|---|---|---|
| Web sağlığı | `https://<DOMAIN>/web-health.txt` | HTTP 200, gövde tam olarak `dojo-web-ok` (`web/public/web-health.txt`; 12 bayt, satır sonu **yok**) | Gateway'i ve derlenmiş web varlığını kanıtlar |
| API hazırlığı | `https://<DOMAIN>/ready` | HTTP 200, gövde `{"status":"ok"}` | API'nin PostgreSQL'e ulaşabildiğini kanıtlar |

`/ready` başarısız olduğunda 503 ve `{"status":"unavailable"}` döner, gövde hiçbir
zaman sır taşımaz. İki denetim de **gövde** beklediği için yalnızca durum kodu
yeterli değildir: durum kodu tek başına SPA fallback'inin `index.html`'yi 200
ile döndürmesini geçirirdi.

Bu iki gövde `ops/verify-monitoring.sh` Faz H'de gerçek gateway üzerinden
karşılaştırılır (her iki vekil modunda, hem herkese açık rotada hem döngü
dinleyicisinde): yalnızca durum kodu değil, sunulan metnin bu tabloyla birebir
aynı olduğu doğrulanır.

### Sağlayıcının karşılaması gereken yetenekler

Sağlayıcı seçimi deployment işidir ve uygulama kodu sağlayıcıdan bağımsızdır.
Seçim yaparken **bu dört yeteneğin dördü de** gereklidir; biri eksikse o
sağlayıcı bu denetim için kullanılamaz:

1. **Gövde (keyword) doğrulaması** — istek gövdesinde bir dizi arayabilmeli.
   Yoksa SPA fallback denetimi geçer ve denetim hiçbir şey kanıtlamaz.
2. **Sertifika doğrulama** — TLS sertifikasını doğrulamalı ve doğrulamayı
   kapatma seçeneği kapalı olmalı (ya da kapatılmamalı).
3. **Beş dakikadan kısa aralık** — saniye cinsinden aralık ayarlanabilmeli.
4. **Bağımsız bildirim kanalı** — sağlayıcının kendi kanalından kesinti ve
   kurtarma bildirimi (e-posta, SMS, telefon, anlık bildirim, Slack).

Dördünü karşılamayan bir sağlayıcı "izleme var" sayılmaz.

### Doğrulanmış örnek: Better Stack Uptime

Bu alt bölüm bilgilendirme amaçlıdır; bir zorunluluk değildir ve seçilmiş bir
sağlayıcı ilan etmez. Kaynaklar **2026-09-30** tarihinde ctx7
(`/websites/betterstack_uptime`) ve betterstack.com üzerinden çekildi; kendi
hesabınızda doğrulamadan önce güncel sayfayı tekrar okuyun.

Kaynaklar:
<https://betterstack.com/docs/uptime/api/update-an-existing-monitor>,
<https://betterstack.com/docs/uptime/api/monitors-api-response-params>,
<https://betterstack.com/docs/uptime/api-monitor>,
<https://betterstack.com/docs/uptime/monitoring-start>,
<https://betterstack.com/pricing>

| Yetenek | Durum | Dayanak |
|---|---|---|
| Gövde doğrulaması | **Var** | `monitor_type` değerleri arasında `keyword`; `required_keyword` alanı, "bu anahtar sayfanızda yoksa yeni bir incident açar" |
| Sertifika doğrulama | **Var** | Monitör yanıtında `attributes.verify_ssl` — "SSL sertifikası geçerliliğini doğrula" |
| Aralık | **Karşılar** | `check_frequency` saniye cinsinden, varsayılan 30; "zaman aşımı değerinden büyük veya eşit olmalı". Fiyat sayfası en kısa aralığı 30 saniye olarak listeler; 300 saniye (5 dk) sınırın içinde |
| Bildirim kanalları | **Var** | `email`, `sms`, `call` (telefon), `push`, `critical_alert`, ayrıca `policy_id` ile tırmanma politikası; Slack/MS Teams/Zapier/webhook entegrasyonları |
| Yönlendirme izleme | **Kapatılabilir** | `follow_redirects` alanı; SPA fallback'i geçirmemek için `false` olmalı |
| Ücretsiz katman | **İki denetim için yeterli** | Fiyat sayfası: 10 monitör, Slack ve e-posta uyarıları. Ücretli katman SMS/telefon ekler |
| Sertifika **bitiş** uyarısı | **Ücretli** | `ssl_expiration` alanı mevcut; "sertifika son kullanma uyarıları aktif ücretli abonelik gerektirir" — bu, denetim sırasındaki doğrulamadan farklıdır |

Beklenmedik davranış: bir `policy_id` atanmışsa basit `call`/SMS/e-posta/push
ayarları yok sayılır. Bağımsız kanalı "e-posta" ile sağlamak istiyorsanız
monitöre tırmanma politikası atamayın ya da politikayı e-posta adımıyla
tanımlayın.

Kaynak kodda **hiçbir** sağlayıcı adı geçmez: denetimler dışarıdan yapılan
HTTP GET talepleridir ve uygulama onların varlığını bilmez.

Tek değil iki denetim, çünkü hata biçimleri bağımsızdır: ölü bir veritabanı
`/ready`'yi başarısız kılarken web sağlık varlığı hâlâ 200 döner ve tam olarak
tek bir birleşik denetimin gizleyeceği durum budur.

Yapılandırma notları:

- **HTTPS gerektirin ve sertifikayı doğrulayın.** Düz HTTP'yi veya
  sertifika yok sayımını kabul eden bir sağlayıcı gerçek site hakkında hiçbir
  şey kanıtlamaz.
- **Tam durumu ve gövdeyi gerektirin.** `/ready` bir yönlendirme veya SPA
  fallback'inin 200 döndürmesiyle sağlanmamalıdır; gövde denetimi, yönlendirilmiş
  bir API yanıtını `index.html`'den ayıran şeydir.
- **Ayrı alan adı modunda `https://` URL'yi kullanın.** Caddy'nin sahibi
  olduğu bir alan adına düz HTTP 308 yönlendirmesi döndürür; bu bir yönlendirmedir,
  varlık değil.
- **Kullanılabilirlik uyarılarını sağlayıcının kendi kanalıyla gönderin**
  (e-posta, SMS ya da ikinci bir sağlayıcı). VPS üzerinden bildirim yapan bir
  izleyici, VPS'in çöktüğünü bildiremez.

### Kesinti ve kurtarma tatbikatı

Sağlayıcı adını, denetim kimliklerini, her iki URL'yi ve aşağıdaki kanıtı
kaydedin. Bu canlı doğrulamadır; bir rehberin var olması, bir denetimin var
olduğunun kanıtı değildir.

Denetimleri kurduktan **sonra, kesintiye başlamadan önce** şu ön-uçuşu
yapın; SPA fallback bu iki şeyle ayırt edilir:

```bash
# 1. Her iki URL doğrudan beklenen yanıtı vermeli
curl -sS -o /dev/null -w '%{http_code}\n' https://<DOMAIN>/web-health.txt   # 200
curl -sS https://<DOMAIN>/web-health.txt                                  # dojo-web-ok
curl -sS -o /dev/null -w '%{http_code}\n' https://<DOMAIN>/ready           # 200
curl -sS https://<DOMAIN>/ready                                           # {"status":"ok"}
```

2. **SPA fallback'in neden yalnızca durum koduyla yakalanamayacağını görün.**
   Bilinmeyen her yol `index.html`'e düşer ve **200** döner:

   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' https://<DOMAIN>/olmayan-yol   # 200
   curl -sS https://<DOMAIN>/olmayan-yol | head -c 60                       # <!doctype html>...
   ```

   Yani 200'e bakan bir monitör burada **geçer**. Doğru sonuç: monitörün
   `dojo-web-ok` dizisini aradığından emin olun — sağlayıcının gövde
   doğrulama ayarı açık değilse bu denetim gerçekte hiçbir şey kanıtlamaz.

3. `/web-health.txt` varlığı gerçekten derlenmiş mi (yoksa 404, SPA değil):

   ```bash
   # varlık yokken de gateway 404 döner, index.html'e düşmez
   docker exec dojo-prod-gateway-1 ls -l /srv/web-health.txt
   ```

```bash
# Kontrollü kesinti: yalnızca API'yi durdurun. Web sağlık varlığı 200 kalmalı.
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.<mode>.yml stop backend
# İzleyin: barındırılan denetim /ready denetimi için DOWN, web-health denetimi
# için UP bildirmeli. Zaman damgalarını kaydedin.
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.<mode>.yml start backend
# İzleyin: /ready denetimi UP dönmeli. Zaman damgasını kaydedin.
```

Ardından, host izin veriyorsa tam kesinti (`docker compose … stop` ya da VPS'i
durdurma): her iki denetim de DOWN bildirmeli ve sağlayıcının kendi bildirimi
gelmelidir.

### Kaydedilecek alanlar

Sonuçları, alan adlarını şu kayda yazın:
[`docs/verification/issue-22-production-monitoring.md`](../verification/issue-22-production-monitoring.md).
O dosya alanları `PENDING` olarak tanımlar; tatbikat sonrası yalnızca **gerçekten
gördüğünüz** değerlerle doldurulur.

| Alan | Ne yazılır |
|---|---|
| `monitor_provider` | Sağlayıcının adı ve hesabın sahibi (kim, hangi ekip/kisi) |
| `monitor_web_health_id` / `monitor_api_ready_id` | Sağlayıcının verdiği iki denetim kimliği |
| `monitor_web_health_url` / `monitor_api_ready_url` | `https://` ile başlayan tam URL'ler |
| `monitor_interval_seconds` | Kurulan aralık (≤ 300) |
| `monitor_certificate_validation` | Doğrulamanın açık olduğunun nasıl doğrulandığı |
| `monitor_body_assertion_verified` | Gövde doğrulamasının nasıl doğrulandığı (bkz. ön-uçuş) |
| `monitor_notification_contact` | Bildirim kanalı ve **teslim** alındığına dair gözlem |
| `outage_detected_at` / `recovery_detected_at` | DOWN ve UP zaman damgaları (UTC) |
| `outage_receipt` | Kesinti ve kurtarma bildiriminin alındığı kanal + zaman |

Asla kaydedilmez: sağlayıcı API anahtarı, cihaz/push token'ı, `ops/.env`
içeriği, Firebase kimlik dosyasının herhangi bir parçası.

### Android uyarı doğrulaması (sentetik, üretim diski doldurmadan)

Bu adım **#32 (eşleştirme) ve #36 (FCM alıcısı)** düşene kadar
yapılamaz; o iki issue açıkken bu bölüm "yapılamaz" olarak kaydedilir, uydurma
bir gözlem yazılmaz. İstemcinin uygulayacağı sözleşme
[`docs/contracts/operational-alerts.md`](../contracts/operational-alerts.md)
dosyasındadır; kabul adımları (ön plan / arka plan / değiştirme / inceleme varsayımı
yok) aynı dosyanın "Prerequisites and acceptance" bölümündedir.

Disk uyarısını **diski doldurmadan** üretmek, üretim diski doldurmak yerine
eşikleri değiştirmektir. Doğrulama kuralı `0 < low < recovery <= 100`
olduğundan şu iki ayar yeterlidir:

```bash
# disk.low uyarısı üret: gerçek boş alan oranı %99'un altında olduğu için olay açar
# ops/.env  ->  MONITORING_DISK_LOW_PERCENT=99
#              MONITORING_DISK_RECOVERY_PERCENT=100
docker compose --env-file ops/.env -p dojo-prod -f ops/docker-compose.prod.yml \
  -f ops/docker-compose.<mode>.yml -f ops/docker-compose.monitoring.yml up -d worker
# Bir toplama turu bekle (varsayılan 60sn), cihazda "Disk alanı azalıyor" bildirimi gör.

# disk.recovered uyarısı üret: gerçek boş alan %2'nin üstünde olduğu için kurtarır
# ops/.env  ->  MONITORING_DISK_LOW_PERCENT=1
#              MONITORING_DISK_RECOVERY_PERCENT=2
# -> "Disk alanı normale döndü" bildirimi; aynı incident, ikinci uyarı değil.
```

**Yeniden teslim nasıl zorlanır — dürüst cevap:** `restart` ile olmaz. Olay
durumu kalıcıdır, yeniden başlatma ikinci bir `disk.low` üretmez. Aynı
`alert_id`'nin ikinci kez kabul edilmesi, sağlayıcı kabul ettiği hâlde onayın
kaydedilmeden ölmesi durumunda olur ve **böyle bir tetikleyici vardır**:

- teslim kiralaması 60 saniyedir (`claim_alert_delivery(..., lease_seconds=60)`,
  `dojo-core/src/dojo/adapters/db.py:1367`),
- gönderim ile onay ayrı adımlardır (`deliver_pending` → gönderir → `_acknowledge`,
  `dojo-core/src/dojo/monitoring.py:101-190`).

Yani worker'ı **FCM kabul ettikten hemen sonra, onay yazılmadan** `SIGKILL`
ile düşürürseniz (ör. `docker kill --signal=SIGKILL dojo-prod-worker-1`), kiralama
sahipsiz kalır; 60 saniye sonra bir sonraki teslim turu aynı uyarıyı aynı
`alert_id` ile yeniden gönderir ve cihazda **değiştirme** beklenir.

Bu pencere dar olduğu için sonuç **belirlenimci değildir**; birkaç deneme
gerekebilir. Kod yolu testlerle doğrulanmıştır:
`dojo-core/tests/test_monitoring_delivery.py::test_lost_acknowledgement_redelivers_the_same_alert_and_tag`
ve `::test_expired_lease_is_reclaimed_and_its_stale_acknowledgement_refused`.
Gözlem yapılamazsa alan `PENDING` kalır; benzetilmiş bir gözlem yazılmaz.

Geçici taşıma hatasından sonra kurtarma ise canlı olarak üretilebilir:

```bash
# 1. Kimlik dosyasını geçici olarak geçersiz bir dosyayla değiştirin
sudo install -m 600 -o dojo -g dojo /dev/null /etc/dojo/firebase-credentials.json
docker compose … up -d worker
# -> monitoring.delivery_send_failed, uyarı PENDING kalır, "gönderildi" denmez
# 2. Gerçek dosyayı geri koyun ve worker'ı yeniden başlatın
sudo install -m 600 -o dojo -g dojo ~/firebase-adminsdk.json /etc/dojo/firebase-credentials.json
docker compose … up -d worker
# -> bekleyen uyarı aynı alert_id ile bir sonraki teslim turunda gider
```

İki farklı görünüm vardır ve ikisi de kayda değer: SDK'nın kimlik hatası bir
**istisna** olduğu için `monitoring.delivery_send_failed` yazılır; FCM projesi
yanlış ya da API kapalı olduğunda ise sağlayıcı bir **sonuç** döndürür, istisna
fırlatmaz ve uyarı `monitoring.delivery_rejected` olarak kaydedilir
(`status="retry:provider_error"`). İkisi de aynı sonucu verir: uyarı `PENDING`
kalır, hiçbir şey "gönderildi" sayılmaz.

`job.failed` uyarısı için var olmayan bir iş kaynağı yaratın (ör. geçersiz
medya yolu olan bir paket) veya `monitoring.` olayları arasında
`job.failed` gövdesini arayın; sıfır cihaz varsa uyarı `PENDING` kalır ve bu
doğru davranıştır, teslim edilmiş sayılmaz.

Beklenen gözlemler (kanıt kaydındaki alan adlarıyla — kayıt dosyasında bu adların
tam olarak bulunduğu yazılıdır; burada listelenen her ad doğrudan bir kayıt
alanıdır):

| Alan | Ne yazılır |
|---|---|
| `disk_low_alert_observed` | Disk uyarısının **teslim edildiği** görüldüğü (bkz. yukarıdaki eşik değiştirme yöntemi) |
| `disk_recovery_alert_observed` | Aynı olayın kurtarma uyarısının teslim edildiği görüldüğü |
| `failed_job_alert_observed` | `job.failed` uyarısının teslim edildiği görüldüğü |
| `transport_retry_recovery` | Geçici taşıma hatasından sonra uyarının yeniden geldiği |
| `android_device_build` | Cihaz modeli + APK build kimliği (token **yok**) |
| `android_foreground_display` | Ön planda Türkçe başlık/gövdenin görüldüğü |
| `android_background_display` | Arka planda (ayrıca kapatılmışken) bildirim tepsisinde görüldüğü |
| `android_tag_equals_alert_id` | `adb shell dumpsys notification` çıktısında etiketin `alert_id` ile aynı olduğu |
| `android_redelivery_replaces` | Aynı uyarı ikinci kez geldiğinde tek bildirim kaldığı |
| `android_no_review_navigation` | Bildirime dokununca inceleme ekranı değil pano açıldığı |

`adb shell dumpsys notification` çıktısı bir **push token içerebilir**; kanıt
kaydına yalnızca ilgili bildirim satırları yazılır, ham çıktı yazılmaz.

## 7. Sır sızdırmadan sorun giderme

Yapı gereği güvenli; öyle kalması değerli:

- Kimlik dosyasını **asla** `cat` etmeyin, `ops/.env`yi yazdırmayın, secret
  okumayı uman bir `docker inspect` çalıştırmayın. Kimlik bilgisi bir dosya
  mount'udur, bu yüzden `inspect` çıktısında hiç yok — tam olarak amaç budur.
- Günlükleri her şeyi döküp göz atmak yerine `event` ile filtreleyin. Biçimlendirici
  zaten mesaj metnini, başlıkları, sorgu dizgelerini ve istisna değerlerini
  düşürdüğü için filtrelenmiş bir görünüm bir kayda güvenle yapıştırılabilir.
- Kimlik bilgilerinin sorun olup olmadığını sızdırmadan kontrol etmek için:
  ```bash
  docker exec dojo-prod-worker-1 stat -c '%A %s' /run/secrets/firebase-credentials.json
  docker logs --since 10m dojo-prod-worker-1 | jq -c 'select(.event|startswith("monitoring."))'
  ```
  Yalnızca dosya boyutu ve kipi; asla içerik.
- Tipli bir kimlik hatasıyla `monitoring.delivery_send_failed`, bağlanan
  dosyanın kullanılabilir bir servis hesabı olmadığı anlamına gelir. Dosyayı
  düzeltin ve worker'ı yeniden başlatın; bekleyen uyarı bir sonraki teslim
  turunda gider, hiçbir şey kaybolmaz.
- `monitoring.delivery_rejected` (`status` `retry:provider_error`) ise kimlik
  dosyası değil **sağlayıcı** tarafı reddediyor demektir: FCM v1 API'si bu
  projede açık değil, kota dolmuş ya da bir kurul politikası projeyi
  reddediyor. `status` `invalid:invalid_registration` ise tek bir cihazın
  kaydı geçersiz sayıldı ve o token silindi; bu bir cihaz sorunudur, teslimat
  sistemi değil. Kalıcı hatada uyarı `PENDING` kalır ve saatte bir yeniden
  denenir; `docker compose … logs db | grep operational_alerts` ile
  `disk_low_alert_observed` benzeri bir kanıt alabilirsiniz.

## 8. Doğrulama

```bash
bash ops/verify-prod.sh        # dağıtım sözleşmesi: sağlık denetimleri, günlük sınırları,
                               # iki vekil modu, volume kalıcılığı ve GERÇEK backend
                               # /ready hazırlığının düşüp toparlanması
bash ops/verify-monitoring.sh  # çalışma zamanı: iki modda gateway, secret mount, güvenli JSON günlükler
```

Kapsam, düşünülerek bölünmüştür ve ikisi birbirinin yerine geçmez:

- **Gerçek backend'in hazırlık sözleşmesi** (`ops/verify-prod.sh` Faz F) gerçek
  backend imajını, gerçek veritabanına karşı ayağa kaldırır, veritabanını
  götürür ve geri getirir: `/ready` sağlıklı → veritabanı yokken başarısız →
  veritabanı dönünce toparlanır. Yani canlı ayakta olan backend'de
  düşme/toplarlanma çalışma zamanında doğrulanmıştır.
- **Gateway'in hazırlık ve web sağlığını bağımsız yönlendirmesi**
  (`ops/verify-monitoring.sh` Faz H) üretim Caddyfile'ını her iki vekil modunda
  gerçek bir ağ geçidi konteynerine karşı çalıştırır. API'nin arkasında, ağ
  adı `backend:8000` olan **sentetik bir API vekili** vardır: bu, bağımsız
  yönlendirmenin bir Caddy meselesi olması ve üretimdeki çözümlemeyle birebir
  aynı olması içindir. Vekil gerçek backend'in kendi `/ready` semantiğini
  test etmez; bu, yukarıdaki Faz F'nin işidir.

Her iki betik de benzersiz adlandırılmış geçici bir proje, sentetik ortam
değerleri ve kendi imajlarını kullanır ve yalnızca kendilerinin oluşturduğunu
kaldırır. Hiçbiri `ops/.env`yi okumaz, hiçbiri secret değeri yazdırmaz.
`verify-monitoring.sh` hiçbir zaman bildirim göndermez: sağlayıcı kimlik
bilgisi yoktur ve FCM denetimlerini ağ olmadan çalıştırır.

Bu ikisi **canlı** doğrulamanın yerine geçmez: gerçek bir Android cihazı
sentetik bir uyarıyı görüntülemeden ve yukarıdaki barındırılan kesinti/kurtarma
tatbikatı yapılıp kaydedilmeden #22 tamamlanmış sayılmaz.

### Kanıt kaydı nerede

Kabul ölçütü başına alan alan sonuçlar ve PENDING/BLOCKED gerekçeleri
[`docs/verification/issue-22-production-monitoring.md`](../verification/issue-22-production-monitoring.md)
dosyasındadır. Android tarafındaki karşılık, uygulanacak istemci sözleşmesi
[`docs/contracts/operational-alerts.md`](../contracts/operational-alerts.md)
dosyasındadır; bu ikisi birlikte, kodu okumadan bu işi yürütebilecek bir operatör
içindir.
