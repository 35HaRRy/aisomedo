import { useRef, useState } from "react";
import type { EditorMediaOut } from "../api/openapi";
import { tr } from "../i18n";
import { UploadPanel } from "../uploads/UploadPanel";
import { usePackageEditorContext } from "./PackageEditorProvider";
import { VideoSectionEditor } from "./VideoSectionEditor";

export function ActivePackagePanel() {
  const editor = usePackageEditorContext(), copy = tr.packageManagement;
  const [opened, setOpened] = useState<string | null>(null);
  const dragging = useRef<string | null>(null);
  const snapshot = editor.snapshot;
  const blocked = editor.busy || editor.stale || editor.offline;
  const byId = new Map(snapshot?.media.map(m => [m.media_id, m]));
  const ordered = (snapshot?.montage.order ?? []).map(id => byId.get(id)).filter((m): m is EditorMediaOut => !!m && m.status === "finalized");
  const removed = snapshot?.media.filter(m => m.status === "removed") ?? [];
  const move = (from: string, to: string) => {
    if (blocked || from === to) return;
    const order = ordered.map(m => m.media_id), a = order.indexOf(from), b = order.indexOf(to);
    if (a < 0 || b < 0) return;
    order.splice(a, 1); order.splice(b, 0, from); void editor.reorder(order);
  };
  const excess = snapshot && editor.proposedTotal !== null ? editor.proposedTotal - snapshot.montage.max_duration_seconds : null;
  return <>
    <section className="summary-sheet package-editor" aria-labelledby="active-media-title">
      <div className="package-section-heading"><h2 id="active-media-title">{copy.activeMedia}</h2><button disabled={editor.busy || editor.offline} onClick={() => void editor.refresh()}>{copy.refresh}</button></div>
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
        <div className="upload-actions package-save-actions"><button className="primary" disabled={!editor.canSave} onClick={() => void editor.save()}>{editor.busy ? copy.saving : copy.save}</button>
          <button disabled={!editor.dirty || editor.busy} onClick={() => editor.discard()}>{copy.discard}</button></div>
        {!ordered.length && <p>{copy.noMedia}</p>}
        <ol aria-label={copy.order} className="package-media-list">{ordered.map((media, index) => <li key={media.media_id} onDragOver={event => { if (dragging.current && !blocked) event.preventDefault(); }} onDrop={event => { event.preventDefault(); if (dragging.current) move(dragging.current, media.media_id); dragging.current = null; }}>
          <div className="package-media-heading"><div><h3>{media.filename}</h3><p className="muted">{media.is_video ? copy.video : copy.photo} · {media.effective_duration === null ? copy.unknownDuration : `${media.effective_duration.toFixed(2)} s`}</p></div>
            <div className="upload-actions"><button draggable={!blocked} disabled={blocked} aria-label={`${media.filename} ${copy.dragLabel}`} onDragStart={event => { dragging.current = media.media_id; event.dataTransfer.setData("text/plain", media.media_id); event.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => { dragging.current = null; }}>{copy.drag}</button>
              <button disabled={blocked || index === 0} aria-label={`${media.filename} ${copy.upLabel}`} onClick={() => move(media.media_id, ordered[index - 1].media_id)}>{copy.up}</button>
              <button disabled={blocked || index === ordered.length - 1} aria-label={`${media.filename} ${copy.downLabel}`} onClick={() => move(media.media_id, ordered[index + 1].media_id)}>{copy.down}</button></div></div>
          {!media.is_video && media.preview_url && <img className="package-photo-preview" src={media.preview_url} alt={`${media.filename} ${copy.preview}`} loading="lazy" />}
          <div className="upload-actions">{media.is_video && <button aria-label={`${media.filename} ${copy.editLabel}`} aria-expanded={opened === media.media_id} onClick={() => setOpened(opened === media.media_id ? null : media.media_id)}>{opened === media.media_id ? copy.closeEditor : copy.edit}</button>}
            <button disabled={blocked} aria-label={`${media.filename} ${copy.removeLabel}`} onClick={() => void editor.remove(media.media_id)}>{copy.remove}</button></div>
          {opened === media.media_id && media.is_video && <VideoSectionEditor key={media.media_id} media={media} ranges={editor.draft[media.media_id] ?? []} inputs={editor.draftInputs[media.media_id] ?? []} validationError={editor.validationErrors[media.media_id] ?? null} disabled={blocked}
            onChange={ranges => editor.setRanges(media.media_id, ranges)} onInputChange={(i, bound, value) => editor.setInput(media.media_id, i, bound, value)} />}
        </li>)}</ol>
        {!!removed.length && <section className="removed-media" aria-labelledby="removed-media-title"><h3 id="removed-media-title">{copy.removed}</h3><p className="muted">{copy.removedHelp}</p><ul className="package-media-list">{removed.map(media => <li key={media.media_id} className="package-media-heading"><h3>{media.filename}</h3>
          <button disabled={blocked} aria-label={`${media.filename} ${copy.restoreLabel}`} onClick={() => void editor.restore(media.media_id)}>{copy.restore}</button></li>)}</ul></section>}
      </>}
    </section><UploadPanel />
  </>;
}
