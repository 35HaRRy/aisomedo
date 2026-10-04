import { useRef, useState, type ReactNode } from "react";
import type { ClientOut } from "../api/openapi";
import { tr } from "../i18n";
import { BrandingStep } from "../onboarding/BrandingStep";
import { CardsStep } from "../onboarding/CardsStep";
import { ConsentStep } from "../onboarding/ConsentStep";
import { InstagramStep } from "../onboarding/InstagramStep";
import { PlanStep } from "../onboarding/PlanStep";
import { ReminderSettings } from "./ReminderSettings";

function SettingsSection({ title, onRefresh, children }: { title: string; onRefresh: () => void; children: (onSaved: () => void) => ReactNode }) {
  const [revision, setRevision] = useState(0);
  const [acknowledged, setAcknowledged] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  function saved() {
    setRevision(value => value + 1); setAcknowledged(true); onRefresh(); heading.current?.focus();
  }
  return <section className="summary-sheet settings-section" aria-label={title}>
    <h2 ref={heading} tabIndex={-1}>{title}</h2>
    {acknowledged && <p role="status">{tr.settingsPage.saved}</p>}
    <div key={revision} onChange={() => setAcknowledged(false)} onSubmitCapture={() => setAcknowledged(false)} onClick={() => setAcknowledged(false)}>{children(saved)}</div>
  </section>;
}

export function SettingsSummary({ client, onRefresh }: { client: ClientOut; onRefresh: () => void }) {
  return <><header className="page-heading"><h1>{tr.settings}</h1><p>{tr.settingsPage.intro}</p><a href="#/onboarding">{tr.settingsPage.openSetup}</a></header>
    <section className="summary-sheet"><h2>{tr.client}</h2><p>{client.name}</p></section>
    <div className="settings-grid">
      <SettingsSection title={tr.plan} onRefresh={onRefresh}>{onSaved => <PlanStep onSaved={onSaved} />}</SettingsSection>
      <SettingsSection title={tr.settingsPage.reminders} onRefresh={onRefresh}>{onSaved => <ReminderSettings onSaved={onSaved} />}</SettingsSection>
      <SettingsSection title={tr.settingsPage.logo} onRefresh={onRefresh}>{onSaved => <BrandingStep kind="logo" onSaved={onSaved} />}</SettingsSection>
      <SettingsSection title={tr.settingsPage.caption} onRefresh={onRefresh}>{onSaved => <BrandingStep kind="caption_template" onSaved={onSaved} />}</SettingsSection>
      <SettingsSection title={tr.settingsPage.cards} onRefresh={onRefresh}>{onSaved => <CardsStep onboarding={false} onSaved={onSaved} />}</SettingsSection>
      <SettingsSection title={tr.instagram} onRefresh={onRefresh}>{onSaved => <InstagramStep onSaved={onSaved} />}</SettingsSection>
      <SettingsSection title={tr.settingsPage.consent} onRefresh={onRefresh}>{onSaved => <ConsentStep readOnly onSaved={onSaved} />}</SettingsSection>
    </div>
  </>;
}
