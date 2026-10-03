import type { DashboardOut } from "../api/openapi";
import { formatDate, statusLabel, tr } from "../i18n";
import { PendingActions } from "./Dashboard";
import { PackageManager } from "../packages/PackageManager";

export function PackageSummary({ data, reviewId }: { data: DashboardOut; reviewId: number | null }) {
  const found = data.pending_actions.some(action => action.review_id === reviewId);
  return <><header className="page-heading"><h1>{tr.package}</h1><p>{tr.packageIntro}</p></header>
    {reviewId !== null && !found && <p role="status" className="notice">{tr.reviewGone}</p>}
    <section className="summary-sheet"><h2>{data.package?.folder_name ?? tr.noPackage}</h2>
      {data.package ? <dl><div><dt>{tr.state}</dt><dd>{statusLabel(data.package.status)}</dd></div>
        <div><dt>{tr.createdAt}</dt><dd>{formatDate(data.package.created_at)}</dd></div></dl> : <p>{tr.noPackageHelp}</p>}
    </section>
    <PackageManager />
    <PendingActions data={data} />
    <p className="muted">{tr.reviewNotice}</p>
  </>;
}
