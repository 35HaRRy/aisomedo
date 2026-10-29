import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../App";
import { getDemoRuntime, stopDemo } from "./runtime";
import { readPairingMarker, writePairingMarker } from "./routing";
import { api } from "../api/client";
import { SessionProvider, useSession } from "../session";

beforeEach(() => { localStorage.clear(); window.location.hash = "#/demo/dashboard"; });
afterEach(() => { cleanup(); stopDemo(); window.location.hash = ""; });
it("direct demo with a cookie but no marker uses no real session, compat, or events", async () => {
  document.cookie = "old_session=opaque";
  const native = vi.fn(() => Promise.reject(new Error("No backend"))); vi.stubGlobal("fetch", native);
  localStorage.setItem("real-draft", "unchanged");
  render(<StrictMode><App /></StrictMode>);
  expect(await screen.findByRole("heading", { name: "Kontrol Paneli" })).toBeInTheDocument();
  expect(screen.getByText("demo", { selector: ".demo-badge" })).toBeInTheDocument();
  const sandbox = getDemoRuntime();
  fireEvent.click(screen.getByRole("link", { name: "Ayarlar" }));
  await screen.findByRole("heading", { name: "Ayarlar" });
  expect(getDemoRuntime()).toBe(sandbox); expect(window.location.hash).toBe("#/demo/settings");
  expect(native).not.toHaveBeenCalled(); expect(localStorage.getItem("real-draft")).toBe("unchanged");
  expect(readPairingMarker()).toBe(false);
});
it("redirects a marked real session before any real validation, preserving queries", async () => {
  writePairingMarker(true); window.location.hash = "#/demo/package?review=7&folder=a%20b";
  const calls: string[] = [];
  vi.stubGlobal("fetch", async () => { calls.push(window.location.hash); return new Response("{}", { status: 401 }); });
  render(<App />);
  await waitFor(() => expect(calls.length).toBeGreaterThan(0));
  expect(calls.every(hash => hash === "#/package?review=7&folder=a%20b")).toBe(true);
  expect(getDemoRuntime()).toBeNull(); await waitFor(() => expect(readPairingMarker()).toBe(false));
});
it("demo pairing removal exits without revoking real cookies or hints", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const native = vi.fn(); vi.stubGlobal("fetch", native);
  render(<App />); await screen.findByRole("heading", { name: "Kontrol Paneli" });
  fireEvent.click(screen.getByRole("link", { name: "Ayarlar" }));
  await screen.findByRole("heading", { name: "Ayarlar" });
  const cookie = document.cookie;
  fireEvent.click(screen.getByRole("button", { name: "Kaldır" }));
  await waitFor(() => expect(window.location.hash).toBe("#/welcome"));
  expect(document.cookie).toBe(cookie); expect(native).not.toHaveBeenCalled();
});
it("reentry reseeds changes while navigation retains them", async () => {
  vi.stubGlobal("fetch", vi.fn()); render(<App />);
  await screen.findByRole("heading", { name: "Kontrol Paneli" });
  await act(async () => { await api.patchBranding({ caption_template: "Changed" }); });
  expect((await api.branding()).caption_template).toBe("Changed");
  await act(async () => { window.location.hash = "#/welcome"; window.dispatchEvent(new Event("hashchange")); });
  await act(async () => { window.location.hash = "#/demo/dashboard"; window.dispatchEvent(new Event("hashchange")); });
  await screen.findByRole("heading", { name: "Kontrol Paneli" });
  expect((await api.branding()).caption_template).not.toBe("Changed");
});
function Probe() { return <p>{useSession().status}</p>; }
it("a real network error preserves its pairing marker", async () => {
  window.location.hash = "#/dashboard"; writePairingMarker(true);
  vi.stubGlobal("fetch", async () => { throw new TypeError("Offline"); });
  render(<SessionProvider><Probe /></SessionProvider>);
  await screen.findByText("error"); expect(readPairingMarker()).toBe(true);
});
it("keeps dashboard, activity, and review links inside demo mode", async () => {
  vi.stubGlobal("fetch", vi.fn()); render(<App />);
  await screen.findByRole("heading", { name: "Kontrol Paneli" });
  for (const link of document.querySelectorAll<HTMLAnchorElement>('a[href^="#/"]')) {
    expect(link.hash.startsWith("#/demo/")).toBe(true);
  }
});
it("simulates Instagram in settings without opening a window or storing a token", async () => {
  vi.stubGlobal("fetch", vi.fn()); const popup = vi.spyOn(window, "open");
  window.location.hash = "#/demo/settings"; render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: /Instagram bağlantısı/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Instagram ile yetkilendir" }));
  expect(await screen.findByRole("button", { name: "@ornek_studyo_demo_2 hesabını seç" })).toBeInTheDocument();
  expect(popup).not.toHaveBeenCalled(); expect(screen.queryByLabelText("Instagram erişim tokenı")).not.toBeInTheDocument();
});
it("starts a usable demo when browser storage is blocked", async () => {
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new Error("Blocked"); });
  vi.stubGlobal("fetch", vi.fn()); render(<StrictMode><App /></StrictMode>);
  await screen.findByRole("heading", { name: "Kontrol Paneli" });
  expect(getDemoRuntime()?.storage).toBeTruthy();
});
it("a cancelled raw hash exit preserves dirty demo drafts and its runtime", async () => {
  vi.stubGlobal("fetch", vi.fn()); window.location.hash = "#/demo/package"; render(<App />);
  const seconds = await screen.findByRole("spinbutton", { name: "antrenman.jpg Gösterilme süresi (sn)" });
  await waitFor(() => expect(seconds).toBeEnabled());
  fireEvent.change(seconds, { target: { value: "5" } });
  const sandbox = getDemoRuntime();
  await act(async () => { window.location.hash = "#/welcome"; window.dispatchEvent(new Event("hashchange")); });
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(getDemoRuntime()).toBe(sandbox);
  fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));
  expect(window.location.hash).toBe("#/demo/package");
  expect(seconds).toHaveValue(5);
});
