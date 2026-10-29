import { afterEach, expect, it, vi } from "vitest";
import { startDemo, stopDemo } from "./runtime";
import { transportFetch } from "../api/transport";

afterEach(() => { stopDemo(); window.location.hash = ""; vi.unstubAllGlobals(); });
it("keeps one sandbox through remounts and resets it on exit", () => {
  const first = startDemo(); first.storage.setItem("draft", "sample");
  expect(startDemo()).toBe(first);
  expect(startDemo().storage.getItem("draft")).toBe("sample");
  stopDemo(); expect(first.signal.aborted).toBe(true);
  expect(startDemo().storage.getItem("draft")).toBeNull();
});
it("never calls native fetch for demo or unknown operations", async () => {
  window.location.hash = "#/demo/dashboard";
  const native = vi.fn(); vi.stubGlobal("fetch", native);
  await expect(transportFetch("/api/dashboard")).rejects.toThrow();
  startDemo();
  expect((await transportFetch("/api/unknown")).status).toBe(404);
  expect(native).not.toHaveBeenCalled();
});
it("a disposed sandbox cannot turn an old operation into a real request", async () => {
  const sandbox = startDemo(); stopDemo();
  await expect(sandbox.fetch("/api/dashboard")).rejects.toThrow();
});
it("rejects a late real response after entering demo mode", async () => {
  let release!: (value: Response) => void;
  vi.stubGlobal("fetch", () => new Promise<Response>(resolve => { release = resolve; }));
  const pending = transportFetch("/api/dashboard");
  startDemo(); release(new Response("{}"));
  await expect(pending).rejects.toThrow();
});
it("rejects a real response even after a full demo round trip", async () => {
  let release!: (value: Response) => void;
  vi.stubGlobal("fetch", () => new Promise<Response>(resolve => { release = resolve; }));
  const pending = transportFetch("/api/dashboard");
  startDemo(); stopDemo(); release(new Response("{}"));
  await expect(pending).rejects.toThrow();
});
