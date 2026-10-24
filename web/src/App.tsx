import { useEffect, useRef } from "react";
import { api } from "./api/client";
import { ContractBanner } from "./api/compat";
import { ActivitySummary } from "./components/ActivitySummary";
import { Dashboard } from "./components/Dashboard";
import { PackageSummary } from "./components/PackageSummary";
import { CompletedPackages } from "./packages/CompletedPackages";
import { PairingForm } from "./components/PairingForm";
import { SettingsSummary } from "./components/SettingsSummary";
import { tr } from "./i18n";
import { type Area } from "./navigation";
import { SessionProvider, useSession } from "./session";
import { useLiveData } from "./useLiveData";
import { OnboardingProvider, useOnboarding } from "./onboarding/useOnboarding";
import { OnboardingWizard } from "./onboarding/OnboardingWizard";
import { UploadProvider } from "./uploads/UploadProvider";
import { PackageEditorProvider, usePackageEditorContext } from "./packages/PackageEditorProvider";
import { LiveProvider } from "./liveProvider";

function ErrorNotice({ stale, retry }: { stale: boolean; retry: () => void }) {
  return <div role="alert" className="notice"><p>{stale ? tr.stale : tr.loadError}</p>
    <button onClick={retry}>{tr.retry}</button></div>;
}

function PairedShell() {
  const { client } = useSession();
  const editor = usePackageEditorContext();
  const { area, reviewId, occurrenceId, packageFolder, navigate } = editor.navigation;
  const onboarding = useOnboarding();
  const opened = useRef(false);
  useEffect(() => {
    if (!onboarding.setup || opened.current) return;
    opened.current = true;
    if (!onboarding.setup.ready && area === "dashboard") window.location.hash = "#/onboarding";
  }, [onboarding.setup, area]);
  const dashboardVisible = area === "dashboard" || area === "package";
  const snapshot = useLiveData(api.dashboard, dashboardVisible, ["dashboard"]);
  const activity = useLiveData(api.activity, area === "activity", ["activity"]);
  const areas: Exclude<Area, "onboarding">[] = ["dashboard", "package", "completed", "activity", "settings"];
  useEffect(() => { document.title = `${area === "onboarding" ? "Kurulum" : tr[area]} · ${tr.app}`; }, [area]);
  return <UploadProvider><div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#/dashboard" onClick={event => { event.preventDefault(); void navigate("#/dashboard"); }}>{tr.app}</a>
      <nav aria-label={tr.navigation}>{areas.map(item => <a key={item} href={`#/${item}`} onClick={event => { event.preventDefault(); void navigate(`#/${item}`); }} aria-current={area === item ? "page" : undefined}>{tr[item]}</a>)}</nav>
      <div className="sidebar-foot"><span>{tr.client}</span><strong>{client?.name}</strong></div>
    </aside>
    <main id="content" className="main-content" tabIndex={-1}>
      {area !== "onboarding" && onboarding.error && <ErrorNotice stale={!!onboarding.setup} retry={() => void onboarding.refresh().catch(() => {})} />}
      {dashboardVisible && snapshot.error && <ErrorNotice stale={!!snapshot.data} retry={snapshot.retry} />}
      {dashboardVisible && !snapshot.data && !snapshot.error && <p role="status">{tr.loading}</p>}
      {area === "onboarding" ? <OnboardingWizard /> : area === "completed" ? <>
        <header className="page-heading"><h1>{tr.completed}</h1><p>{tr.packageManagement.readOnly}</p></header>
        <CompletedPackages onBack={() => void navigate("#/package")} />
      </> : area === "activity" ? <><header className="page-heading"><h1>{tr.activity}</h1><p>{tr.activityIntro}</p></header>
        {activity.error && <ErrorNotice stale={!!activity.data} retry={activity.retry} />}
        {activity.data ? <ActivitySummary data={activity.data} /> : !activity.error && <p role="status">{tr.loading}</p>}
      </> : area === "settings" && client ? <SettingsSummary client={client} onRefresh={snapshot.retry} /> : snapshot.data && <>
        {area === "dashboard" && <Dashboard data={snapshot.data} stale={snapshot.error} onRefresh={snapshot.retry} />}
        {area === "package" && <PackageSummary data={snapshot.data} reviewId={reviewId} occurrenceId={occurrenceId} packageFolder={packageFolder} onRefresh={snapshot.retry} stale={snapshot.error} />}
      </>}
    </main>
  </div></UploadProvider>;
}

function SessionGate() {
  const session = useSession();
  if (session.status === "paired") return <LiveProvider key={session.generation}><PackageEditorProvider><PairedWorkspace /></PackageEditorProvider></LiveProvider>;
  if (session.status === "unpaired") return <PairingForm />;
  return <main className="session-loading" id="content" tabIndex={-1}><h1>{tr.app}</h1>
    {session.status === "error" ? <ErrorNotice stale={false} retry={() => void session.restore()} /> : <p role="status">{tr.loading}</p>}
  </main>;
}

function PairedWorkspace() {
  const { navigation: { area } } = usePackageEditorContext();
  return <OnboardingProvider enabled={area === "onboarding" || area === "settings"}><PairedShell /></OnboardingProvider>;
}

export function App() {
  return <SessionProvider><a className="skip-link" href="#content" onClick={event => {
    event.preventDefault(); document.getElementById("content")?.focus();
  }}>{tr.skip}</a><ContractBanner /><SessionGate /></SessionProvider>;
}
