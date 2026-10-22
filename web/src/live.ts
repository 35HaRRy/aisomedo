/** Foreground transport plus single-flight, event-triggered resource reads. */
import { responseVersions, SupersededRead } from "./api/client";
export type LivePhase = "connecting" | "syncing" | "sync-failed" | "live" | "disconnected" | "unauthorized";
type Frame = (event: string, data: unknown) => void;
const MAX_FRAME_BYTES = 64 * 1024;
const encoder = new TextEncoder();

export async function readSse(body: ReadableStream<Uint8Array>, frame: Frame, signal: AbortSignal): Promise<void> {
  const reader = body.getReader(), decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "", event = "message", data: string[] = [], bytes = 0;
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", cancel, { once: true });
  const line = (text: string, newlineBytes: number) => {
    bytes += encoder.encode(text).length + newlineBytes;
    if (bytes > MAX_FRAME_BYTES) throw new Error("SSE frame too large");
    if (!text) {
      if (data.length) frame(event, ["ready", "change", "resync", "heartbeat"].includes(event)
        ? JSON.parse(data.join("\n")) as unknown : data.join("\n"));
      event = "message"; data = []; bytes = 0; return;
    }
    if (text.startsWith(":")) return;
    const colon = text.indexOf(":"), field = colon < 0 ? text : text.slice(0, colon);
    let value = colon < 0 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  };
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let end: number;
      while ((end = buffer.search(/[\r\n]/)) >= 0) {
        if (!done && buffer[end] === "\r" && end === buffer.length - 1) break;
        const width = buffer[end] === "\r" && buffer[end + 1] === "\n" ? 2 : 1;
        line(buffer.slice(0, end), width); buffer = buffer.slice(end + width);
      }
      if (bytes + encoder.encode(buffer).length > MAX_FRAME_BYTES) throw new Error("SSE frame too large");
      if (done) {
        if (buffer || bytes || data.length) throw new Error("Incomplete SSE frame");
        return;
      }
    }
  } finally {
    signal.removeEventListener("abort", cancel);
    await reader.cancel().catch(() => {}); reader.releaseLock();
  }
}

type Consumer = {
  refresh(signal: AbortSignal): Promise<void>;
  resources: readonly string[];
  controller: AbortController | null;
  pending: boolean;
  synchronized: boolean;
  failed: boolean;
};
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const matches = (resources: readonly string[], key: string) => resources.some(resource => resource === key || resource.endsWith("*") && key.startsWith(resource.slice(0, -1)));

export class LiveCoordinator {
  private phase: LivePhase = "connecting";
  private listeners = new Set<() => void>();
  private consumers = new Set<Consumer>();
  private versions = new Map<string, number>();
  private controller: AbortController | null = null;
  private heartbeat: ReturnType<typeof setTimeout> | undefined;
  private reconnect: ReturnType<typeof setTimeout> | undefined;
  private ready = false;
  private running = false;
  private terminal = false;
  private attempt = 0;
  private epoch = 0;
  private owners = 0;

  constructor(private fetcher: (url: string, init: RequestInit) => Promise<Response> = (url, init) => fetch(url, init)) {}
  getSnapshot = (): LivePhase => this.phase;
  watch = (listener: () => void): (() => void) => {
    this.listeners.add(listener); return () => { this.listeners.delete(listener); };
  };
  private setPhase(phase: LivePhase) {
    if (this.phase === phase) return;
    this.phase = phase; this.listeners.forEach(listener => listener());
  }
  private synchronize() {
    if (this.ready) this.setPhase([...this.consumers].some(consumer => consumer.failed) ? "sync-failed"
      : [...this.consumers].every(consumer => consumer.synchronized) ? "live" : "syncing");
  }
  private available = () => !document.hidden && navigator.onLine;
  private deadline() {
    clearTimeout(this.heartbeat);
    this.heartbeat = setTimeout(() => this.disconnect(), 45000);
  }
  private disconnect(retry = true) {
    this.epoch++; this.ready = false;
    this.controller?.abort(); this.controller = null;
    clearTimeout(this.heartbeat); clearTimeout(this.reconnect); this.reconnect = undefined;
    for (const consumer of this.consumers) {
      consumer.controller?.abort(); consumer.synchronized = false; consumer.pending = true; consumer.failed = false;
    }
    this.setPhase("disconnected");
    if (retry && this.running && !this.terminal && this.available()) {
      const delay = Math.min(30000, 1000 * 2 ** Math.min(5, this.attempt++) * (0.8 + Math.random() * 0.4));
      this.reconnect = setTimeout(() => { this.reconnect = undefined; void this.connect(); }, delay);
    }
  }
  private wake = () => {
    if (!this.available()) { this.disconnect(false); return; }
    if (!this.controller && !this.terminal) {
      clearTimeout(this.reconnect); this.reconnect = undefined; void this.connect();
    }
  };
  private async connect() {
    if (!this.running || this.controller || !this.available() || this.terminal) return;
    this.setPhase("connecting");
    const controller = new AbortController(), epoch = ++this.epoch;
    this.controller = controller; this.deadline();
    try {
      const response = await this.fetcher("/api/events", { credentials: "same-origin", cache: "no-store", headers: { Accept: "text/event-stream" }, signal: controller.signal });
      if (controller.signal.aborted || epoch !== this.epoch) return;
      if (response.status === 401 || response.status === 426) {
        this.terminal = true; this.disconnect(false);
        if (response.status === 401) this.setPhase("unauthorized");
        else window.dispatchEvent(new Event("dojo:contract"));
        return;
      }
      if (!response.ok || response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== "text/event-stream" || !response.body) throw new Error("Invalid live response");
      await readSse(response.body, (event, data) => {
        if (!controller.signal.aborted && epoch === this.epoch) this.acceptMessage(event, data);
      }, controller.signal);
      if (!controller.signal.aborted && epoch === this.epoch) this.disconnect();
    } catch {
      if (!controller.signal.aborted && epoch === this.epoch) this.disconnect();
    }
  }
  start(): () => void {
    if (++this.owners === 1) {
      this.running = true; this.ready = false; this.terminal = false; this.attempt = 0;
      this.setPhase("connecting");
      document.addEventListener("visibilitychange", this.wake);
      for (const event of ["focus", "online", "offline"]) window.addEventListener(event, this.wake);
      this.wake();
    }
    let active = true;
    return () => { if (active) { active = false; if (--this.owners === 0) this.stop(); } };
  }
  stop() {
    this.running = false; this.owners = 0; this.disconnect(false); this.versions.clear();
    document.removeEventListener("visibilitychange", this.wake);
    for (const event of ["focus", "online", "offline"]) window.removeEventListener(event, this.wake);
  }
  acceptMessage(event: string, value: unknown) {
    if (!["ready", "change", "heartbeat", "resync"].includes(event)) return;
    if (!object(value)) throw new Error("Invalid live frame");
    if (event === "resync") {
      if (typeof value.reason !== "string") throw new Error("Invalid resync");
      if (value.reason === "unauthorized") { this.terminal = true; this.disconnect(false); this.setPhase("unauthorized"); }
      else this.disconnect();
      return;
    }
    if (event === "ready") {
      if (value.protocol !== 1 || this.ready) throw new Error("Invalid live protocol");
      this.ready = true; this.deadline();
      for (const consumer of this.consumers) { consumer.pending = false; void this.run(consumer); }
      this.synchronize(); return;
    }
    if (!this.ready) throw new Error("Live frame before readiness");
    if (event === "heartbeat") { this.deadline(); this.attempt = 0; return; }
    if (typeof value.event_id !== "string" || !value.event_id || value.event_id.length > 128 || !object(value.versions)) throw new Error("Invalid invalidation");
    const changed: string[] = [];
    for (const [key, version] of Object.entries(value.versions)) {
      if (!key || key.length > 255 || !Number.isSafeInteger(version) || Number(version) < 1) throw new Error("Invalid resource version");
      if (Number(version) > (this.versions.get(key) ?? 0)) { this.versions.set(key, Number(version)); changed.push(key); }
    }
    this.deadline();
    for (const consumer of this.consumers) if (changed.some(key => matches(consumer.resources, key))) void this.run(consumer);
  }
  private async run(consumer: Consumer, followup = false) {
    if (!this.ready || !this.consumers.has(consumer)) return;
    consumer.synchronized = false;
    if (consumer.controller) { consumer.pending = true; this.synchronize(); return; }
    const controller = new AbortController(), epoch = this.epoch;
    consumer.controller = controller; consumer.pending = false; consumer.failed = false; this.synchronize();
    try {
      await consumer.refresh(controller.signal);
      if (!controller.signal.aborted && epoch === this.epoch) {
        const behind = [...responseVersions(controller.signal)].some(([key, version]) => version < (this.versions.get(key) ?? 0));
        if (behind && !followup) consumer.pending = true;
        consumer.synchronized = !behind && !consumer.pending;
        consumer.failed = behind && followup;
        if (!behind) for (const [key, version] of responseVersions(controller.signal)) this.versions.set(key, Math.max(this.versions.get(key) ?? 0, version));
      }
    } catch (error) {
      consumer.synchronized = false;
      if (error instanceof SupersededRead && !followup && !controller.signal.aborted) consumer.pending = true;
      else if (!controller.signal.aborted && epoch === this.epoch) consumer.failed = true;
    }
    finally {
      consumer.controller = null;
      if (consumer.pending && this.ready && this.consumers.has(consumer)) { consumer.pending = false; void this.run(consumer, true); }
      else this.synchronize();
    }
  }
  subscribe(refresh: Consumer["refresh"], resources: readonly string[]): () => void {
    const consumer: Consumer = { refresh, resources: [...resources], controller: null, pending: false, synchronized: false, failed: false };
    this.consumers.add(consumer);
    if (this.ready) void this.run(consumer);
    return () => { this.consumers.delete(consumer); consumer.controller?.abort(); this.synchronize(); };
  }
  retry(resources?: readonly string[]) {
    if (!this.ready) { this.wake(); return; }
    for (const consumer of this.consumers) if (!resources || resources.some(key => matches(consumer.resources, key))) void this.run(consumer);
  }
}

export const live = new LiveCoordinator();
export function startLiveRefresh(refresh: Consumer["refresh"], resources: readonly string[]): () => void {
  return live.subscribe(refresh, resources);
}
