import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type PublicationOutcome } from "../api/client";
import type { DashboardOut } from "../api/openapi";
import { formatDate, tr } from "../i18n";
import { useSession } from "../session";
import { useLiveData } from "../useLiveData";
import { PackageManager } from "../packages/PackageManager";
import { CollapsiblePanel } from "../components/CollapsiblePanel";
import { MediaActionIcon } from "../packages/MediaActionIcon";
import { SavedReelPanel } from "../packages/SavedReelPanel";
import { usePackageEditorContext } from "../packages/PackageEditorProvider";
import { workspaceHref } from "../demo/routing";

type Decision = "approve" | "skip" | "reschedule";
const copy = tr.review;

function ReviewPanel({ id, onRefresh, stale }: { id: number; onRefresh: () => void; stale: boolean }) {
  const [checking, setChecking] = useState(true);
  const load = useCallback(async (signal: AbortSignal) => {
    try { const detail = await api.review(id, signal); if (!signal.aborted) setChecking(false); return detail; }
    catch (error) { if (error instanceof ApiError && error.status === 404) { if (!signal.aborted) setChecking(false); return null; } throw error; }
  }, [id]);
  const snapshot = useLiveData(load, true, ["publication"]), { invalidate } = useSession();
  const detail = snapshot.data, review = detail?.review;
  const [decision, setDecision] = useState<Decision | null>(null);
  const [time, setTime] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [done, setDone] = useState<Decision | null>(null);
  const [publication, setPublication] = useState<PublicationOutcome | null>(null);
  const [publicationFailure, setPublicationFailure] = useState<PublicationOutcome | null>(null);
  const [nextRegular, setNextRegular] = useState<string | null>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { setPreviewReady(false); setPreviewFailed(false); setDecision(null); }, [detail?.preview_url, review?.version]);
  const publishing = review?.status === "publishing" || review?.status === "pending" && publication?.status === "publishing";
  const gone = snapshot.updatedAt !== null && (!review || !["pending", "failed", "uncertain", "publishing"].includes(review.status));
  const blocked = checking || busy || publishing || stale || snapshot.error || !navigator.onLine || !detail?.render_ready || gone || !!done || !!message;
  // datetime-local has no zone. This flow explicitly asks for Istanbul (UTC+03:00), not browser time.
  const dueAt = time ? `${time}:00+03:00` : "";
  const future = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(time) && new Date(dueAt).getTime() > Date.now()
    && (!detail?.next_regular_at || new Date(dueAt).getTime() < new Date(detail.next_regular_at).getTime());
  const refresh = () => {
    if (busy) return;
    setChecking(true); setMessage(null); setDecision(null); setPublicationFailure(null); setPreviewReady(false); setPreviewFailed(false); setReload(value => value + 1);
    snapshot.retry(); onRefresh();
  };
  const resolve = async () => {
    if (!review || !decision || blocked || decision === "approve" && !previewReady || decision === "reschedule" && !future || request.current) return;
    const current = new AbortController(); request.current = current; setBusy(true);
    try {
      if (decision === "approve") {
        const result = await api.approveReview(id, { version: review.version }, current.signal);
        if (!current.signal.aborted) {
          setPublication(result.publication);
          if (result.publication && ["failed", "uncertain", "publishing"].includes(result.publication.status)) {
            // Keep observing the review until confirmed or available for retry.
            setPublicationFailure(result.publication.status === "publishing" ? null : result.publication);
            setDecision(null);
            snapshot.retry(); onRefresh();
            return;
          }
        }
      }
      else if (decision === "skip") {
        const result = await api.skipReview(id, { version: review.version, confirmed: true }, current.signal);
        setNextRegular(result.next_regular_at);
      } else await api.rescheduleReview(id, { version: review.version, new_due_at: dueAt }, current.signal);
      if (!current.signal.aborted) { setPublicationFailure(null); setDone(decision); setDecision(null); snapshot.retry(); onRefresh(); }
    } catch (error) {
      if (current.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) invalidate();
      else {
        const handled = error instanceof ApiError && (error.status === 404 || error.status === 409 && error.detail?.includes("already handled"));
        setMessage(handled ? tr.reviewGone : error instanceof ApiError && error.status === 409 ? copy.conflict : copy.uncertain);
        setDecision(null); setPreviewReady(false); snapshot.retry(); onRefresh();
      }
    } finally { request.current = null; if (!current.signal.aborted) setBusy(false); }
  };
  const publicationPending = publishing;
  useEffect(() => {
    if (publication?.status === "publishing" && review?.status === "approved") setDone("approve");
  }, [publication?.status, review?.status]);
  const outcome = review && ["failed", "uncertain"].includes(review.status) ? review.status : publicationFailure?.status;
  const failureMessage = review?.instagram_fail_message ?? publicationFailure?.error;
  return <>
    <header className="page-heading"><h1>{copy.title}</h1><p>{copy.intro}</p></header>
    {!snapshot.updatedAt && !snapshot.error && <p role="status">{tr.loading}</p>}
    {snapshot.error && <p role="alert" className="notice">{copy.readError}</p>}
    {!done && publicationPending && <p role="status" className="notice">{copy.publicationPending}</p>}
    {outcome && <div role="alert" className="notice">
      <p>{outcome === "uncertain" ? copy.publicationUncertain : copy.publicationFailed}</p>
      {failureMessage && <p>{failureMessage}</p>}
    </div>}
    {done ? <div role="status" className="notice">
      <p>{publicationPending ? copy.publicationPending : copy.done[done]}</p>
      {done === "skip" && <p>{copy.nextRegular}: {nextRegular ? formatDate(nextRegular) : copy.noRegular}</p>}
    </div>
      : gone ? <p role="status" className="notice">{tr.reviewGone}</p> : <>
        {message && <p role="alert" className="notice">{message}</p>}
        {review && <CollapsiblePanel className="summary-sheet review-sheet" title={review.package_folder} actions={<>
          <button className="media-icon-button" disabled={busy} onClick={refresh} aria-label={copy.refresh} title={copy.refresh}><MediaActionIcon action="refresh" /></button>
          {!publishing && <a className="media-icon-button" href={workspaceHref("#/package")} aria-label={copy.edit} title={copy.edit}><MediaActionIcon action="edit" /></a>}
        </>}>
          {review.status in copy.statuses && <p role="status">{copy.statuses[review.status as keyof typeof copy.statuses]}</p>}
          <div className="review-content"><div data-tour="review-preview">
            {detail?.render_ready && detail.preview_url ? <video key={`${detail.preview_url}-${reload}`} src={detail.preview_url} controls playsInline preload="auto" aria-label={copy.video}
              onLoadedData={() => { setPreviewReady(true); setPreviewFailed(false); }} onError={() => { setPreviewFailed(true); setPreviewReady(false); }} />
              : <p role="status">{copy.stale}</p>}
            {previewFailed && <p role="status" className="notice">{tr.editor.previewFailed}</p>}
          </div><div className="review-decision" data-tour="review-decision"><h3>{copy.caption}</h3><p className="review-caption">{review.caption ?? copy.noCaption}</p>
            <p className="muted">{copy.previewHelp}</p>
            <div className="upload-actions"><button className="primary icon-label-button" disabled={blocked || !previewReady} onClick={() => setDecision("approve")}><MediaActionIcon action="approve" />{copy.approve}</button>
              <button className="icon-label-button" disabled={blocked} onClick={() => setDecision("skip")}><MediaActionIcon action="skip" />{copy.skip}</button>
              <button className="icon-label-button" disabled={blocked} onClick={() => setDecision("reschedule")}><MediaActionIcon action="schedule" />{copy.reschedule}</button></div>
            {decision && <form className="review-confirmation" onSubmit={event => { event.preventDefault(); void resolve(); }}><fieldset disabled={blocked}>
              <legend>{copy.confirm[decision]}</legend><p>{decision === "approve" ? copy.approveWarning : decision === "skip" ? copy.skipWarning : copy.rescheduleWarning}</p>
              {decision === "skip" && <p>{copy.nextRegular}: {detail?.next_regular_at ? formatDate(detail.next_regular_at) : copy.noRegular}</p>}
              {decision === "reschedule" && <><label htmlFor="review-time">{copy.newTime}</label><input id="review-time" type="datetime-local" value={time} required aria-describedby="review-time-help" onChange={event => setTime(event.target.value)} /><p id="review-time-help" className="muted">{copy.futureTime}</p>{detail?.next_regular_at && <p>{copy.nextRegular}: {formatDate(detail.next_regular_at)}</p>}</>}
              <div className="upload-actions"><button type="button" onClick={() => setDecision(null)}>{tr.editor.cancel}</button><button className={decision === "approve" ? "danger" : "primary"} disabled={decision === "reschedule" && !future || decision === "approve" && !previewReady}>{copy.confirm[decision]}</button></div>
            </fieldset></form>}
          </div></div>
        </CollapsiblePanel>}
      </>}
    <div className="upload-actions review-navigation">{(!review || gone || done) && <button disabled={busy} onClick={refresh}>{copy.refresh}</button>}<a href={workspaceHref("#/dashboard")}>{copy.back}</a></div>
  </>;
}

function DueContinuation({ data, occurrenceId, packageFolder, onRefresh, stale }: { data: DashboardOut; occurrenceId: number; packageFolder: string | null; onRefresh: () => void; stale: boolean }) {
  const actions = data.pending_actions.filter(item => item.occurrence_id === occurrenceId);
  const action = actions.find(item => item.state === "review_ready" && (!packageFolder || item.package_folder === packageFolder)) ?? actions[0];
  const boundFolder = useRef(packageFolder);
  if (!boundFolder.current && action?.package_folder) boundFolder.current = action.package_folder;
  const folder = boundFolder.current;
  const changed = !!folder && data.package?.folder_name !== folder;
  const boundReview = useRef<number | null>(null);
  if (!changed && action?.state === "review_ready" && action.review_id !== null) boundReview.current = action.review_id;
  if (boundReview.current !== null) return <ReviewPanel key={boundReview.current} id={boundReview.current} onRefresh={onRefresh} stale={stale || changed} />;
  if (changed) return <p role="status" className="notice">{copy.changedPackage} <a href={workspaceHref("#/dashboard")}>{copy.back}</a></p>;
  if (!action) return <p role="status" className="notice">{tr.reviewGone} <a href={workspaceHref("#/dashboard")}>{copy.back}</a></p>;
  return <><header className="page-heading"><h1>{tr.package}</h1><p>{tr.packageIntro}</p></header><PackageManager /><SavedReelPanel /></>;
}

export function ReviewFlow(props: { data: DashboardOut; reviewId: number | null; occurrenceId: number | null; packageFolder: string | null; onRefresh: () => void; stale: boolean }) {
  const editor = usePackageEditorContext(), snapshot = editor.snapshot;
  const requested = useRef<string | null>(null);
  const continuation = useRef(props.occurrenceId);
  const openedReview = useRef(false);
  const action = props.data.pending_actions.find(item => continuation.current !== null
    ? item.occurrence_id === continuation.current : props.reviewId !== null
    ? item.review_id === props.reviewId : item.occurrence_id === props.occurrenceId);
  if (action?.state === "review_ready") openedReview.current = true;
  // Publishing can briefly mark an opened review as preparing. Keep its result mounted.
  if (!openedReview.current && action && ["preparing", "empty_package"].includes(action.state)) continuation.current = action.occurrence_id;
  useEffect(() => {
    if (props.stale || !editor.canEdit || !snapshot || !action ||
      !["empty_package", "preparing"].includes(action.state) || !(Date.parse(action.due_at) <= Date.now()) ||
      snapshot.package.folder_name !== action.package_folder || props.packageFolder && props.packageFolder !== action.package_folder ||
      !snapshot.montage.order.length || snapshot.montage.over_limit || !snapshot.montage.duration_complete ||
      ![undefined, null, "missing", "stale"].includes(snapshot.render_status)) return;
    const key = `${action.occurrence_id}:${snapshot.package.id}:${snapshot.content_revision}`;
    if (requested.current === key) return;
    requested.current = key;
    void editor.renderPreview();
  }, [action, editor, snapshot, props.stale, props.packageFolder]);
  return continuation.current !== null ? <DueContinuation {...props} occurrenceId={continuation.current} />
    : props.reviewId !== null ? <ReviewPanel key={props.reviewId} id={props.reviewId} onRefresh={props.onRefresh} stale={props.stale} /> : null;
}
