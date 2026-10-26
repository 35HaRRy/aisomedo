import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import type { EditorMediaOut } from "../api/openapi";
import { tr } from "../i18n";
import { UploadPanel } from "../uploads/UploadPanel";
import { useUploads } from "../uploads/UploadProvider";
import { usePackageEditorContext } from "./PackageEditorProvider";
import { VideoSectionEditor } from "./VideoSectionEditor";
import { MediaActionIcon } from "./MediaActionIcon";
import { CollapsiblePanel } from "../components/CollapsiblePanel";
import { MediaFullscreenDialog } from "./MediaFullscreenDialog";

export function ActivePackagePanel() {
  const editor = usePackageEditorContext(), copy = tr.packageManagement;
  const uploads = useUploads();
  const [viewing, setViewing] = useState<EditorMediaOut | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  const dragging = useRef<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [dragged, setDragged] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{ id: string; position: "before" | "after" } | null>(null);
  const snapshot = editor.snapshot;
  useEffect(() => { setViewing(null); }, [snapshot?.package.id, snapshot?.content_revision]);
  const clearPackage = async () => {
    const target = editor.pendingClear ?? snapshot?.package;
    if (!target || !window.confirm(`${target.folder_name}\n\n${copy.clearWarning}`)) return;
    uploads.controller.pauseAll();
    if (await editor.clearPackage()) {
      uploads.controller.reset();
      setOpened(null);
      window.dispatchEvent(new Event("focus"));
    }
  };
  const blocked = !editor.canEdit;
  const clearDrag = useCallback(() => { dragging.current = null; setSelected(null); setDragged(null); setDropTarget(null); }, []);
  useEffect(() => {
    const release = () => { if (!dragging.current) setSelected(null); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") clearDrag(); };
    window.addEventListener("pointerup", release); window.addEventListener("pointercancel", release);
    window.addEventListener("keydown", escape); window.addEventListener("blur", clearDrag);
    return () => {
      window.removeEventListener("pointerup", release); window.removeEventListener("pointercancel", release);
      window.removeEventListener("keydown", escape); window.removeEventListener("blur", clearDrag);
    };
  }, [clearDrag]);
  useEffect(() => { clearDrag(); }, [blocked, snapshot?.package.folder_name, clearDrag]);
  const byId = new Map(snapshot?.media.map(m => [m.media_id, m]));
  const ordered = (snapshot?.montage.order ?? []).map(id => byId.get(id)).filter((m): m is EditorMediaOut => !!m && m.status === "finalized");
  const removed = snapshot?.media.filter(m => m.status === "removed") ?? [];
  const move = (from: string, to: string, position?: "before" | "after") => {
    if (blocked || from === to) return;
    const order = ordered.map(m => m.media_id), a = order.indexOf(from), b = order.indexOf(to);
    if (a < 0 || b < 0) return;
    order.splice(a, 1);
    order.splice(position ? order.indexOf(to) + (position === "after" ? 1 : 0) : b, 0, from);
    if (order.every((id, index) => id === ordered[index].media_id)) return;
    void editor.reorder(order);
  };
  const dropPosition = (event: DragEvent<HTMLLIElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return event.clientX > rect.left + rect.width / 2 ? "after" : "before";
  };
  const canDrop = (event: DragEvent<HTMLLIElement>) => !!dragging.current && !blocked && !(event.target instanceof Element && event.target.closest(".video-section-editor"));
  const excess = snapshot && editor.proposedTotal !== null ? editor.proposedTotal - snapshot.montage.max_duration_seconds : null;
  return <>
    <CollapsiblePanel className="summary-sheet package-editor" title={copy.activeMedia} actions={<>
      <button className="media-icon-button" aria-label={copy.refresh} title={copy.refresh} disabled={editor.busy || editor.offline} onClick={() => void editor.refresh()}><MediaActionIcon action="refresh" /></button>
      <button className="media-icon-button danger" aria-label={editor.pendingClear ? copy.retryClear : copy.clear} title={editor.pendingClear ? copy.retryClear : copy.clear} disabled={editor.busy || editor.offline || !editor.pendingClear && (!snapshot || editor.loading || editor.stale)} onClick={() => void clearPackage()}><MediaActionIcon action="remove" /></button></>}>
      {editor.loading && !snapshot && <p role="status">{tr.loading}</p>}
      {editor.error && <p role="alert" className="notice">{copy.errors[editor.error]}</p>}
      {editor.offline && <p role="status" className="notice">{copy.offline}</p>}
      {editor.stale && <p role="alert" className="notice">{copy.stale}</p>}
      {editor.persistenceError && <div role="alert" className="notice"><p>{copy.persistenceErrors[editor.persistenceError]}</p>
        {editor.persistenceError === "unavailable" && <button onClick={() => void editor.retryDraftPersistence()}>{copy.retryDraft}</button>}
      </div>}
      {Object.entries(editor.conflicts).map(([key]) => <section key={key} role="region" aria-label={`${key} ${copy.conflictSuffix}`} className="notice">
        <h3>{copy.conflictTitle}</h3><p>{copy.conflictHelp}</p>
        <div className="upload-actions"><button onClick={() => editor.resolveConflict(key, "local")}>{copy.useLocal}</button>
          <button onClick={() => editor.resolveConflict(key, "server")}>{copy.useServer}</button></div>
      </section>)}
      {!snapshot && !editor.loading && !editor.error && <p>{copy.noActive}</p>}
      {snapshot && <>
        {!ordered.length && <p>{copy.noMedia}</p>}
        <ol aria-label={copy.order} className="package-media-list package-media-grid">{ordered.map(media => <li key={media.media_id} data-editor-open={opened === media.media_id || undefined} data-selected={selected === media.media_id || undefined} data-dragging={dragged === media.media_id || undefined} data-drop-position={dropTarget?.id === media.media_id ? dropTarget.position : undefined}
          onDragOver={event => {
            if (!canDrop(event) || dragging.current === media.media_id) { setDropTarget(null); return; }
            event.preventDefault(); event.dataTransfer.dropEffect = "move";
            setDropTarget({ id: media.media_id, position: dropPosition(event) });
          }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropTarget(null); }}
          onDrop={event => {
            if (canDrop(event)) { event.preventDefault(); move(dragging.current!, media.media_id, dropPosition(event)); }
            clearDrag();
          }}>
          <div className="package-media-heading"><div><h3 title={media.filename}>{media.filename}</h3>
            <div className="package-media-meta"><p className="muted">{media.is_video ? copy.video : copy.photo} · {media.effective_duration === null ? copy.unknownDuration : `${media.effective_duration.toFixed(2)} s`}{editor.isDirty(media.media_id) && <> · <strong>{copy.cardDraft}</strong></>}</p>
              {!media.is_video && <input className="photo-duration-input" type="number" min="0.04" step="0.01" disabled={blocked} aria-label={`${media.filename} ${copy.photoDuration}`} aria-invalid={!!editor.validationErrors[media.media_id]} value={editor.draftInputs[media.media_id]?.[0]?.end ?? "3"} onChange={event => editor.setPhotoDuration(media.media_id, event.target.value)} />}
            </div>
            {editor.validationErrors[media.media_id] && <span role="alert" className="photo-duration-error">{copy.photoDurationHelp}</span>}
          </div>
            <div className="package-media-actions">
              {media.is_video && <button className="media-icon-button" aria-label={`${media.filename} ${copy.editLabel}`} title={`${media.filename} ${copy.editLabel}`} aria-expanded={opened === media.media_id} onClick={() => setOpened(opened === media.media_id ? null : media.media_id)}><MediaActionIcon action={opened === media.media_id ? "close" : "edit"} /></button>}
              <CardSaveActions id={media.media_id} />
              <button className="media-icon-button" disabled={blocked} aria-label={`${media.filename} ${copy.removeLabel}`} title={`${media.filename} ${copy.removeLabel}`} onClick={() => void editor.remove(media.media_id)}><MediaActionIcon action="remove" /></button>
              <button className="media-icon-button media-drag-handle" draggable={!blocked} disabled={blocked} aria-label={`${media.filename} ${copy.dragLabel}`} title={`${media.filename} ${copy.dragLabel}`}
                onPointerDown={() => { if (!blocked) setSelected(media.media_id); }}
                onDragStart={event => {
                  if (blocked) { event.preventDefault(); return; }
                  dragging.current = media.media_id; setSelected(media.media_id); setDragged(media.media_id);
                  event.dataTransfer.setData("text/plain", media.media_id); event.dataTransfer.effectAllowed = "move";
                  const row = event.currentTarget.closest("li")!;
                  const rect = row.getBoundingClientRect();
                  event.dataTransfer.setDragImage?.(row, Math.max(0, event.clientX - rect.left), Math.max(0, event.clientY - rect.top));
                }} onDragEnd={clearDrag}><MediaActionIcon action="drag" /></button>
            </div></div>
          {opened !== media.media_id && <button className="media-image-button" aria-label={`${media.filename} ${tr.editor.viewOriginal}`} onClick={() => setViewing(media)}>
            <MediaThumbnail key={`${media.media_id}:${media.thumbnail_url}:${media.preview_url}`} media={media} />
          </button>}
          {opened === media.media_id && media.is_video && <VideoSectionEditor key={media.media_id} media={media} ranges={editor.draft[media.media_id] ?? []} inputs={editor.draftInputs[media.media_id] ?? []} validationError={editor.validationErrors[media.media_id] ?? null} disabled={blocked} dirty={editor.isDirty(media.media_id)} onRetryPreview={() => void editor.retrySectionPreview(media.media_id)}
            onChange={ranges => editor.setRanges(media.media_id, ranges)} onInputChange={(i, bound, value) => editor.setInput(media.media_id, i, bound, value)} />}
          {editor.saveBlockedReasonFor(media.media_id) && editor.saveBlockedReasonFor(media.media_id) !== "unchanged" && <p id={`save-reason-${media.media_id}`} className="muted card-save-reason" role="status">{copy.saveReasons[editor.saveBlockedReasonFor(media.media_id)!]}</p>}
        </li>)}</ol>
        {!!removed.length && <CollapsiblePanel className="removed-media" title={copy.removed} level={3}><p className="muted">{copy.removedHelp}</p><ul className="package-media-list">{removed.map(media => <li key={media.media_id} className="package-media-heading"><h3>{media.filename}</h3>
          <button className="media-icon-button" disabled={blocked} aria-label={`${media.filename} ${copy.restoreLabel}`} title={`${media.filename} ${copy.restoreLabel}`} onClick={() => void editor.restore(media.media_id)}><MediaActionIcon action="restore" /></button></li>)}</ul></CollapsiblePanel>}
        <div className="montage-duration" aria-live="polite">
          <p>{copy.total}: <strong>{editor.proposedTotal === null ? copy.unknownTotal : `${editor.proposedTotal.toFixed(2)} s`}</strong> / {snapshot.montage.max_duration_seconds.toFixed(2)} s</p>
          {excess !== null && excess > 0 && <p className="upload-error">{copy.limitHelp} {excess.toFixed(2)} s</p>}
          <p className="muted">{editor.dirty ? copy.unsaved : copy.saved}</p>
          {snapshot.render_stale && <p className="muted">{copy.renderStale}</p>}
        </div>
      </>}
    </CollapsiblePanel><fieldset className="package-upload-controls" disabled={editor.busy || editor.offline || !!editor.pendingClear} aria-label={tr.upload.title}><UploadPanel /></fieldset>
    {viewing && <MediaFullscreenDialog key={viewing.media_id} media={viewing} onClose={() => setViewing(null)} />}
  </>;
}

function CardSaveActions({ id }: { id: string }) {
  const editor = usePackageEditorContext(), copy = tr.packageManagement;
  const reason = editor.saveBlockedReasonFor(id);
  return <div className="upload-actions package-save-actions">
    <button className="media-icon-button primary" aria-label={copy.save} title={copy.save} disabled={!editor.canSaveMedia(id)} aria-describedby={reason && reason !== "unchanged" ? `save-reason-${id}` : undefined} onClick={() => void editor.save(id)}><MediaActionIcon action="save" /></button>
    <button className="media-icon-button" aria-label={copy.discard} title={copy.discardHelp} disabled={!editor.isDirty(id) || editor.busy || editor.offline} onClick={() => editor.discard(id)}><MediaActionIcon action="discard" /></button>
  </div>;
}

function MediaThumbnail({ media }: { media: EditorMediaOut }) {
  const [failed, setFailed] = useState(false);
  const source = media.is_video ? media.thumbnail_url : media.preview_url;
  return source && !failed ? <img className="package-photo-preview" src={source} alt={`${media.filename} ${tr.packageManagement.preview}`} loading="lazy" onError={() => setFailed(true)} />
    : <span>{tr.editor.previewMissing}</span>;
}
