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
| `FCM_PROJECT_ID` | — (`GOOGLE_CLOUD_PROJECT` de okunur) | Firebase projesi. İzleme override'i ile **zorunlu**: FCM proje adresine göre çalışır ve projesini bilemeyen bir dağıtım başlangıçta başarısız olur (§2) |
| `MONITORING_INTERVAL_SECONDS` | `60` | Disk örnekleme aralığı |
| `MONITORING_DISK_LOW_PERCENT` | `15` | Bu boş oranın altında düşük alan olayı açılır |
| `MONITORING_DISK_RECOVERY_PERCENT` | `20` | Bu boş oranında ve üstünde kurtarılır |
| `MONITORING_DISK_PATHS` | `{"media":"/media","root":"/"}` | Adlandırılmış disk hedefleri, ad → **mutlak** container içi yol |
| `WORKER_HEALTH_IDLE_SECONDS` | `120` | Worker boş döngüsünde en fazla kayıt yaşı |
| `WORKER_HEALTH_BUSY_SECONDS` | `3600` | Worker meşgul en fazla yaş |
| `WORKER_HEALTH_PATH` | `/tmp/dojo-worker-health.json` | Container yerel sağlık kaydı |

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
3. `ops/.env` içine yalnızca **yolu** yazın:
   ```
   FCM_CREDENTIALS_FILE=/etc/dojo/firebase-credentials.json
   ```
4. Worker'ı `up -d` ile ayağa kaldırın.

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
| `monitoring.disk_sample_failed` | Bir hedef okunamadı. Olay durumu korunur: örneklenemeyen hedef asla kurtarma kanıtı değildir |
| `monitoring.overrun` | Bir toplama turu aralığı aştı; `status` atlanan tur sayısını taşır |
| `monitoring.delivery` | Uyarılar sağlayıcı tarafından kabul edildi (görüntülendiğinin kanıtı değil) |
| `monitoring.delivery_send_failed` | Bir gönderim istisna fırlattı; uyarı bekliyor ve yeniden denenecek |
| `monitoring.notifier_missing` | İzleme FCM olmadan açıldı; başlangıç reddedildi |
| `monitoring.config_invalid` | Etkin bir ayar geçersiz; başlangıç reddedildi |
| `monitoring.shutdown_incomplete` | Toplayıcı sınırlı birleşmeyi aştı, `status="alive"` |
| `job.outcome` | Bir çalıştırma bitti; yalnızca `job_id` ve `status` |
| `worker.health_write_failed` | Sağlık kaydı yazılamadı; denetim sağlıksız bildirecek |

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
  şeyi değiştirmez. Asla kurtarma olarak okunmaz.
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

## 6. Barındırılan HTTPS izleme

Uygulama tarafı denetimler, üzerinde çalıştıkları makinenin kesintisini
bildiremez; bu yüzden iki harici denetim gerekir. HTTPS yoklaması ve sertifika
doğrulaması olan barındırılan bir sağlayıcı kullanın, aralık beş dakika veya
daha kısa olsun.

| Denetim | URL | Beklenen | Neden ayrı |
|---|---|---|---|
| Web sağlığı | `https://<DOMAIN>/web-health.txt` | HTTP 200, gövde `ok` içerir | Gateway'i ve derlenmiş web varlığını kanıtlar |
| API hazırlığı | `https://<DOMAIN>/ready` | HTTP 200, gövde `"status":"ok"` içerir | API'nin PostgreSQL'e ulaşabildiğini kanıtlar |

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
