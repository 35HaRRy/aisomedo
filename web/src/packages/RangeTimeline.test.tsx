import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { RangeTimeline } from "./RangeTimeline";
import type { VideoRange } from "./ranges";

beforeEach(() => {
  class Pointer extends MouseEvent { pointerId: number; constructor(type: string, init: PointerEventInit) { super(type, init); this.pointerId = init.pointerId ?? 1; } }
  vi.stubGlobal("PointerEvent", Pointer);
});
function setup(initial: VideoRange[] = []) {
  const change = vi.fn(), seek = vi.fn(), capture = vi.fn(), release = vi.fn();
  function Probe() {
    const [ranges, setRanges] = useState(initial);
    return <><RangeTimeline duration={30} ranges={ranges} playhead={0} disabled={false} onChange={value => { change(value); setRanges(value); }} onSeek={seek} /><output>{JSON.stringify(ranges)}</output></>;
  }
  render(<Probe />);
  const track = screen.getByRole("group", { name: "Video zaman çizelgesi" });
  vi.spyOn(track, "getBoundingClientRect").mockReturnValue({ left: 100, width: 300 } as DOMRect);
  track.setPointerCapture = capture; track.releasePointerCapture = release;
  const gesture = (start: number, end: number, target: Element = track) => {
    fireEvent.pointerDown(target, { pointerId: 1, button: 0, clientX: 100 + start * 10 });
    fireEvent.pointerMove(track, { pointerId: 1, clientX: 100 + end * 10 });
    fireEvent.pointerUp(track, { pointerId: 1, clientX: 100 + end * 10 });
  };
  return { track, change, seek, capture, release, gesture };
}

it("creates source ordered 0–5/10–15/24–30 retained windows without a network write", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const { gesture, capture, release } = setup();
  gesture(0, 5); gesture(10, 15); gesture(24, 30);
  expect(screen.getByText('[{"start":0,"end":5},{"start":10,"end":15},{"start":24,"end":30}]')).toBeInTheDocument();
  expect(capture).toHaveBeenCalledWith(1); expect(release).toHaveBeenCalledWith(1); expect(fetcher).not.toHaveBeenCalled();
});

it("click seeks; cancel restores pre-gesture sections", () => {
  const { track, gesture, seek } = setup([{ start: 10, end: 15 }]);
  gesture(5, 5.2); expect(seek).toHaveBeenCalledWith(5.2);
  fireEvent.pointerDown(track, { pointerId: 1, button: 0, clientX: 100 });
  fireEvent.pointerMove(track, { pointerId: 1, clientX: 150 });
  fireEvent.pointerCancel(track, { pointerId: 1 });
  expect(screen.getByText('[{"start":10,"end":15}]')).toBeInTheDocument();
});

it("resize uses geometry, clamps neighbors, and cancels without changing order", () => {
  const { gesture, track } = setup([{ start: 0, end: 5 }, { start: 10, end: 15 }]);
  const start = screen.getByRole("slider", { name: "2. bölüm başlangıcı" });
  gesture(10, 2, start); expect(start).toHaveAttribute("aria-valuenow", "5");
  const end = screen.getByRole("slider", { name: "2. bölüm bitişi" });
  gesture(15, 40, end); expect(end).toHaveAttribute("aria-valuenow", "30");
  fireEvent.pointerDown(start, { pointerId: 2, button: 0, clientX: 150 });
  fireEvent.pointerMove(track, { pointerId: 2, clientX: 180 });
  fireEvent.pointerCancel(track, { pointerId: 2 });
  expect(start).toHaveAttribute("aria-valuenow", "5");
});

it("keyboard uses 0.1/1 second steps and one-frame limit", () => {
  setup([{ start: 10, end: 15 }]);
  const start = screen.getByRole("slider", { name: "1. bölüm başlangıcı" });
  fireEvent.keyDown(start, { key: "ArrowRight" }); expect(start).toHaveAttribute("aria-valuenow", "10.1");
  fireEvent.keyDown(start, { key: "ArrowLeft", shiftKey: true }); expect(start).toHaveAttribute("aria-valuenow", "9.1");
  fireEvent.keyDown(start, { key: "End" }); expect(start).toHaveAttribute("aria-valuenow", "14.96");
});

it("timeline events never propagate to montage row reordering", () => {
  const down = vi.fn(), drag = vi.fn();
  render(<div onPointerDown={down} onDragStart={drag}><RangeTimeline duration={30} ranges={[{ start: 0, end: 5 }]} playhead={0} disabled={false} onChange={() => {}} onSeek={() => {}} /></div>);
  const slider = screen.getByRole("slider", { name: "1. bölüm başlangıcı" });
  fireEvent.pointerDown(slider, { pointerId: 1, button: 0 }); fireEvent.dragStart(slider);
  expect(down).not.toHaveBeenCalled(); expect(drag).not.toHaveBeenCalled();
});
