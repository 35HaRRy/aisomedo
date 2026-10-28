import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../App";
import type { StatusOut } from "../api/openapi";
import { client, dashboard, emptyEditor, setupState } from "../test/fixtures";
import { invalidateLive, liveResponse } from "../test/live";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
let plan = dashboard().plan;
let branding = { logo_asset: "branding/assets/" + "a".repeat(32) + ".png", caption_template: "Dojo", intro_asset: null as string | null, intro_duration: null as number | null, outro_asset: null, outro_duration: null };
let reminders = { interval_minutes: 360, delivery_start: "08:00:00", delivery_end: "22:00:00", timezone: "Europe/Istanbul" };
let instagram: StatusOut = { health: "reconnect_required", ig_username: "old_dojo" };
let reminderStatus = 200;
let dashboardStatus = 200;
let consentStatus = 200;
let setupStatus = 200;
let acceptedAt: string | null = "2026-08-03T07:00:00Z";
let cardSkips = 0;
let activityAction = "plan.updated";
let revocations = 0;

beforeEach(() => {
  window.location.hash = "#/settings";
  plan = dashboard().plan;
  branding = { logo_asset: "branding/assets/" + "a".repeat(32) + ".png", caption_template: "Dojo", intro_asset: null, intro_duration: null, outro_asset: null, outro_duration: null };
  reminders = { interval_minutes: 360, delivery_start: "08:00:00", delivery_end: "22:00:00", timezone: "Europe/Istanbul" };
  instagram = { health: "reconnect_required", ig_username: "old_dojo" };
  reminderStatus = 200; dashboardStatus = 200; consentStatus = 200; setupStatus = 200;
  acceptedAt = "2026-08-03T07:00:00Z"; cardSkips = 0; activityAction = "plan.updated"; revocations = 0;
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url === "/api/events") return liveResponse();
    if (url === "/api/compat") return json({ api_version: "0.1.0" });
    if (url === "/api/pairing/me") return json(client);
    if (url === "/api/pairing/clients/1/revoke") { revocations++; return json({ revoked: true }); }
    if (url === "/api/setup") return json(setupState(), setupStatus);
    if (url === "/api/dashboard") return json({ ...dashboard(), plan }, dashboardStatus);
    if (url === "/api/packages/active/editor") return json(emptyEditor());
    if (url === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
    if (url === "/api/settings/plan") {
      if (init.method === "PUT") plan = { ...plan, ...JSON.parse(String(init.body)) };
      return json(plan);
    }
    if (url === "/api/settings/branding/assets") return json({ asset: "branding/assets/" + "b".repeat(32) + ".png" });
    if (url === "/api/settings/branding") {
      if (init.method === "PATCH") branding = { ...branding, ...JSON.parse(String(init.body)) };
      return json(branding);
    }
    if (url === "/api/setup/cards/skip") { cardSkips++; return json(setupState()); }
    if (url === "/api/settings/reminders") {
      if (init.method === "PUT" && reminderStatus === 200) reminders = JSON.parse(String(init.body));
      return json(reminders, init.method === "PUT" ? reminderStatus : 200);
    }
    if (url === "/api/meta/status") return json(instagram);
    if (url === "/api/meta/oauth/start") return json({ auth_url: "https://www.facebook.com/dialog/oauth", attempt_id: "a1" });
    if (url === "/api/meta/oauth/attempts/a1") return json({ id: "a1", status: "completed", candidates: [{ ig_user_id: "2", ig_username: "new_dojo" }] });
    if (url === "/api/meta/oauth/attempts/a1/select") { instagram = { health: "healthy", ig_username: "new_dojo" }; return json(instagram); }
    if (url === "/api/setup/consent") return json({ version: 2, text: "Medya kullanım politikası", accepted_at: acceptedAt }, consentStatus);
    if (url.startsWith("/api/activity")) return json({ events: [{ id: 1, action: activityAction, actor: client, details: {}, occurred_at: "2026-08-03T07:00:00Z" }], next_cursor: null });
    throw new Error(`Unexpected API request: ${init.method ?? "GET"} ${url}`);
  });
});
afterEach(() => vi.useRealTimers());

const step = async (name: string) => { fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^${name}`) })); };
const content = (name: string) => screen.getByRole("heading", { name }).closest(".setup-content") as HTMLElement;

it("replaces settings panels with the embedded setup widget", async () => {
  render(<App />);
  await screen.findByRole("heading", { name: "Ayarlar" });
  const steps = await screen.findByRole("list", { name: "Kurulum adımları" });
  expect(steps.children).toHaveLength(8);
  expect(within(steps).getByRole("button", { name: /^Hatırlatmalar/ })).toHaveAttribute("aria-current", "step");
  expect(screen.queryByRole("link", { name: "Kurulumu bitir" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Kuruluma sonra devam et" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Yayın Planı" })).not.toBeInTheDocument();
  await step("Medya rızası");
  await within(content("Medya rızası")).findByText(/Sürüm 2/);
  expect(within(content("Medya rızası")).queryByRole("checkbox")).not.toBeInTheDocument();
});

it("persists plan, branding and reminder edits across a page remount", async () => {
  const view = render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(360));
  await step("Yayın Planı");
  await waitFor(() => expect(screen.getByLabelText("Yayın saati")).toHaveValue("10:00"));
  fireEvent.change(screen.getByLabelText("Yayın saati"), { target: { value: "13:30" } });
  fireEvent.click(screen.getByRole("button", { name: "Planı kaydet" }));
  await waitFor(() => expect(plan.anchor_time).toBe("13:30"));
  await screen.findByText("Ayarlar kaydedildi.");
  await step("Açıklama şablonu");
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Açıklama şablonu" })).toHaveValue("Dojo"));
  fireEvent.change(screen.getByRole("textbox", { name: "Açıklama şablonu" }), { target: { value: "Yeni Dojo {title}" } });
  fireEvent.click(screen.getByRole("button", { name: "Açıklamayı kaydet" }));
  await waitFor(() => expect(branding.caption_template).toBe("Yeni Dojo {title}"));
  await step("Logo");
  await screen.findByRole("img", { name: "Logo önizlemesi" });
  fireEvent.change(screen.getByLabelText("Logo görseli"), { target: { files: [new File(["image"], "logo.png", { type: "image/png" })] } });
  fireEvent.click(screen.getByRole("button", { name: "Logoyu kaydet" }));
  await waitFor(() => expect(branding.logo_asset).toBe("branding/assets/" + "b".repeat(32) + ".png"));
  await step("İsteğe bağlı kartlar");
  await waitFor(() => expect(screen.getByLabelText("Giriş süresi (saniye)")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Giriş görseli"), { target: { files: [new File(["image"], "intro.png", { type: "image/png" })] } });
  fireEvent.change(screen.getByLabelText("Giriş süresi (saniye)"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Kartları kaydet" }));
  await waitFor(() => expect(branding.intro_duration).toBe(2));
  await step("Hatırlatmalar");
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(360));
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "120" } });
  fireEvent.change(screen.getByLabelText("Bildirim başlangıcı"), { target: { value: "22:00" } });
  fireEvent.change(screen.getByLabelText("Bildirim bitişi"), { target: { value: "08:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Hatırlatmaları kaydet" }));
  await waitFor(() => expect(reminders).toEqual({ interval_minutes: 120, delivery_start: "22:00", delivery_end: "08:00", timezone: "Europe/Istanbul" }));
  view.unmount(); render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(120));
  await step("Yayın Planı");
  await waitFor(() => expect(screen.getByLabelText("Yayın saati")).toHaveValue("13:30"));
  await step("Açıklama şablonu");
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Açıklama şablonu" })).toHaveValue("Yeni Dojo {title}"));
  await step("İsteğe bağlı kartlar");
  await waitFor(() => expect(screen.getByLabelText("Giriş süresi (saniye)")).toHaveValue(2));
  await step("Logo");
  await waitFor(() => expect(screen.getByRole("img", { name: "Logo önizlemesi" })).toHaveAttribute("src", "/api/settings/branding/assets/" + "b".repeat(32) + ".png"));
  expect(cardSkips).toBe(0);
  expect(screen.queryByRole("button", { name: "Kartları değiştirmeden devam et" })).not.toBeInTheDocument();
});

it("keeps reminder draft after rejection and refresh, then adopts server values explicitly", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(360));
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "120" } });
  reminderStatus = 422;
  fireEvent.click(screen.getByRole("button", { name: "Hatırlatmaları kaydet" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(120);
  reminders = { ...reminders, interval_minutes: 60 };
  vi.useFakeTimers();
  await act(async () => { invalidateLive(); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(120);
  fireEvent.click(screen.getByRole("button", { name: "Sunucudaki değerleri yükle" }));
  expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(60);
});

it("rejects invalid reminder values locally without changing stored policy", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(360));
  const button = screen.getByRole("button", { name: "Hatırlatmaları kaydet" });
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "0" } });
  fireEvent.submit(button.closest("form")!);
  await screen.findByRole("alert");
  expect(reminders.interval_minutes).toBe(360);
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "120" } });
  fireEvent.change(screen.getByLabelText("Bildirim bitişi"), { target: { value: "08:00" } });
  fireEvent.submit(button.closest("form")!);
  expect(reminders.delivery_end).toBe("22:00:00");
});

it("shows consent and reconnects Instagram without changing package or recurring anchor", async () => {
  render(<App />); vi.spyOn(window, "open").mockReturnValue(null);
  await step("Medya rızası");
  await screen.findByText(/Rıza kaydedildi/);
  expect(screen.getByText(/Sürüm 2/)).toBeInTheDocument();
  await step("Instagram bağlantısı");
  await screen.findByText(/@old_dojo.*Yeniden bağlantı/);
  fireEvent.click(screen.getByRole("button", { name: "Instagram ile yetkilendir" }));
  fireEvent.click(await screen.findByRole("button", { name: "@new_dojo hesabını seç" }));
  await screen.findByText(/@new_dojo.*Bağlantı doğrulandı/);
  fireEvent.click(screen.getByRole("link", { name: "Kontrol Paneli" }));
  await screen.findByText("03-08-2026 10-00");
  expect(plan.anchor_date).toBe("2026-08-03");
});

it("loads settings independently of dashboard and recovers missing consent", async () => {
  dashboardStatus = 500; consentStatus = 404;
  render(<App />);
  await step("Medya rızası");
  await screen.findByText(/Rıza metni henüz tanımlanmamış/);
  consentStatus = 200;
  fireEvent.click(within(content("Medya rızası")).getByRole("button", { name: "Tekrar dene" }));
  await screen.findByText(/Rıza kaydedildi/);
});

it("shows unconnected Instagram status explicitly", async () => {
  instagram = { health: "not_connected", ig_username: null };
  render(<App />);
  await step("Instagram bağlantısı");
  await within(content("Instagram bağlantısı")).findByText("Hesap bağlı değil");
});

it("reports persisted save separately from an unrelated setup refresh failure", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(360));
  setupStatus = 500;
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "120" } });
  fireEvent.click(screen.getByRole("button", { name: "Hatırlatmaları kaydet" }));
  await screen.findByText("Ayarlar kaydedildi.");
  expect(reminders.interval_minutes).toBe(120);
  expect(screen.getByRole("alert")).toHaveTextContent("Son bilgiler gösteriliyor");
});

it("does not report another device after saving reminders", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(360));
  const warning = "Başka bir cihaz ayarları değiştirdi. Taslağınız korunuyor.";
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "120" } });
  fireEvent.click(screen.getByRole("button", { name: "Hatırlatmaları kaydet" }));
  await waitFor(() => expect(reminders.interval_minutes).toBe(120));
  await screen.findByText("Ayarlar kaydedildi.");
  vi.useFakeTimers();
  await act(async () => { invalidateLive(); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.queryByText(warning)).not.toBeInTheDocument();
  vi.useRealTimers();
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "60" } });
  expect(screen.queryByText(warning)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Hatırlatmaları kaydet" }));
  await waitFor(() => expect(reminders.interval_minutes).toBe(60));
  await screen.findByText("Ayarlar kaydedildi.");
  vi.useFakeTimers();
  await act(async () => { invalidateLive(); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.queryByText(warning)).not.toBeInTheDocument();
});

it("clears previous save acknowledgment when edited draft is later rejected", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(360));
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "120" } });
  fireEvent.click(screen.getByRole("button", { name: "Hatırlatmaları kaydet" }));
  await screen.findByText("Ayarlar kaydedildi.");
  await waitFor(() => expect(screen.getByLabelText("Hatırlatma aralığı (dakika)")).toHaveValue(120));
  fireEvent.change(screen.getByLabelText("Hatırlatma aralığı (dakika)"), { target: { value: "60" } });
  expect(screen.queryByText("Ayarlar kaydedildi.")).not.toBeInTheDocument();
  reminderStatus = 422;
  fireEvent.click(screen.getByRole("button", { name: "Hatırlatmaları kaydet" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("Ayarlar kaydedildi.")).not.toBeInTheDocument();
  expect(reminders.interval_minutes).toBe(120);
});

it("displays unaccepted consent without offering installation-wide acceptance in Settings", async () => {
  acceptedAt = null;
  render(<App />);
  await step("Medya rızası");
  await within(content("Medya rızası")).findByText(/Sürüm 2/);
  expect(within(content("Medya rızası")).queryByRole("checkbox")).not.toBeInTheDocument();
  expect(within(content("Medya rızası")).queryByRole("button", { name: "Rızayı kaydet" })).not.toBeInTheDocument();
  expect(within(content("Medya rızası")).getByRole("status")).toHaveTextContent("henüz kaydedilmedi");
});

it("removes the paired browser only after confirmation", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<App />);
  await screen.findByRole("heading", { name: "Ayarlar" });
  fireEvent.click(screen.getByRole("button", { name: "Kaldır" }));
  expect(revocations).toBe(0);
  expect(screen.getByRole("heading", { name: "Ayarlar" })).toBeInTheDocument();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Kaldır" }));
  await screen.findByRole("heading", { name: "Tarayıcıyı eşleştir" });
  expect(revocations).toBe(1);
});

it.each([
  ["plan.updated", "Yayın planı güncellendi"],
  ["reminders.policy_updated", "Hatırlatma ayarları güncellendi"],
  ["branding.defaults_updated", "Marka ayarları güncellendi"],
  ["consent.accepted", "Medya rızası kaydedildi"],
  ["meta.connected", "Instagram bağlantısı doğrulandı"],
])("refreshes recent Activity for %s with actor and timestamp", async (action, title) => {
  activityAction = action;
  window.location.hash = "#/activity"; render(<App />);
  await screen.findByRole("heading", { name: title });
  const list = screen.getByRole("list");
  expect(within(list).getByText(client.name)).toBeInTheDocument();
  expect(list.querySelector("time")).toHaveAttribute("datetime", "2026-08-03T07:00:00Z");
  activityAction = "review.approved"; vi.useFakeTimers();
  await act(async () => { invalidateLive(); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByRole("heading", { name: "Yayın onaylandı" })).toBeInTheDocument();
});
