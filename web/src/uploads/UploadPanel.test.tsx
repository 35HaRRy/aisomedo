import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SessionProvider, useSession } from "../session";
import { client } from "../test/fixtures";
import { UploadPanel } from "./UploadPanel";
import { UploadProvider } from "./UploadProvider";
import { deferred, installCrypto, uploadServer } from "./testFixtures";
import { api } from "../api/client";

function Gate() {
  const session = useSession();
  return session.status === "paired" ? <UploadProvider onPackageChanged={() => {}}><UploadPanel /></UploadProvider> : <p>{session.status}</p>;
}
function setup(conflicts = false) {
  const server = uploadServer({ conflicts });
  vi.spyOn(api, "me").mockResolvedValue(client);
  vi.spyOn(api, "uploadLimits").mockImplementation(signal => server.transport.limits(signal!));
  vi.spyOn(api, "startUpload").mockImplementation((body, signal) => server.transport.start(body, signal!));
  vi.spyOn(api, "uploadStatus").mockImplementation((id, signal) => server.transport.status(id, signal!));
  vi.spyOn(api, "uploadRange").mockImplementation((id, offset, hash, blob, signal) => server.transport.range(id, offset, hash, blob, signal!));
  vi.spyOn(api, "completeUpload").mockImplementation((id, signal) => server.transport.complete(id, signal!));
  vi.spyOn(api, "resolveUpload").mockImplementation((id, body, signal) => server.transport.resolve(id, body, signal!));
  return server;
}
beforeEach(() => { localStorage.clear(); installCrypto(); });
const select = (name = "dojo.jpg", content = "abc") => fireEvent.change(screen.getByLabelText("Fotoğraf ve video seç"), { target: { files: [new File([content], name, { type: "image/jpeg" })] } });

it("picker stays disabled until limits load and shows confirmed progress", async () => {
  const server = setup();
  const limits = deferred<Awaited<ReturnType<typeof server.transport.limits>>>();
  server.transport.limits.mockImplementationOnce(() => limits.promise);
  render(<SessionProvider><Gate /></SessionProvider>);
  expect(await screen.findByLabelText("Fotoğraf ve video seç")).toBeDisabled();
  await act(async () => limits.resolve({ max_file_bytes: 100, max_package_bytes: 1000 }));
  select();
  await screen.findByText("İşlem sırasına alındı");
  const progress = screen.getByRole("progressbar", { name: "dojo.jpg" });
  expect(progress).toHaveAttribute("value", "3");
  expect(progress).toHaveAttribute("max", "3");
  expect(screen.queryByText("Pakete eklendi")).not.toBeInTheDocument();
});

it("pause, resume and retry operate on selected row", async () => {
  const server = setup();
  const pending = deferred<Awaited<ReturnType<typeof server.transport.range>>>();
  server.transport.range.mockImplementationOnce(() => pending.promise);
  render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  select();
  await waitFor(() => expect(server.transport.range).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "Duraklat" }));
  await screen.findByText("Duraklatıldı");
  server.records.set("upload-1", { ...server.records.get("upload-1")!, received_bytes: 3, received_ranges: [[0, 3]] });
  pending.resolve(server.records.get("upload-1")!);
  fireEvent.click(screen.getByRole("button", { name: "Devam et" }));
  await screen.findByText("İşlem sırasına alındı");
  expect(server.transport.start).toHaveBeenCalledTimes(1);
});

it("reload offers original-file reselection and rejects wrong content inline", async () => {
  const server = setup();
  server.transport.range.mockRejectedValueOnce(new Error("offline"));
  const view = render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  select();
  await screen.findByText("Yükleme kesildi");
  view.unmount();
  render(<SessionProvider><Gate /></SessionProvider>);
  const picker = await screen.findByLabelText("Orijinal dosyayı yeniden seç: dojo.jpg");
  fireEvent.change(picker, { target: { files: [new File(["abd"], "dojo.jpg")] } });
  await screen.findByText("Seçilen dosya orijinal dosyayla eşleşmiyor. Aynı içeriğe sahip orijinal dosyayı seçin.");
  expect(server.transport.range).toHaveBeenCalledTimes(1);
});

it("failed diagnostics render as text, new attempt is explicit, terminal dismiss works", async () => {
  const server = setup();
  server.transport.complete.mockImplementation(async id => {
    const value = { ...server.records.get(id)!, status: "failed", error_reason: "<script>bad</script>" };
    server.records.set(id, value); return value;
  });
  render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  select();
  await screen.findByText("<script>bad</script>");
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByRole("button", { name: "Yeni yükleme başlat" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Listeden kaldır" }));
  expect(screen.queryByText("dojo.jpg")).not.toBeInTheDocument();
});

it("conflict blocks transfer without overwrite or automatic rename", async () => {
  const server = setup();
  server.transport.start.mockImplementationOnce(async body => ({ upload_id: "conflict", declared_size_bytes: body.declared_size_bytes, received_bytes: 0, received_ranges: [], status: "conflict", error_reason: null, conflicts: [] }));
  render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  select();
  await screen.findByText("Dosya adı çakışıyor");
  expect(screen.queryByRole("button", { name: /üzerine yaz/i })).not.toBeInTheDocument();
  expect(server.transport.range).not.toHaveBeenCalled();
});

it("storage warning does not block upload selection", async () => {
  setup();
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw Error("blocked"); });
  render(<SessionProvider><Gate /></SessionProvider>);
  await screen.findByText("Tarayıcı yükleme bilgilerini saklayamıyor. Sayfa yenilenirse bu yükleme kaldığı yerden sürdürülemez.");
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
});

it("shows target image and keep both resumes upload only after explicit decision", async () => {
  const server = setup(true);
  render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  select();
  const preview = await screen.findByRole("img", { name: "Mevcut dosya önizlemesi: dojo.jpg" });
  expect(preview).toHaveAttribute("src", "/api/media/uploads/upload-1/conflicts/dojo.jpg/preview");
  expect(server.transport.range).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Kararı uygula" }));
  await screen.findByText("İşlem sırasına alındı");
  expect(server.transport.resolve.mock.calls[0][1]).toEqual({ decision: "keep_both", apply_to_all: false });
});

it("overwrite needs loaded preview and unchecked explicit irreversible confirmation", async () => {
  const server = setup(true);
  render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  select();
  const preview = await screen.findByRole("img", { name: "Mevcut dosya önizlemesi: dojo.jpg" });
  fireEvent.click(screen.getByRole("radio", { name: "Yeni dosyayı kullan (mevcut dosyayı değiştir)" }));
  expect(screen.getByText(/geri döndürülemez/i)).toBeInTheDocument();
  const confirm = screen.getByRole("checkbox", { name: "Mevcut dosyanın kalıcı olarak silineceğini anlıyorum" });
  expect(confirm).not.toBeChecked();
  const submit = screen.getByRole("button", { name: "Mevcut dosyanın üzerine yaz" });
  expect(submit).toBeDisabled();
  fireEvent.click(confirm);
  expect(submit).toBeDisabled();
  fireEvent.load(preview);
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  await screen.findByText("İşlem sırasına alındı");
  expect(server.transport.resolve.mock.calls[0][1]).toEqual({ decision: "keep_selected", target_media_id: "dojo.jpg", apply_to_all: false, confirmed_overwrite: true });
});

it("preview failure blocks replacement, offers retry, but allows keeping existing", async () => {
  const server = setup(true);
  render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  select();
  fireEvent.error(await screen.findByRole("img", { name: "Mevcut dosya önizlemesi: dojo.jpg" }));
  await screen.findByText(/Önizleme yüklenemedi/);
  fireEvent.click(screen.getByRole("radio", { name: "Yeni dosyayı kullan (mevcut dosyayı değiştir)" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Mevcut dosyanın kalıcı olarak silineceğini anlıyorum" }));
  expect(screen.getByRole("button", { name: "Mevcut dosyanın üzerine yaz" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Önizlemeyi yeniden yükle" })).toBeEnabled();
  fireEvent.click(screen.getByRole("radio", { name: "Mevcut dosyayı koru (yüklemeyi atla)" }));
  fireEvent.click(screen.getByRole("button", { name: "Kararı uygula" }));
  await screen.findByText("Mevcut dosya korundu; yükleme atlandı");
  expect(server.transport.range).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Listeden kaldır" }));
  expect(screen.queryByText("dojo.jpg")).not.toBeInTheDocument();
});

it("shows processed MP4 player without autoplay for video conflict", async () => {
  setup(true);
  render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Fotoğraf ve video seç"), { target: { files: [new File(["video"], "dojo.mov", { type: "video/quicktime" })] } });
  const video = await screen.findByLabelText("Mevcut dosya önizlemesi: dojo.mov");
  expect(video.tagName).toBe("VIDEO");
  expect(video).toHaveAttribute("controls");
  expect(video).not.toHaveAttribute("autoplay");
  expect(video).toHaveAttribute("preload", "metadata");
});

it("bulk checkbox sends compatible apply-to-all and disables duplicate submission", async () => {
  const server = setup(true);
  const pending = deferred<Awaited<ReturnType<typeof server.transport.resolve>>>();
  server.transport.resolve.mockImplementationOnce(() => pending.promise);
  render(<SessionProvider><Gate /></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  select();
  await screen.findByRole("img");
  fireEvent.click(screen.getByRole("checkbox", { name: "Aynı adlı mevcut çakışmaların tümüne uygula" }));
  fireEvent.click(screen.getByRole("radio", { name: "Mevcut dosyayı koru (yüklemeyi atla)" }));
  fireEvent.click(screen.getByRole("button", { name: "Kararı uygula" }));
  expect(screen.getByRole("button", { name: "Kararı uygula" })).toBeDisabled();
  expect(server.transport.resolve.mock.calls[0][1]).toEqual({ decision: "keep_target", apply_to_all: true });
  await act(async () => pending.resolve(server.records.get("upload-1")!));
});
