import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { client } from "../test/fixtures";
import { CompletedPackages } from "./CompletedPackages";
import { deferred, packageSnapshot } from "./testFixtures";

const filename = "Çalışma.MP4", folder = "02-10-2026 13-00-completed";
const url = `/api/packages/${encodeURIComponent(folder)}/artifacts?artifact_ref=media%2Fa%2Foriginal.MP4&download=true`;
const json = (value: unknown) => new Response(JSON.stringify(value));
function detail(name = folder) { return { folder_name: name, media: [{ ...packageSnapshot().media[0], filename, status: "removed", artifacts: [{ artifact_ref: "media/a/original.MP4", kind: "original", filename, content_type: "video/mp4", available: true, url, preview_url: null }] }], order: [], caption: "Arşiv", render_revision: null, artifacts: [{ artifact_ref: "render/reel.mp4", kind: "render", filename: "reel.mp4", content_type: "video/mp4", available: false, url: null, preview_url: null }] }; }
it("completed browsing needs no active package, offers authenticated links, and exposes no writes", async () => {
  const fetcher = vi.fn(async (path: string) => path.endsWith("/me") ? json(client) : path === "/api/packages" ? json([{ ...packageSnapshot().package, folder_name: folder, status: "completed" }]) : json(detail()));
  vi.stubGlobal("fetch", fetcher);
  render(<SessionProvider><CompletedPackages onBack={() => {}} /></SessionProvider>);
  await screen.findByText(filename);
  expect(screen.getByRole("link", { name: /orijinali indir/i })).toHaveAttribute("href", url);
  expect(screen.getByText("reel.mp4 — dosya mevcut değil")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Bölümleri kaydet" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/Dosya seç/)).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(call => call[0].includes("/active"))).toBe(false);
});

it("late old-folder detail never replaces newly selected completed package", async () => {
  const first = deferred<Response>(), second = { ...packageSnapshot().package, id: 2, folder_name: "second", status: "completed" };
  vi.stubGlobal("fetch", async (path: string) => path.endsWith("/me") ? json(client) : path === "/api/packages" ? json([{ ...second, id: 1, folder_name: folder }, second]) : path.endsWith("second") ? json(detail("second")) : first.promise);
  render(<SessionProvider><CompletedPackages onBack={() => {}} /></SessionProvider>);
  await screen.findByRole("option", { name: "second" });
  fireEvent.change(screen.getByLabelText("Tamamlanmış paket seç"), { target: { value: "second" } });
  await screen.findByRole("heading", { name: "second" });
  await act(async () => { first.resolve(json(detail())); });
  await waitFor(() => expect(screen.queryByRole("heading", { name: folder })).not.toBeInTheDocument());
});

it("shows icon downloads and durations in media cards and opens processed media in the viewer", async () => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  const snapshot = packageSnapshot();
  const data = {
    ...detail(), order: ["photo", "a"],
    media: [
      { ...snapshot.media[0], filename, effective_duration: 5, thumbnail_url: "/thumb.jpg", artifacts: [
        { artifact_ref: "media/a/original.mp4", kind: "original", filename, available: true, url },
        { artifact_ref: "media/a/processed.mp4", kind: "processed", filename: "Çalışma.processed.mp4", available: true, url: "/processed-download", preview_url: "/processed.mp4" },
      ], preview_url: "/processed.mp4" },
      { ...snapshot.media[1], media_id: "photo", filename: "profile.jpg", content_type: "image/jpeg", effective_duration: 2.95, preview_url: "/profile.jpg", artifacts: [] },
    ],
    artifacts: [{ artifact_ref: "render/reel.mp4", kind: "render", filename: "reel.mp4", available: true, url: "/reel-download", preview_url: "/reel.mp4" }],
  };
  vi.stubGlobal("fetch", async (path: string) => path.endsWith("/me") ? json(client) : path === "/api/packages" ? json([{ ...snapshot.package, folder_name: folder, status: "completed" }]) : json(data));
  const view = render(<SessionProvider><CompletedPackages onBack={() => {}} /></SessionProvider>);
  await screen.findByText(filename);
  expect(screen.getByText("Fotoğraf · 2.95 s")).toBeVisible();
  expect(screen.getByText("Video · 5.00 s")).toBeVisible();
  for (const name of [/Orijinali indir/, /İşlenmiş dosyayı indir/, /Son Reel'i indir/]) {
    const link = screen.getByRole("link", { name });
    expect(link.textContent).toBe("");
    expect(link.querySelector("svg")).not.toBeNull();
  }
  expect(screen.getByAltText(`${filename} önizlemesi`)).toHaveAttribute("src", "/thumb.jpg");
  fireEvent.click(screen.getByRole("button", { name: `${filename} önizlemesi` }));
  const dialog = screen.getByRole("dialog", { name: filename });
  expect(dialog.querySelector("video")).toHaveAttribute("src", "/processed.mp4");
  fireEvent.click(within(dialog).getByRole("button", { name: "Tam ekranı kapat" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "profile.jpg önizlemesi" }));
  expect(within(screen.getByRole("dialog")).getByRole("img")).toHaveAttribute("src", "/profile.jpg");
  view.unmount();
});
