# Organizasyon bazlı çalışma alanları

Durum: Kullanıcı tarafından 2026-11-04 tarihinde onaylandı.

## Amaç ve kararlar

Tek ortak çalışma alanını, ortak PostgreSQL veritabanında birbirinden ayrılmış organizasyonlara dönüştürmek. Mevcut pairing tabanlı, eşit yetkili istemci modeli korunur; kullanıcı hesabı, parola veya rol sistemi eklenmez.

Kullanıcının kararları:
- Ortak veritabanı kullanılacak.
- Organizasyon adı ve e-posta zorunlu, telefon isteğe bağlı olacak.
- Organizasyon pasifleştirildiğinde yeni girişler, pairing kodu üretimi, mevcut oturum erişimi ve arka plan render/yayın işleri duracak.
- Mevcut organizasyona ait olması gereken bütün kayıtlar Kaizen Aikido Akademi'ye bağlanacak.
- Organizasyon yönetimi shell komutlarıyla yapılacak; README, demo, pairing ve landing içerikleri sade biçimde güncellenecek.

## Yaklaşımlar

1. **Seçilen: ortak veritabanı, organizasyona bağlı kayıtlar ve kapsamlı veri erişimi.** Mevcut dağıtımı korur; bütün veri erişim yollarında organizasyon sınırının uygulanması ve test edilmesi gerekir.
2. Organizasyon başına ayrı veritabanı: fiziksel ayrımı güçlendirir, fakat migration, bağlantı ve worker işletimini gereksiz büyütür. Seçilmedi.

## Organizasyon modeli

- Kalıcı dahili kimlik, zorunlu ad, zorunlu geçerli e-posta, boş olabilen telefon, aktif/pasif durumu.
- Tasarım önerisi: adların baş/son boşlukları temizlenir; büyük/küçük harf farkıyla belirsiz organizasyon seçimine izin verilmez. Adla CLI seçimi tek bir organizasyonla eşleşmelidir; boş veya belirsiz seçim reddedilir. Bu eşsizlik veritabanında da korunur.
- E-posta giriş sınırında doğrulanır; e-postanın benzersiz olması şartı eklenmez.
- İlk organizasyon: `Kaizen Aikido Akademi`, `kaizenaikidoakademi@gmail.com`, telefon boş (`-` bilgi yok olarak yorumlanır), aktif.
- Organizasyon silme, organizasyonlar arası taşıma, çoklu üyelik, organizasyon seçici ekran ve yönetim paneli kapsam dışı.

## Sahiplik ve izolasyon

- Eşleştirilmiş her istemci ve pairing kodu tam bir organizasyona aittir. Kod kullanımı istemciyi kodun organizasyonuna bağlar; istek gövdesinden başka organizasyon seçilemez.
- Paylaşım paketleri, medya/yüklemeler, işler, yayın planları/zamanları, incelemeler, ayarlar, marka/caption, Instagram bağlantısı ve OAuth durumları, onay kayıtları, etkinlik kayıtları ve bildirim alıcıları organizasyon bazında ayrılır.
- Bağımlı kayıtların sahipliği mevcut üst kayıttan güvenle türetilebilir; doğrudan sorgulanan kökler açık organizasyon anahtarı taşır. Çapraz organizasyon ilişkileri ve mevcut global tekil kısıtlar gözden geçirilir. Özellikle tek aktif paket, tekil ayar anahtarları ve yayın zamanı tekillikleri organizasyon bazına çekilir.
- API kapsamı yalnızca doğrulanmış istemcinin organizasyonundan türetilir. Organizasyona bağlı servis/store nesneleri istek veya worker işi için sabit kapsam taşır; uygulama genelinde paylaşılan nesnelerin kapsamı değiştirilmez. Kapsam verilmemesi varsayılan organizasyona sessiz erişim sağlamaz.
- Kimlikle erişilen tüm uçlar (istemci iptali, medya, yükleme, paket, inceleme, iş vb.) sahipliği denetler. Başka organizasyonun kaydı dışarıya yokmuş gibi görünür.
- Canlı olaylar, kaynak sürümleri, önbellekler, bildirimler ve worker kilitleri organizasyon sınırını korur; başka organizasyonun değişiklikleri veya alıcıları görünmez.
- Medya dosyaları ve marka varlıkları çakışmayacak kapsamda saklanır. Mevcut yollar korunabilir; yeni yollar için organizasyon ayrımı uygulanır. Kimlik doğrulamalı dosya erişimi sahipliği doğrular. Instagram'ın indirebildiği imzalı URL'ler yalnızca imzalanmış kaynağa izin verir; ilgisiz dosyalara erişim sağlamaz.
- Altyapıya ait süreç sağlığı/disk ölçümleri global kalabilir; organizasyonla ilgili hata ayrıntıları ve teslimatlar organizasyona özel kalır.

## Pairing ve oturumlar

- CLI kod oluşturma komutuna zorunlu organizasyon adı eklenir. Eksik, boş, bulunamayan veya pasif organizasyon için kod üretilmez.
- Uygulama içi kod üretimi otomatik olarak mevcut istemcinin organizasyonunu kullanır.
- İstemci listeleme ve iptal yalnızca aynı organizasyonda çalışır.
- Mevcut tarayıcı cookie ve Android bearer akışları korunur; taşınan istemcilerin tekrar eşleştirilmesi gerekmez.
- Her kimlik doğrulamada organizasyonun aktifliği kontrol edilir. Açık canlı bağlantılar da pasifleştirmeyi algılayıp kapanır; yalnızca yeni HTTP isteğini engellemek yeterli değildir.
- Pasif organizasyondaki, henüz tüketilmemiş kodlar da kullanılamaz. Pasifleştirme veri veya kimlik bilgisi silmez.

## Pasifleştirme ve arka plan işleri

- CLI pasifleştirmesi durumu kalıcı olarak değiştirir; tekrarı güvenlidir. İşlem başka organizasyonları durdurmaz.
- Scheduler yalnızca aktif organizasyonlarda iş üretir. Kuyruktaki işler pasif organizasyonda alınmaz; retry, kurtarma, klasör onarımı ve bildirim yolları da bu sınırı aşamaz.
- Devam eden render, mevcut iptal mekanizmasına aktiflik kontrolü bağlanarak durdurulur; üretilen geçici çıktı başarılı sonuç olarak kaydedilmez. Organizasyon kontrolünün hata vermesi devam izni sayılmaz.
- Yayın akışı dış servise yeni bir yan etki göndermeden önce organizasyon aktifliğini tekrar kontrol eder. Pasifleştirme sırasında Instagram'a zaten gönderilmiş HTTP isteği geri alınamaz; belirsiz gönderim sonucu başarısızmış gibi tekrar gönderilmez. Mevcut belirsiz yayın/kurtarma semantiği korunur.
- Pasifleştirme, süren dış isteğin bitmesini bekleyerek veya bütün render boyunca veritabanı kilidi tutarak uygulanmaz. Yerel iptal kontrolleri ile durur; dış servis sınırındaki geri alınamazlık belgelenir.
- Bekleyen iş ve içerikler silinmez; pasif organizasyon işleri otomatik yeniden başlamaz. Yeniden aktifleştirme komutu bu talebin kapsamında değildir.

## Shell ve mevcut işletim yolları

- Mevcut Python CLI ve paket script kalıpları kullanılarak oluşturma, listeleme ve pasifleştirme komutları eklenir.
- Oluşturma: zorunlu ad/e-posta, isteğe bağlı telefon. Listeleme: kimlik, ad, e-posta, telefon ve durum; kimlik bilgileri/tokenlar yazdırılmaz.
- Pairing kodu CLI'sı zorunlu organizasyon adı alır. Yerel başlatma, demo, test, Docker örnekleri ve bu komutu çağıran scriptler birlikte güncellenir.
- Organizasyona özgü mevcut ayar/render/onay CLI komutları da kapsamı açıkça alır; yanlışlıkla bütün organizasyonlara yazmaz. Gerçekten global olan onay politikası gibi yapıların hangi seviyede kaldığı uygulama envanterinde açıkça belirlenir; mevcut onayların geçerliliği korunur.

## Veri taşıma ve dağıtım

- Mevcut Alembic ve açık şema başlatıcısı kullanılır. Migration ilk organizasyonu oluşturur, sahipliği gereken mevcut veriyi bağlar, gerekli anahtar/kısıt/indexleri günceller; sahipsiz eski kayıt bırakmaz.
- Mevcut paket kimlikleri, dosya referansları, istemci kimlikleri ve hash'lenmiş kimlik bilgileri korunur. Eski medyayı zorunlu dosya taşımasına tabi tutmayan yaklaşım tercih edilir.
- Migration yeni kurulumda da çalışır ve ilk organizasyonu oluşturur. Test belleği adaptörleri/fixture'ları aynı sahiplik kurallarını uygular.
- Karışık eski/yeni süreçlerle çalışma desteklenmez: önce API ve worker durdurulur, veritabanı/medya yedeği alınır, şema yükseltilir, ardından yeni API ve worker başlatılır. Canlı veritabanına bu geliştirme oturumunda kendiliğinden migration uygulanmaz.
- Çok organizasyonlu veri oluştuğunda eski tek organizasyonlu şemaya kayıpsız dönüş garanti edilmez; yedekten geri yükleme güvenli dönüş yoludur.

## Doküman ve arayüz

- README uygulamayı organizasyonlara ayrılmış çalışma alanları olarak anlatır; yeni CLI ve yükseltme adımları eklenir.
- Pairing ekranı organizasyon kodu gerektiğini açıklar; organizasyon listesi sunmaz ve kimlik doğrulama öncesi organizasyon bilgilerini ifşa etmez.
- Landing ve demo metinleri organizasyon bazlı çalışma biçimini anlatır; demo verileri ait oldukları çalışma alanını tutarlı gösterir. Görsel yeniden tasarım yapılmaz.
- API sözleşmesi değişirse mevcut üreteçlerle web/Android tipleri ve etkilenen testler güncellenir. Android'e organizasyon seçici veya hesap sistemi eklenmez.

## Doğrulama ve kabul ölçütleri

- İki organizasyonlu testler: listeleme, kimlikle okuma/yazma, ayar/Instagram bağlantısı, dosya erişimi, canlı olay ve bildirim alıcıları birbirine sızmaz.
- Her organizasyon aynı anda kendi aktif paketine ve bağımsız yayın planına sahip olabilir.
- CLI doğrulaması: zorunlu alanlar, yinelenen ad, eksik/bilinmeyen/pasif organizasyon, listeleme ve idempotent pasifleştirme.
- Pairing kodu ve istemci sahipliği; başka organizasyonun istemcisini iptal edememe; taşınan oturumun çalışması.
- Pasifleştirmeden sonra mevcut cookie/bearer erişimi ve açık canlı bağlantı kapanması; eski kodun reddi.
- Bekleyen işler alınmaz, çalışan render iptal edilir, yayın dış yan etki sınırında durur; diğer organizasyon çalışmaya devam eder. Yarış koşulları deterministik testlerle kapsanır.
- Önceki şema/veri ile migration testi: ilk organizasyon, sahiplik, mevcut kimlik bilgileri ve medya referansları korunur; yeni kurulum da doğrulanır.
- Etkilenen Python, web, script ve üretilen API sözleşmesi kontrolleri çalıştırılır; çalıştırılamayan entegrasyon/Android kontrolleri açıkça raporlanır.

## Uygulayıcıya bırakılanlar

Mevcut store/servis yapısına en az değişiklikle uyacak kapsam taşıma ayrıntıları, doğrudan organizasyon anahtarı gerektiren tam tablo envanteri, komut isimleri, iptal kontrol aralığı ve migration sıralaması uygulama planında somutlaştırılır. Yeni bağımlılık, RLS altyapısı veya genel amaçlı tenancy framework'ü sırf bu değişiklik için eklenmez.

## Süreç kontrol listesi

- [x] Mevcut model, kimlik doğrulama, CLI, şema başlatıcısı ve worker bağlantılarını incele.
- [x] Kritik davranışları kullanıcıyla netleştir ve yaklaşımı seç.
- [x] Tasarımı yaz.
- [x] Bağımsız uygulanabilirlik incelemesini tamamla; planlamayı engelleyen açık soru bulunmadı.
- [x] Kullanıcıdan bu tasarım için onay al.
- [x] Onay sonrası uygulama planını yaz; ardından kodlama ve doğrulamaya geç.
