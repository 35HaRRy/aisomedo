import { afterEach, expect, it } from "vitest";
import { isDemoHash, normalHref, workspaceHref, readPairingMarker, writePairingMarker, noteRealPairing } from "./routing";

afterEach(() => { noteRealPairing(false); localStorage.clear(); });
it("matches only the exact demo segment", () => {
  for (const hash of ["#/demo", "#/demo/", "#/demo/package?review=7"]) expect(isDemoHash(hash)).toBe(true);
  for (const hash of ["#/demonstration", "#/dashboard", "#/demo-other"]) expect(isDemoHash(hash)).toBe(false);
});
it("normalizes the demo base and preserves encoded queries", () => {
  expect(normalHref("#/demo/")).toBe("#/dashboard");
  expect(normalHref("#/demo?review=7")).toBe("#/dashboard?review=7");
  expect(normalHref("#/demo/package?review=7&occurrence=2&folder=a%20b")).toBe("#/package?review=7&occurrence=2&folder=a%20b");
});
it("prefixes workspace links once and allows explicit welcome exits", () => {
  expect(workspaceHref("#/package?review=7", true)).toBe("#/demo/package?review=7");
  expect(workspaceHref("#/demo/settings", true)).toBe("#/demo/settings");
  expect(workspaceHref("#/welcome", true)).toBe("#/welcome");
  expect(workspaceHref("#/package", false)).toBe("#/package");
});
it("uses only a non-secret pairing hint and tolerates blocked storage", () => {
  expect(readPairingMarker()).toBe(false);
  writePairingMarker(true); expect(readPairingMarker()).toBe(true);
  writePairingMarker(false); expect(readPairingMarker()).toBe(false);
  expect(readPairingMarker(null)).toBe(false);
  expect(() => writePairingMarker(true, null)).not.toThrow();
});
it("retains validated pairing in memory when browser storage becomes unavailable", () => {
  noteRealPairing(true);
  expect(readPairingMarker(null)).toBe(true);
  noteRealPairing(false); expect(readPairingMarker(null)).toBe(false);
});
