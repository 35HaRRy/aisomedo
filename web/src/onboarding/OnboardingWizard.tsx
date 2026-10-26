import { useEffect, useRef, useState } from "react";
import { ReminderSettings } from "../components/ReminderSettings";
import { tr } from "../i18n";
import { firstIncompleteRequired } from "./state";
import type { OnboardingStep } from "./types";
import { useOnboarding } from "./useOnboarding";
import { InstagramStep } from "./InstagramStep";
import { ConsentStep } from "./ConsentStep";
import { PlanStep } from "./PlanStep";
import { BrandingStep } from "./BrandingStep";
import { CardsStep } from "./CardsStep";
import { SetupActionTarget } from "./forms";

export const stepTitles: Record<OnboardingStep, string> = {
  pairing: "Tarayıcı eşleştirmesi", instagram: "Instagram bağlantısı", schedule: "Dojo Yayın Planı",
  consent: "Medya rızası", logo: "Dojo logosu", caption_template: "Açıklama şablonu", cards: "İsteğe bağlı kartlar",
  reminders: "Hatırlatmalar",
};
export function OnboardingWizard({ embedded = false }: { embedded?: boolean }) {
  const { setup, error, refresh } = useOnboarding();
  const [selected, setSelected] = useState<OnboardingStep | null | undefined>(embedded ? "reminders" : undefined);
  const [saved, setSaved] = useState(false);
  const advancing = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const progress = useRef<HTMLOListElement>(null);
  const [actionTarget, setActionTarget] = useState<HTMLDivElement | null>(null);
  const step = selected === undefined ? (setup ? firstIncompleteRequired(setup.checklist) : null) : selected;
  useEffect(() => {
    if (!setup || selected !== undefined) return;
    const next = firstIncompleteRequired(setup.checklist);
    setSelected(next ?? (advancing.current && !setup.checklist.find(item => item.key === "cards")?.complete ? "cards" : null));
    advancing.current = false;
  }, [setup, selected]);
  const onSaved = () => {
    if (embedded) { setSaved(true); heading.current?.focus(); return; }
    advancing.current = true; setSelected(undefined);
  };
  useEffect(() => { heading.current?.focus(); }, [step]);
  useEffect(() => {
    const rail = progress.current, active = rail?.querySelector<HTMLElement>('[aria-current="step"]');
    if (rail && active) rail.scrollTo?.({ left: active.offsetLeft - rail.offsetLeft - (rail.clientWidth - active.clientWidth) / 2 });
  }, [step, setup]);
  if (!setup) return error ? <div role="alert">{tr.loadError}<button onClick={() => void refresh().catch(() => {})}>{tr.retry}</button></div> : <p role="status">{tr.loading}</p>;
  const items: Array<{ key: string; complete?: boolean; required?: boolean }> = [...setup.checklist];
  if (embedded) {
    const consent = items.findIndex(item => item.key === "consent");
    items.splice(consent < 0 ? items.length : consent, 0, { key: "reminders" });
  }
  const title = step ? stepTitles[step] : "Kurulum tamamlandı";
  return <section className="onboarding">
    {!embedded && error && <div role="alert" className="notice"><p>{tr.stale}</p></div>}
    {!embedded && <p className="setup-intro">İlk kurulum · Kaydedilen adımlar korunur</p>}
    <div className="setup-widget">
    <ol ref={progress} aria-label="Kurulum adımları" className="onboarding-progress">{items.map((item, index) => <li key={item.key} data-complete={item.complete}>
      <button aria-current={step === item.key ? "step" : undefined} onClick={() => { setSelected(item.key as OnboardingStep); setSaved(false); }}>
        <span className="step-marker" aria-hidden="true">{item.complete ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m5 12 4 4L19 6" /></svg> : index + 1}</span>
        <span>{stepTitles[item.key as OnboardingStep]}{item.key !== "reminders" && <> <small>{item.complete ? "Tamamlandı" : item.required === false ? "İsteğe bağlı" : "Bekliyor"}</small></>}</span>
      </button></li>)}</ol>
    <div className="setup-content">
    <header className="setup-heading">
      {embedded ? <h2 ref={heading} tabIndex={-1}>{title}</h2> : <h1 ref={heading} tabIndex={-1}>{title}</h1>}
      <p>Dojo yayınları için bağlantı, plan ve medya tercihlerini hazırlayın.</p></header>
    {embedded && saved && <p role="status">{tr.settingsPage.saved}</p>}
    <SetupActionTarget.Provider value={actionTarget}>
    <div className="setup-form" onChange={() => setSaved(false)} onSubmitCapture={() => setSaved(false)} onClick={() => setSaved(false)}>{step === "pairing" && <p>Bu tarayıcı eşleştirildi.</p>}
      {step === "instagram" && <InstagramStep onSaved={onSaved} />}
      {step === "consent" && <ConsentStep readOnly={embedded} onSaved={onSaved} />}
      {step === "schedule" && <PlanStep onSaved={onSaved} />}
      {(step === "logo" || step === "caption_template") && <BrandingStep key={step} kind={step} onSaved={onSaved} />}
      {step === "cards" && <CardsStep onboarding={!embedded} onSaved={onSaved} />}
      {step === "reminders" && <ReminderSettings onSaved={onSaved} />}
      {!step && <p>Gerekli adımlar backend tarafından doğrulandı. Kartları isterseniz daha sonra ekleyebilirsiniz.</p>}
    </div>
    </SetupActionTarget.Provider>
    </div>
    {!embedded && <footer className="setup-actions" role="group" aria-label="Kurulum işlemleri">
      <div className="step-actions" ref={setActionTarget} />
      {error && <button onClick={() => void refresh().catch(() => {})}>{tr.retry}</button>}
      {setup.ready ? <a className="action-link" href="#/dashboard">Kurulumu bitir</a> : <a href="#/dashboard">Kuruluma sonra devam et</a>}
    </footer>}
    </div>
  </section>;
}
