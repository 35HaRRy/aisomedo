import { createDemoState } from "./seed";
import { handleDemoRequest } from "./api";

let active: DemoRuntime | null = null;
let generation = 0;

export function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; }, clear: () => values.clear(),
    key: index => [...values.keys()][index] ?? null,
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, String(value)); },
    removeItem: key => { values.delete(key); },
  };
}
export class DemoRuntime {
  readonly generation = ++generation;
  private lifetime = new AbortController();
  readonly signal = this.lifetime.signal;
  readonly storage = memoryStorage();
  readonly drafts = new Map<string, unknown>();
  readonly cleanup = new Set<() => void>();
  readonly objectUrls = new Map<string, string>();
  readonly state = createDemoState(new Date());
  async fetch(path: string, init: RequestInit = {}): Promise<Response> {
    this.signal.throwIfAborted(); init.signal?.throwIfAborted();
    return handleDemoRequest(this.state, path, init, AbortSignal.any([this.signal, ...(init.signal ? [init.signal] : [])]));
  }
  dispose() {
    this.lifetime.abort(); this.cleanup.forEach(cleanup => cleanup()); this.cleanup.clear(); this.storage.clear();
    this.objectUrls.forEach((_type, url) => URL.revokeObjectURL(url)); this.objectUrls.clear();
    this.state.uploadData.clear(); this.state.listeners.clear();
    this.drafts.clear();
  }
}
export function startDemo(): DemoRuntime { return active ??= new DemoRuntime(); }
export function getDemoRuntime(): DemoRuntime | null { return active; }
export function demoGeneration(): number { return generation; }
export function stopDemo(): void { active?.dispose(); active = null; }

export function recoveryStorage(): Storage | null {
  if (active) return active.storage;
  try { return window.localStorage; } catch { return null; }
}
