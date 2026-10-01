import type { ClientOut, DashboardOut } from "../api/openapi";
import { tr } from "../i18n";
import { ConnectionSummary } from "./Dashboard";

export function SettingsSummary({ data, client }: { data: DashboardOut; client: ClientOut }) {
  return <><header className="page-heading"><h1>{tr.settings}</h1><p>{tr.settingsIntro}</p></header>
    <div className="settings-grid"><section className="summary-sheet"><h2>{tr.client}</h2><p>{client.name}</p></section>
      <section className="summary-sheet"><h2>{tr.plan}</h2><p>{tr.cadence}</p>
        <dl><div><dt>{tr.state}</dt><dd>{data.plan.enabled ? tr.enabled : tr.disabled}</dd></div>
          <div><dt>{tr.firstDate}</dt><dd>{data.plan.anchor_date ?? tr.unset}</dd></div>
          <div><dt>{tr.localTime}</dt><dd>{data.plan.anchor_time ?? tr.unset}</dd></div></dl>
        <small>{tr.timezone}</small>
      </section></div><ConnectionSummary data={data} />
  </>;
}
