import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { UploadProvider } from "../uploads/UploadProvider";
import { PackageEditorProvider } from "./PackageEditorProvider";
import { ActivePackagePanel } from "./ActivePackagePanel";
import { editorServer } from "./testFixtures";

beforeEach(() => { localStorage.clear(); Object.defineProperty(navigator, "onLine", { value: true, configurable: true }); });
async function setup(configure?: (server: ReturnType<typeof editorServer>) => void) {
  const server = editorServer(); configure?.(server); vi.stubGlobal("fetch", server.fetcher);
  const view = render(<SessionProvider><PackageEditorProvider><UploadProvider onPackageChanged={() => {}}><ActivePackagePanel /></UploadProvider></PackageEditorProvider></SessionProvider>);
  await screen.findByText("a.mp4"); return { server, ...view };
}

it("remove/restore update ordered and removed rows and mark render stale", async () => {
  const { server } = await setup();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 dosyasını paketten çıkar" }));
  await screen.findByRole("button", { name: "a.mp4 dosyasını geri yükle" });
  expect(screen.getByText("Render güncel değil. Bölüm ve sıra değişiklikleri yeni render gerektirir.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 dosyasını geri yükle" }));
  await screen.findByRole("button", { name: "a.mp4 dosyasını paketten çıkar" });
  expect(server.writes.map(write => write.url)).toEqual([
    "/api/packages/active/media/a/remove?expected_folder_name=02-10-2026%2013-00",
    "/api/packages/active/media/a/restore?expected_folder_name=02-10-2026%2013-00",
  ]);
});

it("keyboard ordering persists identity and rejected reorder never changes displayed order", async () => {
  const { server } = await setup();
  fireEvent.click(screen.getByRole("button", { name: "b.mp4 dosyasını yukarı taşı" }));
  await waitFor(() => expect(within(screen.getByRole("list", { name: "Montaj sırası" })).getAllByRole("heading")[0]).toHaveTextContent("b.mp4"));
  expect(server.writes[0].body).toEqual({ order: ["b", "a"], expected_folder_name: "02-10-2026 13-00" });
  server.writeStatus = 409;
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 dosyasını yukarı taşı" }));
  await screen.findByText("Paket değişti veya işlem reddedildi. Taslakları kontrol ederek paketi yenileyin.");
  expect(within(screen.getByRole("list", { name: "Montaj sırası" })).getAllByRole("heading")[0]).toHaveTextContent("b.mp4");
});

it("drag handles persist order, not timeline gestures", async () => {
  const { server } = await setup(); const values = new Map<string, string>();
  const transfer = { setData: (type: string, value: string) => values.set(type, value), getData: (type: string) => values.get(type) };
  fireEvent.dragStart(screen.getByRole("button", { name: "b.mp4 sırasını sürükle" }), { dataTransfer: transfer });
  fireEvent.drop(screen.getByText("a.mp4").closest("li")!, { dataTransfer: transfer });
  await waitFor(() => expect(server.writes).toHaveLength(1));
  expect(server.writes[0].body).toEqual({ order: ["b", "a"], expected_folder_name: "02-10-2026 13-00" });
});

it("only one preview mounts while invalid inputs survive switching and all videos save together", async () => {
  const { server, container } = await setup();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  fireEvent.click(screen.getByRole("button", { name: "Bölüm ekle" }));
  fireEvent.change(screen.getByLabelText("1. bölüm bitişi (saniye)"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "b.mp4 bölümlerini düzenle" }));
  expect(container.querySelectorAll("video")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Bölüm ekle" }));
  expect(screen.getByRole("button", { name: "Bölümleri kaydet" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  expect(screen.getByLabelText("1. bölüm bitişi (saniye)")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("1. bölüm bitişi (saniye)"), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Bölümleri kaydet" }));
  await waitFor(() => expect(server.writes).toHaveLength(1));
  expect(server.writes[0].body).toEqual({ expected_folder_name: "02-10-2026 13-00", selections: { a: [{ start: 0, end: 5 }], b: [{ start: 0, end: 1 }] } });
});

it("upload refresh appends media but keeps dirty inputs and locks changed snapshot", async () => {
  const { server } = await setup();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  fireEvent.click(screen.getByRole("button", { name: "Bölüm ekle" }));
  server.snapshot.media.push({ ...server.snapshot.media[1], media_id: "c", filename: "c.mp4" });
  server.snapshot.montage.order.push("c");
  act(() => window.dispatchEvent(new Event("focus")));
  await screen.findByText("c.mp4");
  expect(screen.getByLabelText("1. bölüm bitişi (saniye)")).toHaveValue("1");
  expect(screen.getByRole("button", { name: "Bölümleri kaydet" })).toBeDisabled();
  expect(screen.getByText("Paket dışarıdan değişti. Taslaklar korunuyor; yazmadan önce yenileyin veya değişiklikleri atın.")).toBeInTheDocument();
});

it("remount shows persisted ranges rather than previous local input state", async () => {
  const { server, unmount } = await setup();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  fireEvent.click(screen.getByRole("button", { name: "Bölüm ekle" }));
  fireEvent.click(screen.getByRole("button", { name: "Bölümleri kaydet" }));
  await waitFor(() => expect(server.writes).toHaveLength(1));
  await screen.findByText("Bölümler kaydedildi."); unmount();
  render(<SessionProvider><PackageEditorProvider><UploadProvider onPackageChanged={() => {}}><ActivePackagePanel /></UploadProvider></PackageEditorProvider></SessionProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  expect(screen.getByLabelText("1. bölüm bitişi (saniye)")).toHaveValue("1");
  expect(screen.getByRole("button", { name: "Bölümleri kaydet" })).toBeDisabled();
});

it("known over-limit total differs from unknown source duration", async () => {
  const { unmount } = await setup(server => { server.snapshot.montage.max_duration_seconds = 40; });
  expect(screen.getByText(/Sınırı aşan süreyi azaltın: 20.00 s/)).toBeInTheDocument(); unmount();
  await setup(server => { server.snapshot.media[0].source_duration = null; server.snapshot.media[0].effective_duration = null; });
  expect(screen.getByText("Süre hesaplanamıyor")).toBeInTheDocument();
  expect(screen.queryByText(/Sınırı aşan süreyi azaltın/)).not.toBeInTheDocument();
});
