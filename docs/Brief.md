### Uygulama tarifi - WIP

- This app basically has these features:
    - Shares entries on Instagram
    - Stores and manages entry files (text and picture) will be shared
    - Schedules next entry time
    - Notify user when an approve is needed
- No user login or login method
- Primary technologies are Kotlin, FastAPI.

### Uygulama kullanımı

- Paylaşımlarda kullanılabilecek dosyaları kaydetme
    - Tür seçimi yapılır. Seçeneğe göre aşşağıdaki süreçler işler:
        - Tür “Dojo içi” ise
            1. Kullanıcıdan yüklemek istediği dosyaları dosya sisteminden seçmesi istenir.
            2. Tüm içeriklerin olduğu klasörde “Dojo” adındaki klasörde son oluşturulmuş klasörü bulunur. Klasör adında “-completed” olmamalı. Bu klasörün temsili adı “son görev içerik klasörü” dır.
            3. **Böyle bir klasör bulunamazsa:** `[dd-MM-yyyy hh:mm]` formatında yeni bir "dojo - son görev içerik klasörü" oluşturulduktan sonra sürece devam edilir.
            4. Seçilen dosyalar “dojo - son görev içerik klasörü” ne kopyalanır.
            5. **Aynı isimde dosyalar zaten varsa:** her dosya için kullanıcıya 3 seçenek sunulur.
                1. 2 dosyayı da tut → seçili dosyayı isminin sonuna “-1” ekleyerek kopyalar.
                2. Seçili dosyayı tut → Seçili dosyayı hedefteki dosyanın üstüne yazar.
                3. Hedefteki dosyayı tut → Seçili dosya için herhangi bir işlem yapmaz.  
- Reels olarak paylaşım yapma seçenekleri
    - Dojo içi resim veya videoları paylaşmak
        - Paylaşım içerikleri dersin başında, içinde veya sonunda herhangi bir temada çekilmiş fotoğraf veya video olabilir.
        - Bu paylaşım sürece 2 haftada 1 Pazartesi günü görev olarak çalışır.
        - Görevin yaptığı işlemler şunlar:
            1. “dojo - son görev içerik klasörü” bulunur.
            2. “dojo - son görev içerik klasörü” nde görsel varsa bunları Instagramda paylaşsın. Paylaşma süreci şu keilde olmalı:
                1. Kolaj?
                2. Şablon metin?
            3. Klasörde görsel yoksa bir uyarı kutusundan 2 buton ile işlem yaptırsın:
                1. İlk buton “Görsel yükle” olsun. Bu buton ile “son görev içerik klasörü” ne bu görseller yüklenebilsin ve 2. adım & Instagram paylaşım sürecini başlatsın.
                2. 2. buton “Paylaşım yapma” olsun. Bu buton ile herhangi bir işlem yapılmasın.
            4. Bu adıma kadar olan adımlar başarıyla tamamlanmışsa sırayla aşağıdaki adımlar gerçekleşsin:
                1. “dojo - son görev içerik klasörü” varsa isminin sonuna “-completed” eklensin.
                2. dojo klasörüne “[dd-MM-yyyy hh:mm]” isim formatıyla yeni bir klasör oluşturulsun.
            5. Görev 3-a adımına girmişse veya manuel başlatılmışsa paylaşılacak olan içerik gösterilerek onay istensin. Aksi halde süreç onaysız otomatik ilerlesin.
            6. Görev tamamlandığında kullanıcıya olumlu veya olumsuz bildirilsin.
        - Bu görev menüden “Dojo içi görsel paylaş” menüsü ile manuel de başlatılabilsin.
    - Aralıklar ile mini paylaşımlar yapmak
        - Paylaşım içerikleri Aikido ile ilgili yararlı görseller, yazılar, videolar, linkler veya Instagram paylaşımları olabilir.
        - Bunlar temsili adı “Scheduled Entries” olan bir listede saklansın.
        - Liste sıralı olsun ve paylaşımın yapılacağı tarihleri uygulama göstersin.
        - Listedeki eleman sırası değiştirilebilsin. Haliyle paylaşımın yapılacağı tarih de değiştirilebilsin.
        - Listeye yeni eleman eklenebilsin veya olan düzenlenebilsin veya çıkarılabilsin.
        - Bu paylaşım süreci “Dojo içi resim veya videoları paylaşmak” işinin çalışmadığı Pazartesi günleri 2 haftada bir görev olarak çalışır.
        - Görevin yaptığı işlemler şunlar:
            1. “Scheduled entries” listesinden sıradaki paylaşılacak elemanı belirle. 
            2. Paylaşılacak eleman bir metin ise metin Kaizen’in antetli kağıt görselinin üstüne yazılarak paylaşılsın. Aynı metin paylaşımın açıklamasına da yazılsın. Metnin “author” bilgisi varsa o da görsele eklensin.
            3. Paylaşılacak eleman bir görsel ise görselin sağ altına Kaizen’in logosu yerleştirilsin.
- Hikaye olarak paylaşım yapma seçenekleri:
    - Önemli günlerde paylaşımda bulunmak.
        - Paylaşım içerikleri dini ve milli bayramlar olabilir.
        - Bunlar temsili adı “Special day Entries” olan bir listede saklansın.
        - Bir gün evvel hatırlatsın. Onay istesin. Onlaylanırsa 00:01’da paylaşımı yapsın.
        - Hatırlatmada örnek paylaşılacak görsel olsun.
        - Görselin sağ alt köşesinde dojo’nun logosu olsun.
    - Keyfi aralıklar ile ders gün ve saatlerini paylaşmak.
        - Hazır görseli ve metni olsun. Güncellenebilsin.
        - Hazır görseli paylaşmadan evvel onay istesin. Onaylanırsa anında paylaşım yapsın.
        - Uygulamada da anlık paylaş butonu olsun.
    - Öğrencilerin doğum günlerini dojo içi resimleri ile kutlama.
        - Öğrenci tanımlaması yaparak doğum tarihi ve görselleri kaydedilebilsin / güncellenebilsin / silinebilsin.
        - Uygulama öğrenicinin kayıtlı görsellerini kolaj yapsın.
        - Görselin sağ alt köşesinde dojo’nun logosu olsun.
        - Bir gün evvel hatırlatsın. Onay istesin. Onlaylanırsa 00:01’da paylaşımı yapsın.
        - Hatırlatmada örnek paylaşılacak görsel olsun.
    -- Kalıcı paylaşımları da hikaye de paylaşmak.
