import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider } from "./useOnboarding";
import { ConsentStep } from "./ConsentStep";
import { api } from "../api/client";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function mount(initial = 1, accepted: string | null = null, missing = false) {
  let version = initial;
  let acceptance = accepted;
  const sent = vi.fn();
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/me")) return json(client);
    if (url === "/api/setup") return json(setupState("consent"));
    if (url.endsWith("/accept")) {
      const body = JSON.parse(String(init.body)); sent(body);
      if (body.version !== version) return json({}, 409);
      acceptance = "2026-10-01T10:00:00Z";
      return json({ version, accepted_at: acceptance });
    }
    return json({ version, text: `<b>Policy ${version}</b>`, accepted_at: acceptance }, missing ? 404 : 200);
  });
  const content = (show = true) => <SessionProvider><OnboardingProvider>{show && <ConsentStep onSaved={vi.fn()} />}</OnboardingProvider></SessionProvider>;
  const view = render(content());
  return { ...view, leave: () => view.rerender(content(false)), sent, update: (v: number, a: string | null = null) => { version = v; acceptance = a; } };
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
it("renders plain policy and requires acknowledgement of displayed version", async () => {
  const { sent } = mount();
  await screen.findByText("<b>Policy 1</b>");
  expect(document.querySelector("b")).toBeNull();
  const checkbox = screen.getByRole("checkbox");
  expect(checkbox).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Rızayı kaydet" })).toBeDisabled();
  fireEvent.click(checkbox); fireEvent.click(screen.getByRole("button", { name: "Rızayı kaydet" }));
  await waitFor(() => expect(sent).toHaveBeenCalledWith({ version: 1 }));
  await screen.findByText(/Rıza kaydedildi/);
});
it("resets acknowledgement when live version changes", async () => {
  const { update } = mount();
  await screen.findByRole("checkbox"); fireEvent.click(screen.getByRole("checkbox"));
  update(2);
  vi.useFakeTimers(); await act(async () => { window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByText("<b>Policy 2</b>")).toBeInTheDocument();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});
it("reloads policy after stale acceptance 409 without auto acceptance", async () => {
  const { update, sent } = mount();
  await screen.findByRole("checkbox"); fireEvent.click(screen.getByRole("checkbox")); update(2);
  fireEvent.click(screen.getByRole("button", { name: "Rızayı kaydet" }));
  await screen.findByText("<b>Policy 2</b>");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(sent).toHaveBeenCalledTimes(1);
  expect(sent).toHaveBeenCalledWith({ version: 1 });
});
it("shows inherited timestamp without resubmission", async () => {
  mount(1, "2026-10-01T10:00:00Z");
  await screen.findByText(/Rıza kaydedildi/);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});
it("missing policy blocks safely", async () => {
  mount(1, null, true);
  await screen.findByText(/Rıza metni henüz tanımlanmamış/);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});
it("reflects acceptance by another device", async () => {
  const { update, sent } = mount();
  await screen.findByRole("checkbox"); update(1, "2026-10-01T10:00:00Z");
  vi.useFakeTimers(); await act(async () => { window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByText(/Rıza kaydedildi/)).toBeInTheDocument();
  expect(sent).not.toHaveBeenCalled();
});

it("disables duplicate acceptance and aborts on leaving step", async () => {
  const { leave } = mount();
  let signal: AbortSignal | undefined;
  let complete: (value: { version: number; accepted_at: string }) => void = () => {};
  const accept = vi.spyOn(api, "acceptConsent").mockImplementation((_version, s) => {
    signal = s; return new Promise(done => { complete = done; });
  });
  await screen.findByRole("checkbox"); fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Rızayı kaydet" }));
  expect(screen.getByRole("button", { name: "Kaydediliyor…" })).toBeDisabled();
  leave();
  expect(signal?.aborted).toBe(true);
  await act(async () => complete({ version: 1, accepted_at: "2026-10-01T10:00:00Z" }));
  expect(accept).toHaveBeenCalledTimes(1);
});
