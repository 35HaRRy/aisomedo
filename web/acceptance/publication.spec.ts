import { test, expect, type Page, type BrowserContext, type APIRequestContext } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import type { DashboardOut, ReviewDetailOut, PackageOut } from "../src/api/openapi";

test.describe.configure({ mode: "serial" });
let context: BrowserContext, page: Page;
let fixtures: APIRequestContext;
const caption = "Dojo acceptance · birlikte";
const videoBytes = readFileSync("e2e/fixtures/timeline.mp4");
// Real small PNG used as uploaded branding, not a mocked HTTP response.
const logo = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAANklEQVR4nO3QQQ0AQAgDwePU4D/4g6CCz9TANhOV2e9w/zLuAAECBAgQIECAAAECBAgQILACA4EGAkM8LDwgAAAAAElFTkSuQmCC", "base64");

type Evidence = {
  containers: { id: string; caption: string; sha256: string; bytes: number }[];
  publications: { id: string; container_id: string }[];
  notifications: { notification: { data: Record<string, string> }; tokens: string[] }[];
};
async function json<T>(url: string): Promise<T> {
  const response = await context.request.get(url);
  expect(response.ok(), `GET ${url}`).toBe(true);
  return response.json() as Promise<T>;
}
async function evidence(): Promise<Evidence> {
  const response = await fixtures.get("/evidence");
  expect(response.ok()).toBe(true);
  return response.json() as Promise<Evidence>;
}
async function upload(name: string) {
  await page.goto("/#/package");
  // Each case starts a fresh page while retaining its real paired-session cookie.
  // Hash-only navigation otherwise retains the previous case's upload limits.
  await page.reload();
  await page.getByLabel("Fotoğraf ve video seç", { exact: true }).setInputFiles({
    name, mimeType: "video/mp4", buffer: videoBytes,
  });
  await expect(page.getByRole("region", { name: "Aktif paket medyası", exact: true })
    .getByRole("heading", { name, exact: true })).toBeVisible();
  return (await json<DashboardOut>("/api/dashboard")).package!.folder_name;
}
async function approveAndVerify(folder: string, index: number) {
  await page.goto("/#/dashboard");
  await page.getByRole("link", { name: "İnceleme özeti", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Yayın İncelemesi", exact: true })).toBeVisible();
  const id = Number(new URLSearchParams(page.url().split("?")[1]).get("review"));
  expect(id).toBeGreaterThan(0);
  const detail = await json<ReviewDetailOut>(`/api/reviews/${id}`);
  expect(detail.review.package_folder).toBe(folder);
  expect(detail.review.caption).toBe(caption);
  await expect(page.getByText(caption, { exact: true })).toBeVisible();
  const video = page.getByLabel("İncelenen Reel", { exact: true });
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(2);
  await video.evaluate((v: HTMLVideoElement) => v.play());
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0);
  const preview = await context.request.get(detail.preview_url!);
  expect(preview.ok()).toBe(true);
  const bytes = await preview.body();
  expect(bytes.length).toBeGreaterThan(0);
  const digest = createHash("sha256").update(bytes).digest("hex");
  await expect.poll(async () => (await evidence()).notifications.some(n =>
    n.tokens.includes("acceptance-device") && String(n.notification.data.review_id) === String(id),
  )).toBe(true);
  expect((await evidence()).publications).toHaveLength(index);
  await page.screenshot({ path: `/evidence/review-${index}-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `/evidence/review-${index}-mobile.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("button", { name: "Onayla ve yayınla", exact: true }).click();
  await page.getByRole("button", { name: "Yayınlamayı onayla", exact: true }).click();
  await expect(page.getByText("Yayınlama onayı alındı.", { exact: true })).toBeVisible();
  await expect.poll(async () => (await json<PackageOut[]>("/api/packages")).some(
    p => p.folder_name === `${folder}-completed` && p.status === "completed",
  )).toBe(true);
  const external = await evidence();
  expect(external.containers).toHaveLength(index + 1);
  expect(external.publications).toHaveLength(index + 1);
  expect(external.containers[index]).toMatchObject({ caption, sha256: digest, bytes: bytes.length });
  expect(external.publications[index].container_id).toBe(external.containers[index].id);
  expect(external.publications[index].id).toBeTruthy();
  // Read-only view of real worker progress, not a control that calls run_tick.
  const before = (await (await fixtures.get("/worker-health")).json()).monotonic as number;
  await expect.poll(async () => {
    const health = await (await fixtures.get("/worker-health")).json();
    return health.phase === "idle" && health.monotonic > before + 1;
  }).toBe(true);
  expect((await evidence()).publications).toHaveLength(index + 1);
}

test.beforeAll(async ({ browser, playwright }) => {
  context = await browser.newContext({ baseURL: process.env.ACCEPTANCE_BASE_URL });
  fixtures = await playwright.request.newContext({ baseURL: process.env.ACCEPTANCE_FIXTURES_URL });
  page = await context.newPage();
  const seed = JSON.parse(readFileSync(process.env.ACCEPTANCE_SEED_FILE!, "utf8"));
  const device = await context.request.post("/api/pairing/validate", {
    data: { code: seed.device_code, kind: "device", name: "Acceptance device" },
  });
  expect(device.ok()).toBe(true);
  const registration = await context.request.put("/api/pairing/me/push-token", {
    headers: { Authorization: `Bearer ${(await device.json()).token}`, "X-Android-Version-Code": "1" },
    data: { token: "acceptance-device" },
  });
  expect(registration.ok()).toBe(true);
  await page.goto("/");
  await page.getByLabel("Eşleştirme kodu", { exact: true }).fill(seed.browser_code);
  await page.getByLabel("Tarayıcı adı", { exact: true }).fill("Acceptance browser");
  await page.getByRole("button", { name: "Eşleştir", exact: true }).click();
  await page.getByRole("button", { name: /^Instagram bağlantısı/ }).click();
  await page.getByLabel("Instagram erişim tokenı").fill("acceptance-token");
  await page.getByRole("button", { name: "Token ile bağlan", exact: true }).click();
  await expect(page.getByRole("button", { name: "Instagram bağlantısı Tamamlandı", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Dojo Yayın Planı/ }).click();
  await page.getByLabel("İlk yayın tarihi").fill("2026-10-19");
  await page.getByLabel("Yayın saati", { exact: true }).fill("07:00");
  await page.getByLabel("Düzenli yayını etkinleştir").check();
  await page.getByRole("button", { name: "Planı kaydet", exact: true }).click();
  await expect(page.getByRole("button", { name: "Dojo Yayın Planı Tamamlandı", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Dojo logosu/ }).click();
  await page.getByLabel("Logo görseli").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: logo });
  await page.getByRole("button", { name: "Logoyu kaydet", exact: true }).click();
  await expect(page.getByRole("button", { name: "Dojo logosu Tamamlandı", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Açıklama şablonu/ }).click();
  await page.getByLabel("Açıklama şablonu", { exact: true }).fill(caption);
  await page.getByRole("button", { name: "Açıklamayı kaydet", exact: true }).click();
  await expect(page.getByRole("button", { name: "Açıklama şablonu Tamamlandı", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Medya rızası/ }).click();
  await page.getByRole("checkbox", { name: "Metni okudum ve medya kullanımına rıza veriyorum." }).check();
  await page.getByRole("button", { name: "Rızayı kaydet", exact: true }).click();
  await expect.poll(async () => (await json<{ ready: boolean }>("/api/setup")).ready).toBe(true);
  // Bring the due boundary inside the actual configured notification delivery window.
  await page.goto("/#/settings");
  await page.getByLabel("Bildirim başlangıcı", { exact: true }).fill("06:00");
  await page.getByLabel("Bildirim bitişi", { exact: true }).fill("23:00");
  await page.getByRole("button", { name: "Hatırlatmaları kaydet", exact: true }).click();
  await expect(page.getByText("Ayarlar kaydedildi.", { exact: true })).toBeVisible();
});
test.afterAll(async () => { await context?.close(); await fixtures?.dispose(); });

test("scheduled publication preserves reviewed artifact", async () => {
  const folder = await upload("scheduled.mp4");
  const advance = await fixtures.post("/clock", { data: { now: "2026-10-19T07:00:01+03:00" } });
  expect(advance.ok()).toBe(true);
  await approveAndVerify(folder, 0);
});

test("manual publication preserves cadence", async () => {
  const folder = await upload("manual.mp4");
  const before = (await json<DashboardOut>("/api/dashboard")).next_slot;
  expect(before?.kind).toBe("regular");
  await page.goto("/#/dashboard");
  await page.getByRole("button", { name: "Manuel Yayın İncelemesi iste", exact: true }).click();
  await expect(page.getByRole("link", { name: "İncelemeye devam et", exact: true })).toBeVisible();
  await approveAndVerify(folder, 1);
  expect((await json<DashboardOut>("/api/dashboard")).next_slot?.due_at).toBe(before?.due_at);
});
