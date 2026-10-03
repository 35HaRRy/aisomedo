import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { DashboardOut } from "../api/openapi";
import { formatDate, tr } from "../i18n";
import { useSession } from "../session";
import { useLiveData } from "../useLiveData";
import { UploadPanel } from "../uploads/UploadPanel";

type Decision = "approve" | "skip" | "reschedule";
const copy = tr.review;

function ReviewPanel({ id, onRefresh, stale }: { id: number; onRefresh: () => void; stale: boolean }) {
  const [checking, setChecking] = useState(true);
  const load = useCallback(async (signal: AbortSignal) => {
    try { const detail = await api.review(id, signal); if (!signal.aborted) setChecking(false); return detail; }
    catch (error) { if (error instanceof ApiError && error.status === 404) { if (!signal.aborted) setChecking(false); return null; } throw error; }
  }, [id]);
  const snapshot = useLiveData(load), { invalidate } = useSession();
  const detail = snapshot.data, review = detail?.review;
  const [decision, setDecision] = useState<Decision | null>(null);
  const [time, setTime] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [done, setDone] = useState<Decision | null>(null);
  const [nextRegular, setNextRegular] = useState<string | null>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { setPreviewReady(false); setPreviewFailed(false); setDecision(null); }, [detail?.preview_url, review?.version]);
  const gone = snapshot.updatedAt !== null && (!review || review.status !== "pending");
  const blocked = checking || busy || stale || snapshot.error || !navigator.onLine || !detail?.render_ready || gone || !!done || !!message;
  // datetime-local has no zone. This flow explicitly asks for Istanbul (UTC+03:00), not browser time.
  const dueAt = time ? `${time}:00+03:00` : "";
  const future = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(time) && new Date(dueAt).getTime() > Date.now();
  const refresh = () => {
    if (busy) return;
    setChecking(true); setMessage(null); setDecision(null); setPreviewReady(false); setPreviewFailed(false); setReload(value => value + 1);
    snapshot.retry(); onRefresh();
  };
  const resolve = async () => {
    if (!review || !decision || blocked || decision === "approve" && !previewReady || decision === "reschedule" && !future || request.current) return;
    const current = new AbortController(); request.current = current; setBusy(true);
    try {
      if (decision === "approve") await api.approveReview(id, { version: review.version }, current.signal);
      else if (decision === "skip") {
        const result = await api.skipReview(id, { version: review.version, confirmed: true }, current.signal);
        setNextRegular(result.next_regular_at);
      } else await api.rescheduleReview(id, { version: review.version, new_due_at: dueAt }, current.signal);
      if (!current.signal.aborted) { setDone(decision); setDecision(null); snapshot.retry(); onRefresh(); }
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
  return <>
    <header className="page-heading"><h1>{copy.title}</h1><p>{copy.intro}</p></header>
    {!snapshot.updatedAt && !snapshot.error && <p role="status">{tr.loading}</p>}
    {snapshot.error && <p role="alert" className="notice">{copy.readError}</p>}
    {done ? <div role="status" className="notice"><p>{copy.done[done]}</p>{done === "skip" && <p>{copy.nextRegular}: {nextRegular ? formatDate(nextRegular) : copy.noRegular}</p>}</div>
      : gone ? <p role="status" className="notice">{tr.reviewGone}</p> : <>
        {message && <p role="alert" className="notice">{message}</p>}
        {review && <section className="summary-sheet review-sheet" aria-label={copy.title}>
          <h2>{review.package_folder}</h2>
          <div className="review-content"><div>
            {detail?.render_ready && detail.preview_url ? <video key={`${detail.preview_url}-${reload}`} src={detail.preview_url} controls playsInline preload="auto" aria-label={copy.video}
              onLoadedData={() => { setPreviewReady(true); setPreviewFailed(false); }} onError={() => { setPreviewFailed(true); setPreviewReady(false); }} />
              : <p role="status">{copy.stale}</p>}
            {previewFailed && <p role="status" className="notice">{tr.editor.previewFailed}</p>}
          </div><div className="review-decision"><h3>{copy.caption}</h3><p className="review-caption">{review.caption ?? copy.noCaption}</p>
            <p className="muted">{copy.previewHelp}</p>
            <div className="upload-actions"><button className="primary" disabled={blocked || !previewReady} onClick={() => setDecision("approve")}>{copy.approve}</button>
              <button disabled={blocked} onClick={() => setDecision("skip")}>{copy.skip}</button>
              <button disabled={blocked} onClick={() => setDecision("reschedule")}>{copy.reschedule}</button></div>
            {decision && <form className="review-confirmation" onSubmit={event => { event.preventDefault(); void resolve(); }}><fieldset disabled={blocked}>
              <legend>{copy.confirm[decision]}</legend><p>{decision === "approve" ? copy.approveWarning : decision === "skip" ? copy.skipWarning : copy.rescheduleWarning}</p>
              {decision === "skip" && <p>{copy.nextRegular}: {detail?.next_regular_at ? formatDate(detail.next_regular_at) : copy.noRegular}</p>}
              {decision === "reschedule" && <><label htmlFor="review-time">{copy.newTime}</label><input id="review-time" type="datetime-local" value={time} required aria-describedby="review-time-help" onChange={event => setTime(event.target.value)} /><p id="review-time-help" className="muted">{copy.futureTime}</p></>}
              <div className="upload-actions"><button type="button" onClick={() => setDecision(null)}>{tr.editor.cancel}</button><button className={decision === "approve" ? "danger" : "primary"} disabled={decision === "reschedule" && !future || decision === "approve" && !previewReady}>{copy.confirm[decision]}</button></div>
            </fieldset></form>}
          </div></div>
        </section>}
      </>}
    <div className="upload-actions review-navigation"><button disabled={busy} onClick={refresh}>{copy.refresh}</button><a href="#/dashboard">{copy.back}</a>{!gone && !done && <a href="#/package">{copy.edit}</a>}</div>
  </>;
}

function DueContinuation({ data, occurrenceId, packageFolder, onRefresh, stale }: { data: DashboardOut; occurrenceId: number; packageFolder: string | null; onRefresh: () => void; stale: boolean }) {
  const load = useCallback(async (signal: AbortSignal) => {
    try { return await api.packageEditor(signal); }
    catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
  }, []);
  const snapshot = useLiveData(load);
  const actions = data.pending_actions.filter(item => item.occurrence_id === occurrenceId);
  const action = actions.find(item => item.state === "review_ready" && (!packageFolder || item.package_folder === packageFolder)) ?? actions[0];
  const boundFolder = useRef(packageFolder);
  if (!boundFolder.current && action?.package_folder) boundFolder.current = action.package_folder;
  const editor = snapshot.data, folder = boundFolder.current;
  const changed = !!folder && (data.package?.folder_name !== folder || !!editor && editor.package.folder_name !== folder);
  const [busy, setBusy] = useState(false), [error, setError] = useState(false);
  const { invalidate } = useSession();
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  if (changed) return <p role="status" className="notice">{copy.changedPackage} <a href="#/dashboard">{copy.back}</a></p>;
  if (!action) return <p role="status" className="notice">{tr.reviewGone} <a href="#/dashboard">{copy.back}</a></p>;
  if (action.review_id !== null && action.state === "review_ready") return <ReviewPanel key={action.review_id} id={action.review_id} onRefresh={onRefresh} stale={stale} />;
  const rendering = editor?.render_status === "queued" || editor?.render_status === "processing";
  const blocked = stale || snapshot.error || busy || !navigator.onLine || !editor || !editor.montage.order.length || editor.montage.over_limit || !editor.montage.duration_complete || rendering;
  const render = async () => {
    if (blocked || !editor || request.current) return;
    const current = new AbortController(); request.current = current; setBusy(true); setError(false);
    try { await api.renderPackage(editor.package.folder_name, editor.render_status === "failed", current.signal); }
    catch (failure) {
      if (current.signal.aborted) return;
      if (failure instanceof ApiError && failure.status === 401) invalidate(); else setError(true);
    } finally { request.current = null; if (!current.signal.aborted) { setBusy(false); snapshot.retry(); onRefresh(); } }
  };
  return <><header className="page-heading"><h1>{copy.title}</h1><p>{copy.uploadIntro}</p></header>
    {folder && <h2>{folder}</h2>}
    <fieldset className="package-upload-controls" disabled={stale || busy || snapshot.error} aria-label={tr.upload.title}><UploadPanel /></fieldset>
    <section className="summary-sheet review-continuation">
      {(snapshot.error || error) && <p role="alert" className="notice">{error ? copy.renderError : copy.readError}</p>}
      {rendering && <p role="status">{copy.preparing}</p>}
      <div className="upload-actions"><button className="primary" disabled={blocked} onClick={() => void render()}>{copy.continue}</button>
        <button disabled={busy} onClick={() => { setError(false); snapshot.retry(); onRefresh(); }}>{copy.refresh}</button><a href="#/package">{copy.edit}</a><a href="#/dashboard">{copy.back}</a></div>
    </section></>;
}

export function ReviewFlow(props: { data: DashboardOut; reviewId: number | null; occurrenceId: number | null; packageFolder: string | null; onRefresh: () => void; stale: boolean }) {
  return props.reviewId !== null ? <ReviewPanel key={props.reviewId} id={props.reviewId} onRefresh={props.onRefresh} stale={props.stale} />
    : props.occurrenceId !== null ? <DueContinuation {...props} occurrenceId={props.occurrenceId} /> : null;
}
