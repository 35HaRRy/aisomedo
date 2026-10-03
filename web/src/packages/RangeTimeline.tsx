import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type KeyboardEvent } from "react";
import { tr } from "../i18n";
import { FRAME_SECONDS, type VideoRange } from "./ranges";
export interface RangeTimelineProps { duration: number; ranges: VideoRange[]; playhead: number; disabled: boolean; onChange(ranges: VideoRange[]): void; onSeek(seconds: number): void; }
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));
const precise = (value: number) => Math.round(value * 1000) / 1000;
type Gesture = { pointer: number; x: number; start: number; before: VideoRange[]; index?: number; bound?: "start" | "end"; moved: boolean; low: number; high: number };
export function RangeTimeline({ duration, ranges, playhead, disabled, onChange, onSeek }: RangeTimelineProps) {
  const track = useRef<HTMLDivElement>(null), gesture = useRef<Gesture | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const point = (x: number) => {
    const rect = track.current!.getBoundingClientRect();
    return precise(clamp((x - rect.left) / (rect.width || 1) * duration, 0, duration));
  };
  const begin = (event: ReactPointerEvent, index?: number, bound?: "start" | "end") => {
    event.stopPropagation();
    if (disabled || event.button !== 0 || gesture.current) return;
    const start = point(event.clientX);
    let low = 0, high = duration;
    if (index !== undefined && bound) {
      setSelected(index);
      low = bound === "start" ? ranges[index - 1]?.end ?? 0 : ranges[index].start + FRAME_SECONDS;
      high = bound === "end" ? ranges[index + 1]?.start ?? duration : ranges[index].end - FRAME_SECONDS;
    } else {
      if (ranges.some(r => r.start < start && start < r.end)) return;
      low = Math.max(0, ...ranges.filter(r => r.end <= start).map(r => r.end));
      high = Math.min(duration, ...ranges.filter(r => r.start >= start).map(r => r.start));
    }
    gesture.current = { pointer: event.pointerId, x: event.clientX, start, before: ranges.map(r => ({ ...r })), index, bound, moved: false, low, high };
    track.current?.setPointerCapture?.(event.pointerId);
  };
  const move = (event: ReactPointerEvent) => {
    event.stopPropagation();
    const current = gesture.current;
    if (!current || current.pointer !== event.pointerId || disabled) return;
    if (Math.abs(event.clientX - current.x) >= 6) current.moved = true;
    if (!current.moved) return;
    const time = precise(clamp(point(event.clientX), current.low, current.high));
    if (current.index !== undefined && current.bound) {
      onChange(current.before.map((r, index) => index === current.index ? { ...r, [current.bound!]: time } : r));
    } else {
      const start = Math.min(time, current.start), end = Math.max(time, current.start);
      if (end - start + 1e-9 >= FRAME_SECONDS) onChange([...current.before, { start, end }].sort((a, b) => a.start - b.start));
      else onChange(current.before);
    }
  };
  const finish = (event: ReactPointerEvent, cancel: boolean) => {
    event.stopPropagation();
    const current = gesture.current;
    if (!current || current.pointer !== event.pointerId) return;
    gesture.current = null;
    if (cancel) onChange(current.before);
    else if (!current.moved && current.index === undefined) onSeek(point(event.clientX));
    track.current?.releasePointerCapture?.(event.pointerId);
  };
  useEffect(() => {
    if (disabled && gesture.current) { const old = gesture.current; gesture.current = null; onChange(old.before); }
  }, [disabled, onChange]);
  const key = (event: KeyboardEvent, index: number, bound: "start" | "end") => {
    event.stopPropagation();
    if (disabled || !["ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const low = bound === "start" ? ranges[index - 1]?.end ?? 0 : ranges[index].start + FRAME_SECONDS;
    const high = bound === "end" ? ranges[index + 1]?.start ?? duration : ranges[index].end - FRAME_SECONDS;
    const delta = ["ArrowLeft", "ArrowDown"].includes(event.key) ? -1 : 1;
    const value = event.key === "Home" ? low : event.key === "End" ? high : ranges[index][bound] + delta * (event.shiftKey ? 1 : 0.1);
    onChange(ranges.map((range, i) => i === index ? { ...range, [bound]: precise(clamp(value, low, high)) } : range));
  };
  return <div className="range-timeline" onDragStart={event => { event.preventDefault(); event.stopPropagation(); }}>
    <div className="timeline-ruler" aria-hidden="true">{[0, 1, 2, 3, 4].map(i => <span key={i}>{(duration * i / 4).toFixed(1)} s</span>)}</div>
    <div ref={track} role="group" aria-label={tr.editor.timeline} aria-disabled={disabled} className="timeline-track"
      onPointerDown={event => begin(event)} onPointerMove={move} onPointerUp={event => finish(event, false)} onPointerCancel={event => finish(event, true)}>
      {!ranges.length && <span className="timeline-whole" aria-hidden="true">{tr.editor.wholeTrack}</span>}
      {ranges.map((range, index) => <div key={index} className="timeline-section" data-selected={selected === index} style={{ left: `${range.start / duration * 100}%`, width: `${(range.end - range.start) / duration * 100}%` }}>
        <span className="timeline-section-body" onPointerDown={event => { event.stopPropagation(); setSelected(index); }}>{index + 1}</span>
        {(["start", "end"] as const).map(bound => <button key={bound} type="button" role="slider" disabled={disabled} className={`timeline-handle timeline-handle-${bound}`}
          aria-label={`${index + 1}. bölüm ${bound === "start" ? "başlangıcı" : "bitişi"}`}
          aria-valuenow={range[bound]} aria-valuemin={bound === "start" ? ranges[index - 1]?.end ?? 0 : precise(range.start + FRAME_SECONDS)}
          aria-valuemax={bound === "end" ? ranges[index + 1]?.start ?? duration : precise(range.end - FRAME_SECONDS)}
          aria-valuetext={`${range[bound].toFixed(2)} saniye`}
          onPointerDown={event => begin(event, index, bound)} onKeyDown={event => key(event, index, bound)}><span aria-hidden="true" /></button>)}
      </div>)}
      <span className="timeline-playhead" aria-hidden="true" style={{ left: `${clamp(playhead, 0, duration) / duration * 100}%` }} />
    </div><p className="muted">{tr.editor.timelineHelp}</p>
  </div>;
}
