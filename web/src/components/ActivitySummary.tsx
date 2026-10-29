import type { ActivityPageOut } from "../api/openapi";
import { formatDate, tr } from "../i18n";
import { workspaceHref } from "../demo/routing";

export function ActivitySummary({ data }: { data: ActivityPageOut }) {
  return data.events.length ? <ol className="activity-list">{data.events.map(event => <li key={event.id}>
    <div><h2>{tr.events[event.action] ?? tr.eventFallback}</h2>
      <p>{typeof event.actor === "string" ? tr.system : event.actor.name}</p>
      {typeof event.details.review_id === "number" && Number.isSafeInteger(event.details.review_id) && event.details.review_id > 0 && <a href={workspaceHref(`#/package?review=${event.details.review_id}`)}>{tr.reviewSummary}</a>}
      {event.action === "review.created" && typeof event.details.review_id !== "number" && typeof event.details.occurrence_id === "number" && Number.isSafeInteger(event.details.occurrence_id) && event.details.occurrence_id > 0 && <a href={workspaceHref(`#/package?occurrence=${event.details.occurrence_id}${typeof event.details.package === "string" ? `&folder=${encodeURIComponent(event.details.package)}` : ""}`)}>{tr.reviewSummary}</a>}
      {event.action === "media.overwritten" && <div className="audit-overwrite">
        {typeof event.details.filename === "string" && <p><strong>{event.details.filename}</strong></p>}
        {typeof event.details.target_media_id === "string" && <p>{tr.auditTarget}: {event.details.target_media_id}</p>}
        {typeof event.details.media_id === "string" && <p>{tr.auditReplacement}: {event.details.media_id}</p>}
      </div>}</div>
    <time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time>
  </li>)}</ol> : <p>{tr.noActivity}</p>;
}
