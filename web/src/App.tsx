import { useEffect, useRef } from "react";
import { api } from "./api/client";
import { ContractBanner } from "./api/compat";
import { ActivitySummary } from "./components/ActivitySummary";
import { Dashboard } from "./components/Dashboard";
import { PackageSummary } from "./components/PackageSummary";
import { PairingForm } from "./components/PairingForm";
import { SettingsSummary } from "./components/SettingsSummary";
import { formatDate, tr } from "./i18n";
import { useNavigation, type Area } from "./navigation";
import { SessionProvider, useSession } from "./session";
import { useLiveData } from "./useLiveData";
import { OnboardingProvider, useOnboarding } from "./onboarding/useOnboarding";
import { OnboardingWizard } from "./onboarding/OnboardingWizard";

function ErrorNotice({ stale, retry }: { stale: boolean; retry: () => void }) {
  return <div role="alert" className="notice"><p>{stale ? tr.stale : tr.loadError}</p>
    <button onClick={retry}>{tr.retry}</button></div>;
}

function PairedShell() {
  const { client } = useSession();
  const { area, reviewId } = useNavigation();
  const onboarding = useOnboarding();
  const opened = useRef(false);
  useEffect(() => {
    if (!onboarding.setup || opened.current) return;
    opened.current = true;
    if (!onboarding.setup.ready && area === "dashboard") window.location.hash = "#/onboarding";
  }, [onboarding.setup, area]);
  const snapshot = useLiveData(api.dashboard, area !== "onboarding");
  const activity = useLiveData(api.activity, area === "activity");
  const areas: Exclude<Area, "onboarding">[] = ["dashboard", "package", "activity", "settings"];
  useEffect(() => { document.title = `${area === "onboarding" ? "Kurulum" : tr[area]} · ${tr.app}`; }, [area]);
  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#/dashboard">{tr.app}</a>
      <nav aria-label={tr.navigation}>{areas.map(item => <a key={item} href={`#/${item}`} aria-current={area === item ? "page" : undefined}>{tr[item]}</a>)}</nav>
      <div className="sidebar-foot"><span>{tr.client}</span><strong>{client?.name}</strong></div>
    </aside>
    <main id="content" className="main-content" tabIndex={-1}>
      <div className="refresh-status"><span>{tr.live}</span>{snapshot.updatedAt && <span>{tr.lastUpdated}: {formatDate(snapshot.updatedAt)}</span>}</div>
      {area !== "onboarding" && onboarding.error && <ErrorNotice stale={!!onboarding.setup} retry={() => void onboarding.refresh().catch(() => {})} />}
      {area !== "onboarding" && snapshot.error && <ErrorNotice stale={!!snapshot.data} retry={snapshot.retry} />}
      {area !== "onboarding" && !snapshot.data && !snapshot.error && <p role="status">{tr.loading}</p>}
      {area === "onboarding" ? <OnboardingWizard /> : area === "activity" ? <><header className="page-heading"><h1>{tr.activity}</h1><p>{tr.activityIntro}</p></header>
        {activity.error && <ErrorNotice stale={!!activity.data} retry={activity.retry} />}
        {activity.data ? <ActivitySummary data={activity.data} /> : !activity.error && <p role="status">{tr.loading}</p>}
      </> : snapshot.data && <>
        {area === "dashboard" && <Dashboard data={snapshot.data} />}
        {area === "package" && <PackageSummary data={snapshot.data} reviewId={reviewId} />}
        {area === "settings" && client && <SettingsSummary data={snapshot.data} client={client} />}
      </>}
    </main>
  </div>;
}

function SessionGate() {
  const session = useSession();
  if (session.status === "paired") return <OnboardingProvider key={session.generation}><PairedShell /></OnboardingProvider>;
  if (session.status === "unpaired") return <PairingForm />;
  return <main className="session-loading" id="content" tabIndex={-1}><h1>{tr.app}</h1>
    {session.status === "error" ? <ErrorNotice stale={false} retry={() => void session.restore()} /> : <p role="status">{tr.loading}</p>}
  </main>;
}

export function App() {
  return <SessionProvider><a className="skip-link" href="#content" onClick={event => {
    event.preventDefault(); document.getElementById("content")?.focus();
  }}>{tr.skip}</a><ContractBanner /><SessionGate /></SessionProvider>;
}
