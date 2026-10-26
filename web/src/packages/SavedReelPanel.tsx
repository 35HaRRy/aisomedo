import { useEffect, useState } from "react";
import { CollapsiblePanel } from "../components/CollapsiblePanel";
import { tr } from "../i18n";
import { MediaActionIcon } from "./MediaActionIcon";
import { usePackageEditorContext } from "./PackageEditorProvider";

export function SavedReelPanel() {
  const editor = usePackageEditorContext(), snapshot = editor.snapshot, copy = tr.packageManagement;
  const [failed, setFailed] = useState(false), [metadata, setMetadata] = useState<number | null>(null);
  useEffect(() => { setFailed(false); setMetadata(null); }, [snapshot?.render_preview_url, snapshot?.render_status]);
  if (!snapshot) return null;
  const ready = snapshot.render_status === "ready" && !!snapshot.render_preview_url;
  const duration = ready ? snapshot.render_duration ?? metadata : null;
  const title = `${copy.savedPreview} · ${ready ? duration === null ? copy.unknownDuration : `${duration.toFixed(2)} s` : copy.notRendered}`;
  return <CollapsiblePanel className="summary-sheet saved-reel-preview" title={title} actions={<button className="media-icon-button" aria-label={copy.render} title={copy.render}
    disabled={!editor.canEdit || !snapshot.montage.order.length || snapshot.montage.over_limit || !snapshot.montage.duration_complete || ["queued", "processing"].includes(snapshot.render_status ?? "")}
    onClick={() => void editor.renderPreview(failed)}><MediaActionIcon action="render" /></button>}>
    <p className="muted">{copy.renderHelp}</p>
    {editor.dirty && <p role="status">{tr.editor.previewDraftWarning}</p>}
    <p role="status">{!snapshot.render_status || ["missing", "stale"].includes(snapshot.render_status) ? copy.notRenderedBody : copy.renderStates[snapshot.render_status]}</p>
    {ready && <video key={snapshot.render_preview_url} src={snapshot.render_preview_url!} controls playsInline preload="metadata" aria-label={copy.savedPreview}
      onLoadedMetadata={event => { const seconds = event.currentTarget.duration; if (Number.isFinite(seconds) && seconds > 0) setMetadata(seconds); }} onError={() => setFailed(true)} />}
    {failed && <p role="alert">{tr.editor.previewFailed}</p>}
  </CollapsiblePanel>;
}
