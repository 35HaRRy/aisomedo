import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider } from "./useOnboarding";
import { CardsStep } from "./CardsStep";

function mount() {
  const sent = vi.fn();
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/me")) return new Response(JSON.stringify(client));
    if (url.endsWith("/skip")) { sent("skip"); return new Response(JSON.stringify(setupState())); }
    if (url === "/api/setup") return new Response(JSON.stringify(setupState()));
    if (init.method === "PATCH") sent(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ logo_asset: "logo.png", caption_template: "Dojo", intro_asset: "intro.png", intro_duration: 2, outro_asset: null, outro_duration: null }));
  });
  render(<SessionProvider><OnboardingProvider><CardsStep onSaved={vi.fn()} /></OnboardingProvider></SessionProvider>);
  return sent;
}
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
it("saves positive decimal duration", async () => {
  const sent = mount();
  await waitFor(() => expect(screen.getByLabelText("Giriş süresi (saniye)")).toHaveValue(2));
  fireEvent.change(screen.getByLabelText("Giriş süresi (saniye)"), { target: { value: "1.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Kartları kaydet" }));
  await waitFor(() => expect(sent).toHaveBeenCalledWith({ intro_duration: 1.5 }));
});
it.each(["0", "-1"])("rejects invalid duration %s", async value => {
  const sent = mount(); await screen.findByText("Giriş kartı tanımlı");
  fireEvent.change(screen.getByLabelText("Giriş süresi (saniye)"), { target: { value } });
  fireEvent.submit(screen.getByRole("button", { name: "Kartları kaydet" }).closest("form")!);
  await screen.findByRole("alert"); expect(sent).not.toHaveBeenCalled();
});
