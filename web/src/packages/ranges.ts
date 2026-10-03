import type { ActiveEditorOut, VideoRangeOut } from "../api/openapi";
export type VideoRange = VideoRangeOut;
export type SelectionMap = Record<string, VideoRange[]>;
export type RangeInput = { start: string; end: string };
export const FRAME_SECONDS = 1 / 25;
export function validateRanges(ranges: VideoRange[], duration: number): string | null {
  if (!Number.isFinite(duration) || duration <= 0) return "duration";
  const ordered = [...ranges].sort((a, b) => a.start - b.start);
  for (let index = 0; index < ordered.length; index++) {
    const { start, end } = ordered[index];
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > duration || end - start + 1e-9 < FRAME_SECONDS) return "bounds";
    if (index && ordered[index - 1].end > start) return "overlap";
  }
  return null;
}
export function retainedDuration(ranges: VideoRange[], duration: number): number {
  return ranges.length ? ranges.reduce((sum, range) => sum + range.end - range.start, 0) : duration;
}
export function addRangeAtPlayhead(ranges: VideoRange[], playhead: number, duration: number): VideoRange[] | null {
  if (!Number.isFinite(playhead) || validateRanges(ranges, duration) || playhead < 0 || playhead >= duration) return null;
  if (ranges.some(range => range.start <= playhead && playhead < range.end)) return null;
  const next = Math.min(duration, ...ranges.filter(range => range.start > playhead).map(range => range.start));
  const end = Math.min(playhead + 1, next);
  if (end - playhead + 1e-9 < FRAME_SECONDS) return null;
  return [...ranges, { start: playhead, end }].sort((a, b) => a.start - b.start);
}
export function proposedDuration(snapshot: ActiveEditorOut, draft: SelectionMap): number | null {
  let total = snapshot.montage.card_duration;
  for (const media of snapshot.media.filter(item => item.status === "finalized")) {
    if (!media.is_video) { if (media.effective_duration === null) return null; total += media.effective_duration; continue; }
    const duration = media.source_duration;
    const ranges = draft[media.media_id] ?? [];
    if (duration === null || validateRanges(ranges, duration)) return null;
    total += retainedDuration(ranges, duration);
  }
  return total;
}
