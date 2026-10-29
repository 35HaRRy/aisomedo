export type TourId = "dashboard" | "package" | "review" | "settings";
export type TourStep = { id: string; target: string; title: string; description: string };
export const tours: Record<TourId, TourStep[]> = {
  dashboard: [
    { id: "dashboard.overview", target: '[data-tour="dashboard-overview"]', title: "Kontrol Paneli’ne hoş geldin", description: "Aktif Paket’ini, Yayın Planı’nı ve bağlantı durumunu buradan takip edebilirsin." },
    { id: "dashboard.review", target: '[data-tour="package-link"]', title: "Yayın zamanı ve inceleme", description: "Güncel Paket’te medyanı hazırla. Yayın zamanı geldiğinde Reel’i incele; sen onaylamadan paylaşım yapılmaz." },
  ],
  package: [
    { id: "package.overview", target: '[data-tour="package-overview"]', title: "Paylaşım Paketi’ni hazırla", description: "Fotoğraf ve video yükle panelini açarak dosyalarını seç. Yükleme durumunu aynı sayfadan izleyebilirsin." },
    { id: "package.media", target: '[data-tour="package-media"]', title: "Sırala, bölümleri seç, önizle", description: "Aktif paket medyasında sıralamayı değiştir ve videoda kalacak bölümleri seç. Düzenlemelerini kaydet; ardından Reel önizlemesini hazırla." },
  ],
  review: [
    { id: "review.preview", target: '[data-tour="review-preview"]', title: "Önce Reel’i incele", description: "Bu video ve açıklama aynı yayın sürümüne aittir. Önizlemeyi açmak veya izlemek paylaşım yapmaz." },
    { id: "review.decision", target: '[data-tour="review-decision"]', title: "Son karar sende", description: "İçerik hazırsa onayla ve yayınla. Hazır değilse bu zamanı atla veya başka zamana planla. Tanıtım hiçbir kararı senin yerine vermez." },
  ],
  settings: [
    { id: "settings.overview", target: '[data-tour="settings-overview"]', title: "Çalışma alanının ayarları", description: "Instagram bağlantını, Yayın Planı’nı, markanı ve hatırlatmalarını burada düzenle." },
    { id: "settings.help", target: '[data-tour="help"]', title: "Tanıtıma istediğin zaman dön", description: "Yardım’dan tanıtımları yeniden başlatabilir veya uygulamanın tanıtım sayfasını açabilirsin. Bu tercihler yalnızca bu tarayıcıda saklanır." },
  ],
};
