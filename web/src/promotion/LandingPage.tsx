import { useEffect, useRef, useState } from "react";
import { ThemeToggle } from "../theme";
import { SocialLinks } from "../components/SocialLinks";
import "./promotion.css";

const steps = [
  { title: "Anları bir araya getir.", text: "Fotoğraf ve videoları Aktif Paket’e yükle. Yükleme durumunu tek yerden takip et; kesintiden sonra kaldığın yerden devam et.", image: "package", action: "Düzenlemeyi keşfet" },
  { title: "Hikâyenin sırasını sen belirle.", text: "Medyayı sırala, videoda kalmasını istediğin bölümleri seç. Logon ve açıklama şablonunla paylaşımına kendi kimliğini ver.", image: "sections", action: "İnceleme adımına geç" },
  { title: "Sen onaylamadan yayınlanmaz.", text: "Hazırlanan Reel’i ve açıklamasını birlikte incele. Uygun zamanda onayla; hazır değilsen Yayın İncelemesi’ni atla veya başka zamana taşı.", image: "review", action: "Yayın sonrasını gör" },
  { title: "Paylaşımın izini kaybetme.", text: "Instagram’ın doğruladığı yayınlar Tamamlanmış Paketler’de yerini alır. Etkinlik kaydıyla ne olduğunu geriye dönük takip et.", image: "completed", action: "Android uygulamasını keşfet" },
];
const sections = [["intro", "Başlangıç"], ["benefits", "Neden Aisomedo?"], ["workflow", "Nasıl çalışır?"], ["android", "Android"]];

function Icon({ kind }: { kind: "collect" | "edit" | "approve" }) {
  return <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === "collect" ? <><rect x="7" y="14" width="29" height="27" rx="3" /><path d="M14 7h24a3 3 0 0 1 3 3v24M12 34l8-9 6 6 5-5M14 21h.01" /></>
      : kind === "edit" ? <><path d="M6 13h36M6 35h36M15 8v10M33 30v10" /><rect x="7" y="21" width="11" height="6" rx="1" /><rect x="22" y="21" width="19" height="6" rx="1" /></>
      : <><path d="M24 5 40 12v12c0 9-16 19-16 19S8 33 8 24V12Z" /><path d="m16 24 6 6 11-12" /></>}
  </svg>;
}

export function LandingPage({ onOpenApp }: { onOpenApp: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState("intro"), [step, setStep] = useState(0);
  useEffect(() => {
    document.title = "Aisomedo · Antrenmandan paylaşmaya";
    if (typeof window.IntersectionObserver !== "function") return;
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        const target = entry.target as HTMLElement;
        if (target.dataset.section) setActive(target.dataset.section);
        if (target.dataset.storyStep) setStep(Number(target.dataset.storyStep));
      }
    }, { rootMargin: "-20% 0px -45% 0px", threshold: 0 });
    root.current?.querySelectorAll("[data-section], [data-story-step]").forEach(node => observer.observe(node));
    return () => observer.disconnect();
  }, []);
  function go(id: string) {
    const target = root.current?.querySelector<HTMLElement>(`[data-anchor="${id}"]`);
    target?.scrollIntoView({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
    target?.focus({ preventScroll: true });
  }
  return <div className="promotion" ref={root}>
    <header className="promotion-header">
      <button className="promotion-wordmark" onClick={() => go("intro")} aria-label="Aisomedo başlangıç"><span className="brand-mark" aria-hidden="true">A</span>Aisomedo</button>
      <nav aria-label="Tanıtım bölümleri">{sections.map(([id, label]) => <button key={id} aria-current={active === id ? "location" : undefined} onClick={() => go(id)}>{label}</button>)}</nav>
    </header>
    <ThemeToggle floating />
    <main id="content" tabIndex={-1}>
      <section className="promotion-hero" data-section="intro" data-anchor="intro" tabIndex={-1}>
        <div className="promotion-hero-copy"><h1>Antrenmandan paylaşmaya.<br /><span>Kontrol sende.</span></h1>
          <p>Biriken fotoğraf ve videoları markana ait Instagram Reels’lerine dönüştür. Aisomedo hazırlığı bir araya getirir, son söz sende kalır.</p>
          <div className="promotion-actions"><button className="primary" onClick={onOpenApp}>Uygulamayı aç</button><button onClick={() => go("workflow")}>Akışı keşfet</button></div>
          <p className="promotion-note">Yükle. Düzenle. İncele. Onayla ve yayınla.</p>
        </div>
        <div className="promotion-hero-proof"><img src="/promotion/workflow.svg" width="680" height="400" alt="Fotoğraf ve videoların düzenleme, insan onayı ve Instagram yayınına uzanan akışı" />
          <figure><img src="/promotion/web/dashboard.png" width="1280" height="900" alt="Aisomedo kontrol panelinde yayın planı ve bekleyen inceleme" /><figcaption>Gerçek uygulama arayüzü · örnek veriler</figcaption></figure>
        </div>
      </section>
      <section className="promotion-benefits" data-section="benefits" data-anchor="benefits" tabIndex={-1}>
        <h2>İçeriğe odaklan.<br />Dağınık sürece değil.</h2>
        <div className="promotion-benefit-grid">
          <article><Icon kind="collect" /><h3>Tek Paylaşım Paketi</h3><p>Fotoğraf, video, sıralama ve açıklama aynı akışta. Dosyalar arasında kaybolmadan hazırlan.</p></article>
          <article><Icon kind="edit" /><h3>Sana ait bir kurgu</h3><p>Kalacak bölümleri seç. Logonu ve kartlarını ekle. Hazırlanan dikey Reel’i yayın öncesinde gör.</p></article>
          <article><Icon kind="approve" /><h3>Planlı, ama kontrolsüz değil</h3><p>Yayın Planı zamanı hatırlatır. İnceleme ve onay adımı, neyin paylaşılacağına senin karar vermeni sağlar.</p></article>
        </div>
      </section>
      <section className="promotion-workflow" data-section="workflow" data-anchor="workflow" tabIndex={-1}>
        <header><h2>Bir paketin<br />paylaşıma yolculuğu.</h2><p>Kaydırarak süreci izle veya adımlar arasında geçiş yap.</p></header>
        <div className="promotion-story">
          <figure className="promotion-stage" aria-label="Akışın etkin ekran görüntüsü">
            <div className="promotion-stage-tabs" aria-hidden="true">{steps.map((item, index) => <span key={item.image} data-active={index === step}>{index + 1}</span>)}</div>
            <img key={steps[step].image} src={`/promotion/web/${steps[step].image}.png`} width="1280" height="1000" alt={steps[step].title} loading="lazy" />
            <figcaption>Örnek verilerle uygulama görünümü</figcaption>
          </figure>
          <div>{steps.map((item, index) => <article className="promotion-story-step" data-story-step={index} data-anchor={`step-${index}`} tabIndex={-1} key={item.image}>
            <span className="promotion-step-count">Adım {index + 1} / {steps.length}</span><h3>{item.title}</h3><p>{item.text}</p>
            <img className="promotion-inline-screen" src={`/promotion/web/${item.image}.png`} width="1280" height="1000" alt={`${item.title} — örnek uygulama ekranı`} loading="lazy" />
            <button onClick={() => go(index === 3 ? "android" : `step-${index + 1}`)}>{item.action}<span aria-hidden="true"> ↓</span></button>
          </article>)}</div>
        </div>
      </section>
      <section className="promotion-android" data-section="android" data-anchor="android" tabIndex={-1}>
        <div><h2>Bilgisayarda hazırla.<br />Android’den de yanında olsun.</h2><p>Yerel Android uygulamasıyla aynı çalışma alanına bağlan. Medyanı yükle, paketini takip et ve Yayın İncelemesi’ni telefonundan aç.</p>
          <a className="promotion-download" href="https://github.com/35HaRRy/aisomedo/releases/download/android-v0.2.0/aisomedo.apk">Android APK indir · v0.2.0</a>
          <p><a href="https://github.com/35HaRRy/aisomedo/releases/download/android-v0.2.0/aisomedo.apk.sha256">SHA-256 doğrulama dosyası</a></p>
          <p className="promotion-note">Kendi sunucuna bağlanır. İlk bağlantıda tek kullanımlık eşleştirme kodu gerekir.</p>
        </div><div className="promotion-android-art" aria-hidden="true"><svg viewBox="0 0 280 340" fill="none"><rect x="64" y="15" width="152" height="306" rx="22" stroke="currentColor" strokeWidth="3" /><path d="M110 32h60M127 303h26" stroke="currentColor" strokeWidth="3" strokeLinecap="round" /><rect x="83" y="61" width="114" height="142" rx="5" fill="var(--accent-soft)" /><path d="m106 132 24 24 45-52" stroke="var(--accent)" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" /><path d="M86 226h108M86 244h80M86 262h93" stroke="currentColor" strokeWidth="3" strokeLinecap="round" /></svg><p>Web ve Android.<br />Aynı Paylaşım Paketi.</p></div>
      </section>
      <section className="promotion-close" data-anchor="start" tabIndex={-1}><h2>Bir sonraki paylaşımın<br />buradan başlasın.</h2><p>Hazırlığı bir araya getir. Yayını elinde tut.</p><button className="primary" onClick={onOpenApp}>Uygulamayı aç</button></section>
    </main><footer className="promotion-footer"><strong>Aisomedo</strong><SocialLinks /></footer>
  </div>;
}
