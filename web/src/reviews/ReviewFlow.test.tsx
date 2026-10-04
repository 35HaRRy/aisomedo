import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "../App";
import { client, dashboard, emptyEditor, setupState } from "../test/fixtures";

let state = dashboard(), editor = emptyEditor();
let detail = reviewDetail();
let actionStatus = 200;
let readStatus = 200;
let editorStatus = 200;
let pendingRead: Promise<void> | null = null;
let actionDetail: string | null = null;
let publication: { status: string; error: string | null } | null = null;
let writes: { path: string; body: unknown }[] = [];
function reviewDetail(id = 2) {
  return { review: { id, occurrence_id: 1, version: 3, package_folder: "03-08-2026 10-00", revision_digest: `exact-${id}`,
    caption: "Exact caption\n#dojo", status: "pending", created_at: "2026-08-03T07:00:00Z" },
    render_ready: true, preview_url: `/api/packages/active/render/preview?revision=exact-${id}`, next_regular_at: "2026-08-17T07:00:00Z" };
}
beforeEach(() => {
  localStorage.clear(); state = dashboard(); editor = emptyEditor(); detail = reviewDetail();
  actionStatus = 200; readStatus = 200; editorStatus = 200; pendingRead = null; actionDetail = null; writes = [];
  publication = null;
  state.pending_actions = [{ occurrence_id: 1, review_id: 2, version: 3, state: "review_ready", package_folder: state.package!.folder_name, due_at: state.generated_at }];
  window.location.hash = "#/package?review=2";
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    if (url.endsWith("/compat")) return json({ api_version: "0.1.0" });
    if (url.endsWith("/me")) return json(client);
    if (url === "/api/setup") return json(setupState());
    if (url === "/api/dashboard") return json(state);
    if (url === "/api/packages/active/editor") return json(editor, editorStatus);
    if (url === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
    if (url === "/api/packages") return json([]);
    if (url.startsWith("/api/reviews/") && (!init?.method || init.method === "GET")) { if (pendingRead) await pendingRead; return json(detail, readStatus); }
    if (init?.method === "POST") {
      writes.push({ path: url, body: JSON.parse(String(init.body)) });
      if (actionStatus === 200 && url.startsWith("/api/reviews/")) {
        detail.review.status = url.endsWith("/approve") ? "approved" : url.endsWith("/skip") ? "skipped" : "rescheduled";
        state.pending_actions = [];
      }
      return json(actionDetail ? { detail: actionDetail } : { review: detail.review, publication, next_regular_at: detail.next_regular_at }, actionStatus);
    }
    if (url.includes("/activity")) return json({ events: [{ id: 1, action: "review.created", actor: "worker", details: { review_id: 2 }, occurred_at: state.generated_at }], next_cursor: null });
    throw new Error(`Unexpected request: ${url}`);
  });
});
async function loadedPreview() {
  await screen.findByText(/Exact caption\s+#dojo/);
  const video = screen.getByLabelText("İncelenen Reel");
  fireEvent.loadedData(video);
  return video;
}

it("opens exact review without editing or publishing and requires loaded preview plus confirmation", async () => {
  render(<App />);
  await screen.findByText(/Exact caption\s+#dojo/);
  expect(screen.queryByRole("heading", { name: "Aktif paket medyası" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Onayla ve yayınla" })).toBeDisabled();
  const video = await loadedPreview();
  expect(video).toHaveAttribute("src", "/api/packages/active/render/preview?revision=exact-2");
  expect(writes).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Onayla ve yayınla" }));
  expect(screen.getByText(/Instagram.*hemen/)).toBeInTheDocument();
  expect(writes).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Yayınlamayı onayla" }));
  await screen.findByText("Yayınlama onayı alındı.");
  expect(writes).toEqual([{ path: "/api/reviews/2/approve", body: { version: 3 } }]);
  expect(screen.queryByRole("button", { name: "Onayla ve yayınla" })).not.toBeInTheDocument();
});

it("skip shows next regular slot and sends explicit confirmation only after second action", async () => {
  render(<App />); await loadedPreview();
  fireEvent.click(screen.getByRole("button", { name: "Bu zamanı atla" }));
  expect(screen.getByText(/17 Ağustos 2026.*10:00/)).toBeInTheDocument();
  expect(writes).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Atlamayı onayla" }));
  await screen.findByText("Bu Yayın Zamanı atlandı. Paket korunuyor.");
  expect(writes[0]).toEqual({ path: "/api/reviews/2/skip", body: { version: 3, confirmed: true } });
});

it("successful approval HTTP response still displays publication failure after review refresh", async () => {
  publication = { status: "failed", error: "PUBLIC_BASE_URL must use publicly reachable HTTPS" };
  render(<App />); await loadedPreview();
  fireEvent.click(screen.getByRole("button", { name: "Onayla ve yayınla" }));
  fireEvent.click(screen.getByRole("button", { name: "Yayınlamayı onayla" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Instagram'a yayın yapılamadı"));
  expect(screen.getByRole("alert")).toHaveTextContent(publication.error!);
  expect(screen.queryByText("Yayınlama onayı alındı.")).not.toBeInTheDocument();
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(screen.getByRole("alert")).toHaveTextContent("Video korunuyor");
  expect(writes).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Onayla ve yayınla" })).not.toBeInTheDocument();
});

it.each(["publishing", "uncertain"])("%s publication is unconfirmed, not a successful publish", async status => {
  publication = { status, error: null };
  render(<App />); await loadedPreview();
  fireEvent.click(screen.getByRole("button", { name: "Onayla ve yayınla" }));
  fireEvent.click(screen.getByRole("button", { name: "Yayınlamayı onayla" }));
  await screen.findByText(/Yayın henüz doğrulanmadı/);
  expect(screen.queryByText("Yayınlama onayı alındı.")).not.toBeInTheDocument();
  expect(writes).toHaveLength(1);
});

it.each(["failed", "publishing", "uncertain"])("continuation retains %s outcome after occurrence disappears", async status => {
  publication = { status, error: "PUBLIC_BASE_URL must use publicly reachable HTTPS" };
  window.location.hash = `#/package?occurrence=1&folder=${encodeURIComponent(state.package!.folder_name)}`;
  render(<App />); await loadedPreview();
  fireEvent.click(screen.getByRole("button", { name: "Onayla ve yayınla" }));
  fireEvent.click(screen.getByRole("button", { name: "Yayınlamayı onayla" }));
  const outcome = status === "failed" ? /Instagram'a yayın yapılamadı/ : /Yayın henüz doğrulanmadı/;
  await screen.findByText(outcome);
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(screen.getByText(outcome)).toBeInTheDocument();
  expect(screen.queryByText("Bu inceleme başka bir cihazda tamamlanmış veya artık mevcut değil.")).not.toBeInTheDocument();
  expect(writes).toHaveLength(1);
});

it("reschedule validates future Istanbul time independently of browser timezone", async () => {
  render(<App />); await loadedPreview();
  fireEvent.click(screen.getByRole("button", { name: "Başka zamana planla" }));
  fireEvent.change(screen.getByLabelText("Yeni Yayın Zamanı (İstanbul)"), { target: { value: "2000-08-04T12:30" } });
  expect(screen.getByRole("button", { name: "Yeni zamanı onayla" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Yeni Yayın Zamanı (İstanbul)"), { target: { value: "2099-08-04T12:30" } });
  fireEvent.click(screen.getByRole("button", { name: "Yeni zamanı onayla" }));
  await screen.findByText("Yeni Yayın Zamanı kaydedildi. Paket korunuyor.");
  expect(writes[0]).toEqual({ path: "/api/reviews/2/reschedule", body: { version: 3, new_due_at: "2099-08-04T12:30:00+03:00" } });
});

it("stale action reports already handled and refreshes instead of replaying publication", async () => {
  render(<App />); await loadedPreview();
  fireEvent.click(screen.getByRole("button", { name: "Onayla ve yayınla" }));
  actionStatus = 409; detail.review.status = "skipped"; detail.render_ready = false;
  fireEvent.click(screen.getByRole("button", { name: "Yayınlamayı onayla" }));
  await screen.findByText("Bu inceleme başka bir cihazda tamamlanmış veya artık mevcut değil.");
  expect(writes).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Onayla ve yayınla" })).not.toBeInTheDocument();
});

it("failed live read and failed preview block decisions; retry restores authoritative state", async () => {
  render(<App />); const video = await loadedPreview();
  fireEvent.error(video);
  expect(screen.getByRole("button", { name: "Onayla ve yayınla" })).toBeDisabled();
  readStatus = 500;
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("İnceleme bilgileri"));
  expect(screen.getByRole("button", { name: "Bu zamanı atla" })).toBeDisabled();
  readStatus = 200;
  fireEvent.click(screen.getByRole("button", { name: "İncelemeyi yenile" }));
  await waitFor(() => expect(screen.queryByText(/İnceleme bilgileri yüklenemedi/)).not.toBeInTheDocument());
  await loadedPreview();
  expect(screen.getByRole("button", { name: "Onayla ve yayınla" })).toBeEnabled();
});

it("empty due package continues to render and review without creating another occurrence", async () => {
  state.pending_actions[0] = { ...state.pending_actions[0], review_id: null, version: null, state: "empty_package" };
  window.location.hash = `#/package?occurrence=1&folder=${encodeURIComponent(state.package!.folder_name)}`;
  render(<App />);
  await screen.findByLabelText("Fotoğraf ve video seç");
  const next = screen.getByRole("button", { name: "Render ve incelemeye devam et" });
  expect(next).toBeDisabled();
  editor.montage.order = ["clip"];
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  await waitFor(() => expect(next).toBeEnabled());
  fireEvent.click(next);
  await waitFor(() => expect(writes).toEqual([{ path: "/api/packages/active/render", body: { expected_folder_name: "03-08-2026 10-00", retry: false } }]));
  state.pending_actions[0] = { ...state.pending_actions[0], review_id: 2, version: 3, state: "review_ready" };
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  await loadedPreview();
  expect(screen.queryByLabelText("Fotoğraf ve video seç")).not.toBeInTheDocument();
});

it("activity links open exact review and obsolete continuation cannot render another package", async () => {
  window.location.hash = "#/activity";
  render(<App />);
  expect(await screen.findByRole("link", { name: "İnceleme özeti" })).toHaveAttribute("href", "#/package?review=2");
  await act(async () => { window.location.hash = "#/package?occurrence=1&folder=old-package"; window.dispatchEvent(new Event("hashchange")); });
  await screen.findByText("Paket değişti. Güncel işlemi kontrol panelinden açın.");
  expect(screen.queryByLabelText("Fotoğraf ve video seç")).not.toBeInTheDocument();
  expect(writes).toEqual([]);
});

it("manual refresh blocks every decision until authoritative read finishes", async () => {
  render(<App />); await loadedPreview();
  let finish!: () => void;
  pendingRead = new Promise<void>(resolve => { finish = resolve; });
  fireEvent.click(screen.getByRole("button", { name: "İncelemeyi yenile" }));
  expect(screen.getByRole("button", { name: "Bu zamanı atla" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Başka zamana planla" })).toBeDisabled();
  await act(async () => { finish(); });
  await waitFor(() => expect(screen.getByRole("button", { name: "Bu zamanı atla" })).toBeEnabled());
});

it("absent active package still permits upload for an empty due occurrence", async () => {
  state.package = null; editorStatus = 404;
  state.pending_actions[0] = { ...state.pending_actions[0], review_id: null, version: null, state: "empty_package", package_folder: null };
  window.location.hash = "#/package?occurrence=1";
  render(<App />);
  await screen.findByLabelText("Fotoğraf ve video seç");
  await waitFor(() => expect(screen.getByLabelText("Fotoğraf ve video seç")).toBeEnabled());
  expect(screen.getByRole("button", { name: "Render ve incelemeye devam et" })).toBeDisabled();
});

it("continuation selects ready revision over older preparing review for same occurrence", async () => {
  detail = reviewDetail(3);
  state.pending_actions = [
    { ...state.pending_actions[0], state: "preparing" },
    { ...state.pending_actions[0], review_id: 3, state: "review_ready" },
  ];
  window.location.hash = `#/package?occurrence=1&folder=${encodeURIComponent(state.package!.folder_name)}`;
  render(<App />);
  const video = await loadedPreview();
  expect(video).toHaveAttribute("src", "/api/packages/active/render/preview?revision=exact-3");
  expect(screen.queryByLabelText("Fotoğraf ve video seç")).not.toBeInTheDocument();
});

it("known already-handled action is shown even when authoritative refresh fails", async () => {
  render(<App />); await loadedPreview();
  fireEvent.click(screen.getByRole("button", { name: "Bu zamanı atla" }));
  actionStatus = 409; actionDetail = "review 2 was already handled by another device"; readStatus = 500;
  fireEvent.click(screen.getByRole("button", { name: "Atlamayı onayla" }));
  await screen.findByText("Bu inceleme başka bir cihazda tamamlanmış veya artık mevcut değil.");
  expect(screen.getByRole("button", { name: "Onayla ve yayınla" })).toBeDisabled();
  expect(writes).toHaveLength(1);
});
