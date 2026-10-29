import { afterEach, expect, it } from "vitest";
import { createDemoState } from "./seed";
import { startDemo, stopDemo } from "./runtime";

afterEach(stopDemo);
const send = (path: string, body?: unknown, method = body === undefined ? "GET" : "POST", headers?: HeadersInit) =>
  startDemo().fetch(`/api/${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body), headers });
it("seeds complete fictional collections and one active package at any date", () => {
  for (const now of [new Date("2026-10-29"), new Date("2030-03-05")]) {
    const state = createDemoState(now);
    expect(state.completed.length).toBeGreaterThanOrEqual(2);
    expect(state.editor.media.length).toBeGreaterThanOrEqual(2);
    expect(state.reviews.size).toBeGreaterThanOrEqual(2);
    expect(state.activity.events.length).toBeGreaterThanOrEqual(2);
    expect(state.candidates.length).toBeGreaterThanOrEqual(2);
    expect(state.dashboard.next_slots!.length).toBeGreaterThanOrEqual(2);
    expect(state.dashboard.package?.id).toBe(state.editor.package.id);
    expect(Date.parse(state.dashboard.next_slot!.due_at)).toBeGreaterThan(now.getTime());
    expect(state.setup.ready).toBe(true);
    expect(new Date(`${state.plan.anchor_date}T12:00:00Z`).getUTCDay()).toBe(1);
  }
});
it("settings writes are visible in later reads, invalid writes change nothing", async () => {
  expect((await send("settings/branding", { caption_template: "Demo caption" }, "PATCH")).status).toBe(200);
  expect(await (await send("settings/branding")).json()).toMatchObject({ caption_template: "Demo caption" });
  expect((await send("settings/reminders", { interval_minutes: -1 }, "PUT")).status).toBe(422);
  expect(await (await send("settings/reminders")).json()).toMatchObject({ interval_minutes: 360 });
});
it("checks package revisions and rejects invalid groups before mutation", async () => {
  const state = startDemo().state, pkg = state.editor.package;
  const body = { expected_package_id: pkg.id, expected_folder_name: pkg.folder_name, base_content_revision: 1,
    changes: [{ key: "photo:photo-1", base: { seconds: 4 }, proposed: { seconds: 5 } }] };
  expect((await send("packages/active/edits", body, "PUT")).status).toBe(200);
  expect(state.editor.media[0].effective_duration).toBe(5);
  expect((await send("packages/active/edits", body, "PUT")).status).toBe(409);
  expect((await send("packages/active/edits", { ...body, base_content_revision: 2, changes: [{ key: "photo:photo-1", proposed: { seconds: -2 } }] }, "PUT")).status).toBe(422);
  expect(state.editor.content_revision).toBe(2);
});
it.each(["approve", "skip", "reschedule"])("%s has a distinct coherent review outcome", async action => {
  const state = startDemo().state, before = state.completed.length;
  const response = await send(`reviews/1/${action}`, { version: 1, confirmed: true, new_due_at: new Date(Date.now() + 3600000).toISOString() });
  expect(response.status).toBe(200);
  expect(state.reviews.get(1)?.review.status).toBe(action === "approve" ? "approved" : action === "skip" ? "skipped" : "rescheduled");
  expect(state.completed.length).toBe(before + (action === "approve" ? 1 : 0));
  expect((await send(`reviews/1/${action}`, { version: 1, confirmed: true })).status).toBe(409);
});
it("fails closed on unknown methods, routes, invalid JSON and aborted work", async () => {
  expect((await send("unknown")).status).toBe(404);
  expect((await send("settings/plan", {}, "DELETE")).status).toBe(404);
  expect((await startDemo().fetch("/api/settings/plan", { method: "PUT", body: "{" })).status).toBe(422);
  const signal = AbortSignal.abort();
  await expect(startDemo().fetch("/api/dashboard", { signal })).rejects.toThrow();
});
it("persists order and selections with preconditions, rejecting malformed lists", async () => {
  const state = startDemo().state, folder = state.editor.package.folder_name;
  const headers = { "If-Match": '"1:1"' };
  expect((await send("packages/active/order", { order: ["video-1", "photo-1"], expected_folder_name: folder }, "PUT", headers)).status).toBe(200);
  expect(state.editor.montage.order).toEqual(["video-1", "photo-1"]);
  expect((await send("packages/active/order", { order: ["photo-1", "photo-1"], expected_folder_name: folder }, "PUT", { "If-Match": '"1:2"' })).status).toBe(422);
  expect((await send("packages/active/selections", { selections: { "video-1": [{ start: 1, end: 3 }] }, expected_folder_name: folder }, "PUT", { "If-Match": '"1:2"' })).status).toBe(200);
  expect(state.editor.montage.combined_duration).toBe(6);
});
it("rejects an invalid duration atomically without applying its other selections", async () => {
  const state = startDemo().state;
  const response = await send("packages/active/selections", { expected_folder_name: state.editor.package.folder_name,
    selections: { "video-1": [{ start: 1, end: 3 }] }, photo_durations: { "photo-1": -1 } }, "PUT", { "If-Match": '"1:1"' });
  expect(response.status).toBe(422); expect(state.editor.montage.selections).toEqual({});
});
it("keeps the dashboard schedule and review boundary coherent with plan edits", async () => {
  expect((await send("settings/plan", { enabled: false, anchor_date: "2030-03-04", anchor_time: "10:00" }, "PUT")).status).toBe(200);
  expect(startDemo().state.dashboard.next_slots?.some(slot => slot.kind === "regular")).toBe(false);
  expect(startDemo().state.dashboard.next_slot).toBeNull();
});
it("clearing a package cancels its pending review before another package can be approved", async () => {
  const state = startDemo().state;
  await send("packages/active/clear", { confirmed: true, expected_package_id: 1, expected_folder_name: state.editor.package.folder_name }, "POST", { "If-Match": '"1:1"' });
  expect(state.reviews.get(1)?.review.status).toBe("cancelled");
  const completed = state.completed.length;
  expect((await send("reviews/1/approve", { version: 1 })).status).toBe(409);
  expect(state.completed).toHaveLength(completed);
});
it("an old review cannot approve the current editor's unrelated package", async () => {
  const state = startDemo().state;
  state.editor.package = { ...state.editor.package, id: 11, folder_name: "New demo package" };
  state.dashboard.package = state.editor.package;
  expect((await send("reviews/1/approve", { version: 1 })).status).toBe(409);
  expect(state.dashboard.package?.id).toBe(11); expect(state.completed).toHaveLength(2);
});
