import { useEffect, useRef, useState } from "react";
import { tr } from "../i18n";
import { firstIncompleteRequired } from "./state";
import type { OnboardingStep } from "./types";
import { useOnboarding } from "./useOnboarding";
import { InstagramStep } from "./InstagramStep";
import { ConsentStep } from "./ConsentStep";
import { PlanStep } from "./PlanStep";
import { BrandingStep } from "./BrandingStep";
import { CardsStep } from "./CardsStep";

export const stepTitles: Record<OnboardingStep, string> = {
  pairing: "Tarayıcı eşleştirmesi", instagram: "Instagram bağlantısı", schedule: "Dojo Yayın Planı",
  consent: "Medya rızası", logo: "Dojo logosu", caption_template: "Açıklama şablonu", cards: "İsteğe bağlı kartlar",
};
export function OnboardingWizard() {
  const { setup, error, refresh } = useOnboarding();
  const [selected, setSelected] = useState<OnboardingStep | null | undefined>(undefined);
  const advancing = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const step = selected === undefined ? (setup ? firstIncompleteRequired(setup.checklist) : null) : selected;
  useEffect(() => {
    if (!setup || selected !== undefined) return;
    const next = firstIncompleteRequired(setup.checklist);
    setSelected(next ?? (advancing.current && !setup.checklist.find(item => item.key === "cards")?.complete ? "cards" : null));
    advancing.current = false;
  }, [setup, selected]);
  const onSaved = () => { advancing.current = true; setSelected(undefined); };
  useEffect(() => { heading.current?.focus(); }, [step]);
  if (!setup) return error ? <div role="alert">{tr.loadError}<button onClick={() => void refresh().catch(() => {})}>{tr.retry}</button></div> : <p role="status">{tr.loading}</p>;
  return <section className="onboarding">
    {error && <div role="alert" className="notice"><p>{tr.stale}</p><button onClick={() => void refresh().catch(() => {})}>{tr.retry}</button></div>}
    <header className="page-heading"><p>İlk kurulum · Kaydedilen adımlar korunur</p>
      <h1 ref={heading} tabIndex={-1}>{step ? stepTitles[step] : "Kurulum tamamlandı"}</h1>
      <p>Dojo yayınları için bağlantı, plan ve medya tercihlerini hazırlayın.</p></header>
    <ol aria-label="Kurulum adımları" className="onboarding-progress">{setup.checklist.map(item => <li key={item.key}>
      <button aria-current={step === item.key ? "step" : undefined} onClick={() => setSelected(item.key as OnboardingStep)}>
        {stepTitles[item.key as OnboardingStep]} <small>{item.complete ? "Tamamlandı" : item.required === false ? "İsteğe bağlı" : "Bekliyor"}</small>
      </button></li>)}</ol>
    <div className="summary-sheet">{step === "pairing" && <p>Bu tarayıcı eşleştirildi.</p>}
      {step === "instagram" && <InstagramStep onSaved={onSaved} />}
      {step === "consent" && <ConsentStep onSaved={onSaved} />}
      {step === "schedule" && <PlanStep onSaved={onSaved} />}
      {(step === "logo" || step === "caption_template") && <BrandingStep key={step} kind={step} onSaved={onSaved} />}
      {step === "cards" && <CardsStep onSaved={onSaved} />}
      {!step && <><p>Gerekli adımlar backend tarafından doğrulandı. Kartları isterseniz daha sonra ekleyebilirsiniz.</p><a href="#/dashboard">Kontrol Paneline git</a></>}
    </div>
    {setup.ready && <a className="action-link" href="#/dashboard">Kurulumu bitir</a>}
    <a href="#/dashboard">Kuruluma sonra devam et</a>
  </section>;
}
