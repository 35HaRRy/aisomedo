# Kaizen-Instagram Bot — İş Akışları İnceleme Raporu

**Kapsam:** Bu doküman yalnızca mevcut iş akışlarındaki eksik/belirsiz adımları tespit edip düzeltir. Yeni bir özellik eklenmemiş, mevcut hiçbir özellik çıkarılmamıştır. Teknoloji veya uygulama detayına girilmemiştir.

---

## 1. Genel (Tüm Akışları Etkileyen) Tespitler

Aşağıdaki eksiklikler birden fazla akışta tekrar ettiği için önce burada toparlanmış, ilgili akışlarda tekrar edilmemiştir.

| # | Tespit | Neden Sorun |
|---|--------|-------------|
| G1 | Uygulamanın çekirdek özelliklerinden biri **"Onay gerektiğinde kullanıcıyı bilgilendirme"** olarak tanımlanmış, ancak akışların bir kısmı (Dojo içi Reels, Mini paylaşımlar) hiçbir onay adımı içermeden doğrudan otomatik paylaşım yapıyor; bir kısmı (Önemli günler, Doğum günleri) onay adımı içeriyor. Bu tutarsızlık, hangi paylaşım türlerinin denetimsiz otomatik yayınlanacağını belirsiz bırakıyor. | Tutarsız iş kuralı — aynı öneme sahip aksiyonlar (Instagram'da halka açık paylaşım) farklı kontrol seviyelerine sahip. |
| G2 | Hiçbir otomatik paylaşım görevinde **paylaşım başarısız olursa** ne yapılacağı tanımlı değil (Instagram API hatası, ağ hatası, içerik reddi vb.). | Sessiz başarısızlık riski — kullanıcı paylaşımın yapılmadığını fark etmeyebilir. |
| G3 | Onay istenen akışlarda (Önemli gün, Doğum günü) **kullanıcı onayı reddederse veya hiç yanıt vermezse** ne olacağı tanımlı değil. | Süreç yarım kalıyor, listeden kalkıp kalkmayacağı belirsiz. |
| G4 | 2 haftada bir çalışan görevlerin (Dojo içi paylaşım / Mini paylaşım) **hangi Pazartesi'nin "1. hafta" sayılacağı** (referans başlangıç tarihi) tanımlı değil. | İki görevin aynı Pazartesi çakışması veya hiç tetiklenmemesi riski. |
| G5 | Aynı takvim gününe birden fazla otomatik görevin denk gelmesi durumu (ör. bir öğrencinin doğum günü + dini bayram aynı gün) ele alınmamış. | Hikaye akışında çakışma/öncelik belirsiz. |

---

## 2. İçerik Dosyası Kaydetme (Dojo İçi Tür Seçimi)

**Mevcut akış özeti:** Kullanıcı dosya seçer → sistem "Dojo" klasöründeki en son oluşturulmuş, adında "-completed" geçmeyen klasörü bulur → dosyalar oraya kopyalanır.

**Eksiklikler:**
- 2. adımda "son oluşturulmuş klasör" bulunamazsa (ör. ilk kullanım, hiç klasör yoksa ya da tüm klasörler "-completed" ise) ne yapılacağı tanımlı değil.
- Kopyalama sırasında aynı isimde dosya zaten varsa (çakışma) davranış tanımlı değil.
- Kopyalama tamamlandığında kullanıcıya bir onay/özet bildirimi verilmiyor.

**Düzeltilmiş akış:**
1. Kullanıcıdan yüklemek istediği dosyalar dosya sisteminden seçilir.
2. "Dojo" klasöründe adında "-completed" olmayan, en son oluşturulmuş klasör aranır.
   - **Böyle bir klasör bulunamazsa:** kullanıcıya bilgi verilir ve `[dd-MM-yyyy]` formatında yeni bir "son görev içerik klasörü" oluşturulduktan sonra sürece devam edilir.
3. Seçilen dosyalar bu klasöre kopyalanır.
   - **Aynı isimde dosya zaten varsa:** dosya adı çakışmayacak şekilde otomatik olarak ayırt edici bir ek ile kaydedilir (üzerine yazılmaz).
4. Kopyalama tamamlandığında kullanıcıya kaç dosyanın başarıyla eklendiğine dair bir özet gösterilir.

---

## 3. Reels — Dojo İçi Görsel/Video Paylaşımı (2 Haftada Bir Pazartesi)

**Eksiklikler:**
- "Kolaj?" ve "Şablon metin?" olarak işaretlenmiş kısımlar bir iş kuralı değil, açık bir karar ihtiyacıdır — birden fazla görsel/video varsa bunların tek bir gönderide mi (kolaj) yoksa ayrı ayrı mı paylaşılacağı, paylaşım açıklamasında sabit bir şablon metin mi kullanılacağı belirsiz. **(Aşağıda soru olarak işaretlendi.)**
- "Görsel yükle" butonuyla dosya yüklendikten sonra sürecin devamı (paylaşımın gerçekleşmesi, klasörün "-completed" olarak işaretlenmesi) akışta tarif edilmemiş — 4. adım bir "çıkmaz" gibi görünüyor.
- 6. adımda yeni klasörün ne zaman oluşturulacağı belirsiz: paylaşım işleminden önce mi sonra mı, ve aynı tarihli bir klasör zaten varsa (aynı gün içinde ikinci bir tetikleme) ne olacağı tanımlı değil.
- Manuel tetiklenen "Dojo içi görsel paylaş" menü akışı yalnızca 4. adımı (yükleme) kapsıyor; menüden başlatılan sürecin paylaşım ve klasör kapatma adımlarını (2, 6) da içerip içermeyeceği belirtilmemiş.
- Onay adımı yok — bkz. G1.
- Paylaşım hatası senaryosu yok — bkz. G2.

**Düzeltilmiş akış:**
1. "dojo - son görev içerik klasörü" bulunur.
2. Bu klasörde görsel/video varsa, önceden belirlenecek paylaşım biçimine göre (bkz. Soru S1, S2) Instagram'da paylaşılır.
3. Klasörde görsel/video yoksa kullanıcıya iki seçenekli bir uyarı gösterilir: **"Görsel yükle"** / **"Paylaşım yapma"**.
4. **"Görsel yükle"** seçilirse: kullanıcı dosyaları "son görev içerik klasörü"ne yükler, ardından süreç 2. adıma dönerek paylaşım işlemini gerçekleştirir.
5. **"Paylaşım yapma"** seçilirse: herhangi bir işlem yapılmadan görev sonlandırılır (klasör kapatma adımı da uygulanmaz, klasör bir sonraki görev döneminde tekrar değerlendirilir).
6. Paylaşım başarıyla tamamlandıktan sonra: "son görev içerik klasörü"nün adının sonuna "-completed" eklenir ve "Dojo" klasörü altında `[dd-MM-yyyy]` adıyla yeni bir "sonraki görev içerik klasörü" oluşturulur.
   - Aynı tarihli bir klasör zaten varsa, klasör adına ayırt edici bir sıra eki eklenir.
7. Paylaşım başarısız olursa klasör "-completed" olarak işaretlenmez; kullanıcıya paylaşımın başarısız olduğuna dair bir bildirim gönderilir.
8. Menüden **"Dojo içi görsel paylaş"** seçilerek başlatılan manuel süreç, yukarıdaki 1–7. adımların tamamını (yalnızca yükleme değil) uygular.

---

## 4. Reels — Aralıklarla Mini Paylaşımlar (Scheduled Entries)

**Eksiklikler:**
- "Sıradaki paylaşılacak eleman" listedeki sıraya göre mi (yukarıdan aşağı), yoksa listede atanmış bir tarihe göre mi belirlenecek, net değil.
- Liste boşken görev tetiklenirse ne olacağı tanımlı değil.
- Onay adımı yok — bkz. G1. Paylaşım hatası senaryosu yok — bkz. G2.
- Paylaşım sonrası elemanın listeden çıkarılıp çıkarılmayacağı (veya "paylaşıldı" olarak işaretlenip işaretlenmeyeceği) belirtilmemiş.

**Düzeltilmiş akış:**
1. "Scheduled Entries" listesinden, listedeki sıraya göre bir sonraki eleman belirlenir.
   - **Liste boşsa:** görev herhangi bir işlem yapmadan sonlanır, kullanıcıya listenin boşaldığına dair bir bildirim gönderilir.
2. Eleman bir metin ise: metin Kaizen'in antetli kağıt görselinin üzerine yazılarak paylaşılır; aynı metin paylaşımın açıklama kısmına da eklenir. Metnin "author" bilgisi varsa görsele de eklenir.
3. Eleman bir görsel ise: görselin sağ altına Kaizen'in logosu yerleştirilerek paylaşılır.
4. Paylaşım başarıyla tamamlanırsa eleman listeden çıkarılır (veya "paylaşıldı" durumuna alınır — bkz. Soru S3).
5. Paylaşım başarısız olursa eleman listede kalır, kullanıcıya bildirim gönderilir.

### 4a. Kaynak İçerik Ekleme: Morihei Ueshiba – "Barış Sanatı" Alıntıları

Bu adım, yukarıdaki tekrarlayan paylaşım görevinden farklı olarak **tek seferlik bir içerik besleme sürecidir**; mevcut dokümanda bu ayrım yapılmamış ve tekrarlayan görevin bir alt maddesi gibi sunulmuş, bu da kafa karıştırıcı.

**Eksiklikler:**
- Kaynaktan çıkarılan sözlerin çevirisinin doğruluğunu kim/nasıl teyit edecek belirtilmemiş — otomatik çeviri sonrası bir gözden geçirme adımı yok.
- Kaç sözün, hangi sıklıkla kaydedileceği (tamamı tek seferde mi, parça parça mı) belirsiz.

**Düzeltilmiş akış (tek seferlik, manuel tetiklenen içerik hazırlama süreci):**
1. Belirtilen kaynaktaki sözler ayıklanır.
2. Türkçeye çevrilir.
3. Çeviriler kullanıcıya gösterilerek onayı istenir.
4. Onaylanan sözler "Scheduled Entries" listesine metin türünde içerik olarak eklenir.

---

## 5. Hikaye — Önemli Günlerde Paylaşım

**Eksiklikler:**
- Onay reddedilirse veya bildirime hiç yanıt verilmezse (00:01'e kadar) ne olacağı tanımsız — bkz. G3.
- Paylaşım sonrası (veya reddedilme sonrası) elemanın "Special Day Entries" listesinden çıkarılıp çıkarılmayacağı, bir sonraki yıl için tekrar kullanılıp kullanılmayacağı belirtilmemiş.
- Hatırlatmadaki "örnek paylaşılacak görsel" ile fiilen paylaşılacak görselin aynı olup olmadığı net değil.

**Düzeltilmiş akış:**
1. Paylaşım tarihinden bir gün önce kullanıcıya, paylaşılacak örnek görsel ile birlikte bir onay bildirimi gönderilir.
2. Kullanıcı onaylarsa, ilgili günün 00:01'inde görsel (sağ alt köşesinde dojo logosu ile) hikaye olarak paylaşılır.
3. Kullanıcı onayı reddederse veya paylaşım saatine kadar yanıt vermezse, paylaşım yapılmaz ve durum kullanıcıya bildirilir.
4. Paylaşım gerçekleşsin ya da gerçekleşmesin, ilgili gün geçtikten sonra eleman "Special Day Entries" listesinde bir sonraki yıl için pasif durumda kalır (silinmez) — bkz. Soru S4.

---

## 6. Hikaye — Ders Gün ve Saatlerinin Paylaşımı

**Eksiklikler:**
- "Keyfi aralıklarla" ifadesi bir tetikleme kuralı değil, tanımsız bir zamanlama — bu görevin ne zaman/nasıl tetikleneceği (kullanıcı manuel mi başlatıyor, yoksa sistem rastgele bir aralıkla mı çalıştırıyor) belirsiz.
- Aynı işlev için hem "onay isteyip onaylanınca paylaşma" hem de ayrıca "anlık paylaş butonu" tanımlanmış; bu iki mekanizmanın ne zaman kullanılacağı (biri diğerinin yerine mi geçiyor, yoksa ikisi de mi aktif) net değil.

**Düzeltilmiş akış:**
1. Kullanıcı, ders gün/saat bilgisini içeren hazır görsel ve metni istediği zaman günceller.
2. Paylaşım, kullanıcının manuel olarak sürece başlamasıyla tetiklenir (otomatik/zamanlanmış bir tetikleme bu görev için tanımlanmamıştır — bkz. Soru S5).
3. Kullanıcı süreci başlattığında hazır görsel ile birlikte bir onay istenir.
4. Onaylanırsa görsel anında hikaye olarak paylaşılır.
5. Uygulama içindeki "anlık paylaş" butonu, 2–4. adımların (onay istemeden) doğrudan tetiklenmesi için kullanılır — yani onaylı akışın kısayoludur, ayrı bir süreç değildir.

---

## 7. Hikaye — Öğrenci Doğum Günü Kutlaması

**Eksiklikler:**
- Öğrencinin kayıtlı görseli yoksa kolaj adımının ne yapacağı tanımlı değil.
- Onay reddedilirse/yanıtsız kalırsa ne olacağı tanımsız — bkz. G3.
- Doğum tarihi kaydının her yıl otomatik olarak tetiklenip tetiklenmeyeceği (yıllık tekrar mantığı) açıkça belirtilmemiş.

**Düzeltilmiş akış:**
1. Öğrencinin doğum tarihi, geldiğinde otomatik olarak süreci tetikler.
2. Öğrencinin kayıtlı görsellerinden bir kolaj oluşturulur, sağ alt köşesine dojo logosu eklenir.
   - **Kayıtlı görsel yoksa:** kullanıcıya bilgi verilir, kolaj oluşturma adımı atlanır ve kullanıcıdan görsel eklemesi istenir; görsel eklenmezse paylaşım yapılmaz.
3. Doğum gününden bir gün önce, örnek görsel ile birlikte kullanıcıya onay bildirimi gönderilir.
4. Onaylanırsa doğum gününün 00:01'inde paylaşım yapılır.
5. Onay reddedilirse veya yanıt verilmezse paylaşım yapılmaz, kullanıcıya bilgi verilir.

---

## 8. Hikaye — Kalıcı Paylaşımların Hikayede Paylaşılması

Bu madde dokümanda **başlık dışında hiçbir açıklama içermiyor.** Hangi içeriğin "kalıcı paylaşım" sayıldığı, tetikleme koşulu, onay gerekip gerekmediği ve paylaşım sıklığı tanımlanmamış olduğu için bu akış şu an değerlendirilemez durumda. Diğer akışlarla tutarlı bir kural üretebilmem için aşağıdaki Soru S6'yı yanıtlamanız gerekiyor.

---

## 9. Kararınızı Gerektiren Sorular

| # | Soru |
|---|------|
| S1 | Dojo içi Reels paylaşımında birden fazla görsel/video varsa bunlar tek bir kolaj/karışık gönderi halinde mi, yoksa ayrı ayrı gönderiler halinde mi paylaşılsın? |
| S2 | Dojo içi Reels paylaşımlarında sabit bir şablon açıklama metni kullanılsın mı? Kullanılacaksa içeriği ne olmalı? |
| S3 | Mini paylaşımlar tamamlandığında "Scheduled Entries" listesinden tamamen silinsin mi, yoksa "paylaşıldı" durumunda listede tutulup arşivlensin mi? |
| S4 | Önemli gün paylaşımları bir sonraki yıl için otomatik olarak tekrar aktif hale mi gelsin, yoksa her yıl kullanıcı tarafından manuel olarak mı yeniden tanımlansın? |
| S5 | Ders gün/saat paylaşımı tamamen manuel mi kalsın, yoksa belirli bir zamanlama kuralına (ör. ayda bir) mı bağlansın? |
| S6 | "Kalıcı paylaşımların hikayede paylaşılması" akışı için: hangi içerik "kalıcı" sayılıyor, tetikleme koşulu ve onay ihtiyacı nedir? |
| S7 | Genel olarak (G1): otomatik Instagram paylaşımlarının tamamı onay adımından mı geçsin, yoksa yalnızca belirli türler (ör. kişiye özel/duygusal içerikler) için mi onay istensin? |

---

**Not:** Bu rapor yalnızca mevcut akışlardaki eksik/belirsiz noktaları netleştirmekte ve süreç bütünlüğünü sağlayan (boş liste, hata, çakışma gibi) standart durumları eklemektedir. Hiçbir yeni özellik önerilmemiş, mevcut hiçbir özellik kaldırılmamıştır.
