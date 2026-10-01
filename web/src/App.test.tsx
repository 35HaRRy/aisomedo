import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { client, dashboard, setupState } from "./test/fixtures";

let paired = true;
let snapshot = dashboard();
let dashboardStatus = 200;
let pairingStatus = 200;
let activityStatus = 200;
let setup = setupState();
let setupStatus = 200;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(() => {
  paired = true; snapshot = dashboard(); dashboardStatus = 200; pairingStatus = 200; activityStatus = 200;
  setup = setupState(); setupStatus = 200;
  window.location.hash = "#/dashboard";
  vi.stubGlobal("fetch", async (url: string) => {
    if (url.endsWith("/compat")) return json({ api_version: "0.1.0" });
    if (url.endsWith("/me")) return paired ? json(client) : json({}, 401);
    if (url.endsWith("/validate")) { if (pairingStatus === 200) paired = true; return json({}, pairingStatus); }
    if (url.includes("/activity")) return json({ events: [{ id: 1, action: "future.event", actor: "system", details: {}, occurred_at: snapshot.generated_at }], next_cursor: null }, activityStatus);
    if (url === "/api/setup") return json(setup, setupStatus);
    return json(snapshot, dashboardStatus);
  });
});

it("resumes incomplete setup once and preserves intentional navigation", async () => {
  setup = setupState("instagram");
  render(<App />);
  await screen.findByRole("heading", { name: "Instagram bağlantısı" });
  expect(window.location.hash).toBe("#/onboarding");
  fireEvent.click(screen.getByRole("link", { name: "Kontrol Paneli" }));
  await screen.findByText("03-08-2026 10-00");
  vi.useFakeTimers();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(window.location.hash).toBe("#/dashboard");
});

it("opens onboarding directly without dashboard data and reopens from settings", async () => {
  window.location.hash = "#/onboarding"; dashboardStatus = 500;
  render(<App />);
  await screen.findByRole("heading", { name: "Kurulum tamamlandı" });
  expect(screen.getAllByRole("navigation")[0].querySelectorAll("a")).toHaveLength(4);
});

it("shows initial setup error without inventing completion or redirect", async () => {
  setupStatus = 500;
  render(<App />);
  await screen.findByRole("alert");
  expect(window.location.hash).toBe("#/dashboard");
  setupStatus = 200; setup = setupState("logo");
  fireEvent.click(screen.getByRole("button", { name: "Tekrar dene" }));
  await screen.findByRole("heading", { name: "Dojo logosu" });
});

it("reopens from Settings and resumes after reload", async () => {
  window.location.hash = "#/settings";
  const view = render(<App />);
  fireEvent.click(await screen.findByRole("link", { name: "Kurulumu aç" }));
  await screen.findByRole("heading", { name: "Kurulum tamamlandı" });
  view.unmount(); setup = setupState("consent");
  render(<App />);
  await screen.findByRole("heading", { name: "Medya rızası" });
});
afterEach(() => vi.useRealTimers());

it("shows four areas and all five dashboard categories", async () => {
  render(<App />);
  await screen.findByText("03-08-2026 10-00");
  const nav = screen.getByRole("navigation");
  for (const name of ["Kontrol Paneli", "Güncel Paket", "Etkinlik", "Ayarlar"])
    expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
  for (const name of ["Dojo Paylaşım Paketi", "Sonraki Yayın Zamanı", "Bekleyen işlem", "Instagram", "Worker"])
    expect(screen.getByText(name)).toBeInTheDocument();
  expect(screen.getByText(/17 Ağustos 2026.*10:00/)).toBeInTheDocument();
});

it("pairs a browser and explains invalid and throttled codes", async () => {
  paired = false;
  render(<App />);
  await screen.findByRole("heading", { name: "Tarayıcıyı eşleştir" });
  fireEvent.change(screen.getByLabelText("Eşleştirme kodu"), { target: { value: "CODE" } });
  fireEvent.change(screen.getByLabelText("Tarayıcı adı"), { target: { value: "Web" } });
  pairingStatus = 401;
  fireEvent.click(screen.getByRole("button", { name: "Eşleştir" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Kod geçersiz veya süresi dolmuş");
  pairingStatus = 429;
  fireEvent.click(screen.getByRole("button", { name: "Eşleştir" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Çok fazla deneme"));
  pairingStatus = 200;
  fireEvent.click(screen.getByRole("button", { name: "Eşleştir" }));
  await screen.findByText("03-08-2026 10-00");
});

it("refreshes review arrivals and other-device resolution without reload", async () => {
  vi.useFakeTimers();
  await act(async () => { render(<App />); });
  expect(screen.getByText("Bekleyen işlem yok")).toBeInTheDocument();
  snapshot.pending_actions = [{ occurrence_id: 1, review_id: 2, version: 1, due_at: snapshot.generated_at, package_folder: "03-08-2026 10-00", state: "review_ready" }];
  await act(async () => { window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(1); });
  const link = screen.getByRole("link", { name: "İnceleme özeti" });
  expect(link).toHaveAttribute("href", "#/package?review=2");
  await act(async () => { window.location.hash = "#/package?review=2"; window.dispatchEvent(new Event("hashchange")); });
  snapshot.pending_actions = [];
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByText("Bu inceleme başka bir cihazda tamamlanmış veya artık mevcut değil.")).toBeInTheDocument();
});

it("keeps old data visibly stale on error and clears it on revoked session", async () => {
  vi.useFakeTimers();
  await act(async () => { render(<App />); });
  expect(screen.getByText("03-08-2026 10-00")).toBeInTheDocument();
  dashboardStatus = 500;
  await act(async () => { window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByText("03-08-2026 10-00")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Son bilgiler gösteriliyor");
  dashboardStatus = 401;
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.queryByText("03-08-2026 10-00")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Tarayıcıyı eşleştir" })).toBeInTheDocument();
});

it("first failure shows retry, not fabricated package health", async () => {
  dashboardStatus = 500;
  render(<App />);
  await screen.findByRole("alert");
  expect(screen.queryByText("03-08-2026 10-00")).not.toBeInTheDocument();
  dashboardStatus = 200;
  fireEvent.click(screen.getByRole("button", { name: "Tekrar dene" }));
  await screen.findByText("03-08-2026 10-00");
});

it("activity uses safe translated fallback and independent errors", async () => {
  window.location.hash = "#/activity";
  render(<App />);
  await screen.findByText("Etkinlik kaydedildi");
  expect(screen.queryByText("future.event")).not.toBeInTheDocument();
  vi.useFakeTimers(); activityStatus = 500;
  await act(async () => { window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByText("Etkinlik kaydedildi")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Son bilgiler gösteriliyor");
});

it("distinguishes empty package and publishing states", async () => {
  snapshot.package = null;
  render(<App />);
  await screen.findByText("Henüz aktif paket yok");
  vi.useFakeTimers(); snapshot = dashboard(); snapshot.package!.status = "publishing";
  await act(async () => { window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByText("Yayınlanıyor")).toBeInTheDocument();
});

it("skip link focuses content without changing the current area", async () => {
  window.location.hash = "#/settings";
  render(<App />);
  await screen.findByRole("heading", { name: "Ayarlar" });
  fireEvent.click(screen.getByRole("link", { name: "İçeriğe geç" }));
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("main")));
  expect(window.location.hash).toBe("#/settings");
});
