import { expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { UploadOut } from "../api/openapi";
import { transferUpload } from "./transfer";
import { CHUNK_BYTES } from "./types";

function status(size: number, received = 0, state = "receiving"): UploadOut {
  return { upload_id: "upload-1", declared_size_bytes: size, received_bytes: received,
    received_ranges: received ? [[0, received]] : [], status: state, error_reason: null, conflicts: [] };
}
function fixture(size = 3) {
  const file = new File([new Uint8Array(size)], "dojo.mp4");
  const initial = status(size);
  let current = initial;
  const transport = {
    limits: vi.fn(async () => ({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 })),
    start: vi.fn(async () => initial),
    status: vi.fn(async () => current),
    range: vi.fn(async (_id: string, offset: number, _hash: string, body: Blob, _signal: AbortSignal) => {
      current = status(size, Math.max(current.received_bytes, offset + body.size)); return current;
    }),
    complete: vi.fn(async () => { current = status(size, size, "queued"); return current; }),
  };
  return { file, initial, transport, changed: vi.fn(),
    identity: { chunkBytes: CHUNK_BYTES, chunkHashes: Array.from({ length: Math.ceil(size / CHUNK_BYTES) }, (_, i) => String(i).repeat(64)), fingerprint: "a".repeat(64) },
    set: (value: UploadOut) => { current = value; } };
}

it("skips confirmed chunks and retransmits partial chunks", async () => {
  const f = fixture(3 * CHUNK_BYTES);
  f.set(status(f.file.size, CHUNK_BYTES + 10));
  const result = await transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed);
  expect(f.transport.range.mock.calls.map(call => call[1])).toEqual([2097152, 4194304]);
  expect(f.transport.range.mock.calls.map(call => call[2])).toEqual(["1".repeat(64), "2".repeat(64)]);
  expect(f.transport.complete).toHaveBeenCalledTimes(1);
  expect(result.status).toBe("queued");
  expect(f.changed.mock.calls.slice(-1)[0]?.[0].received_bytes).toBe(6291456);
});

it("lost PUT response reconciles then explicit retry skips stored bytes", async () => {
  const f = fixture(CHUNK_BYTES + 3);
  f.transport.range.mockImplementationOnce(async () => { f.set(status(f.file.size, CHUNK_BYTES)); throw new ApiError(0); });
  await expect(transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed)).rejects.toMatchObject({ status: 0 });
  expect(f.changed.mock.calls.slice(-1)[0]?.[0].received_bytes).toBe(2097152);
  await transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed);
  expect(f.transport.range.mock.calls.map(call => [call[0], call[1], call[3].size])).toEqual([["upload-1", 0, 2097152], ["upload-1", 2097152, 3]]);
  expect(f.transport.start).not.toHaveBeenCalled();
});

it.each([0, 409])("lost/conflicting complete %i recognizes accepted completion", async code => {
  const f = fixture();
  f.transport.complete.mockImplementation(async () => { f.set(status(3, 3, code ? "finalized" : "queued")); throw new ApiError(code); });
  const result = await transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed);
  expect(result.status).toBe(code ? "finalized" : "queued");
  await transferUpload(f.file, f.identity, result, f.transport, new AbortController().signal, f.changed);
  expect(f.transport.complete).toHaveBeenCalledTimes(1);
  expect(f.transport.start).not.toHaveBeenCalled();
});

it("complete still receiving fails without looping", async () => {
  const f = fixture();
  f.transport.complete.mockRejectedValue(new ApiError(409));
  await expect(transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed)).rejects.toMatchObject({ status: 409 });
  expect(f.transport.complete).toHaveBeenCalledTimes(1);
});

it("pause while PUT completes ignores late response and next chunk", async () => {
  const f = fixture(CHUNK_BYTES + 1);
  const cancel = new AbortController();
  f.transport.range.mockImplementationOnce(async () => { cancel.abort(); return status(f.file.size, CHUNK_BYTES); });
  await expect(transferUpload(f.file, f.identity, f.initial, f.transport, cancel.signal, f.changed)).rejects.toMatchObject({ name: "AbortError" });
  expect(f.changed).toHaveBeenCalledTimes(1);
  expect(f.transport.range).toHaveBeenCalledTimes(1);
  expect(f.transport.complete).not.toHaveBeenCalled();
});

it.each(["conflict", "failed", "aborted"])("non-receiving %s sends no chunks", async state => {
  const f = fixture();
  f.set(status(3, 0, state));
  expect((await transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed)).status).toBe(state);
  expect(f.transport.range).not.toHaveBeenCalled();
  expect(f.transport.complete).not.toHaveBeenCalled();
});

it.each([
  { upload_id: "another" }, { declared_size_bytes: 4 }, { received_ranges: [[-1, 0]] },
  { received_ranges: [[0, 4]], received_bytes: 4 }, { status: "unknown" },
  { received_ranges: [[0, 1]], received_bytes: 2 },
])("invalid response stops safely %j", async change => {
  const f = fixture();
  f.set({ ...status(3), ...change });
  await expect(transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed)).rejects.toMatchObject({ code: "invalid-response" });
  expect(f.changed).not.toHaveBeenCalled();
  expect(f.transport.range).not.toHaveBeenCalled();
});

it("nonadvancing acknowledgement stops safely", async () => {
  const f = fixture();
  f.transport.range.mockResolvedValue(status(3));
  await expect(transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed)).rejects.toMatchObject({ code: "invalid-response" });
  expect(f.transport.complete).not.toHaveBeenCalled();
});

it.each([401, 404, 400])("definite HTTP error %i is not hidden by reconciliation", async code => {
  const f = fixture();
  f.transport.range.mockRejectedValue(new ApiError(code));
  await expect(transferUpload(f.file, f.identity, f.initial, f.transport, new AbortController().signal, f.changed)).rejects.toMatchObject({ status: code });
  expect(f.transport.status).toHaveBeenCalledTimes(1);
});
