import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import type { EditorMediaOut } from "../api/openapi";
import { tr } from "../i18n";
import { UploadPanel } from "../uploads/UploadPanel";
import { useUploads } from "../uploads/UploadProvider";
import { usePackageEditorContext } from "./PackageEditorProvider";
import { VideoSectionEditor } from "./VideoSectionEditor";
import { MediaActionIcon } from "./MediaActionIcon";

export function ActivePackagePanel() {
  const editor = usePackageEditorContext(), copy = tr.packageManagement;
  const uploads = useUploads();
  const [previewFailed, setPreviewFailed] = useState(false);
  const [opened, setOpened] = useState<string | null>(null);
  const dragging = useRef<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [dragged, setDragged] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{ id: string; position: "before" | "after" } | null>(null);
  const snapshot = editor.snapshot;
  useEffect(() => { setPreviewFailed(false); }, [snapshot?.render_preview_url]);
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
  const blocked = editor.busy || editor.stale || editor.offline;
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
    <section className="summary-sheet package-editor" aria-labelledby="active-media-title">
      <div className="package-section-heading"><h2 id="active-media-title">{copy.activeMedia}</h2><div className="upload-actions"><button disabled={editor.busy || editor.offline} onClick={() => void editor.refresh()}>{copy.refresh}</button>
        <button className="danger" disabled={editor.busy || editor.offline || !editor.pendingClear && (!snapshot || editor.loading || editor.stale)} onClick={() => void clearPackage()}>{editor.pendingClear ? copy.retryClear : copy.clear}</button></div></div>
      {editor.loading && !snapshot && <p role="status">{tr.loading}</p>}
      {editor.error && <p role="alert" className="notice">{copy.errors[editor.error]}</p>}
      {editor.offline && <p role="status" className="notice">{copy.offline}</p>}
      {editor.stale && <p role="alert" className="notice">{copy.stale}</p>}
      {!snapshot && !editor.loading && !editor.error && <p>{copy.noActive}</p>}
      {snapshot && <>
        <div className="montage-duration" aria-live="polite">
          <p>{copy.total}: <strong>{editor.proposedTotal === null ? copy.unknownTotal : `${editor.proposedTotal.toFixed(2)} s`}</strong> / {snapshot.montage.max_duration_seconds.toFixed(2)} s</p>
          {excess !== null && excess > 0 && <p className="upload-error">{copy.limitHelp} {excess.toFixed(2)} s</p>}
          <p className="muted">{editor.dirty ? copy.unsaved : copy.saved}</p>
          {snapshot.render_stale && <p className="muted">{copy.renderStale}</p>}
        </div>
        <div className="upload-actions package-save-actions"><button className="primary" disabled={!editor.canSave} aria-describedby="package-save-reason" onClick={() => void editor.save()}>{editor.busy ? copy.saving : copy.save}</button>
          <button title={copy.discardHelp} disabled={!editor.dirty || editor.busy} onClick={() => editor.discard()}>{copy.discard}</button></div>
        <p id="package-save-reason" className="muted" role="status">{editor.saveBlockedReason ? copy.saveReasons[editor.saveBlockedReason] : ""}</p>
        <section className="saved-reel-preview" aria-labelledby="saved-reel-title">
          <h3 id="saved-reel-title">{copy.savedPreview}</h3><p className="muted">{copy.renderHelp}</p>
          <p role="status">{copy.renderStates[snapshot.render_status ?? "missing"]}</p>
          {snapshot.render_status === "ready" && snapshot.render_preview_url && <video key={snapshot.render_preview_url} src={snapshot.render_preview_url} controls playsInline preload="metadata" aria-label={copy.savedPreview} onError={() => setPreviewFailed(true)} />}
          {previewFailed && <p role="alert" className="notice">{tr.editor.previewFailed}</p>}
          <button disabled={blocked || !ordered.length || snapshot.montage.over_limit || !snapshot.montage.duration_complete || snapshot.render_status === "queued" || snapshot.render_status === "processing"} onClick={() => void editor.renderPreview()}>{copy.render}</button>
        </section>
        {!ordered.length && <p>{copy.noMedia}</p>}
        <ol aria-label={copy.order} className="package-media-list package-media-grid">{ordered.map((media, index) => <li key={media.media_id} data-editor-open={opened === media.media_id || undefined} data-selected={selected === media.media_id || undefined} data-dragging={dragged === media.media_id || undefined} data-drop-position={dropTarget?.id === media.media_id ? dropTarget.position : undefined}
          onDragOver={event => {
            if (!canDrop(event) || dragging.current === media.media_id) { setDropTarget(null); return; }
            event.preventDefault(); event.dataTransfer.dropEffect = "move";
            setDropTarget({ id: media.media_id, position: dropPosition(event) });
          }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropTarget(null); }}
          onDrop={event => {
            if (canDrop(event)) { event.preventDefault(); move(dragging.current!, media.media_id, dropPosition(event)); }
            clearDrag();
          }}>
          <div className="package-media-heading"><div><h3>{media.filename}</h3><p className="muted">{media.is_video ? copy.video : copy.photo} · {media.effective_duration === null ? copy.unknownDuration : `${media.effective_duration.toFixed(2)} s`}</p></div>
            <div className="package-media-actions">
              {media.is_video && <button className="media-icon-button" aria-label={`${media.filename} ${copy.editLabel}`} title={`${media.filename} ${copy.editLabel}`} aria-expanded={opened === media.media_id} onClick={() => setOpened(opened === media.media_id ? null : media.media_id)}><MediaActionIcon action={opened === media.media_id ? "close" : "edit"} /></button>}
              <button className="media-icon-button" disabled={blocked} aria-label={`${media.filename} ${copy.removeLabel}`} title={`${media.filename} ${copy.removeLabel}`} onClick={() => void editor.remove(media.media_id)}><MediaActionIcon action="remove" /></button>
               <button className="media-icon-button" disabled={blocked || index === 0} aria-label={`${media.filename} ${copy.leftLabel}`} title={`${media.filename} ${copy.leftLabel}`} onClick={() => move(media.media_id, ordered[index - 1].media_id)}><MediaActionIcon action="left" /></button>
               <button className="media-icon-button" disabled={blocked || index === ordered.length - 1} aria-label={`${media.filename} ${copy.rightLabel}`} title={`${media.filename} ${copy.rightLabel}`} onClick={() => move(media.media_id, ordered[index + 1].media_id)}><MediaActionIcon action="right" /></button>
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
          {!media.is_video && media.preview_url && <img className="package-photo-preview" src={media.preview_url} alt={`${media.filename} ${copy.preview}`} loading="lazy" />}
          {!media.is_video && <label className="photo-duration-control">Görüntülenme süresi (saniye)
            <input type="number" min="0.04" step="0.01" disabled={blocked} aria-label={`${media.filename} ${copy.photoDuration}`} aria-invalid={!!editor.validationErrors[media.media_id]} value={editor.draftInputs[media.media_id]?.[0]?.end ?? "3"} onChange={event => editor.setPhotoDuration(media.media_id, event.target.value)} />
            {editor.validationErrors[media.media_id] && <span role="alert">{copy.photoDurationHelp}</span>}
          </label>}
          {opened === media.media_id && media.is_video && <VideoSectionEditor key={media.media_id} media={media} ranges={editor.draft[media.media_id] ?? []} inputs={editor.draftInputs[media.media_id] ?? []} validationError={editor.validationErrors[media.media_id] ?? null} disabled={blocked}
            onChange={ranges => editor.setRanges(media.media_id, ranges)} onInputChange={(i, bound, value) => editor.setInput(media.media_id, i, bound, value)} />}
        </li>)}</ol>
        {!!removed.length && <section className="removed-media" aria-labelledby="removed-media-title"><h3 id="removed-media-title">{copy.removed}</h3><p className="muted">{copy.removedHelp}</p><ul className="package-media-list">{removed.map(media => <li key={media.media_id} className="package-media-heading"><h3>{media.filename}</h3>
          <button className="media-icon-button" disabled={blocked} aria-label={`${media.filename} ${copy.restoreLabel}`} title={`${media.filename} ${copy.restoreLabel}`} onClick={() => void editor.restore(media.media_id)}><MediaActionIcon action="restore" /></button></li>)}</ul></section>}
      </>}
    </section><fieldset className="package-upload-controls" disabled={editor.busy || !!editor.pendingClear} aria-label={tr.upload.title}><UploadPanel /></fieldset>
  </>;
}
