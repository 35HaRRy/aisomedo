import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider } from "./useOnboarding";
import { OnboardingWizard } from "./OnboardingWizard";

it("renders seven ordered steps and backend-selected heading", async () => {
  vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(url.endsWith("/me") ? client : setupState("schedule"))));
  render(<SessionProvider><OnboardingProvider><OnboardingWizard /></OnboardingProvider></SessionProvider>);
  await screen.findByRole("heading", { name: "Dojo Yayın Planı" });
  expect(screen.getByRole("list", { name: "Kurulum adımları" }).children).toHaveLength(7);
});

it("keeps dirty current form when another device completes its checklist step", async () => {
  let setup = setupState("caption_template");
  vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(url.endsWith("/me") ? client : url === "/api/setup" ? setup : { caption_template: "Old" })));
  render(<SessionProvider><OnboardingProvider><OnboardingWizard /></OnboardingProvider></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Açıklama şablonu")).toHaveValue("Old"));
  fireEvent.change(screen.getByLabelText("Açıklama şablonu"), { target: { value: "My draft" } });
  setup = setupState();
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(done => setTimeout(done, 20)); });
  expect(screen.getByLabelText("Açıklama şablonu")).toHaveValue("My draft");
});

it("required readiness offers optional cards, focus and explicit finish", async () => {
  let setup = setupState("caption_template");
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/me")) return new Response(JSON.stringify(client));
    if (url === "/api/setup") return new Response(JSON.stringify(setup));
    if (init.method === "PATCH") setup = setupState();
    if (url.endsWith("/skip")) setup.checklist[6].complete = true;
    return new Response(JSON.stringify({ caption_template: "Dojo", intro_asset: null, outro_asset: null }));
  });
  render(<SessionProvider><OnboardingProvider><OnboardingWizard /></OnboardingProvider></SessionProvider>);
  await waitFor(() => expect(screen.getByLabelText("Açıklama şablonu")).toHaveValue("Dojo"));
  fireEvent.click(screen.getByRole("button", { name: "Açıklamayı kaydet" }));
  const heading = await screen.findByRole("heading", { name: "İsteğe bağlı kartlar" });
  expect(heading).toHaveFocus();
  expect(screen.getByRole("button", { name: /İsteğe bağlı kartlar İsteğe bağlı/ })).toHaveAttribute("aria-current", "step");
  expect(screen.getByRole("link", { name: "Kurulumu bitir" })).toHaveAttribute("href", "#/dashboard");
  fireEvent.click(screen.getByRole("button", { name: "Kartları değiştirmeden devam et" }));
  await screen.findByRole("heading", { name: "Kurulum tamamlandı" });
});
