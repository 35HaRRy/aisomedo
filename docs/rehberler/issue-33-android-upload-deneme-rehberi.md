# Android: Aktif Pakete fotoğraf/video yükleme

## Kullanım

1. Dojo sunucusuna bağlanın ve cihazı eşleştirin. **Paket → Aktif Paket** bölümünü açın.
2. **Fotoğraf/video seç** ile Dosyalar gibi kalıcı erişim sağlayan bir kaynaktan
   dosyaları seçin. Android 13+ bildirim iznini ister; izin verirseniz aktarımı
   uygulama dışında bildirimden de izleyebilirsiniz.
3. Dosya önce okunur ve doğrulanır. Bu hazırlık aktarım yüzdesi değildir. Boş veya
   sunucu sınırını aşan dosya, aktarım başlamadan reddedilir. Paket kapasitesini
   sunucu ayrıca denetler.
4. Yükleme satırı ve bildirim yalnızca sunucunun doğruladığı baytları gösterir.
   Başka bir uygulamaya geçebilirsiniz; Android izin verdiği sürece aktarım devam
   eder. Android 14+ kullanıcı tarafından başlatılan aktarım işi, Android 10–13
   ön plan WorkManager işi kullanılır.
5. **Duraklat** mevcut dosyayı durdurur; sıradaki uygun dosyalar devam eder.
   **Devam et** aynı yükleme kimliğini sürdürür. Bildirimdeki Duraklat da aynı
   kalıcı işlemdir. Bildirime dokunmak Paket bölümünü açar.
6. Bağlantı kesilirse kabul edilmiş parçalar yeniden gönderilmeden durum uzlaştırılır.
   Beş ardışık geçici hatadan sonra **Tekrar dene** gerekir. Başlatma yanıtı
   kaybolmuş ve kimlik alınamamışsa da açık yeniden deneme gerekir.
7. **Orijinal dosyayı seç** istenirse aynı içeriği seçin; aynı ad/boyut yeterli
   değildir. Değişmiş dosya eski yüklemeyle karıştırılmaz.
8. **Aktarım bitti; sunucuda sırada/işleniyor**, dosyanın pakete eklendiği anlamına
   gelmez. **Yenile** ile güncel durumu alın. **Aktif Pakete eklendi** kesin sonuçtur.
   Dosya adı çakışmasını web uygulamasında çözün; otomatik üzerine yazılmaz.
9. **Listeden kaldır** yerel takip satırını kaldırır; orijinal medyayı silmez.
   Aynı dosyayı kullanan başka satır varsa onun kalıcı erişimi korunur.

## Android kısıtlamaları

- Bildirim izni kapalıysa görünür bildirim vaat edilmez. **Bildirim ayarlarını aç**
  ile izni/kanalı kontrol edin.
- Pil, ağ veya sistem sağlığı nedeniyle Android işi durdurabilir. Ekran/uygulama
  yeniden açıldığında durum kontrol edilir; gerekirse Devam et/Tekrar dene kullanın.
- Ayarlardan **Zorla durdur** veya görev yöneticisinden durdurma aşılmaz. Uygulamayı
  kendiniz yeniden açın. Sunucunun kabul ettiği parçalar korunur.
- Sunucu değişikliği, eşleştirmenin kaldırılması veya uygulama güncellemesi
  gereksinimi aktarımları durdurur. Yeni eşleştirme eski kuyruğu devralmaz.
- Erişimi kaldırılmış/taşınmış dosya için yeniden seçim gerekir; bulut sağlayıcı
  kalıcı erişim vermiyorsa Dosyalar gibi uyumlu başka bir kaynağı deneyin.

## Doğrulama durumu

Bu dalın ana makine testleri ve APK/lint kontrolleri geçmiştir; gerçek API 33/34+
cihazlarda arka plan/ekran kapalı testleri henüz çalıştırılamamıştır.
[Ayrıntılı kanıt ve eksik kontroller](../verification/issue-33-android-upload.md).
