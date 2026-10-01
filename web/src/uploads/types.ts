import type { UploadInitIn, UploadLimitsOut, UploadOut } from "../api/openapi";

export const CHUNK_BYTES = 2 * 1024 * 1024;
export interface FileIdentity { chunkBytes: number; chunkHashes: string[]; fingerprint: string }
export type UploadPhase = "preparing" | "waiting" | "uploading" | "paused" | "needs-file" | "retryable" | "queued" | "processing" | "finalized" | "failed" | "conflict" | "expired";
export type UploadErrorCode = "network" | "server" | "empty" | "oversize" | "capacity" | "checksum" | "wrong-file" | "hash-unavailable" | "expired" | "conflict" | "invalid-response";
export class UploadFlowError extends Error {
  constructor(public readonly code: UploadErrorCode, public readonly diagnostic?: string) { super(code); }
}
export interface SavedUpload {
  id: string;
  filename: string;
  size: number;
  contentType: string;
  lastModified: number;
  identity: FileIdentity;
  status: UploadOut | null;
}
export interface UploadRow extends Omit<SavedUpload, "identity"> {
  identity: FileIdentity | null;
  phase: UploadPhase;
  preparedBytes: number;
  error: UploadErrorCode | null;
  diagnostic: string | null;
}
export interface UploadTransport {
  limits(signal: AbortSignal): Promise<UploadLimitsOut>;
  start(body: UploadInitIn, signal: AbortSignal): Promise<UploadOut>;
  status(id: string, signal: AbortSignal): Promise<UploadOut>;
  range(id: string, offset: number, checksum: string, body: Blob, signal: AbortSignal): Promise<UploadOut>;
  complete(id: string, signal: AbortSignal): Promise<UploadOut>;
}
