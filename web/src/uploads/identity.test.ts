import { createHash } from "node:crypto";
import { expect, it, vi } from "vitest";
import { fingerprintFile } from "./identity";

function cryptoFixture() {
  const digest = vi.fn(async (_algorithm: string, input: ArrayBuffer | Uint8Array) => {
    const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
    return Uint8Array.from(createHash("sha256").update(bytes).digest()).buffer;
  });
  vi.stubGlobal("crypto", { subtle: { digest } });
  return digest;
}

it("hashes only bounded slices with correct SHA-256", async () => {
  const digest = cryptoFixture();
  const file = new File([new Uint8Array(2 * 1024 * 1024), "abc"], "dojo.mp4");
  const slice = vi.spyOn(file, "slice");
  const identity = await fingerprintFile(file, new AbortController().signal);
  expect(slice.mock.calls.map(([start, end]) => [start, end])).toEqual([[0, 2097152], [2097152, 2097155]]);
  expect(identity.chunkHashes).toHaveLength(2);
  expect(identity.chunkHashes[1]).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  expect(digest.mock.calls.every(call => call[1].byteLength <= 2097152)).toBe(true);
});

it("same content matches regardless of modification time", async () => {
  cryptoFixture();
  const first = await fingerprintFile(new File(["abc"], "a.jpg", { lastModified: 1 }), new AbortController().signal);
  const second = await fingerprintFile(new File(["abc"], "a.jpg", { lastModified: 2 }), new AbortController().signal);
  expect(first).toEqual(second);
});

it("same name and size with changed content differs", async () => {
  cryptoFixture();
  const first = await fingerprintFile(new File(["abc"], "a.jpg"), new AbortController().signal);
  const second = await fingerprintFile(new File(["abd"], "a.jpg"), new AbortController().signal);
  expect(first.fingerprint).not.toBe(second.fingerprint);
});

it("cancel during digest stops later slices and progress", async () => {
  const controller = new AbortController();
  vi.stubGlobal("crypto", { subtle: { digest: async () => { controller.abort(); return new ArrayBuffer(32); } } });
  const file = new File([new Uint8Array(2097153)], "a.mp4");
  const slice = vi.spyOn(file, "slice");
  const progress = vi.fn();
  await expect(fingerprintFile(file, controller.signal, progress)).rejects.toMatchObject({ name: "AbortError" });
  expect(slice).toHaveBeenCalledTimes(1);
  expect(progress).not.toHaveBeenCalled();
});

it("missing crypto is actionable", async () => {
  vi.stubGlobal("crypto", {});
  await expect(fingerprintFile(new File(["a"], "a.jpg"), new AbortController().signal)).rejects.toMatchObject({ code: "hash-unavailable" });
});
