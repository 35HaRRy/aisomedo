import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider } from "./useOnboarding";
import { PlanStep } from "./PlanStep";

function mount(status = 200) {
  const sent = vi.fn(); const saved = vi.fn();
  let plan = { anchor_date: "2026-10-05", anchor_time: "10:00:00", enabled: false, timezone: "Europe/Istanbul" };
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/me")) return new Response(JSON.stringify(client));
    if (url === "/api/setup") return new Response(JSON.stringify(setupState("schedule")));
    if (init.method === "PUT") { sent(JSON.parse(String(init.body))); return new Response(JSON.stringify(plan), { status }); }
    return new Response(JSON.stringify(plan));
  });
  render(<SessionProvider><OnboardingProvider><PlanStep onSaved={saved} /></OnboardingProvider></SessionProvider>);
  return { sent, saved, update: () => { plan = { ...plan, anchor_date: "2026-10-19" }; } };
}
afterEach(() => vi.useRealTimers());
it("saves Monday, local time and disabled plan", async () => {
  const { sent } = mount();
  await waitFor(() => expect(screen.getByLabelText("İlk yayın tarihi")).toHaveValue("2026-10-05"));
  expect(screen.getByText(/Europe\/Istanbul/)).toBeInTheDocument();
  expect(screen.getByText(/iki haftada bir/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Planı kaydet" }));
  await waitFor(() => expect(sent).toHaveBeenCalledWith({ anchor_date: "2026-10-05", anchor_time: "10:00", enabled: false }));
});
it("rejects Tuesday locally without sending", async () => {
  const { sent } = mount();
  await screen.findByLabelText("İlk yayın tarihi");
  fireEvent.change(screen.getByLabelText("İlk yayın tarihi"), { target: { value: "2026-10-06" } });
  fireEvent.click(screen.getByRole("button", { name: "Planı kaydet" }));
  await screen.findByRole("alert"); expect(sent).not.toHaveBeenCalled();
});
it("retains draft on backend rejection and does not advance", async () => {
  const { saved } = mount(422);
  await waitFor(() => expect(screen.getByLabelText("İlk yayın tarihi")).toHaveValue("2026-10-05"));
  fireEvent.change(screen.getByLabelText("Yayın saati"), { target: { value: "13:30" } });
  fireEvent.click(screen.getByRole("button", { name: "Planı kaydet" }));
  await screen.findByRole("alert"); expect(saved).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Yayın saati")).toHaveValue("13:30");
});
it("does not replace dirty draft during foreground refresh", async () => {
  const { update } = mount();
  await waitFor(() => expect(screen.getByLabelText("İlk yayın tarihi")).toHaveValue("2026-10-05"));
  fireEvent.change(screen.getByLabelText("Yayın saati"), { target: { value: "13:30" } }); update();
  vi.useFakeTimers(); await act(async () => { window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByLabelText("Yayın saati")).toHaveValue("13:30");
  fireEvent.click(screen.getByRole("button", { name: "Sunucudaki değerleri yükle" }));
  expect(screen.getByLabelText("İlk yayın tarihi")).toHaveValue("2026-10-19");
});
