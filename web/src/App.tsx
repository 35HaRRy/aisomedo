import { useEffect, useRef, useState } from "react";
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
import { LiveProvider, useLivePhase } from "./liveProvider";
import { MediaActionIcon } from "./packages/MediaActionIcon";
import { ThemeToggle } from "./theme";
import { SocialLinks } from "./components/SocialLinks";
import "driver.js/dist/driver.css";
import { LandingPage } from "./promotion/LandingPage";
import { Walkthrough, replayTours } from "./promotion/Walkthrough";

function ErrorNotice({ stale, retry }: { stale: boolean; retry: () => void }) {
  return <div role="alert" className="notice"><p>{stale ? tr.stale : tr.loadError}</p>
    <button onClick={retry}>{tr.retry}</button></div>;
}

function PairedShell() {
  const { client } = useSession();
  const editor = usePackageEditorContext();
  const { area, reviewId, occurrenceId, packageFolder, navigate } = editor.navigation;
  const onboarding = useOnboarding();
  const livePhase = useLivePhase();
  const opened = useRef(false);
  useEffect(() => {
    if (!onboarding.setup) return;
    if (!onboarding.setup.ready && (area === "settings" || (area === "dashboard" && !opened.current))) {
      opened.current = true;
      window.location.hash = "#/onboarding";
    }
  }, [onboarding.setup, area]);
  const dashboardVisible = area === "dashboard" || area === "package";
  const snapshot = useLiveData(api.dashboard, dashboardVisible, ["dashboard"]);
  const activity = useLiveData(api.activity, area === "activity", ["activity"]);
  const areas: Exclude<Area, "onboarding" | "welcome">[] = ["dashboard", "package", "completed", "activity", "settings"];
  useEffect(() => { document.title = `${area === "onboarding" ? "Kurulum" : area === "welcome" ? "Tanıtım" : tr[area]} · ${tr.app}`; }, [area]);
  if (area === "welcome") return <LandingPage onOpenApp={() => { void navigate("#/dashboard"); }} />;
  return <UploadProvider><div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#/dashboard" onClick={event => { event.preventDefault(); void navigate("#/dashboard"); }}><span className="brand-mark" aria-hidden="true">A</span><span>{tr.app}<small>Video &amp; Reel Stüdyosu</small></span></a>
      <nav aria-label={tr.navigation}>{areas.map(item => <a key={item} data-tour={item === "package" ? "package-link" : undefined} href={`#/${item}`} onClick={event => { event.preventDefault(); void navigate(`#/${item}`); }} aria-current={area === item ? "page" : undefined}><MediaActionIcon action={item} /><span>{tr[item]}</span></a>)}</nav>
      <div className="sidebar-foot"><details className="promotion-help" data-tour="help"><summary>Yardım</summary><button onClick={() => { void navigate("#/welcome"); }}>Uygulama tanıtımı</button><button onClick={event => { event.currentTarget.closest("details")?.removeAttribute("open"); if (client) replayTours(client.id); }}>Tanıtımları yeniden başlat</button></details><div className="paired-client"><span>{tr.client}</span><strong>{client?.name}</strong></div><SocialLinks /><ThemeToggle /></div>
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
      </> : area === "settings" && client ? <SettingsSummary client={client} /> : snapshot.data && <>
        {area === "dashboard" && <Dashboard data={snapshot.data} stale={snapshot.error} onRefresh={snapshot.retry} />}
        {area === "package" && <PackageSummary data={snapshot.data} reviewId={reviewId} occurrenceId={occurrenceId} packageFolder={packageFolder} onRefresh={snapshot.retry} stale={snapshot.error} />}
      </>}
    </main>
    {client && (area === "dashboard" || area === "package" || area === "settings") && <Walkthrough clientId={client.id} tour={area === "package" && (reviewId !== null || occurrenceId !== null) ? "review" : area} enabled={livePhase === "live" && !!onboarding.setup?.ready && !onboarding.error && (area === "settings" || !!snapshot.data && !snapshot.error)} />}
  </div></UploadProvider>;
}

function SessionGate() {
  const session = useSession();
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  if (session.status !== "paired" && (hash === "#/welcome" || ((!hash || hash === "#/") && session.status === "unpaired")))
    return <LandingPage onOpenApp={() => { window.location.hash = "#/pair"; setHash("#/pair"); }} />;
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
