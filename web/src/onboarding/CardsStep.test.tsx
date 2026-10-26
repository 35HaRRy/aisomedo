import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { invalidateLive } from "../test/live";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider } from "./useOnboarding";
import { CardsStep } from "./CardsStep";

function mount() {
  const sent = vi.fn();
  let intro = "intro.png";
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/me")) return new Response(JSON.stringify(client));
    if (url.endsWith("/skip")) { sent("skip"); return new Response(JSON.stringify(setupState())); }
    if (url === "/api/setup") return new Response(JSON.stringify(setupState()));
    if (init.method === "PATCH") sent(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ logo_asset: "logo.png", caption_template: "Dojo", intro_asset: intro, intro_duration: 2, outro_asset: null, outro_duration: null }));
  });
  render(<SessionProvider><OnboardingProvider><CardsStep onSaved={vi.fn()} /></OnboardingProvider></SessionProvider>);
  return Object.assign(sent, { updateImage: () => { intro = "other.png"; } });
}
afterEach(() => vi.useRealTimers());
it("skip retains configured cards and uses separate marker", async () => {
  const sent = mount(); await screen.findByText("Giriş kartı tanımlı");
  fireEvent.click(screen.getByRole("button", { name: "Kartları değiştirmeden devam et" }));
  await waitFor(() => expect(sent).toHaveBeenCalledWith("skip"));
  expect(sent).not.toHaveBeenCalledWith(expect.objectContaining({ intro_asset: null }));
});
it("explicit remove clears asset and duration", async () => {
  const sent = mount(); await screen.findByText("Giriş kartı tanımlı");
  fireEvent.click(screen.getByRole("button", { name: "Giriş kartını kaldır" }));
  fireEvent.click(screen.getByRole("button", { name: "Kartları kaydet" }));
  await waitFor(() => expect(sent).toHaveBeenCalledWith({ intro_asset: null, intro_duration: null }));
});
it("previews the selected card image before saving", async () => {
  mount(); await screen.findByText("Giriş kartı tanımlı");
  fireEvent.change(screen.getByLabelText("Giriş görseli"), { target: { files: [new File(["image"], "intro.png", { type: "image/png" })] } });
  expect(screen.getByRole("img", { name: "Seçilen giriş kartı önizlemesi" })).toHaveAttribute("src", expect.stringMatching(/^blob:/));
});
it("saves positive integer duration", async () => {
  const sent = mount();
  await waitFor(() => expect(screen.getByLabelText("Giriş süresi (saniye)")).toHaveValue(2));
  fireEvent.change(screen.getByLabelText("Giriş süresi (saniye)"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Kartları kaydet" }));
  await waitFor(() => expect(sent).toHaveBeenCalledWith({ intro_duration: 3 }));
});
it.each(["0", "-1", "1.5", "1e2"])("rejects invalid duration %s", async value => {
  const sent = mount(); await screen.findByText("Giriş kartı tanımlı");
  fireEvent.change(screen.getByLabelText("Giriş süresi (saniye)"), { target: { value } });
  const input = screen.getByLabelText("Giriş süresi (saniye)") as HTMLInputElement;
  expect(input.value).not.toBe(value);
  expect(sent).not.toHaveBeenCalled();
});

it("only offers removal for a configured or selected card", async () => {
  mount(); await screen.findByText("Giriş kartı tanımlı");
  expect(screen.queryByRole("button", { name: "Çıkış kartını kaldır" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Giriş kartını kaldır" }));
  expect(screen.queryByRole("button", { name: "Giriş kartını kaldır" })).not.toBeInTheDocument();
});

it("accepts and previews a selected card video", async () => {
  mount(); await screen.findByText("Giriş kartı tanımlı");
  fireEvent.change(screen.getByLabelText("Giriş görseli"), { target: { files: [new File(["video"], "intro.mp4", { type: "video/mp4" })] } });
  expect(screen.getByLabelText("Seçilen giriş kartı önizlemesi").tagName).toBe("VIDEO");
});

it("accepts and previews supported video when the OS provides no MIME type", async () => {
  mount(); await screen.findByText("Giriş kartı tanımlı");
  fireEvent.change(screen.getByLabelText("Giriş görseli"), { target: { files: [new File(["video"], "intro.mkv")] } });
  expect(screen.getByLabelText("Seçilen giriş kartı önizlemesi").tagName).toBe("VIDEO");
});

it("detects asset-only change while duration draft remains intact", async () => {
  const sent = mount();
  await waitFor(() => expect(screen.getByLabelText("Giriş süresi (saniye)")).toHaveValue(2));
  fireEvent.change(screen.getByLabelText("Giriş süresi (saniye)"), { target: { value: "3" } });
  sent.updateImage();
  vi.useFakeTimers(); await act(async () => { invalidateLive(); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByLabelText("Giriş süresi (saniye)")).toHaveValue(3);
  expect(screen.getByRole("button", { name: "Sunucudaki değerleri yükle" })).toBeInTheDocument();
});
