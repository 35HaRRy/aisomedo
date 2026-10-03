# Güncel paket ekranı — takip düzeltmeleri

## Beklenen davranış

- Sunucuda `finalized` olan yüklemeler kuyruktan ve tarayıcı kayıtlarından kaldırılır; paket medyası silinmez. Yükleme panelinde “Listeden kaldır” düğmesi yoktur.
- Paketten çıkarılan medya aktif montajda gösterilmez. Ayrı çıkarılmış medya bölümünden geri yüklenebilir.
- Medya işlemleri erişilebilir Türkçe etiketli SVG ikonları kullanır. Son ikon çapraz oklu sürükleme tutamacıdır; basılı tutulan satır, taşınan satır ve önce/sonra bırakma noktası görünür. Mobilde yukarı/aşağı düğmeleri kullanılabilir.
- Fotoğraflar varsayılan olarak 3 saniyedir. Dosya bazında düzenlenen süre, bölüm değişiklikleriyle birlikte kaydedilir; toplam süre ve render aynı kayıtlı değeri kullanır. En kısa süre bir kare, 0,04 saniyedir.
- “Kaydedilmemiş değişiklikleri geri al” yalnızca yerel bölüm/fotoğraf süresi değişikliklerini geri alır. Dosyaları ve kaydedilmiş düzenlemeleri silmez. Kaydetme düğmesinin devre dışı olma nedeni ayrıca gösterilir; render'ın güncel olmaması kaydetmeyi engellemez.
- “Kaydedilmiş montajı render et”, kaydedilmemiş taslakları korur fakat onları render'a dahil etmez. Güncel sonuç kimlik doğrulamalı, önbelleğe alınmayan ve Range destekli video olarak oynatılır. Eski revision URL'si yeni render'ın baytlarını döndürmez. Başarısız render son tamamlanmış çıktıyı bozmaz.
- “Paketi temizle”, geri alınamaz işlemin kapsamını açıklayan yerel tarayıcı onayını ister. Yalnızca seçili aktif paketin dosyaları, çıkarılmış medyası, ilişkili upload/render tmp dizinleri, işleri, incelemeleri, audit olayları ve iş uyarıları silinir. Tamamlanmış paketler, global ayarlar ve yayın takvimi korunur.

## Temizlik güvenliği ve hata kurtarma

- API, klasör adına ek olarak paket ID'sini doğrular. Aynı dakika oluşturulan yeni paket, eski isteğin hedefi olamaz.
- Paket yazıcıları, medya/render worker'ı ve inceleme hatırlatmaları ortak kilidi kullanır. Zamanlayıcı render sürerken beklemek yerine sonraki turda değerlendirir. Kilit, PostgreSQL bağlantısını yeniden kullanır; kendi bağlantı havuzunu tüketmez.
- Async chunk endpoint'i bloklayan paket işlemini thread pool'da çalıştırır; API event loop'u render kilidini beklerken çalışmaya devam eder.
- Upload init, sunucunun limit yanıtından alınan `active_package_id` değerini `expected_package_id` olarak gönderir. Geç gelen eski yükleme isteği temizlenmiş paketi yeniden oluşturamaz. Yeni paket bulunmaması `0` ile temsil edilir. Eski istemciler için çağrının kilit öncesi gördüğü kimlik de kilit altında tekrar doğrulanır.
- Paket temizlenmeden önce tarayıcı kuyruğu durdurulur. Başarı yanıtından sonra kuyruk sıfırlanır; gecikmiş yanıtlar silinen satırları geri getiremez.
- Sunucuda `.clearing-<package-id>/` staging dizini ve kardeş `.clearing-<package-id>.json` günlüğü kullanılır. DB silmesi başarısızsa dizinler geri taşınır. DB silmesinden sonra dosya temizliği başarısızsa günlük korunur; aynı klasör/ID isteği yalnızca eski staging verisini temizler. İşlem DB silmesinden önce kesilmişse tekrar deneme önce taşınmış dizinleri geri yükler.
- Yarım kalan temizliğin hedef kimliği tarayıcı istemcisi bazında saklanır. Sayfa yenilendikten sonra da “Paket temizliğini tekrar dene” onay isteyerek aynı hedefle devam eder. Yeni paket bunun yerine kullanılmaz. Bu sırada yükleme kontrolleri kapalıdır.
- Tarayıcı depolaması engellenmişse sayfa açıkken tekrar deneme mümkündür. Yenileme sonrasında gerekirse sunucu günlüğündeki klasör adı ve dosya adındaki ID ile aynı onaylı `POST /api/packages/active/clear` isteği tekrar gönderilir. Günlükler elle veya genel bir tmp silme komutuyla temizlenmemelidir.

## Doğrulama komutları

Son sonuçlar: core **666 geçti / 4 atlandı**, backend **160 geçti**, worker **140 geçti**, web **257 geçti**; web TypeScript kontrolü ve üretim derlemesi başarılı. Chromium **7 geçti / 1 atlandı**.

```powershell
uv run --project dojo-core pytest dojo-core/tests -q --tb=short
uv run --project backend pytest backend/tests -q --tb=short
uv run --project worker pytest worker/tests -q --tb=short
```

`web/` dizininde:

```powershell
npm test
npm run build
$env:PLAYWRIGHT_PORT='3019'
npm run test:browser
```

Sözleşme üretimi:

```powershell
uv run --project backend python backend/scripts/export_openapi.py
uv run --project backend python backend/scripts/generate_clients.py
```

## Kapsam ve sınırlamalar

- Tarayıcı kontrolleri Chromium masaüstü ve emüle mobil viewport'ta, fixture API yanıtları ve gerçek oynatılabilir MP4 ile çalıştırılır. Fiziksel mobil cihaz doğrulaması yapılmadı. Mobil native sürükleme testi atlanır; mobil sıralama düğmeleri sınanır.
- Canlı paket silinmedi. Temizlik testleri geçici dizinler, bellek adaptörü ve test PostgreSQL'i kullanır. Canlı worker/Meta yayını bu doğrulamanın parçası değildir.
- Mevcut Ruff uzun satır uyarıları ve `_notify_recovery` içindeki `Notification.data` mypy tür hatası bu değişiklikten önce de vardır. Kapsam dışı consent accent-border tasarım uyarısı korunmuştur.
- Mevcut kullanıcı dokümanları değiştirilmedi; çalışma commit/push/merge edilmedi.
