import { ApiError } from "../api/client";
import type { UploadOut } from "../api/openapi";
import { checkAbort } from "./identity";
import { assertUploadStatus } from "./status";
import { CHUNK_BYTES, UploadFlowError, type FileIdentity, type UploadTransport } from "./types";

function covered(status: UploadOut, start: number, end: number): boolean {
  return status.received_ranges.some(range => range[0] <= start && range[1] >= end);
}

export async function transferUpload(
  file: File, identity: FileIdentity, initial: UploadOut, transport: Pick<UploadTransport, "status" | "range" | "complete">,
  signal: AbortSignal, onStatus: (status: UploadOut) => void,
): Promise<UploadOut> {
  checkAbort(signal);
  assertUploadStatus(initial, file.size);
  if (identity.chunkBytes !== CHUNK_BYTES || identity.chunkHashes.length !== Math.ceil(file.size / CHUNK_BYTES))
    throw new UploadFlowError("invalid-response");
  const id = initial.upload_id;
  const accept = (value: UploadOut) => {
    checkAbort(signal);
    assertUploadStatus(value, file.size, id);
    onStatus(value);
    return value;
  };
  const read = async () => accept(await transport.status(id, signal));
  let current = await read();
  if (current.status !== "receiving") return current;

  for (let offset = 0, index = 0; offset < file.size; offset += CHUNK_BYTES, index++) {
    checkAbort(signal);
    const end = Math.min(file.size, offset + CHUNK_BYTES);
    if (covered(current, offset, end)) continue;
    let next: UploadOut;
    try {
      next = await transport.range(id, offset, identity.chunkHashes[index], file.slice(offset, end), signal);
    } catch (error) {
      checkAbort(signal);
      if (error instanceof ApiError && (error.status === 0 || error.status >= 500 || error.status === 409)) {
        current = await read();
        if (current.status !== "receiving") return current;
      }
      throw error;
    }
    checkAbort(signal);
    assertUploadStatus(next, file.size, id);
    if (next.status === "receiving" && (!covered(next, offset, end)
      || !current.received_ranges.every(range => covered(next, range[0], range[1]))))
      throw new UploadFlowError("invalid-response");
    current = accept(next);
    if (current.status !== "receiving") return current;
  }
  if (current.received_bytes !== file.size) throw new UploadFlowError("invalid-response");
  let completed: UploadOut;
  try { completed = await transport.complete(id, signal); }
  catch (error) {
    checkAbort(signal);
    if (error instanceof ApiError && (error.status === 0 || error.status >= 500 || error.status === 409)) {
      current = await read();
      if (current.status !== "receiving") return current;
    }
    throw error;
  }
  completed = accept(completed);
  if (completed.status === "receiving") throw new UploadFlowError("invalid-response");
  return completed;
}
