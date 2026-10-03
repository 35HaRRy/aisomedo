import { act, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { UploadProvider } from "../uploads/UploadProvider";
import { PackageEditorProvider } from "./PackageEditorProvider";
import { ActivePackagePanel } from "./ActivePackagePanel";
import { editorServer } from "./testFixtures";

beforeEach(() => { localStorage.clear(); Object.defineProperty(navigator, "onLine", { value: true, configurable: true }); });

it("photo duration edits save and discard; disabled save explains unchanged state separately from render", async () => {
  const { server } = await setup(server => {
    server.snapshot.media.push({ ...server.snapshot.media[0], media_id: "photo", filename: "photo.jpg", is_video: false, effective_duration: 3, source_duration: null });
    server.snapshot.montage.order.push("photo");
    server.snapshot.render_stale = true;
  });
  expect(screen.getByText("Kaydedilecek değişiklik yok.")).toBeInTheDocument();
  const duration = screen.getByRole("spinbutton", { name: "photo.jpg görüntülenme süresi (saniye)" });
  expect(duration).toHaveValue(3);
  fireEvent.change(duration, { target: { value: "4.5" } });
  expect(screen.getByRole("button", { name: "Bölümleri kaydet" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Bölümleri kaydet" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Bölümleri kaydet" })).toBeDisabled());
  expect(server.snapshot.media.find(m => m.media_id === "photo")?.effective_duration).toBe(4.5);
  fireEvent.change(duration, { target: { value: "6" } });
  fireEvent.click(screen.getByRole("button", { name: "Kaydedilmemiş değişiklikleri geri al" }));
  expect(duration).toHaveValue(4.5); expect(server.writes).toHaveLength(1);
});

it("clear warns, cancellation writes nothing, confirmation removes package and upload queue", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const { server } = await setup();
  fireEvent.click(screen.getByRole("button", { name: "Paketi temizle" }));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("geri alınamaz"));
  expect(server.writes).toHaveLength(0);
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Paketi temizle" }));
  await screen.findByText("Aktif paket yok. Medya yükleyerek yeni paket oluşturabilirsiniz.");
  expect(screen.queryByRole("list", { name: "Montaj sırası" })).not.toBeInTheDocument();
  expect(server.writes[0].body).toEqual({ expected_folder_name: "02-10-2026 13-00", expected_package_id: 1, confirmed: true });
});

it("saved reel preview shows rendered artifact and render action keeps unsaved section drafts", async () => {
  const { server, container } = await setup(server => {
    server.snapshot.render_status = "ready"; server.snapshot.render_preview_url = "/api/packages/active/render/preview?revision=saved";
  });
  expect(screen.getByLabelText("Kaydedilmiş Reel önizlemesi", { selector: "video" })).toHaveAttribute("src", "/api/packages/active/render/preview?revision=saved");
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  fireEvent.click(screen.getByRole("button", { name: "Bölüm ekle" }));
  fireEvent.click(screen.getByRole("button", { name: "Kaydedilmiş montajı render et" }));
  await waitFor(() => expect(server.writes).toHaveLength(1));
  expect(server.writes[0].url).toBe("/api/packages/active/render");
  expect(screen.getByLabelText("1. bölüm bitişi (saniye)")).toHaveValue("1");
  expect(container.querySelector(".saved-reel-preview")).toBeInTheDocument();
});
async function setup(configure?: (server: ReturnType<typeof editorServer>) => void) {
  const server = editorServer(); configure?.(server); vi.stubGlobal("fetch", server.fetcher);
  const view = render(<SessionProvider><PackageEditorProvider><UploadProvider onPackageChanged={() => {}}><ActivePackagePanel /></UploadProvider></PackageEditorProvider></SessionProvider>);
  await screen.findByText("a.mp4"); return { server, ...view };
}

function addPhoto(server: ReturnType<typeof editorServer>) {
  server.snapshot.media.push({ ...server.snapshot.media[0], media_id: "c", filename: "c.jpg", content_type: "image/jpeg", is_video: false, source_duration: null, effective_duration: 5, preview_url: "/c.jpg" });
  server.snapshot.montage.order.push("c");
}
function transfer() { return { setData: vi.fn(), setDragImage: vi.fn(), effectAllowed: "", dropEffect: "" }; }
function dragAt(type: "dragOver" | "drop", row: HTMLElement, dataTransfer: ReturnType<typeof transfer>, clientX: number) {
  const event = createEvent[type](row, { dataTransfer });
  Object.defineProperty(event, "clientX", { value: clientX });
  Object.defineProperty(event, "clientY", { value: 150 });
  fireEvent(row, event);
}

it("media actions use labelled SVG icons with drag handle last", async () => {
  await setup();
  const row = screen.getByText("a.mp4").closest("li")!;
  const buttons = within(row).getAllByRole("button");
  for (const button of buttons) {
    expect(button.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(button).toHaveAttribute("title", button.getAttribute("aria-label"));
    expect(button.textContent).toBe("");
  }
  expect(buttons[buttons.length - 1]).toHaveAccessibleName("a.mp4 sırasını sürükle");
  fireEvent.click(within(row).getByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  const close = within(row).getByRole("button", { name: "a.mp4 bölümlerini düzenle" });
  expect(close).toHaveAttribute("aria-expanded", "true");
  expect(close.querySelector("svg")).not.toBeNull();
});

it("holding drag handle highlights only that row and release or cancellation clears selection", async () => {
  await setup();
  const handle = screen.getByRole("button", { name: "a.mp4 sırasını sürükle" }), row = handle.closest("li")!;
  fireEvent.pointerDown(handle);
  expect(row).toHaveAttribute("data-selected", "true");
  expect(screen.getByText("b.mp4").closest("li")).not.toHaveAttribute("data-selected", "true");
  fireEvent.pointerUp(window);
  expect(row).not.toHaveAttribute("data-selected", "true");
  fireEvent.pointerDown(handle);
  fireEvent.pointerCancel(window);
  expect(row).not.toHaveAttribute("data-selected", "true");
});

it.each([
  ["a", "c", "before", ["b", "a", "c"]],
  ["a", "c", "after", ["b", "c", "a"]],
  ["c", "a", "before", ["c", "a", "b"]],
  ["c", "a", "after", ["a", "c", "b"]],
  ["b", "c", "after", ["a", "c", "b"]],
  ["b", "a", "before", ["b", "a", "c"]],
] as const)("dropping %s %s %s accounts for removed source position", async (source, target, position, expected) => {
  const { server } = await setup(addPhoto), dataTransfer = transfer();
  const handle = screen.getByRole("button", { name: `${source === "c" ? "c.jpg" : `${source}.mp4`} sırasını sürükle` });
  const sourceRow = handle.closest("li")!, targetRow = screen.getByText(target === "c" ? "c.jpg" : `${target}.mp4`).closest("li")!;
  vi.spyOn(targetRow, "getBoundingClientRect").mockReturnValue({ top: 100, left: 0, height: 100, width: 400 } as DOMRect);
  fireEvent.dragStart(handle, { dataTransfer });
  expect(dataTransfer.setDragImage).toHaveBeenCalledWith(sourceRow, expect.any(Number), expect.any(Number));
  expect(sourceRow).toHaveAttribute("data-selected", "true");
  expect(sourceRow).toHaveAttribute("data-dragging", "true");
  const x = position === "before" ? 100 : 300;
  dragAt("dragOver", targetRow, dataTransfer, x);
  expect(targetRow).toHaveAttribute("data-drop-position", position);
  expect(server.writes).toHaveLength(0);
  expect(within(screen.getByRole("list", { name: "Montaj sırası" })).getAllByRole("heading").map(h => h.textContent)).toEqual(["a.mp4", "b.mp4", "c.jpg"]);
  dragAt("drop", targetRow, dataTransfer, x);
  await waitFor(() => expect(server.snapshot.montage.order).toEqual(expected));
  expect(server.writes[0].body).toEqual({ order: [...expected], expected_folder_name: "02-10-2026 13-00" });
  expect(sourceRow).not.toHaveAttribute("data-selected", "true");
  expect(targetRow).not.toHaveAttribute("data-drop-position");
});

it("cancelled and unchanged drops never persist, and external or timeline drags cannot reorder", async () => {
  const { server } = await setup(), dataTransfer = transfer();
  const handle = screen.getByRole("button", { name: "b.mp4 sırasını sürükle" }), row = screen.getByText("a.mp4").closest("li")!;
  vi.spyOn(row, "getBoundingClientRect").mockReturnValue({ top: 100, left: 100, height: 100, width: 100 } as DOMRect);
  fireEvent.dragStart(handle, { dataTransfer });
  dragAt("dragOver", row, dataTransfer, 125);
  expect(row).toHaveAttribute("data-drop-position", "before");
  fireEvent.dragEnd(handle);
  expect(row).not.toHaveAttribute("data-drop-position");
  expect(handle.closest("li")).not.toHaveAttribute("data-selected", "true");
  dragAt("drop", row, dataTransfer, 125);
  fireEvent.dragStart(handle, { dataTransfer });
  dragAt("drop", row, dataTransfer, 175); // b is already after a.
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  const timeline = screen.getByRole("group", { name: "Video zaman çizelgesi" });
  fireEvent.dragStart(timeline, { dataTransfer });
  dragAt("dragOver", row, dataTransfer, 125);
  expect(row).not.toHaveAttribute("data-drop-position");
  dragAt("drop", row, dataTransfer, 125);
  fireEvent.dragStart(handle, { dataTransfer });
  dragAt("dragOver", row, dataTransfer, 125);
  dragAt("dragOver", timeline, dataTransfer, 125);
  expect(row).not.toHaveAttribute("data-drop-position");
  dragAt("drop", timeline, dataTransfer, 125);
  expect(server.writes).toHaveLength(0);
});

it("rejected drag drop retains server order and clears all drag visuals", async () => {
  await setup(server => { server.writeStatus = 409; });
  const dataTransfer = transfer();
  const handle = screen.getByRole("button", { name: "b.mp4 sırasını sürükle" }), row = screen.getByText("a.mp4").closest("li")!;
  fireEvent.dragStart(handle, { dataTransfer });
  dragAt("dragOver", row, dataTransfer, 0);
  dragAt("drop", row, dataTransfer, 0);
  await screen.findByText("Paket değişti veya işlem reddedildi. Taslakları kontrol ederek paketi yenileyin.");
  expect(within(screen.getByRole("list", { name: "Montaj sırası" })).getAllByRole("heading").map(h => h.textContent)).toEqual(["a.mp4", "b.mp4"]);
  expect(row).not.toHaveAttribute("data-drop-position");
  expect(handle.closest("li")).not.toHaveAttribute("data-selected", "true");
});

it("remove/restore update ordered and removed rows and mark render stale", async () => {
  const { server } = await setup();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 dosyasını paketten çıkar" }));
  await screen.findByRole("button", { name: "a.mp4 dosyasını geri yükle" });
  expect(within(screen.getByRole("list", { name: "Montaj sırası" })).queryByText("a.mp4")).not.toBeInTheDocument();
  const removed = screen.getByRole("region", { name: "Paketten çıkarılmış medya" });
  expect(within(removed).getByText("a.mp4")).toBeInTheDocument();
  expect(screen.getByText("Render güncel değil. Bölüm ve sıra değişiklikleri yeni render gerektirir.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 dosyasını geri yükle" }));
  await screen.findByRole("button", { name: "a.mp4 dosyasını paketten çıkar" });
  expect(within(screen.getByRole("list", { name: "Montaj sırası" })).getByText("a.mp4")).toBeInTheDocument();
  expect(server.writes.map(write => write.url)).toEqual([
    "/api/packages/active/media/a/remove?expected_folder_name=02-10-2026%2013-00",
    "/api/packages/active/media/a/restore?expected_folder_name=02-10-2026%2013-00",
  ]);
});

it("removed photos stay out of active order even when snapshot order still contains their ID", async () => {
  await setup(server => { addPhoto(server); server.snapshot.media[2].status = "removed"; });
  expect(within(screen.getByRole("list", { name: "Montaj sırası" })).queryByText("c.jpg")).not.toBeInTheDocument();
  const restore = screen.getByRole("button", { name: "c.jpg dosyasını geri yükle" });
  expect(restore.querySelector("svg")).not.toBeNull();
  expect(restore).toHaveAttribute("title", "c.jpg dosyasını geri yükle");
  fireEvent.click(restore);
  await waitFor(() => expect(within(screen.getByRole("list", { name: "Montaj sırası" })).getByText("c.jpg")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "c.jpg dosyasını paketten çıkar" }));
  await screen.findByRole("button", { name: "c.jpg dosyasını geri yükle" });
  expect(within(screen.getByRole("list", { name: "Montaj sırası" })).queryByText("c.jpg")).not.toBeInTheDocument();
});

it("keyboard ordering persists identity and rejected reorder never changes displayed order", async () => {
  const { server } = await setup();
  expect(screen.getByRole("button", { name: "a.mp4 dosyasını sola taşı" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "b.mp4 dosyasını sağa taşı" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 dosyasını sağa taşı" }));
  await waitFor(() => expect(within(screen.getByRole("list", { name: "Montaj sırası" })).getAllByRole("heading")[0]).toHaveTextContent("b.mp4"));
  expect(server.writes[0].body).toEqual({ order: ["b", "a"], expected_folder_name: "02-10-2026 13-00" });
  server.writeStatus = 409;
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 dosyasını sola taşı" }));
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

it("removing a numerically moved row removes displayed section, not its sorted neighbor", async () => {
  const { server } = await setup(server => { server.snapshot.montage.selections.a = [{ start: 0, end: 5 }, { start: 10, end: 15 }]; });
  fireEvent.click(screen.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  fireEvent.change(screen.getByLabelText("1. bölüm bitişi (saniye)"), { target: { value: "25" } });
  fireEvent.change(screen.getByLabelText("1. bölüm başlangıcı (saniye)"), { target: { value: "20" } });
  fireEvent.click(screen.getByRole("button", { name: "1. bölümü kaldır" }));
  expect(screen.getByLabelText("1. bölüm başlangıcı (saniye)")).toHaveValue("10");
  expect(screen.getByLabelText("1. bölüm bitişi (saniye)")).toHaveValue("15");
  fireEvent.click(screen.getByRole("button", { name: "Bölümleri kaydet" }));
  await waitFor(() => expect(server.snapshot.montage.selections.a).toEqual([{ start: 10, end: 15 }]));
});
