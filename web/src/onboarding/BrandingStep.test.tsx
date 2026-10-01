import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { SessionProvider } from "../session";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider } from "./useOnboarding";
import { BrandingStep } from "./BrandingStep";

function mount(kind: "logo" | "caption_template", uploadStatus = 201) {
  let caption = "Old";
  const sent = vi.fn(); const saved = vi.fn();
  const content = (show = true) => <SessionProvider><OnboardingProvider>{show && <BrandingStep kind={kind} onSaved={saved} />}</OnboardingProvider></SessionProvider>;
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/me")) return new Response(JSON.stringify(client));
    if (url === "/api/setup") return new Response(JSON.stringify(setupState(kind)));
    if (url.endsWith("/assets")) return new Response(JSON.stringify({ asset: "branding/assets/new.png", preview_url: "/api/settings/branding/assets/new.png" }), { status: uploadStatus });
    if (init.method === "PATCH") sent(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ logo_asset: "legacy/logo.png", caption_template: caption, intro_asset: "intro.png", intro_duration: 2, outro_asset: null, outro_duration: null }));
  });
  const view = render(content());
  return { ...view, sent, saved, update: () => { caption = "Fresh"; }, leave: () => view.rerender(content(false)) };
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
it("uploads and installs only logo with authenticated preview", async () => {
  const { sent } = mount("logo");
  await screen.findByText(/Logo tanımlı/);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain("legacy/logo.png");
  fireEvent.change(screen.getByLabelText("Logo görseli"), { target: { files: [new File(["image"], "logo.png", { type: "image/png" })] } });
  fireEvent.click(screen.getByRole("button", { name: "Logoyu kaydet" }));
  await waitFor(() => expect(sent).toHaveBeenCalledWith({ logo_asset: "branding/assets/new.png" }));
});
it("patches only caption, rejects whitespace and preserves dirty text", async () => {
  const { sent, update } = mount("caption_template");
  await waitFor(() => expect(screen.getByLabelText("Açıklama şablonu")).toHaveValue("Old"));
  fireEvent.change(screen.getByLabelText("Açıklama şablonu"), { target: { value: "  " } });
  fireEvent.click(screen.getByRole("button", { name: "Açıklamayı kaydet" }));
  await screen.findByRole("alert"); expect(sent).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Açıklama şablonu"), { target: { value: "Draft" } }); update();
  vi.useFakeTimers(); await act(async () => { window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByLabelText("Açıklama şablonu")).toHaveValue("Draft");
  fireEvent.click(screen.getByRole("button", { name: "Sunucudaki değerleri yükle" }));
  expect(screen.getByLabelText("Açıklama şablonu")).toHaveValue("Fresh");
  fireEvent.click(screen.getByRole("button", { name: "Açıklamayı kaydet" }));
  await act(async () => {});
  expect(sent).toHaveBeenCalledWith({ caption_template: "Fresh" });
});
it.each(["unsupported", "oversized"])("rejects %s file before upload", async kind => {
  mount("logo"); const upload = vi.spyOn(api, "uploadBranding");
  const file = kind === "oversized" ? new File([new Uint8Array(10 * 1024**2 + 1)], "big.png", { type: "image/png" }) : new File(["svg"], "bad.svg", { type: "image/svg+xml" });
  fireEvent.change(screen.getByLabelText("Logo görseli"), { target: { files: [file] } });
  await screen.findByRole("alert"); expect(upload).not.toHaveBeenCalled();
});
it("keeps old defaults after backend dimension rejection", async () => {
  const { sent, saved } = mount("logo", 422);
  await screen.findByText(/Logo tanımlı/);
  fireEvent.change(screen.getByLabelText("Logo görseli"), { target: { files: [new File(["image"], "logo.png", { type: "image/png" })] } });
  fireEvent.click(screen.getByRole("button", { name: "Logoyu kaydet" }));
  await screen.findByRole("alert"); expect(sent).not.toHaveBeenCalled(); expect(saved).not.toHaveBeenCalled();
  expect(screen.getByText(/Logo tanımlı/)).toBeInTheDocument();
});
it("late upload cannot install after leaving step", async () => {
  const { leave, sent } = mount("logo");
  let complete: (value: { asset: string; preview_url: string }) => void = () => {};
  vi.spyOn(api, "uploadBranding").mockImplementation(() => new Promise(done => { complete = done; }));
  fireEvent.change(screen.getByLabelText("Logo görseli"), { target: { files: [new File(["x"], "logo.png", { type: "image/png" })] } });
  fireEvent.click(screen.getByRole("button", { name: "Logoyu kaydet" })); leave();
  await act(async () => complete({ asset: "branding/assets/late.png", preview_url: "/api/settings/branding/assets/late.png" }));
  expect(sent).not.toHaveBeenCalled();
});
