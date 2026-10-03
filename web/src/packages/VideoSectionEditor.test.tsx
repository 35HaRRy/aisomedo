import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { VideoSectionEditor } from "./VideoSectionEditor";
import type { RangeInput, VideoRange } from "./ranges";
import { packageSnapshot } from "./testFixtures";

function setup(initial: VideoRange[] = [{ start: 10, end: 15 }]) {
  const input = vi.fn(), change = vi.fn();
  function Probe() {
    const [ranges, setRanges] = useState(initial), [inputs, setInputs] = useState<RangeInput[]>(initial.map(r => ({ start: String(r.start), end: String(r.end) })));
    return <VideoSectionEditor media={packageSnapshot().media[0]} ranges={ranges} inputs={inputs} validationError={null} disabled={false}
      onChange={values => { change(values); setRanges(values); setInputs(values.map(r => ({ start: String(r.start), end: String(r.end) }))); }}
      onInputChange={(index, bound, value) => { input(index, bound, value); setInputs(old => old.map((r, i) => i === index ? { ...r, [bound]: value } : r)); }} />;
  }
  const view = render(<Probe />); return { ...view, input, change };
}

it("exact controlled fields and keyboard handles describe the same retained windows", () => {
  const { input } = setup();
  expect(screen.getByText("Yalnızca seçili bölümler kullanılacak.")).toBeInTheDocument();
  expect(screen.getByRole("slider", { name: "1. bölüm başlangıcı" })).toHaveAttribute("aria-valuenow", "10");
  expect(screen.getByLabelText("1. bölüm bitişi (saniye)")).toHaveValue("15");
  fireEvent.keyDown(screen.getByRole("slider", { name: "1. bölüm bitişi" }), { key: "ArrowLeft" });
  expect(screen.getByLabelText("1. bölüm bitişi (saniye)")).toHaveValue("14.9");
  fireEvent.change(screen.getByLabelText("1. bölüm bitişi (saniye)"), { target: { value: "" } });
  expect(input).toHaveBeenCalledWith(0, "end", ""); expect(screen.getByLabelText("1. bölüm bitişi (saniye)")).toHaveValue("");
});

it("last section removal returns whole-video mode and preserves usable focus", () => {
  const { change } = setup();
  fireEvent.click(screen.getByRole("button", { name: "1. bölümü kaldır" }));
  expect(change).toHaveBeenLastCalledWith([]);
  expect(screen.getByText("Bölüm seçilmedi: videonun tamamı kullanılacak.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Bölüm ekle" })).toHaveFocus();
});

it("preview uses native seeking, error/retry, and never fetches a blob", () => {
  const { container } = setup(); const video = container.querySelector("video")!;
  expect(video).toHaveAttribute("controls"); expect(video).toHaveAttribute("playsinline"); expect(video).toHaveAttribute("preload", "metadata");
  expect(video).toHaveAttribute("src", packageSnapshot().media[0].preview_url);
  fireEvent.error(video); expect(screen.getByText("Video önizlemesi yüklenemedi.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Önizlemeyi yeniden yükle" }));
  expect(container.querySelector("video")).not.toBe(video);
});

it("add at playhead leaves unavailable gap unchanged and explains why", () => {
  const { container, change } = setup([{ start: 0, end: 30 }]);
  const video = container.querySelector("video")!; video.currentTime = 5; fireEvent.timeUpdate(video);
  fireEvent.click(screen.getByRole("button", { name: "Bölüm ekle" }));
  expect(screen.getByText("Bu konumda en az bir kare uzunluğunda boş bölüm yok.")).toBeInTheDocument(); expect(change).not.toHaveBeenCalled();
});

it("missing duration blocks editing rather than guessing bounds", () => {
  render(<VideoSectionEditor media={{ ...packageSnapshot().media[0], source_duration: null }} ranges={[]} inputs={[]} validationError={null} disabled={false} onChange={() => {}} onInputChange={() => {}} />);
  expect(screen.getByText("Video süresi bilinmiyor. Videoyu yeniden işleyin veya paketten çıkarın.")).toBeInTheDocument();
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
});
