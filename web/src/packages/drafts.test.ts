import { expect, it } from "vitest";
import { createDraftStore, reconcileDraft, resolveDraftConflict, type DraftTransaction, type StoredDraft } from "./drafts";
import { packageSnapshot } from "./testFixtures";

const key = { origin: "https://dojo.test", clientId: 7, packageId: 42 };
const draft = (): StoredDraft => ({ schemaVersion: 1, localRevision: 0, folderName: "active",
  baseContentRevision: 3, groups: { "video:a": { base: { ranges: [] }, proposed: { ranges: [{ start: "0", end: "" }] } } },
  inputs: { a: [{ start: "0", end: "" }] }, uncertain: false });

function memory() {
  const rows = new Map<string, unknown>();
  let rejectWrites = false;
  const transaction: DraftTransaction = async (key, operation) => {
    const outcome = operation(structuredClone(rows.get(key) ?? null));
    if (outcome.write) {
      if (rejectWrites) throw new Error("quota");
      if (outcome.next === null) rows.delete(key); else rows.set(key, structuredClone(outcome.next));
    }
    return outcome.result;
  };
  const store = createDraftStore(transaction, async () => [...rows.entries()]);
  return { ...store, rows, quota: () => { rejectWrites = true; } };
}

it("reopens incomplete input with the original comparison baseline", async () => {
  const store = memory();
  expect(await store.readDraft(key)).toBeNull();
  expect(await store.writeDraft(key, 0, draft())).toBe(1);
  const reopened = await store.readDraft(key);
  expect(reopened?.inputs.a[0].end).toBe("");
  expect(reopened?.groups["video:a"].base).toEqual({ ranges: [] });
  expect(reopened?.localRevision).toBe(1);
});

it("separates server, paired identity and package", async () => {
  const store = memory(); await store.writeDraft(key, 0, draft());
  expect(await store.readDraft({ ...key, clientId: 8 })).toBeNull();
  expect(await store.readDraft({ ...key, origin: "https://other.test" })).toBeNull();
  expect(await store.readDraft({ ...key, packageId: 43 })).toBeNull();
  expect(await store.listDrafts(key)).toEqual([{ packageId: 42, draft: { ...draft(), localRevision: 1 } }]);
});

it("competing tabs compare-and-replace atomically instead of overwriting", async () => {
  const store = memory();
  const second = structuredClone(draft()); second.inputs.a[0].end = "9";
  const results = await Promise.allSettled([store.writeDraft(key, 0, draft()), store.writeDraft(key, 0, second)]);
  expect(results[0]).toMatchObject({ status: "fulfilled", value: 1 });
  expect(results[1]).toMatchObject({ status: "rejected", reason: new Error("draft_conflict") });
  expect((await store.readDraft(key))?.inputs.a[0].end).toBe("");
  await expect(store.deleteDraft(key, 0)).rejects.toThrow("draft_conflict");
});

it("quota failure leaves the previous durable draft untouched", async () => {
  const store = memory(); await store.writeDraft(key, 0, draft());
  store.quota();
  const replacement = draft(); replacement.inputs.a[0].end = "5";
  await expect(store.writeDraft(key, 1, replacement)).rejects.toThrow("quota");
  expect((await store.readDraft(key))?.inputs.a[0].end).toBe("");
});

it("uncertain commands survive reopening and no storage action submits them", async () => {
  const store = memory(); const uncertain = { ...draft(), uncertain: true };
  await store.writeDraft(key, 0, uncertain);
  expect((await store.readDraft(key))?.uncertain).toBe(true);
  expect((await store.listDrafts(key))[0].draft.uncertain).toBe(true);
});

it.each([
  { schemaVersion: 2 }, { localRevision: "1" }, { inputs: { a: [{ start: 0, end: "" }] } },
  { groups: { unknown: { base: {}, proposed: {} } } }, { credential: "private" },
])("quarantines invalid/unsupported records without deleting or applying them", async corrupt => {
  const store = memory(); await store.writeDraft(key, 0, draft());
  const id = [...store.rows.keys()][0];
  store.rows.set(id, { ...(store.rows.get(id) as object), ...corrupt });
  const before = structuredClone(store.rows.get(id));
  await expect(store.readDraft(key)).rejects.toThrow("draft_corrupt");
  await expect(store.writeDraft(key, 1, draft())).rejects.toThrow("draft_corrupt");
  expect(store.rows.get(id)).toEqual(before);
});

it("confirmed deletion removes only the exact acknowledged local revision", async () => {
  const store = memory(); await store.writeDraft(key, 0, draft());
  await store.writeDraft(key, 1, draft());
  await expect(store.deleteDraft(key, 1)).rejects.toThrow("draft_conflict");
  expect((await store.readDraft(key))?.localRevision).toBe(2);
  await store.deleteDraft(key, 2);
  expect(await store.readDraft(key)).toBeNull();
});

it("deletion leaves a revision tombstone so stale tabs cannot overwrite a recreated draft", async () => {
  const store = memory();
  await store.writeDraft(key, 0, draft());
  await store.deleteDraft(key, 1);
  expect(await store.readDraft(key)).toBeNull();
  expect(await store.listDrafts(key)).toEqual([]);
  await expect(store.writeDraft(key, 1, draft())).rejects.toThrow("draft_conflict");
  expect(await store.writeDraft(key, 0, draft())).toBe(3);
  const stale = draft(); stale.inputs.a[0].end = "9";
  await expect(store.writeDraft(key, 1, stale)).rejects.toThrow("draft_conflict");
  expect((await store.readDraft(key))?.inputs.a[0].end).toBe("");
});

it("independent server changes preserve only locally edited groups and their baselines", () => {
  const snapshot = packageSnapshot(), local = draft();
  local.folderName = snapshot.package.folder_name;
  snapshot.montage.selections.b = [{ start: 10, end: 15 }];
  const result = reconcileDraft({ ...key, packageId: snapshot.package.id }, local, snapshot);
  expect(result.applicable).toBe(true); expect(result.conflicts).toEqual({});
  expect(result.draft?.groups["video:a"].base).toEqual({ ranges: [] });
  expect(result.draft?.inputs.a[0].end).toBe("");
});

it("same-video changes conflict as one group, and explicit local choice can conflict again", () => {
  const snapshot = packageSnapshot(), local = draft();
  local.folderName = snapshot.package.folder_name;
  snapshot.montage.selections.a = [{ start: 2, end: 5 }];
  const result = reconcileDraft({ ...key, packageId: snapshot.package.id }, local, snapshot);
  expect(result.conflicts).toEqual({ "video:a": { ranges: [{ start: 2, end: 5 }] } });
  const resolved = resolveDraftConflict(result.draft!, "video:a", result.conflicts["video:a"], "local", 8);
  expect(resolved?.groups["video:a"].base).toEqual({ ranges: [{ start: 2, end: 5 }] });
  expect(resolved?.inputs.a[0].end).toBe("");
  snapshot.montage.selections.a = [{ start: 3, end: 5 }];
  expect(reconcileDraft({ ...key, packageId: snapshot.package.id }, resolved!, snapshot).conflicts).toHaveProperty("video:a");
});

it("uncertain already-applied proposal reconciles without a second mutation", () => {
  const snapshot = packageSnapshot(), local = draft();
  local.folderName = snapshot.package.folder_name; local.uncertain = true;
  local.inputs.a = [{ start: "0", end: "5" }];
  local.groups["video:a"].proposed = { ranges: [{ start: 0, end: 5 }] };
  snapshot.montage.selections.a = [{ start: 0, end: 5 }];
  expect(reconcileDraft({ ...key, packageId: snapshot.package.id }, local, snapshot).draft).toBeNull();
});

it("completed or replaced package leaves its draft recoverable but inapplicable", () => {
  const snapshot = packageSnapshot(), local = draft();
  local.folderName = snapshot.package.folder_name;
  expect(reconcileDraft(key, local, snapshot)).toMatchObject({ applicable: false, draft: local });
  snapshot.package.status = "completed";
  expect(reconcileDraft({ ...key, packageId: snapshot.package.id }, local, snapshot).applicable).toBe(false);
});
