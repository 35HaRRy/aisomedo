import type { ActivityPageOut } from "../api/openapi";
import { formatDate, tr } from "../i18n";

export function ActivitySummary({ data }: { data: ActivityPageOut }) {
  return data.events.length ? <ol className="activity-list">{data.events.map(event => <li key={event.id}>
    <div><h2>{tr.events[event.action] ?? tr.eventFallback}</h2>
      <p>{typeof event.actor === "string" ? tr.system : event.actor.name}</p></div>
    <time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time>
  </li>)}</ol> : <p>{tr.noActivity}</p>;
}
