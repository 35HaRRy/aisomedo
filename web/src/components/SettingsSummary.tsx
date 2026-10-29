import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { ClientOut } from "../api/openapi";
import { tr } from "../i18n";
import { OnboardingWizard } from "../onboarding/OnboardingWizard";
import { useSession } from "../session";
import { getDemoRuntime } from "../demo/runtime";

export function SettingsSummary({ client }: { client: ClientOut }) {
  const { invalidate } = useSession();
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState(false);
  async function remove() {
    if (!window.confirm(tr.settingsPage.removeWarning)) return;
    if (getDemoRuntime()) { window.location.hash = "#/welcome"; return; }
    setRemoving(true); setRemoveError(false);
    try {
      await api.revokeClient(client.id);
      invalidate();
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) invalidate();
      else setRemoveError(true);
    } finally {
      setRemoving(false);
    }
  }
  return <><header className="page-heading"><h1 data-tour="settings-overview">{tr.settings}</h1><p>{tr.settingsPage.intro}</p></header>
    <section className="summary-sheet"><div className="client-row"><div><h2>{tr.client}</h2><p>{client.name}</p></div>
      <button className="danger" onClick={() => void remove()} disabled={removing}>{tr.settingsPage.remove}</button></div>
      {removeError && <p role="alert">{tr.settingsPage.removeFailed}</p>}</section>
    <OnboardingWizard embedded />
  </>;
}
