import { useEffect, useRef, useState } from "react";
import { tr } from "../i18n";
import { firstIncompleteRequired } from "./state";
import type { OnboardingStep } from "./types";
import { useOnboarding } from "./useOnboarding";

export const stepTitles: Record<OnboardingStep, string> = {
  pairing: "Tarayıcı eşleştirmesi", instagram: "Instagram bağlantısı", schedule: "Dojo Yayın Planı",
  consent: "Medya rızası", logo: "Dojo logosu", caption_template: "Açıklama şablonu", cards: "İsteğe bağlı kartlar",
};
export function OnboardingWizard() {
  const { setup, error, refresh } = useOnboarding();
  const [selected, setSelected] = useState<OnboardingStep | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const step = selected ?? (setup ? firstIncompleteRequired(setup.checklist) : null);
  useEffect(() => { heading.current?.focus(); }, [step]);
  if (!setup) return error ? <div role="alert">{tr.loadError}<button onClick={() => void refresh().catch(() => {})}>{tr.retry}</button></div> : <p role="status">{tr.loading}</p>;
  return <section className="onboarding">
    <header className="page-heading"><p>İlk kurulum · Kaydedilen adımlar korunur</p>
      <h1 ref={heading} tabIndex={-1}>{step ? stepTitles[step] : "Kurulum tamamlandı"}</h1>
      <p>Dojo yayınları için bağlantı, plan ve medya tercihlerini hazırlayın.</p></header>
    <ol aria-label="Kurulum adımları" className="onboarding-progress">{setup.checklist.map(item => <li key={item.key}>
      <button aria-current={step === item.key ? "step" : undefined} onClick={() => setSelected(item.key as OnboardingStep)}>
        {stepTitles[item.key as OnboardingStep]} <small>{item.complete ? "Tamamlandı" : item.required === false ? "İsteğe bağlı" : "Bekliyor"}</small>
      </button></li>)}</ol>
    <div className="summary-sheet">{step === "pairing" && <p>Bu tarayıcı eşleştirildi.</p>}
      {!step && <><p>Gerekli adımlar backend tarafından doğrulandı. Kartları isterseniz daha sonra ekleyebilirsiniz.</p><a href="#/dashboard">Kontrol Paneline git</a></>}
    </div><a href="#/dashboard">Kuruluma sonra devam et</a>
  </section>;
}
