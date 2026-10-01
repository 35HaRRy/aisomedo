import { CHUNK_BYTES, UploadFlowError, type FileIdentity } from "./types";

export function checkAbort(signal: AbortSignal): void {
  if (signal.aborted) throw new DOMException("", "AbortError");
}

function readSlice(blob: Blob, signal: AbortSignal): Promise<ArrayBuffer> {
  checkAbort(signal);
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const cancel = () => reader.abort();
    const cleanup = () => signal.removeEventListener("abort", cancel);
    reader.onload = () => { cleanup(); resolve(reader.result as ArrayBuffer); };
    reader.onerror = () => { cleanup(); reject(new UploadFlowError("hash-unavailable")); };
    reader.onabort = () => { cleanup(); reject(new DOMException("", "AbortError")); };
    signal.addEventListener("abort", cancel, { once: true });
    reader.readAsArrayBuffer(blob);
  });
}

export async function fingerprintFile(file: File, signal: AbortSignal, onProgress?: (bytes: number) => void): Promise<FileIdentity> {
  checkAbort(signal);
  if (!globalThis.crypto?.subtle) throw new UploadFlowError("hash-unavailable");
  const hash = async (bytes: ArrayBuffer | Uint8Array<ArrayBuffer>) => {
    let digest: ArrayBuffer;
    try { digest = await crypto.subtle.digest("SHA-256", bytes); }
    catch { checkAbort(signal); throw new UploadFlowError("hash-unavailable"); }
    checkAbort(signal);
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  };
  const chunkHashes: string[] = [];
  for (let offset = 0; offset < file.size; offset += CHUNK_BYTES) {
    checkAbort(signal);
    const end = Math.min(offset + CHUNK_BYTES, file.size);
    chunkHashes.push(await hash(await readSlice(file.slice(offset, end), signal)));
    onProgress?.(end);
  }
  const descriptor = new TextEncoder().encode(JSON.stringify({ chunkBytes: CHUNK_BYTES, size: file.size, chunkHashes }));
  return { chunkBytes: CHUNK_BYTES, chunkHashes, fingerprint: await hash(descriptor) };
}
