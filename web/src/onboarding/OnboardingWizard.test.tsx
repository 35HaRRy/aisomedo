import { render, screen } from "@testing-library/react";
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
