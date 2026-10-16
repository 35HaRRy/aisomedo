import type { DashboardOut } from "../api/openapi";
import { useRef, useState } from "react";
import { api } from "../api/client";
import { formatDate, statusLabel, tr } from "../i18n";

export function PendingActions({ data }: { data: DashboardOut }) {
  return <section className="pending-section" aria-labelledby="pending-title">
    <h2 id="pending-title">{tr.pending}</h2>
    {data.pending_actions.length === 0 ? <><h3>{tr.noPending}</h3><p>{tr.noPendingHelp}</p></>
      : <ul className="action-list">{data.pending_actions.map(action => <li key={`${action.occurrence_id}-${action.review_id}`}>
        <div><h3>{statusLabel(action.state)}</h3><p>{formatDate(action.due_at)}</p></div>
        <a className="action-link" href={action.review_id ? `#/package?review=${action.review_id}` : `#/package?occurrence=${action.occurrence_id}${action.package_folder ? `&folder=${encodeURIComponent(action.package_folder)}` : ""}`}>
          {action.review_id ? tr.reviewSummary : tr.openPackage}
        </a>
      </li>)}</ul>}
  </section>;
}

export function ConnectionSummary({ data }: { data: DashboardOut }) {
  return <section className="connections" aria-labelledby="connections-title">
    <h2 id="connections-title">{tr.systems}</h2>
    <dl>
      <div><dt>{tr.instagram}</dt><dd><span className={`status status-${data.instagram.health}`}>{statusLabel(data.instagram.health)}</span><small>{data.instagram.username ? `@${data.instagram.username}` : tr.noAccount}</small></dd></div>
      <div><dt>{tr.worker}</dt><dd><span className={`status status-${data.worker.status}`}>{statusLabel(data.worker.status)}</span>{data.worker.phase && <small>{statusLabel(data.worker.phase)}</small>}</dd></div>
    </dl><p className="muted">{tr.workerHelp}</p>
  </section>;
}

export function Dashboard({ data }: { data: DashboardOut }) {
  const [requested, setRequested] = useState(false), [occurrence, setOccurrence] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const flight = useRef(false);
  async function requestReview() {
    if (flight.current) return;
    flight.current = true; setRequested(true);
    try { setOccurrence((await api.manualPublish()).id); }
    catch { setFailed(true); }
  }
  return <><header className="page-heading"><h1>{tr.dashboard}</h1><p>{tr.dashboardIntro}</p></header>
    <PendingActions data={data} />
    <div className="dashboard-columns">
      <div className="publishing-summary">
        <section><h2>{tr.packageTitle}</h2>
          <h3>{data.package?.folder_name ?? tr.noPackage}</h3>
          <p>{data.package ? statusLabel(data.package.status) : tr.noPackageHelp}</p>
          <a href="#/package">{tr.openPackage}</a>
          <p>{tr.manualHelp}</p>
          <button disabled={requested || data.pending_actions.length > 0 || !navigator.onLine} onClick={() => void requestReview()}>{tr.manualReview}</button>
          {occurrence !== null && <p><a href={`#/package?occurrence=${occurrence}${data.package ? `&folder=${encodeURIComponent(data.package.folder_name)}` : ""}`}>{tr.manualContinue}</a></p>}
          {failed && <p role="alert">{tr.manualUncertain}</p>}
        </section>
        <section><h2>{tr.nextSlot}</h2>
          <h3 className="slot-date">{data.next_slot ? formatDate(data.next_slot.due_at) : tr.noSlot}</h3>
          {data.next_slot && <p>{statusLabel(data.next_slot.kind)}</p>}
          <small>{tr.timezone}</small>
        </section>
      </div>
      <ConnectionSummary data={data} />
    </div>
  </>;
}
