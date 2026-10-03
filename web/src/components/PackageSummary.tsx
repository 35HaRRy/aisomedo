import type { DashboardOut } from "../api/openapi";
import { formatDate, statusLabel, tr } from "../i18n";
import { PendingActions } from "./Dashboard";
import { PackageManager } from "../packages/PackageManager";
import { ReviewFlow } from "../reviews/ReviewFlow";

export function PackageSummary({ data, reviewId, occurrenceId, packageFolder, onRefresh, stale }: { data: DashboardOut; reviewId: number | null; occurrenceId: number | null; packageFolder: string | null; onRefresh: () => void; stale: boolean }) {
  if (reviewId !== null || occurrenceId !== null) return <ReviewFlow key={`${reviewId}-${occurrenceId}-${packageFolder}`} data={data} reviewId={reviewId} occurrenceId={occurrenceId} packageFolder={packageFolder} onRefresh={onRefresh} stale={stale} />;
  return <><header className="page-heading"><h1>{tr.package}</h1><p>{tr.packageIntro}</p></header>
    <section className="summary-sheet"><h2>{data.package?.folder_name ?? tr.noPackage}</h2>
      {data.package ? <dl><div><dt>{tr.state}</dt><dd>{statusLabel(data.package.status)}</dd></div>
        <div><dt>{tr.createdAt}</dt><dd>{formatDate(data.package.created_at)}</dd></div></dl> : <p>{tr.noPackageHelp}</p>}
    </section>
    <PackageManager />
    <PendingActions data={data} />
    <p className="muted">{tr.reviewNotice}</p>
  </>;
}
