import { useEffect, useRef, useState } from "react";
import type { EditorMediaOut } from "../api/openapi";
import { tr } from "../i18n";
import { MediaActionIcon } from "./MediaActionIcon";

export function MediaFullscreenDialog({ media, processed = false, onClose }: { media: Pick<EditorMediaOut, "filename" | "is_video" | "original_url" | "preview_url">; processed?: boolean; onClose(): void }) {
  const dialog = useRef<HTMLDialogElement>(null), close = useRef<HTMLButtonElement>(null);
  const [failed, setFailed] = useState(false), [loading, setLoading] = useState(true);
  const source = media.is_video && !processed ? media.original_url : media.preview_url;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null, element = dialog.current!;
    element.showModal(); close.current?.focus();
    return () => {
      element.querySelector("video")?.pause();
      element.close(); previous?.focus();
    };
  }, []);
  return <dialog ref={dialog} className="media-fullscreen" aria-label={media.filename} onCancel={event => { event.preventDefault(); onClose(); }}>
    <span tabIndex={0} className="dialog-focus-guard" onFocus={() => (dialog.current?.querySelector("video") ?? close.current)?.focus()} />
    <header><h2 title={media.filename}>{media.filename}</h2><button ref={close} className="media-icon-button" aria-label={tr.editor.closeViewer} title={tr.editor.closeViewer} onClick={onClose}><MediaActionIcon action="close" /></button></header>
    {!source || failed ? <p role="alert">{processed ? tr.editor.processedFailed : tr.editor.originalFailed}</p> : <>
      {loading && <p role="status">{tr.loading}</p>}
      {media.is_video ? <video src={source} controls playsInline autoPlay onLoadedData={() => setLoading(false)} onError={() => setFailed(true)} aria-label={media.filename} />
        : <img src={source} alt={media.filename} onLoad={() => setLoading(false)} onError={() => setFailed(true)} />}
    </>}
    <span tabIndex={0} className="dialog-focus-guard" onFocus={() => close.current?.focus()} />
  </dialog>;
}
