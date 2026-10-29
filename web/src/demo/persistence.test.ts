import { afterEach, expect, it, vi } from "vitest";
import { startDemo, stopDemo } from "./runtime";
import { readTourProgress, writeTourProgress } from "../promotion/tourProgress";

afterEach(stopDemo);
it("keeps drafts and walkthrough progress memory-only and refuses late writes after disposal", async () => {
  const { demoDraftStore } = await vi.importActual<typeof import("../packages/drafts")>("../packages/drafts");
  const persisted = vi.spyOn(Storage.prototype, "setItem");
  const runtime = startDemo(), store = demoDraftStore(runtime);
  const key = { origin: window.location.origin, clientId: 900001, packageId: 1 };
  const draft = { schemaVersion: 1 as const, localRevision: 0, folderName: "demo", baseContentRevision: 1,
    groups: { "photo:photo-1": { base: { seconds: 4 }, proposed: { seconds: 5 } } }, inputs: {}, uncertain: false };
  await store.writeDraft(key, 0, draft);
  expect((await store.readDraft(key))?.localRevision).toBe(1);
  writeTourProgress(900001, { version: 1, completed: ["intro"], dismissed: [], skipAll: false });
  expect(readTourProgress(900001).completed).toEqual(["intro"]);
  expect(persisted).not.toHaveBeenCalled();
  stopDemo(); await expect(store.writeDraft(key, 1, draft)).rejects.toThrow();
  startDemo(); expect(readTourProgress(900001).completed).toEqual([]);
});
