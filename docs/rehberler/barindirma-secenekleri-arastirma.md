# aisomedo: barındırma seçenekleri ve sağlayıcı koşulları

**Erişim tarihi: 2026-10-04.** Yalnızca canlı resmî fiyat/koşul sayfaları kullanıldı. Fiyatlar teklif değildir; ülke, veri merkezi, stok, ödeme süresi, vergi ve yenileme koşulları satın alma öncesi yeniden kontrol edilmelidir. Uygulama kodu bu araştırmada incelenmedi; aşağıdaki uygulama bilgileri ana incelemeyi yapan oturumdan aktarıldı.

## Kısa karar

Az kullanıcılı ilk üretim için **tek x86 Linux VPS üzerinde mevcut Compose düzenini korumak**, ücretsiz servisleri birleştirmekten daha doğrudan bir seçenektir. OVHcloud ile Hetzner karşılaştırılabilir; fiyat kadar disk, yedek, stok ve render sırasındaki CPU davranışı önemlidir. **2–4 vCPU, en az 4 GB, tercihen 8 GB RAM ve 80–160 GB disk** bir başlangıç planlama aralığıdır; ölçülmüş kapasite veya performans garantisi değildir.

| Seçenek | Bu uygulama için değerlendirme |
| --- | --- |
| AWS “always free” | Süresiz ücretsiz EC2 yok. Yeni Free plan süre/kredi bitince kapanır; ücretli AWS üretim seçeneği ayrı değerlendirilmelidir. |
| Vercel Hobby + Neon Free | Kişisel, ticari olmayan demo için değerlendirilebilir. Mevcut sürekli worker, büyük medya ve ortak disk mimarisinin ücretsiz üretim karşılığı değildir. |
| OVHcloud VPS | Mevcut Compose, PostgreSQL, FFmpeg ve kalıcı diski birlikte çalıştırmak için uygun aday; ilan edilen başlangıç fiyatının ödeme/yenileme koşulları doğrulanmalıdır. |
| Hetzner Cloud | Benzer VPS adayı; IPv4/yedek ayrı ücretli. Ucuz CX/CAX serisinde araştırma sırasında stok uyarısı görüldü. |
| Oracle Always Free | Deneysel alternatif; kapasite bulunamaması ve boşta kaynak geri alma riski nedeniyle tek üretim dayanağı olarak önerilmez. |

Bu tablo aşağıdaki doğrulanmış koşullardan çıkarılmış teknik değerlendirmedir; “ücretsiz” kesintisiz üretim veya veri kurtarma garantisi anlamına gelmez.

## Uygulamayla eşleşme: ana oturumdan doğrulanmış bağlam

- `ops/docker-compose.prod.yml`: `postgres:16-alpine`, Alembic init, FastAPI backend, sürekli worker ve derlenmiş React/Vite arayüzünü sunan Caddy gateway. Backend/worker ortak `/media` ve worker-health volume kullanıyor. Tek VPS düzeni `docs/ops/deployment.md` içinde zaten belgelenmiş.
- Init/backend/worker DB adresleri `@db:5432` üzerinden türetiliyor. Neon yalnızca bir ortam değişkeni değiştirilerek takılamaz; Compose override, bağımlılıklar ve init/db seçimi ele alınmalı.
- Worker varsayılan olarak her **10 saniyede** DB sorguluyor; `/ready` kontrolü **15 saniyede** DB'ye erişiyor. Bunlar Neon'a yönlendirilirse az ziyaretçi olması veritabanının boşta kaldığı anlamına gelmez.
- FFmpeg/ffprobe alt süreçleri kalıcı yerel medya yollarını kullanıyor. Varsayılan sınırlar **2 GiB/dosya**, **20 GiB/aktif paket** (`dojo-core/src/dojo/publishing.py:116–117`; ana oturumun aktardığı spec:150–151). Tamamlanmış medyanın otomatik silinmesi MVP dışı (spec:221). Kaynaklar, çıktılar, arşivler ve render geçici dosyaları birlikte disk bütçesine girmeli.
- Frontend aynı-origin API/cookie düzeninde. Yalnız frontend'i Vercel'e ayırmak rewrite veya CORS/cookie/trusted-proxy çalışması ekler; otomatik, sıfır değişiklikli taşıma değildir.

## AWS: hesap tarihini ayırmak zorunlu

- **15 Temmuz 2025'ten önce açılan hesaplar:** EC2'nin eski ücretsiz dönemi hesap açılışından **12 ay**; uygun tipler `t2.micro`/`t3.micro`, kota aşımı ücretli. Dolayısıyla araştırma tarihinde bu tarihten önce açılmış hesapların standart 12 aylık EC2 dönemi zaten dolmuştur. **15 Temmuz 2025 ve sonrasında açılan hesaplar:** **100 USD** başlangıç kredisi, etkinliklerden **100 USD'ye kadar** ek kredi; Free plan **en fazla 6 ay veya kredi bitene kadar**. Kaynak: [EC2 hesap-tarihi tablosu](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html), [AWS Free Tier](https://aws.amazon.com/free/).
- Free plan bitince hesap/projeler askıya alınır ve kaynak/veri erişimi kesilir. AWS FAQ, yükseltme için **90 gün** veri saklama ve sonrasında kalıcı silme bildiriyor. Paid plan kredi/kota üstü kullanım için ücretlendirir. Bu, kalıcı ücretsiz VM teklifi değildir. Kaynak: [Free Tier FAQ, Free Plan Q3–Q6 ve Paid Plan Q1](https://aws.amazon.com/free/free-tier-faqs/), [AWS Billing](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html).
- **Lambda Functions** aylık **1 milyon istek + 400.000 GB-saniye** ücretsiz kullanım sunar. Klasik on-demand function tek çağrısı **900 saniye / 15 dakika** ile sınırlı; `/tmp` **512–10.240 MB** geçici alan, ilk **512 MB** ek ücret olmadan. Bu, süresiz EC2/worker/disk değildir. Provisioned Concurrency'de Lambda free tier uygulanmaz; diğer AWS servisleri ve transfer ayrıca ücretlenebilir. Kaynak: [Lambda fiyatları](https://aws.amazon.com/lambda/pricing/), [Lambda kotaları](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html).
- Uygulama açısından: ücretli EC2 mevcut VM yaklaşımına daha yakın; Lambda'ya geçiş işlerin parçalanması, tetikleyici/kuyruk ve haricî medya deposu tasarımı gerektirir. AWS maliyetini EC2 etiketinden ibaret saymayın: EBS, snapshot, IP, transfer ve kullanılan ek hizmetler dahil hesaplanmalı; bu araştırmada bölgeye özel EC2 toplamı doğrulanmadığı için fiyat tahmini verilmedi.
- **Kaynak tutarlılığı notu:** hesap ayrımının yürürlük tarihi EC2 dokümanında 15 Temmuz; [resmî duyuru](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/) 16 Temmuz 2025 tarihli. Güncel FAQ kredi son kullanımı konusunda farklı bölümlerde 6/12 ay ifadeleri içeriyor. Bu nedenle Paid plana taşınan krediler için tek, kesin süre iddiası yapılmadı; hesap içi kredi son kullanımı kontrol edilmeli.

## Vercel Hobby: ücretsiz ama ticari olmayan kişisel kullanım

- Hobby **0 USD/ay**, yalnız **ticari olmayan kişisel kullanım**. Ticari kullanım Pro/Enterprise gerektirir; “ticari” tanımı yalnız abonelik almak değildir, projenin üretimine katılan kişilerin finansal kazancı, ürün/hizmet tanıtımı ve reklam gibi durumları da kapsar. Pro ilanı **20 USD/ay**, kullanım/aşım ve vergiler ayrıca; ücretli developer seat **20 USD/ay**. Kaynak: [Fair Use – Commercial usage](https://vercel.com/docs/limits/fair-use-guidelines#commercial-usage), [fiyatlar](https://vercel.com/pricing), [Hobby](https://vercel.com/docs/plans/hobby).
- Hobby Functions / Fluid Compute: aylık **4 aktif CPU-saat**, **360 GB-saat provisioned memory**, **1 milyon çağrı**; **2 GB / 1 vCPU**, tek çağrıda **300 saniye** azami süre. Standart Python bundle **500 MB** açılmış boyut; uygun projelerde Large Functions **5 GB beta** istisnası mevcut. Request/response body sınırı **4,5 MB**. Kaynak: [Hobby kaynakları](https://vercel.com/docs/plans/hobby), [Functions limits](https://vercel.com/docs/functions/limitations).
- Dosya sistemi read-only; yazılabilir `/tmp` scratch alanı **500 MB**. Ortak kalıcı Docker `/media` volume karşılığı değildir; dosyalar kalıcı haricî depoya alınmalı. Python runtime desteklenir; sorun “Python hiç çalışmaz” değil, mevcut sürekli süreç/disk/iş modeliyle eşleşmedir. Kaynak: [Runtimes – filesystem ve Python](https://vercel.com/docs/functions/runtimes).
- Hobby cron: proje başına **100 cron**, her cron **günde en fazla bir kez**; hassas zamanlama garanti edilmez, dokümandaki örnek 01:00 işinin 01:00–01:59 arasında çağrılması. Pro/Enterprise **dakikada bir** ve dakika hassasiyeti. Eski “Hobby yalnız 2 cron” bilgisi güncel değildir. Kaynak: [Cron usage & pricing](https://vercel.com/docs/cron-jobs/usage-and-pricing).
- Hobby aylık **100 GB Fast Data Transfer**, **10 GB Fast Origin Transfer**. Limit aşımında çoğu kaynak için yeniden kullanım **30 gün** bekleyebilir; ücretsiz planda ek kota satın alınamaz. Blob ayrı bir ürün: **1 GB** ücretsiz depolama, **10 GB/ay** Blob transfer; bunu Functions kalıcı yerel diski sanmayın. Kaynak: [Hobby](https://vercel.com/docs/plans/hobby), [Vercel fiyat tablosu](https://vercel.com/pricing).
- Vercel'in Workflows, Sandbox ve beta/deneysel servisleri bulunuyor; **“Vercel hiçbir worker desteklemez” sonucu çıkarılmıyor**. Buradaki sonuç daha dar: mevcut Compose worker + ortak kalıcı medya + büyük upload yapısı, Hobby Functions/cron koşullarına doğrudan taşınamıyor. Başka Vercel ürününe yeniden tasarım ücretsiz, eşdeğer bir kurulum garantisi değildir.

## Neon Free: canlı kaynakta 0,5 GB değil 1 GB

| Özellik | 2026-10-04'te canlı resmî kaynakta görülen Free koşulu |
| --- | --- |
| Ücret / projeler / branch | **0 USD/ay**, **100 proje**, **10 branch/proje** |
| Compute | **100 CU-saat/proje/ay**; autoscaling en çok **2 CU / yaklaşık 8 GB RAM** |
| PostgreSQL depolama | **1 GB/proje**, projeler toplamında **20 GB/hesap**; eski 0,5 GB bilgisi canlı sayfayla uyuşmuyor |
| Uyuma | **5 dakika** hareketsizlikte scale-to-zero; Free'de kapatılamaz |
| Dış transfer | **5 GB/proje/ay**; proje ürünleri arasında ortak |
| Geri dönüş / backup | **6 saat** history, **1 GB** değişiklik sınırı; **1 manuel snapshot**, zamanlanmış snapshot Free'de yok |
| Destek / SLA | Community support; **Free ve Launch'ta uptime SLA yok**, Scale'de var |

Tablonun doğrudan kaynakları: [Neon pricing](https://neon.com/pricing), [planlar ve compute formülü](https://neon.com/docs/introduction/plans). History tablosunun bazı yerlerinde “1 GB-month” birimi, metinde “1 GB change history” yazıyor; uzun süreli bağımsız yedek varmış gibi yorumlanmadı. Plan tablolarında Instant Restore satırında “—” görünse de aynı plan dokümanının ayrıntı metni Free için ücretsiz 6 saatlik PITR açıklıyor; bu kaynak içi tutarsızlık satın alma/operasyon öncesi kontrol edilmeli.

**Bu uygulamada kritik hesap:** Neon'un resmî compute aralığı **0,25 CU**'dan başlıyor. Sürekli DB sorgulaması scale-to-zero'yu engelleyebilir; sağlayıcı bunu açıkça dokümante ediyor. Ana oturumun bildirdiği 10 saniyelik worker polling ve 15 saniyelik DB readiness sorguları Neon'a giderse, en küçük compute'un sürekli açık kaldığı varsayımında **0,25 × 24 × 30 = 180 CU-saat/30 gün**. Bu, ücretsiz **100 CU-saat** bütçesini aşar; aynı varsayımda kota **400 aktif saat ≈ 16,7 gün** sürer. Bu hesap gerçek kullanım ölçümü değil, mevcut polling davranışının maliyet sonucudur. Kaynak: [Compute size, minimum ve “Compute is not suspending”](https://neon.com/docs/manage/computes), [100 CU-saat ve formül](https://neon.com/docs/introduction/plans#compute).

- CU-saat veya dış transfer bitince compute sonraki döneme/yükseltmeye kadar askıya alınır. PostgreSQL depolama sınırı aşılınca yazma/depolama artıran işlemler başarısız olabilir; doküman bu sınırlarda verinin silinmediğini söylüyor. Kaynak: [Free limit aşımı](https://neon.com/docs/introduction/plans#what-happens-if-i-exceed-my-free-plan-limits).
- Launch **0,106 USD/CU-saat**, PostgreSQL storage **0,35 USD/GB-ay**, PITR history **0,20 USD/GB-ay**, snapshot storage **0,09 USD/GB-ay**; aylık minimum yok. Yalnız yukarıdaki 180 CU-saat compute varsayımı **19,08 USD** eder; storage/history/backup/vergiler hariç ve ücretsiz allowance ücretli plan için düşülmemiştir. Kaynak: [Neon fiyatları](https://neon.com/pricing).
- Canlı fiyat sayfası Free'de ayrıca **5 GB/proje Object Storage** gösteriyor; bu PostgreSQL kotasından ayrı, transfer bütçesi ortak. Yeni depolama ürününün varlığı yerel medya yollarının kendiliğinden taşındığı anlamına gelmez. Manuel snapshot sayısının “dahil” olması sınırsız/ücretsiz bağımsız backup anlamına gelmez; kaynak ücret tablosu snapshot storage ücretini ayrıca belirtir. Kaynak: [Neon planları](https://neon.com/docs/introduction/plans#object-storage), [snapshot açıklaması](https://neon.com/docs/introduction/plans#snapshots).

## OVHcloud VPS: bölgesel başlangıç fiyatı, yenileme ayrı kontrol

İrlanda satış sayfasında **“VPS 2027”** adıyla şu teklifler görüldü. Bu sayfa etiketi aktarılıyor; gelecekte yürürlüğe girecek politika tarihi iddia edilmiyor. Tüm fiyatlar **KDV hariç, “from” / başlangıç fiyatı**; Türkiye'den aynı satış kanalının/teklifin uygulanacağı varsayılmadı. Kaynak: [OVHcloud İrlanda VPS](https://www.ovhcloud.com/en-ie/vps/).

| Plan | vCore / RAM / NVMe disk | İlan edilen aylık başlangıç |
| --- | --- | --- |
| VPS-1 | **2 / 4 GB / 40 GB** | **3,81 EUR** |
| VPS-2 | **4 / 8 GB / 75 GB** | **7,21 EUR** |
| VPS-3 | **6 / 12 GB / 100 GB** | **10,40 EUR** |
| VPS-4 | **8 / 24 GB / 200 GB** | **19,96 EUR** |

- Teklif bağlantıları `pricing=upfront12` içeriyor. **Bunlar doğrulanmış taahhütsüz aylık veya sabit yenileme fiyatı değildir.** Birleşik Krallık configurator erişimi hata verdi; promo süresi, peşin ödeme, aylık ödeme farkı ve yenileme toplamı doğrulanamadı, rakam uydurulmadı. Örnek: [VPS-2 teklif bağlantısı](https://www.ovhcloud.com/en-ie/vps/configurator/?planCode=vps-2027-model2&brick=VPS%2BModel%2B2&pricing=upfront12&processor=%20&vcore=4__vCore&storage=75__SSD__NVMe).
- Başlangıç fiyatının bölgesel farkına örnek: UK VPS-1 **3,31 GBP**, VPS-2 **6,29 GBP**, VPS-3 **9,01 GBP**, hepsi KDV hariç “from”. World sayfası VPS-1 **4,54 USD**, VPS-2 **8,50 USD** gösteriyor; farklı döviz/kanal fiyatlarını aynı teklif gibi karıştırmayın. Kaynak: [UK VPS](https://www.ovhcloud.com/en-gb/vps/), [World VPS](https://www.ovhcloud.com/en/vps/).
- İlan edilen özellikler: dedicated IPv4, anti-DDoS ve günlük standard backup dahil; **99,9% altyapı SLA**. Plan kartları standard backup için önceki **24 saat** der; ayrıntılı options sayfası bunu günlük oluşturulup 24 saat tutulan yedek olarak açıklıyor. Premium **7 günlük** rolling backup ayrı; fiyatı çekilen sayfada “No results” olduğu için doğrulanamadı. İrlanda snapshot başlangıcı **0,30 EUR/ay KDV hariç**, UK **0,27 GBP/ay KDV hariç**. Kaynak: [İrlanda VPS](https://www.ovhcloud.com/en-ie/vps/), [UK backup seçenekleri](https://www.ovhcloud.com/en-gb/vps/options/).
- Ana sayfadaki 7 günlük backup dipnotunu ücretsiz standard planla karıştırmayın: sayfa standard/premium metinlerini birlikte veriyor. Ek diskler backup dipnotunda hariç; premium kopyalar aynı veri merkezinde tutuluyor. VPS yedeği bağımsız, uygulama-tutarlı PostgreSQL ve medya yedek stratejisi yerine tek başına kullanılmamalı. Kaynak: [VPS backup dipnotu](https://www.ovhcloud.com/en-gb/vps/), [options](https://www.ovhcloud.com/en-gb/vps/options/).
- Trafik “unlimited” sözü bölgeye bağlı: Mumbai/Singapore/Sydney için VPS-1 **500 GB/ay**, VPS-2/VPS-3 **1 TB/ay**, VPS-4 **3 TB/ay**, aşımda **10 Mbps** hız sınırı. Avrupa seçimiyle APAC teklifini aynı koşullarda saymayın. Kaynak: [bölge dipnotu](https://www.ovhcloud.com/en-ie/vps/).
- Bu uygulamada 40 GB giriş diski dar; 75 GB plan da önerilen 80–160 GB aralığının alt ucundan küçük. Aktif paket, çıktı, arşiv ve DB büyümesi için gerçek disk planlaması yapın; gerekirse 100 GB veya ek disk seçin, ek disk yedeğini ayrıca planlayın.

## Hetzner Cloud: eski ucuz fiyatları kullanmayın

Resmî **15 Haziran 2026** fiyat güncellemesi yeni sipariş ve rescale için geçerli. Aşağıdaki liste **Almanya/Finlandiya, KDV ve IPv4 hariç**. Kaynak: [resmî fiyat güncellemesi](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/).

| Plan | Güncel listelenen aylık tavan | Kaynakta görülen donanım |
| --- | --- | --- |
| CX23 | **5,49 EUR** | **2 vCPU / 4 GB / 40 GB NVMe** |
| CX33 | **8,49 EUR** | **4 vCPU / 8 GB / 80 GB NVMe** |
| CAX11 | **5,99 EUR** | **2 ARM vCPU / 4 GB / 40 GB NVMe** |
| CPX22 | **19,49 EUR** | **2 AMD vCPU / 4 GB / 80 GB NVMe** |
| CPX32 | **35,49 EUR** | **4 AMD vCPU / 8 GB / 160 GB NVMe** |

Donanım kaynakları: [Cost-Optimized](https://www.hetzner.com/cloud/cost-optimized/), [Regular Performance](https://www.hetzner.com/cloud/regular-performance/). Araştırmada Cost-Optimized ürünleri açıkça **“not available”** gösterdi; Regular sayfasında da oluşturma bağlantılarının yanında stok uyarıları görüldü. Canlı sayfa dinamik fiyat alanlarını boş döndürdüğünden fiyatlar resmî tarihli güncelleme tablosundan alındı. Stok ve nihai fiyat konsoldan doğrulanmalı; “hemen 8,49 EUR'ya alınabilir” garantisi verilmez.

- Primary IPv4 **0,50 EUR/ay** KDV hariç; IPv6 ücretsiz. Otomatik backup server fiyatının **%20'si**, **7 günlük backup slotu**. Böylece CX33 stok bulunursa hesaplanan **8,49 + 0,50 + 1,698 ≈ 10,69 EUR/ay**; CPX32 için **35,49 + 0,50 + 7,098 ≈ 43,09 EUR/ay**. KDV, haricî yedek/arşiv ve ek disk hariçtir. Kaynak: [Primary IP fiyatı](https://docs.hetzner.com/cloud/servers/primary-ips/overview/), [backup faturalandırması](https://docs.hetzner.com/cloud/billing/faq/#how-do-you-bill-for-snapshots-and-backups).
- Server backup/snapshot bağlı **Volumes'u içermez**. Snapshot manuel, silinene kadar korunur ve GB-ay üzerinden ayrıca faturalanır; canlı resmî sayfada sayısal snapshot birim fiyatı alınamadığı için burada yazılmadı. Kaynak: [Backup/Snapshot kapsamı](https://docs.hetzner.com/cloud/servers/backups-snapshots/overview/), [billing FAQ](https://docs.hetzner.com/cloud/billing/faq/).
- AB planlarında tablolar **20 TB** trafik içeriyor; diğer bölgelerde kota farklı. Kapatılmış VM var olduğu sürece faturalanır; aylık tavan yalnız VM bedelidir, eklentilerin/transfer aşımının toplamını sınırlamaz. Kaynak: [Cost-Optimized](https://www.hetzner.com/cloud/cost-optimized/), [billing FAQ](https://docs.hetzner.com/cloud/billing/faq/).
- Shared CPU planları değişken performans/orta yük için sunuluyor; sürekli yüksek render yükünde dedicated CPU değerlendirin. ARM CAX ucuz görünse de image/binary/FFmpeg uyumluluğu ayrıca doğrulanmadan x86 önerisinin yerine koymayın. Kaynak: [Shared/Dedicated açıklaması](https://www.hetzner.com/cloud/).

## Oracle Always Free: yardımcı deney seçeneği

Canlı resmî sayfa A1 için **1.500 OCPU-saat + 9.000 GB-saat/ay**, bunu **2 OCPU / 12 GB RAM** eşdeğeri olarak gösteriyor; eski “4 OCPU / 24 GB” anlatımı bu çekilen belgeyle uyuşmuyor. Ayrıca toplam **200 GB boot+block storage**, **5 volume backup**, **10 TB/ay** dış transfer belirtiliyor. Kaynak: [Oracle Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Aynı kaynak home region şartını, `out of host capacity` ihtimalini ve **7 günlük** dönemde CPU 95. yüzdeliği **%20'nin altında**, network **%20'nin altında**, A1 için memory **%20'nin altında** kaldığında idle kaynakların geri alınabileceğini açıklıyor. Bu yüzden ücretsiz kapasiteye güvenerek yayın takvimini/tek worker'ı üretime bağlamak risklidir. Burada kaynak metni aynen esas alındı; kota değişikliğinin yürürlük tarihi tahmin edilmedi.

## Toplam maliyet ve üretim kontrolü

VPS liste fiyatı toplam maliyet değildir: **alan adı/yenilemesi, vergiler, ek medya/arşiv deposu, ek disk, bağımsız DB+medya yedekleri, transfer aşımı, izleme ve dış API kullanım bedelleri** ayrıca hesaplanmalı. Dahil günlük yedek bağımsız felaket kurtarma değildir; altyapı SLA'sı uygulamanın render/yayın başarısını garanti etmez.

Önce düşük eşzamanlılıkla render süresi, CPU/RAM zirvesi ve paket başına kaynak+çıktı+geçici dosya boyutu ölçülmeli. İlk üretimde güvenli erişim/TLS, gizli bilgiler, disk alarmı, servis yeniden başlatma, yedek geri yükleme testi ve tamamlanmış medya için manuel/haricî arşiv politikası gerekli. Mevcut tek-VPS yaklaşımını bunlar olmadan “production hazır” saymayın; yalnızca frontend ve DB'yi ücretsiz servislere taşımak bu ihtiyaçları ortadan kaldırmaz.
