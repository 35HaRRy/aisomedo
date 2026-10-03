import type { EditorMediaOut } from "../api/openapi";
import { useId, useRef, useState } from "react";
import { tr } from "../i18n";
import { addRangeAtPlayhead, retainedDuration, type RangeInput, type VideoRange } from "./ranges";
import { RangeTimeline } from "./RangeTimeline";
export interface VideoSectionEditorProps { media: EditorMediaOut; ranges: VideoRange[]; inputs: RangeInput[]; validationError: string | null; disabled: boolean; onChange(ranges: VideoRange[]): void; onInputChange(index: number, bound: "start" | "end", value: string): void; }
export function VideoSectionEditor({ media, ranges, inputs, validationError, disabled, onChange, onInputChange }: VideoSectionEditorProps) {
  const [playhead, setPlayhead] = useState(0), [failed, setFailed] = useState(false), [attempt, setAttempt] = useState(0), [noGap, setNoGap] = useState(false);
  const video = useRef<HTMLVideoElement>(null), add = useRef<HTMLButtonElement>(null), id = useId();
  const duration = media.source_duration;
  if (duration === null || !Number.isFinite(duration) || duration <= 0) return <p role="status" className="notice">{tr.editor.unknownDuration}</p>;
  const seek = (seconds: number) => { if (video.current) video.current.currentTime = seconds; setPlayhead(seconds); };
  const editingBlocked = disabled || !!validationError;
  return <section className="video-section-editor" aria-label={`${media.filename} bölümleri`} onPointerDown={event => event.stopPropagation()} onDragStart={event => { event.stopPropagation(); event.preventDefault(); }}>
    <div className="section-preview">
      {media.preview_url ? <video ref={video} key={attempt} src={media.preview_url} controls playsInline preload="metadata" aria-label={`${media.filename} video önizlemesi`}
        onTimeUpdate={event => setPlayhead(event.currentTarget.currentTime)} onError={() => setFailed(true)} /> : <p>{tr.editor.previewMissing}</p>}
      {failed && <div role="alert"><p>{tr.editor.previewFailed}</p><button onClick={() => { setAttempt(attempt + 1); setFailed(false); }}>{tr.editor.previewRetry}</button></div>}
      <p className="time-readout">{tr.editor.playhead}: {playhead.toFixed(2)} / {duration.toFixed(2)} s</p>
    </div>
    <div className="section-edit-controls"><p className="selection-semantics">{inputs.length ? tr.editor.selectedOnly : tr.editor.wholeVideo}</p>
      <RangeTimeline duration={duration} ranges={ranges} playhead={playhead} disabled={editingBlocked} onChange={onChange} onSeek={seek} />
      {validationError && <p id={`${id}-error`} className="upload-error" role="alert">{tr.editor.invalidRange}</p>}
      <ol className="range-fields">{inputs.map((input, index) => <li key={index}>
        <strong>{index + 1}. bölüm</strong>
        {(["start", "end"] as const).map(bound => <label key={bound} htmlFor={`${id}-${index}-${bound}`}>{index + 1}. bölüm {bound === "start" ? "başlangıcı" : "bitişi"} (saniye)
          <input id={`${id}-${index}-${bound}`} inputMode="decimal" type="text" disabled={disabled} value={input[bound]} aria-invalid={!!validationError} aria-describedby={validationError ? `${id}-error` : undefined}
            onChange={event => onInputChange(index, bound, event.target.value)} /></label>)}
        <button disabled={editingBlocked} aria-label={`${index + 1}. bölümü kaldır`} onClick={() => {
          // Field rows retain their identity while partial text is edited;
          // timeline ranges are independently sorted into source-time order.
          onChange(inputs.filter((_, i) => i !== index).map(r => ({ start: Number(r.start), end: Number(r.end) })));
          add.current?.focus();
        }}>{tr.editor.removeSection}</button>
      </li>)}</ol>
      <div className="upload-actions"><button ref={add} disabled={editingBlocked} onClick={() => { const next = addRangeAtPlayhead(ranges, playhead, duration); setNoGap(!next); if (next) onChange(next); }}>{tr.editor.addSection}</button>
        <span className="time-readout">{tr.editor.retained}: {validationError ? "—" : retainedDuration(ranges, duration).toFixed(2)} s</span></div>
      {noGap && <p role="status">{tr.editor.noGap}</p>}
    </div>
  </section>;
}
