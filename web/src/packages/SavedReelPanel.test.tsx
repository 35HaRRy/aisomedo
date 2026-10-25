import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { PackageEditorProvider, usePackageEditorContext } from "./PackageEditorProvider";
import { SavedReelPanel } from "./SavedReelPanel";
import { editorServer } from "./testFixtures";

beforeEach(() => { window.location.hash = "#/package"; });

function Edit() {
  const editor = usePackageEditorContext();
  return <button onClick={() => editor.setRanges("a", [{ start: 0, end: 5 }])}>Edit draft</button>;
}

it("displays measured render duration, not dirty montage duration, and renders saved inputs", async () => {
  const server = editorServer();
  server.snapshot.render_status = "ready"; server.snapshot.render_preview_url = "/saved-reel.mp4";
  server.snapshot.render_duration = 12.34;
  vi.stubGlobal("fetch", server.fetcher);
  render(<SessionProvider><PackageEditorProvider><Edit /><SavedReelPanel /></PackageEditorProvider></SessionProvider>);
  await screen.findByRole("heading", { name: "Kaydedilmiş Reel önizlemesi · 12.34 s" });
  fireEvent.click(screen.getByText("Edit draft"));
  expect(screen.getByLabelText("Kaydedilmiş Reel önizlemesi")).toHaveAttribute("src", "/saved-reel.mp4");
  expect(screen.getByText("Önizleme kaydedilmemiş değişiklikleri içermez.")).toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Kaydedilmiş montajı render et" })));
  await waitFor(() => expect(server.writes).toHaveLength(1));
  expect(server.writes[0].url).toBe("/api/packages/active/render");
  expect(server.snapshot.montage.selections).toEqual({});
});

it("uses loaded file metadata only when legacy render duration is absent", async () => {
  const server = editorServer();
  server.snapshot.render_status = "ready"; server.snapshot.render_preview_url = "/legacy.mp4";
  vi.stubGlobal("fetch", server.fetcher);
  render(<SessionProvider><PackageEditorProvider><SavedReelPanel /></PackageEditorProvider></SessionProvider>);
  const video = await screen.findByLabelText("Kaydedilmiş Reel önizlemesi");
  Object.defineProperty(video, "duration", { value: 8.125 }); fireEvent.loadedMetadata(video);
  expect(screen.getByRole("heading", { name: "Kaydedilmiş Reel önizlemesi · 8.13 s" })).toBeInTheDocument();
});
