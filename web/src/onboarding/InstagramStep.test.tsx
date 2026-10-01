import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { SessionProvider } from "../session";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider } from "./useOnboarding";
import { InstagramStep } from "./InstagramStep";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function mount(status = 200) {
  const sent = vi.fn();
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/me")) return json(client);
    if (url === "/api/setup") return json(setupState("instagram"));
    if (url.endsWith("/token")) { sent(JSON.parse(String(init.body))); return json({ health: "healthy", ig_username: "dojo" }, status); }
    return json({ health: "healthy", ig_username: "old_dojo" });
  });
  const onSaved = vi.fn();
  const view = render(<SessionProvider><OnboardingProvider><InstagramStep onSaved={onSaved} /></OnboardingProvider></SessionProvider>);
  return { ...view, sent, onSaved };
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
it.each([200, 422, 502, 503])("clears masked token without leaking secrets for status %i", async status => {
  const { sent } = mount(status);
  const input = screen.getByLabelText("Instagram erişim tokenı");
  expect(input).toHaveAttribute("type", "password");
  fireEvent.change(input, { target: { value: "private-token" } });
  fireEvent.click(screen.getByRole("button", { name: "Token ile bağlan" }));
  await waitFor(() => expect(sent).toHaveBeenCalledWith({ access_token: "private-token" }));
  await waitFor(() => expect(input).toHaveValue(""));
  expect(document.body.textContent).not.toContain("private-token");
  expect(window.location.href).not.toContain("private-token");
  expect(localStorage.length + sessionStorage.length).toBe(0);
  if (status === 200) await screen.findByText(/@dojo · Bağlantı doğrulandı/);
  else await screen.findByRole("alert");
});
it("disables duplicate token submit and discards pending result on unmount", async () => {
  const { unmount, onSaved } = mount();
  let complete: (value: { health: string }) => void = () => {};
  const connect = vi.spyOn(api, "connectInstagramToken").mockImplementation(() => new Promise(done => { complete = done; }));
  fireEvent.change(screen.getByLabelText("Instagram erişim tokenı"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Token ile bağlan" }));
  expect(screen.getByRole("button", { name: "Bağlantı doğrulanıyor…" })).toBeDisabled();
  unmount(); await act(async () => complete({ health: "healthy" }));
  expect(connect).toHaveBeenCalledTimes(1); expect(onSaved).not.toHaveBeenCalled();
});
it("opens explicit OAuth safely and requires candidate selection", async () => {
  mount();
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  vi.spyOn(api, "startOAuth").mockResolvedValue({ auth_url: "https://www.facebook.com/dialog/oauth", attempt_id: "a1" });
  vi.spyOn(api, "oauthAttempt").mockResolvedValue({ id: "a1", status: "completed", candidates: [
    { ig_user_id: "1", ig_username: "one" }, { ig_user_id: "2", ig_username: "two" },
  ] });
  const select = vi.spyOn(api, "selectInstagramAccount").mockResolvedValue({ health: "healthy", ig_username: "two" });
  fireEvent.click(screen.getByRole("button", { name: "Instagram ile yetkilendir" }));
  await screen.findByRole("link", { name: "Yetkilendirme sayfasını aç" });
  expect(open).toHaveBeenCalledWith("https://www.facebook.com/dialog/oauth", "_blank", "noopener,noreferrer");
  await screen.findByRole("button", { name: "@two hesabını seç" });
  expect(select).not.toHaveBeenCalled();
  expect(screen.getByText(/@old_dojo · Bağlantı doğrulandı/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "@two hesabını seç" }));
  await waitFor(() => expect(select).toHaveBeenCalledWith("a1", "2", expect.any(AbortSignal)));
});
it.each(["failed", "expired", "unknown"])("offers OAuth retry for %s", async status => {
  mount(); vi.spyOn(window, "open").mockReturnValue(null);
  vi.spyOn(api, "startOAuth").mockResolvedValue({ auth_url: "https://www.facebook.com/", attempt_id: "a1" });
  const poll = vi.spyOn(api, "oauthAttempt").mockResolvedValue({ id: "a1", status, candidates: [] });
  fireEvent.click(screen.getByRole("button", { name: "Instagram ile yetkilendir" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Instagram ile yetkilendir" })).toBeEnabled();
  vi.useFakeTimers(); await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(poll).toHaveBeenCalledTimes(1);
});

it("stops foreground attempt polling after unmount", async () => {
  const { unmount } = mount(); vi.spyOn(window, "open").mockReturnValue(null);
  vi.spyOn(api, "startOAuth").mockResolvedValue({ auth_url: "https://www.facebook.com/", attempt_id: "a1" });
  const poll = vi.spyOn(api, "oauthAttempt").mockResolvedValue({ id: "a1", status: "pending", candidates: [] });
  fireEvent.click(screen.getByRole("button", { name: "Instagram ile yetkilendir" }));
  await screen.findByText(/Bu sayfa sonucu kontrol ediyor/);
  unmount(); vi.useFakeTimers(); await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(poll).toHaveBeenCalledTimes(1);
});
