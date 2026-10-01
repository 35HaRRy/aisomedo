import { useState } from "react";
import { formatDate, tr } from "../i18n";
import { useUploads } from "./UploadProvider";
import type { ConflictDecision, UploadRow } from "./types";

interface Target extends Record<string, unknown> {
  media_id: string;
  filename: string;
  size_bytes: number;
  uploaded_at: string;
  processed: { content_type: "image/jpeg" | "video/mp4" };
}
function isTarget(value: unknown): value is Target {
  if (!value || typeof value !== "object") return false;
  const target = value as Partial<Target>;
  return typeof target.media_id === "string" && !!target.media_id && typeof target.filename === "string"
    && Number.isSafeInteger(target.size_bytes) && target.size_bytes! >= 0
    && typeof target.uploaded_at === "string" && Number.isFinite(Date.parse(target.uploaded_at))
    && !!target.processed && ["image/jpeg", "video/mp4"].includes(target.processed.content_type);
}

export function ConflictControls({ row }: { row: UploadRow }) {
  const { controller, snapshot } = useUploads();
  const targets = row.status?.conflicts?.filter(isTarget) ?? [];
  const [targetId, setTargetId] = useState(targets[0]?.media_id ?? "");
  const [decision, setDecision] = useState<ConflictDecision>("keep_both");
  const [applyAll, setApplyAll] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<"loading" | "ready" | "failed">("loading");
  const [attempt, setAttempt] = useState(0);
  const target = targets.find(value => value.media_id === targetId);
  const overwrite = decision === "keep_selected";
  const busy = !!snapshot.resolvingId;
  const blocked = busy || (overwrite && (!target || !confirmed || preview !== "ready"));
  const previewLabel = `${tr.conflict.preview}: ${target?.filename ?? ""}`;
  const source = target && row.status
    ? `/api/media/uploads/${encodeURIComponent(row.status.upload_id)}/conflicts/${encodeURIComponent(target.media_id)}/preview${attempt ? `?attempt=${attempt}` : ""}` : undefined;
  const retryPreview = () => { setConfirmed(false); setPreview("loading"); setAttempt(value => value + 1); };
  return <form className="conflict-controls" aria-label={`${tr.conflict.title}: ${row.filename}`} aria-busy={busy}
    onSubmit={event => {
      event.preventDefault();
      if (blocked) return;
      setConfirmed(false);
      document.getElementById(`${row.id}-name`)?.focus();
      void controller.resolve(row.id, { decision, apply_to_all: applyAll,
        ...(overwrite ? { target_media_id: targetId, confirmed_overwrite: true } : {}) });
    }}>
    <p>{tr.conflict.intro}</p>
    {targets.length > 1 && <div><label htmlFor={`${row.id}-target`}>{tr.conflict.target}</label>
      <select id={`${row.id}-target`} value={targetId} disabled={busy} onChange={event => {
        setTargetId(event.target.value); setConfirmed(false); setPreview("loading"); setAttempt(0);
      }}>{targets.map(value => <option key={value.media_id} value={value.media_id}>{value.filename} · {value.media_id}</option>)}</select></div>}
    {target ? <figure className="conflict-preview">
      {target.processed.content_type === "video/mp4"
        ? <video key={`${targetId}-${attempt}`} src={source} aria-label={previewLabel} controls playsInline preload="metadata"
          onLoadedMetadata={() => setPreview("ready")} onError={() => { setPreview("failed"); setConfirmed(false); }} />
        : <img key={`${targetId}-${attempt}`} src={source} alt={previewLabel}
          onLoad={() => setPreview("ready")} onError={() => { setPreview("failed"); setConfirmed(false); }} />}
      <figcaption><strong>{target.filename}</strong><span>{new Intl.NumberFormat("tr-TR").format(target.size_bytes)} {tr.upload.units[0]} · {formatDate(target.uploaded_at)}</span>
        <span>{tr.conflict.targetId}: {target.media_id}</span></figcaption>
      {preview === "loading" && <p role="status" className="muted">{tr.conflict.previewLoading}</p>}
      {preview === "failed" && <div role="alert" className="upload-error"><p>{tr.conflict.previewFailed}</p>
        <button type="button" disabled={busy} onClick={retryPreview}>{tr.conflict.previewRetry}</button></div>}
    </figure> : <p role="status" className="muted">{tr.conflict.noTarget}</p>}
    <fieldset disabled={busy} aria-describedby={`${row.id}-bulk-help`}>
      <legend>{tr.conflict.choose}</legend>
      {(["keep_both", "keep_selected", "keep_target"] as const).map(value => <label className="conflict-choice" key={value}>
        <input type="radio" name={`${row.id}-decision`} checked={decision === value}
          disabled={value === "keep_selected" && !target} onChange={() => { setDecision(value); setConfirmed(false); }} />
        <span>{tr.conflict.decisions[value]}</span></label>)}
      <label className="conflict-choice"><input type="checkbox" checked={applyAll} onChange={event => { setApplyAll(event.target.checked); setConfirmed(false); }} />
        <span>{tr.conflict.applyAll}</span></label>
      <p id={`${row.id}-bulk-help`} className="muted">{tr.conflict.bulkHelp}</p>
      {overwrite && <div className="conflict-warning" role="note" aria-labelledby={`${row.id}-warning`}>
        <p id={`${row.id}-warning`}><strong>{tr.conflict.warning}</strong></p>
        <p>{target?.filename}{applyAll ? ` · ${tr.conflict.bulkWarning}` : ""}</p>
        <label className="conflict-choice"><input type="checkbox" checked={confirmed}
          aria-describedby={`${row.id}-warning`} onChange={event => setConfirmed(event.target.checked)} />
          <span>{tr.conflict.confirm}</span></label>
      </div>}
    </fieldset>
    <div className="upload-actions"><button type="submit" className={overwrite ? "danger" : "primary"} disabled={blocked}>{overwrite ? tr.conflict.overwrite : tr.conflict.apply}</button>
      <button type="button" disabled={busy} onClick={() => { setConfirmed(false); void controller.refresh(new AbortController().signal); }}>{tr.conflict.refresh}</button></div>
    {busy && <p role="status">{tr.conflict.resolving}</p>}
  </form>;
}
