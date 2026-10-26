import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { live } from "../live";
import { resetResourceVersions } from "../api/client";
import { readyLive } from "./live";
import { draftMemory } from "./drafts";

if (typeof URL.createObjectURL !== "function") {
  let sequence = 0;
  Object.defineProperty(URL, "createObjectURL", { value: () => `blob:preview-${++sequence}` });
}
if (typeof URL.revokeObjectURL !== "function") Object.defineProperty(URL, "revokeObjectURL", { value: () => {} });

vi.mock("../packages/drafts", async () => {
  const actual = await vi.importActual<typeof import("../packages/drafts")>("../packages/drafts");
  const { draftMemory } = await import("./drafts");
  const store = actual.createDraftStore(draftMemory.transaction, draftMemory.entries);
  return { ...actual, ...store, clearIdentityDrafts: draftMemory.clearIdentity };
});

beforeEach(() => { resetResourceVersions(); draftMemory.reset(); readyLive(); });
afterEach(() => { cleanup(); live.stop(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
