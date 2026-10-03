import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";
import { App } from "../App";
import type { UploadOut } from "../api/openapi";
import { client, dashboard, emptyEditor, setupState } from "../test/fixtures";
import { deferred, installCrypto } from "./testFixtures";

beforeEach(() => { localStorage.clear(); installCrypto(); window.location.hash = "#/package"; });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function fixture({ fileLimit = 100000000, holdFirst = false, loseFirst = false, deny = false } = {}) {
  const first = deferred<Response>();
  const offsets: number[] = [];
  let initializations = 0;
  let current: UploadOut | null = null;
  const fetcher = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url === "/api/compat") return json({ api_version: "0.1.0" });
    if (url === "/api/pairing/me") return json(client);
    if (url === "/api/setup") return json(setupState());
    if (url === "/api/dashboard") return json(dashboard());
    if (url === "/api/packages/active/editor") return json(emptyEditor());
    if (url === "/api/packages") return json([]);
    if (url === "/api/media/upload-limits") return json({ max_file_bytes: fileLimit, max_package_bytes: 1000000000 });
    if (url === "/api/media/uploads" && init.method === "POST") {
      const body = JSON.parse(String(init.body));
      current = { upload_id: `upload-${++initializations}`, declared_size_bytes: body.declared_size_bytes,
        received_bytes: 0, received_ranges: [], status: "receiving", error_reason: null, conflicts: [] };
      return json(current, 201);
    }
    if (url.includes("/ranges?")) {
      if (deny) return json({}, 401);
      const query = new URL(url, "http://fixture").searchParams;
      const offset = Number(query.get("offset"));
      const blob = init.body as Blob;
      const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result as ArrayBuffer); reader.onerror = reject; reader.readAsArrayBuffer(blob);
      });
      expect(query.get("checksum_sha256")).toBe(createHash("sha256").update(new Uint8Array(bytes)).digest("hex"));
      offsets.push(offset);
      current = { ...current!, received_bytes: offset + blob.size, received_ranges: [[0, offset + blob.size]] };
      if (offsets.length === 1 && loseFirst) throw new TypeError("lost response");
      if (offsets.length === 1 && holdFirst) return first.promise;
      return json(current);
    }
    if (url.endsWith("/complete")) { current = { ...current!, status: "queued" }; return json(current); }
    if (url.startsWith("/api/media/uploads/")) return json(current);
    throw Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { fetcher, offsets, first, initializations: () => initializations,
    current: () => current!, set: (value: UploadOut) => { current = value; } };
}
async function select(file: File) {
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Fotoğraf ve video seç"), { target: { files: [file] } });
}

it("actual API flow preserves File through navigation and resumes paused accepted chunk", async () => {
  const f = fixture({ holdFirst: true });
  render(<App />);
  await select(new File([new Uint8Array(2097155)], "dojo.mp4", { type: "video/mp4" }));
  await waitFor(() => expect(f.offsets).toEqual([0]));
  fireEvent.click(screen.getByRole("button", { name: "Duraklat" }));
  await screen.findByText("Duraklatıldı");
  fireEvent.click(screen.getByRole("link", { name: "Ayarlar" }));
  await screen.findByRole("heading", { name: "Ayarlar" });
  fireEvent.click(screen.getByRole("link", { name: "Güncel Paket" }));
  await screen.findByText("Duraklatıldı");
  f.first.resolve(json(f.current()));
  fireEvent.click(screen.getByRole("button", { name: "Devam et" }));
  await screen.findByText("İşlem sırasına alındı");
  expect(f.offsets).toEqual([0, 2097152]);
  expect(f.initializations()).toBe(1);
  expect(screen.getByRole("progressbar", { name: "dojo.mp4" })).toHaveAttribute("value", "2097155");
});

it("actual API reload rejects wrong file and shows authoritative worker outcomes", async () => {
  const f = fixture({ loseFirst: true });
  const view = render(<App />);
  await select(new File(["abc"], "dojo.jpg", { type: "image/jpeg" }));
  await screen.findByText("Yükleme kesildi");
  view.unmount();
  render(<App />);
  const reselect = await screen.findByLabelText("Orijinal dosyayı yeniden seç: dojo.jpg");
  fireEvent.change(reselect, { target: { files: [new File(["abd"], "dojo.jpg")] } });
  await screen.findByText("Seçilen dosya orijinal dosyayla eşleşmiyor. Aynı içeriğe sahip orijinal dosyayı seçin.");
  expect(f.offsets).toEqual([0]);
  fireEvent.change(screen.getByLabelText("Orijinal dosyayı yeniden seç: dojo.jpg"), { target: { files: [new File(["abc"], "dojo.jpg")] } });
  await screen.findByText("İşlem sırasına alındı");
  expect(f.initializations()).toBe(1);
  expect(f.offsets).toEqual([0]);
  f.set({ ...f.current(), status: "processing" });
  await act(async () => window.dispatchEvent(new Event("focus")));
  await screen.findByText("Medya doğrulanıyor");
  f.set({ ...f.current(), status: "failed", error_reason: "invalid JPEG contents" });
  await act(async () => window.dispatchEvent(new Event("focus")));
  await screen.findByText("invalid JPEG contents");
  expect(screen.queryByText("Pakete eklendi")).not.toBeInTheDocument();
});

it("actual API oversize rejects before initiation and session loss returns pairing", async () => {
  const f = fixture({ fileLimit: 2 });
  const view = render(<App />);
  await select(new File(["abc"], "dojo.jpg"));
  await screen.findByText("Dosya yapılandırılan sınırı aşıyor. Gösterilen sınıra uygun daha küçük bir dosya seçin.");
  expect(f.initializations()).toBe(0);
  expect(f.offsets).toEqual([]);
  view.unmount();
  fixture({ deny: true });
  render(<App />);
  await select(new File(["abc"], "dojo.jpg"));
  await screen.findByRole("heading", { name: "Tarayıcıyı eşleştir" });
  expect(screen.queryByText("dojo.jpg")).not.toBeInTheDocument();
});

it("actual API explicit retry reconciles lost response then automatically removes finalized upload", async () => {
  const f = fixture({ loseFirst: true });
  render(<App />);
  await select(new File([new Uint8Array(2097155)], "dojo.mp4", { type: "video/mp4" }));
  await screen.findByText("Yükleme kesildi");
  const row = screen.getByText("dojo.mp4").closest("li")!;
  const retry = Array.from(row.querySelectorAll("button")).find(button => button.textContent === "Tekrar dene")!;
  fireEvent.click(retry);
  await screen.findByText("İşlem sırasına alındı");
  expect(f.offsets).toEqual([0, 2097152]);
  expect(f.initializations()).toBe(1);
  expect(screen.queryByText("Pakete eklendi")).not.toBeInTheDocument();
  f.set({ ...f.current(), status: "finalized" });
  await act(async () => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(screen.queryByRole("progressbar", { name: "dojo.mp4" })).not.toBeInTheDocument());
  expect(JSON.parse(localStorage.getItem("aisomedo.uploads.v1:1")!).records).toEqual([]);
});

it("completed browsing leaves active upload File and accepted offsets intact", async () => {
  const f = fixture({ holdFirst: true }); render(<App />);
  await select(new File([new Uint8Array(2097155)], "dojo.mp4", { type: "video/mp4" }));
  await waitFor(() => expect(f.offsets).toEqual([0]));
  fireEvent.click(screen.getByRole("button", { name: "Duraklat" }));
  fireEvent.click(screen.getByRole("button", { name: "Tamamlanmış paketler" }));
  await screen.findByText("Henüz tamamlanmış paket yok.");
  expect(screen.queryByLabelText("Fotoğraf ve video seç")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Aktif pakete dön" }));
  await screen.findByText("Duraklatıldı"); f.first.resolve(json(f.current()));
  fireEvent.click(screen.getByRole("button", { name: "Devam et" }));
  await screen.findByText("İşlem sırasına alındı");
  expect(f.offsets).toEqual([0, 2097152]); expect(f.initializations()).toBe(1);
});
