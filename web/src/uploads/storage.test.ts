import { expect, it } from "vitest";
import { readUploads, writeUploads } from "./storage";

function saved() {
  return { id: "row-1", filename: "dojo.jpg", size: 3, contentType: "image/jpeg", lastModified: 1,
    identity: { chunkBytes: 2097152, chunkHashes: ["a".repeat(64)], fingerprint: "b".repeat(64) },
    status: { upload_id: "upload-1", declared_size_bytes: 3, received_bytes: 1, received_ranges: [[0, 1]], status: "receiving", error_reason: null, conflicts: [] } };
}

it("roundtrips metadata only and isolates clients", () => {
  localStorage.clear();
  const record = { ...saved(), file: new File(["abc"], "dojo.jpg"), token: "secret" };
  expect(writeUploads(localStorage, 1, [record])).toBe(true);
  expect(readUploads(localStorage, 1)).toEqual({ available: true, records: [saved()] });
  expect(readUploads(localStorage, 2).records).toEqual([]);
  const stored = localStorage.getItem("aisomedo.uploads.v1:1")!;
  expect(stored).not.toContain("secret");
  expect(stored).not.toContain('"file"');
});

it.each([
  "{", JSON.stringify({ version: 2, records: [saved()] }), JSON.stringify({ version: 1, records: "oops" }),
  ...[
    { size: -1 }, { size: Number.MAX_SAFE_INTEGER + 1 }, { lastModified: "invalid" }, { filename: 42 },
    { identity: { ...saved().identity, chunkBytes: 1024 } },
    { identity: { ...saved().identity, chunkHashes: [] } },
    { identity: { ...saved().identity, fingerprint: "bad" } },
    { status: { ...saved().status, received_bytes: 4 } },
    { status: { ...saved().status, received_ranges: [[-1, 0]] } },
    { status: { ...saved().status, received_ranges: [[0, 2], [1, 3]], received_bytes: 4 } },
    { status: { ...saved().status, status: "unknown" } },
  ].map(change => JSON.stringify({ version: 1, records: [{ ...saved(), ...change }] })),
])("ignores malformed records %s", raw => {
  expect(readUploads({ getItem: () => raw }, 1)).toEqual({ available: true, records: [] });
});

it("deduplicates row and upload IDs", () => {
  const first = saved();
  const raw = JSON.stringify({ version: 1, records: [first, first, { ...first, id: "row-2" }] });
  expect(readUploads({ getItem: () => raw }, 1).records).toEqual([first]);
});

it("does not restore or persist finalized uploads while keeping unfinished metadata", () => {
  const finalized = { ...saved(), status: { ...saved().status, status: "finalized" } };
  const unfinished = { ...saved(), id: "row-2", status: { ...saved().status, upload_id: "upload-2" } };
  const raw = JSON.stringify({ version: 1, records: [finalized, unfinished] });
  expect(readUploads({ getItem: () => raw }, 1).records).toEqual([unfinished]);
  expect(writeUploads(localStorage, 1, [finalized, unfinished])).toBe(true);
  expect(JSON.parse(localStorage.getItem("aisomedo.uploads.v1:1")!).records).toEqual([unfinished]);
});

it("handles unavailable storage without throwing", () => {
  expect(readUploads({ getItem: () => { throw Error("blocked"); } }, 1)).toEqual({ available: false, records: [] });
  expect(writeUploads({ setItem: () => { throw Error("quota"); } }, 1, [saved()])).toBe(false);
});
