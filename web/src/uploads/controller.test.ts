import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { createUploadController } from "./controller";
import { deferred, installCrypto, uploadServer } from "./testFixtures";
import type { UploadOut } from "../api/openapi";

beforeEach(() => { localStorage.clear(); installCrypto(); });

async function fixture(storage: Storage | null = localStorage, conflicts = false) {
  const server = uploadServer({ conflicts });
  const onUnauthorized = vi.fn();
  const onPackageChanged = vi.fn();
  const options = { clientId: 1, transport: server.transport, storage, onUnauthorized, onPackageChanged };
  const controller = createUploadController(options);
  await controller.initialize(new AbortController().signal);
  return { ...server, controller, options, onUnauthorized, onPackageChanged };
}
const file = (content = "abc", time = 1) => new File([content], "dojo.jpg", { type: "image/jpeg", lastModified: time });

it("oversize or empty has no start or hash", async () => {
  const digest = installCrypto();
  const f = await fixture();
  f.transport.limits.mockResolvedValue({ max_file_bytes: 2, max_package_bytes: 100 });
  await f.controller.initialize(new AbortController().signal);
  await f.controller.add([file(), file("")]);
  expect(f.controller.getSnapshot().rows.map(row => row.error)).toEqual(["oversize", "empty"]);
  expect(f.transport.start).not.toHaveBeenCalled();
  expect(digest).not.toHaveBeenCalled();
});

it("limits failure blocks add and can reload", async () => {
  const f = await fixture();
  f.transport.limits.mockRejectedValueOnce(new ApiError(0));
  await f.controller.initialize(new AbortController().signal);
  expect(f.controller.getSnapshot().limitsError).toBe(true);
  await f.controller.add([file()]);
  expect(f.transport.start).not.toHaveBeenCalled();
  await f.controller.initialize(new AbortController().signal);
  await f.controller.add([file()]);
  expect(f.controller.getSnapshot().rows.some(row => row.phase === "queued")).toBe(true);
});

it.each([[413, undefined, "oversize"], [409, "package limit 100 would be exceeded", "capacity"]] as const)("capacity rejection %i sends no ranges", async (code, detail, expected) => {
  const f = await fixture();
  f.transport.start.mockRejectedValue(new ApiError(code, detail));
  await f.controller.add([file()]);
  expect(f.controller.getSnapshot().rows[0].error).toBe(expected);
  expect(f.transport.range).not.toHaveBeenCalled();
});

it("files transfer sequentially and pause releases next row", async () => {
  const f = await fixture();
  const pending = deferred<UploadOut>();
  f.transport.range.mockImplementationOnce(() => pending.promise);
  const work = f.controller.add([file(), new File(["next"], "second.jpg")]);
  await vi.waitFor(() => expect(f.transport.range).toHaveBeenCalledTimes(1));
  expect(f.transport.start).toHaveBeenCalledTimes(1);
  const first = f.controller.getSnapshot().rows[0];
  f.controller.pause(first.id);
  await work;
  expect(f.controller.getSnapshot().rows.map(row => row.phase)).toEqual(["paused", "queued"]);
  pending.resolve({ ...f.records.get(first.status!.upload_id)!, received_bytes: 3, received_ranges: [[0, 3]] });
  await Promise.resolve();
  expect(f.controller.getSnapshot().rows[0].phase).toBe("paused");
});

it("lost initialization response sends no bytes and retries explicitly", async () => {
  const f = await fixture();
  f.transport.start.mockRejectedValueOnce(new ApiError(0));
  await f.controller.add([file()]);
  const row = f.controller.getSnapshot().rows[0];
  expect(row.phase).toBe("retryable");
  expect(row.status).toBeNull();
  expect(f.transport.range).not.toHaveBeenCalled();
  await f.controller.retry(row.id);
  expect(f.controller.getSnapshot().rows[0].phase).toBe("queued");
});

it("reload requires matching content and resumes same ID", async () => {
  const f = await fixture();
  f.transport.range.mockRejectedValueOnce(new ApiError(0));
  await f.controller.add([file()]);
  f.controller.dispose();
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  const row = next.getSnapshot().rows[0];
  expect(row.phase).toBe("needs-file");
  await next.resume(row.id, file("abd"));
  expect(next.getSnapshot().rows[0].error).toBe("wrong-file");
  expect(f.transport.range).toHaveBeenCalledTimes(1);
  await next.resume(row.id, file("abc", 9));
  expect(next.getSnapshot().rows[0].phase).toBe("queued");
  expect(f.transport.start).toHaveBeenCalledTimes(1);
  expect(f.transport.range.mock.calls.map(call => call[0])).toEqual(["upload-1", "upload-1"]);
});

it("queued reload polls without file and terminal state cannot regress", async () => {
  const f = await fixture();
  await f.controller.add([file()]);
  f.controller.dispose();
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  const status = f.records.get("upload-1")!;
  f.records.set("upload-1", { ...status, status: "finalized" });
  await next.refresh(new AbortController().signal);
  expect(next.getSnapshot().rows[0].phase).toBe("finalized");
  f.records.set("upload-1", { ...status, status: "receiving" });
  await next.refresh(new AbortController().signal);
  expect(next.getSnapshot().rows[0].phase).toBe("finalized");
  expect(f.onPackageChanged).toHaveBeenCalledTimes(2);
  next.dismiss(next.getSnapshot().rows[0].id);
  expect(JSON.parse(localStorage.getItem("aisomedo.uploads.v1:1")!).records).toEqual([]);
});

it("worker failure retains diagnostic and new attempt is explicit", async () => {
  const f = await fixture();
  await f.controller.add([file()]);
  f.records.set("upload-1", { ...f.records.get("upload-1")!, status: "failed", error_reason: "invalid JPEG" });
  await f.controller.refresh(new AbortController().signal);
  const row = f.controller.getSnapshot().rows[0];
  expect(row.phase).toBe("failed");
  expect(row.diagnostic).toBe("invalid JPEG");
  await f.controller.resume(row.id);
  expect(f.transport.start).toHaveBeenCalledTimes(1);
  await f.controller.retry(row.id, file("valid"));
  expect(f.transport.start).toHaveBeenCalledTimes(2);
});

it("expired upload requires explicit fresh attempt", async () => {
  const f = await fixture();
  f.transport.range.mockRejectedValueOnce(new ApiError(0));
  await f.controller.add([file()]);
  f.transport.status.mockRejectedValueOnce(new ApiError(404));
  const row = f.controller.getSnapshot().rows[0];
  await f.controller.resume(row.id);
  expect(f.controller.getSnapshot().rows[0].phase).toBe("expired");
  expect(f.transport.start).toHaveBeenCalledTimes(1);
  await f.controller.retry(row.id);
  expect(f.transport.start).toHaveBeenCalledTimes(2);
});

it("filename conflict blocks transfer and retries", async () => {
  const f = await fixture();
  f.transport.start.mockImplementationOnce(async body => ({ upload_id: "conflict", declared_size_bytes: body.declared_size_bytes, received_bytes: 0, received_ranges: [], status: "conflict", conflicts: [], error_reason: null }));
  await f.controller.add([file()]);
  const row = f.controller.getSnapshot().rows[0];
  expect(row.phase).toBe("conflict");
  await f.controller.retry(row.id);
  expect(f.transport.start).toHaveBeenCalledTimes(1);
  expect(f.transport.range).not.toHaveBeenCalled();
});

it("keep both resumes retained file under original upload ID", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file()]);
  const row = f.controller.getSnapshot().rows[0];
  await f.controller.resolve(row.id, { decision: "keep_both" });
  expect(f.controller.getSnapshot().rows[0].phase).toBe("queued");
  expect(f.transport.start).toHaveBeenCalledTimes(1);
  expect(f.transport.range.mock.calls[0][0]).toBe("upload-1");
});

it("keep existing is skipped, not expired, including after reload", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file()]);
  await f.controller.resolve(f.controller.getSnapshot().rows[0].id, { decision: "keep_target" });
  expect(f.controller.getSnapshot().rows[0].phase).toBe("skipped");
  f.controller.dispose();
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  expect(next.getSnapshot().rows[0].phase).toBe("skipped");
  await next.retry(next.getSnapshot().rows[0].id);
  expect(f.transport.start).toHaveBeenCalledTimes(1);
  expect(f.transport.range).not.toHaveBeenCalled();
});

it("bulk resolution reconciles each upload ID and leaves incompatible conflict untouched", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file(), new File(["second"], "DOJO.JPG"), new File(["other"], "other.jpg")]);
  await f.controller.resolve(f.controller.getSnapshot().rows[0].id, { decision: "keep_both", apply_to_all: true });
  expect(f.controller.getSnapshot().rows.map(row => row.phase)).toEqual(["queued", "queued", "conflict"]);
  expect(f.transport.range.mock.calls.map(call => call[0])).toEqual(["upload-1", "upload-2"]);
});

it("restored conflict resolves without bytes until original file is reselected", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file()]);
  f.controller.dispose();
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  const row = next.getSnapshot().rows[0];
  await next.resolve(row.id, { decision: "keep_both" });
  expect(next.getSnapshot().rows[0].phase).toBe("needs-file");
  expect(f.transport.range).not.toHaveBeenCalled();
  await next.resume(row.id, file());
  expect(next.getSnapshot().rows[0].phase).toBe("queued");
});

it("overwrite requires explicit confirmation and a valid target before transport", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file()]);
  const row = f.controller.getSnapshot().rows[0];
  await f.controller.resolve(row.id, { decision: "keep_selected", target_media_id: "dojo.jpg" });
  await f.controller.resolve(row.id, { decision: "keep_selected", target_media_id: "unknown", confirmed_overwrite: true });
  expect(f.transport.resolve).not.toHaveBeenCalled();
  await f.controller.resolve(row.id, { decision: "keep_selected", target_media_id: "dojo.jpg", confirmed_overwrite: true });
  expect(f.controller.getSnapshot().rows[0].phase).toBe("queued");
});

it("lost resolution response reconciles server state without repeating overwrite", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file()]);
  f.transport.resolve.mockImplementationOnce(async id => {
    f.records.set(id, { ...f.records.get(id)!, status: "receiving", conflicts: [] });
    throw new ApiError(0);
  });
  await f.controller.resolve(f.controller.getSnapshot().rows[0].id, { decision: "keep_both" });
  expect(f.controller.getSnapshot().rows[0].phase).toBe("queued");
  expect(f.transport.resolve).toHaveBeenCalledTimes(1);
});

it("resolution is single-flight and ignores results after disposal", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file()]);
  const pending = deferred<UploadOut>();
  f.transport.resolve.mockImplementationOnce(() => pending.promise);
  const row = f.controller.getSnapshot().rows[0];
  const first = f.controller.resolve(row.id, { decision: "keep_both" });
  await f.controller.resolve(row.id, { decision: "keep_target" });
  expect(f.transport.resolve).toHaveBeenCalledTimes(1);
  f.controller.dispose();
  pending.resolve({ ...row.status!, status: "receiving" });
  await first;
  expect(f.controller.getSnapshot().rows).toEqual([]);
  expect(f.transport.range).not.toHaveBeenCalled();
});

it("401 during resolution clears uploads and invalidates session", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file()]);
  f.transport.resolve.mockRejectedValueOnce(new ApiError(401));
  await f.controller.resolve(f.controller.getSnapshot().rows[0].id, { decision: "keep_target" });
  expect(f.onUnauthorized).toHaveBeenCalledTimes(1);
  expect(f.controller.getSnapshot().rows).toEqual([]);
});

it("bulk resolution never resumes a different filename resolved by another client", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file(), new File(["other"], "other.jpg")]);
  // Another client resolves unrelated upload between this browser's last read and decision.
  f.records.set("upload-2", { ...f.records.get("upload-2")!, status: "receiving", conflicts: [] });
  await f.controller.resolve(f.controller.getSnapshot().rows[0].id, { decision: "keep_target", apply_to_all: true });
  expect(f.controller.getSnapshot().rows[0].phase).toBe("skipped");
  expect(f.transport.range).not.toHaveBeenCalled();
  expect(f.transport.status.mock.calls.map(call => call[0])).toEqual(["upload-1"]);
});

it("keep existing intent survives a failed reconciliation and reload", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file()]);
  f.transport.status.mockRejectedValueOnce(new ApiError(0));
  await f.controller.resolve(f.controller.getSnapshot().rows[0].id, { decision: "keep_target" });
  f.controller.dispose();
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  expect(next.getSnapshot().rows[0].phase).toBe("skipped");
  expect(f.transport.resolve).toHaveBeenCalledTimes(1);
  expect(f.transport.range).not.toHaveBeenCalled();
});

it("bulk resolution invalidates older conflict polls before reconciling every compatible ID", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file(), file("second")]);
  const stale = deferred<UploadOut>();
  const oldStatus = structuredClone(f.records.get("upload-1")!);
  f.transport.status.mockImplementationOnce(() => stale.promise);
  const polling = f.controller.refresh(new AbortController().signal);
  const decision = f.controller.resolve(f.controller.getSnapshot().rows[1].id, { decision: "keep_both", apply_to_all: true });
  // Late response was captured before resolution; it must not overwrite fresh state.
  stale.resolve(oldStatus);
  await Promise.all([polling, decision]);
  expect(f.controller.getSnapshot().rows.map(row => row.phase)).toEqual(["queued", "queued"]);
  expect(f.transport.range.mock.calls.map(call => call[0])).toEqual(["upload-1", "upload-2"]);
});

it("bulk recovers missing conflict metadata after partially failed reload", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file(), file("second")]);
  f.controller.dispose();
  f.transport.status.mockResolvedValueOnce(f.records.get("upload-1")!).mockRejectedValueOnce(new ApiError(0));
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  expect(next.getSnapshot().rows[1].status?.conflicts).toEqual([]);
  await next.resolve(next.getSnapshot().rows[0].id, { decision: "keep_target", apply_to_all: true });
  await next.refresh(new AbortController().signal);
  expect(next.getSnapshot().rows.map(row => row.phase)).toEqual(["skipped", "skipped"]);
});

it("bulk refuses to send decision while another conflict's metadata remains unavailable", async () => {
  const f = await fixture(localStorage, true);
  await f.controller.add([file(), file("second")]);
  f.controller.dispose();
  f.transport.status.mockResolvedValueOnce(f.records.get("upload-1")!).mockRejectedValueOnce(new ApiError(0));
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  f.transport.status.mockRejectedValueOnce(new ApiError(0));
  await next.resolve(next.getSnapshot().rows[0].id, { decision: "keep_target", apply_to_all: true });
  expect(f.transport.resolve).not.toHaveBeenCalled();
  expect(next.getSnapshot().resolvingId).toBeNull();
  expect(next.getSnapshot().rows[0].error).toBe("network");
  await next.resolve(next.getSnapshot().rows[0].id, { decision: "keep_target", apply_to_all: true });
  expect(next.getSnapshot().rows.map(row => row.phase)).toEqual(["skipped", "skipped"]);
});

it("storage failures preserve in-memory transfer but report unavailable recovery", async () => {
  const f = await fixture();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw Error("quota"); });
  await f.controller.add([file()]);
  expect(f.controller.getSnapshot().storageAvailable).toBe(false);
  expect(f.controller.getSnapshot().rows[0].phase).toBe("queued");
});

it("dispose during PUT ignores late results and writes", async () => {
  const f = await fixture();
  const pending = deferred<Awaited<ReturnType<typeof f.transport.range>>>();
  f.transport.range.mockImplementationOnce(() => pending.promise);
  const work = f.controller.add([file()]);
  await vi.waitFor(() => expect(f.transport.range).toHaveBeenCalled());
  f.controller.dispose();
  const stored = localStorage.getItem("aisomedo.uploads.v1:1");
  pending.resolve({ ...f.records.get("upload-1")!, received_bytes: 3, received_ranges: [[0, 3]] });
  await work;
  expect(f.transport.complete).not.toHaveBeenCalled();
  expect(localStorage.getItem("aisomedo.uploads.v1:1")).toBe(stored);
  expect(f.controller.getSnapshot().rows).toEqual([]);
});

it.each(["limits", "start", "status", "range", "complete"] as const)("401 during %s invalidates and clears work", async operation => {
  const f = await fixture();
  f.transport[operation].mockRejectedValue(new ApiError(401));
  if (operation === "limits") await f.controller.initialize(new AbortController().signal);
  else await f.controller.add([file()]);
  expect(f.onUnauthorized).toHaveBeenCalledTimes(1);
  expect(f.controller.getSnapshot().rows).toEqual([]);
});

it("bad restored size is actionable and refresh is single-flight", async () => {
  const f = await fixture();
  await f.controller.add([file()]);
  const pending = deferred<Awaited<ReturnType<typeof f.transport.status>>>();
  f.transport.status.mockImplementationOnce(() => pending.promise);
  const first = f.controller.refresh(new AbortController().signal);
  const second = f.controller.refresh(new AbortController().signal);
  pending.resolve({ ...f.records.get("upload-1")!, declared_size_bytes: 99 });
  await Promise.all([first, second]);
  expect(f.controller.getSnapshot().rows[0].error).toBe("invalid-response");
  expect(f.transport.status).toHaveBeenCalledTimes(2);
});

it("restored no-ID metadata requires explicit matching file before new init", async () => {
  const f = await fixture();
  f.transport.start.mockRejectedValueOnce(new ApiError(0));
  await f.controller.add([file()]);
  f.controller.dispose();
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  const row = next.getSnapshot().rows[0];
  expect(row.phase).toBe("needs-file");
  await next.resume(row.id);
  expect(f.transport.start).toHaveBeenCalledTimes(1);
  await next.resume(row.id, file());
  expect(next.getSnapshot().rows[0].phase).toBe("queued");
});

it("blocked storage read does not prevent in-memory uploads", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw Error("blocked"); });
  const f = await fixture();
  await f.controller.add([file()]);
  expect(f.controller.getSnapshot().storageAvailable).toBe(false);
  expect(f.controller.getSnapshot().rows[0].phase).toBe("queued");
});

it("dispose during preparation releases scheduler and ignores digest", async () => {
  const f = await fixture();
  const pending = deferred<ArrayBuffer>();
  const digest = vi.fn(() => pending.promise);
  vi.stubGlobal("crypto", { randomUUID: () => "row", subtle: { digest } });
  const work = f.controller.add([file()]);
  await vi.waitFor(() => expect(digest).toHaveBeenCalled());
  f.controller.dispose();
  await work;
  pending.resolve(new ArrayBuffer(32));
  await Promise.resolve();
  expect(f.transport.start).not.toHaveBeenCalled();
  expect(f.controller.getSnapshot().rows).toEqual([]);
});

it("failed first row and duplicate resume do not block or duplicate next", async () => {
  const f = await fixture();
  f.transport.start.mockRejectedValueOnce(new ApiError(0));
  const pending = deferred<UploadOut>();
  f.transport.range.mockImplementationOnce(() => pending.promise);
  const work = f.controller.add([file(), new File(["next"], "second.jpg")]);
  await vi.waitFor(() => expect(f.transport.range).toHaveBeenCalledTimes(1));
  const row = f.controller.getSnapshot().rows[1];
  await Promise.all([f.controller.resume(row.id), f.controller.retry(row.id)]);
  expect(f.transport.range).toHaveBeenCalledTimes(1);
  pending.resolve({ ...f.records.get("upload-1")!, received_bytes: 4, received_ranges: [[0, 4]] });
  await work;
  expect(f.controller.getSnapshot().rows.map(row => row.phase)).toEqual(["retryable", "queued"]);
});

it("finalized state cannot regress during limits reinitialization", async () => {
  const f = await fixture();
  await f.controller.add([file()]);
  const status = f.records.get("upload-1")!;
  f.records.set("upload-1", { ...status, status: "finalized" });
  await f.controller.refresh(new AbortController().signal);
  f.records.set("upload-1", { ...status, status: "receiving" });
  await f.controller.initialize(new AbortController().signal);
  expect(f.controller.getSnapshot().rows[0].phase).toBe("finalized");
});

it("explicit failed retry without retained file accepts new media reselection", async () => {
  const f = await fixture();
  await f.controller.add([file()]);
  f.records.set("upload-1", { ...f.records.get("upload-1")!, status: "failed", error_reason: "invalid JPEG" });
  f.controller.dispose();
  const next = createUploadController(f.options);
  await next.initialize(new AbortController().signal);
  const row = next.getSnapshot().rows[0];
  await next.retry(row.id);
  expect(next.getSnapshot().rows[0].phase).toBe("needs-file");
  await next.resume(row.id, file("valid"));
  expect(next.getSnapshot().rows[0].phase).toBe("queued");
  expect(f.transport.start).toHaveBeenCalledTimes(2);
});

it("missing crypto yields actionable row instead of crashing selection", async () => {
  const f = await fixture();
  vi.stubGlobal("crypto", {});
  await f.controller.add([file()]);
  expect(f.controller.getSnapshot().rows[0].error).toBe("hash-unavailable");
  expect(f.transport.start).not.toHaveBeenCalled();
});

it("fresh retry keeps another explicitly resumed row eligible behind active upload", async () => {
  const f = await fixture();
  f.transport.start.mockRejectedValueOnce(new ApiError(0));
  await f.controller.add([new File(["fresh"], "fresh.jpg")]);
  f.transport.range.mockRejectedValueOnce(new ApiError(0));
  await f.controller.add([new File(["resume"], "resume.jpg")]);
  const pending = deferred<UploadOut>();
  f.transport.range.mockImplementationOnce(() => pending.promise);
  const active = f.controller.add([new File(["active"], "active.jpg")]);
  await vi.waitFor(() => expect(f.controller.getSnapshot().rows[2].phase).toBe("uploading"));
  const [fresh, resumed] = f.controller.getSnapshot().rows;
  const resume = f.controller.resume(resumed.id);
  const retry = f.controller.retry(fresh.id);
  await vi.waitFor(() => expect(f.controller.getSnapshot().rows[0].phase).toBe("waiting"));
  pending.resolve({ ...f.records.get("upload-2")!, received_bytes: 6, received_ranges: [[0, 6]] });
  await Promise.all([active, resume, retry]);
  expect(f.controller.getSnapshot().rows.map(row => row.phase)).toEqual(["queued", "queued", "queued"]);
  expect(f.transport.range.mock.calls.map(call => call[0])).toEqual(["upload-1", "upload-2", "upload-1", "upload-3"]);
});

it("failed status survives restored status-read network error and remains fresh-retryable", async () => {
  const f = await fixture();
  await f.controller.add([file()]);
  f.records.set("upload-1", { ...f.records.get("upload-1")!, status: "failed", error_reason: "invalid JPEG" });
  await f.controller.refresh(new AbortController().signal);
  f.controller.dispose();
  const next = createUploadController(f.options);
  f.transport.status.mockRejectedValueOnce(new ApiError(0));
  await next.initialize(new AbortController().signal);
  const row = next.getSnapshot().rows[0];
  expect(row.phase).toBe("failed");
  expect(row.diagnostic).toBe("invalid JPEG");
  expect(row.error).toBe("network");
  await next.retry(row.id, file("valid"));
  expect(next.getSnapshot().rows[0].phase).toBe("queued");
  expect(f.transport.start).toHaveBeenCalledTimes(2);
});
