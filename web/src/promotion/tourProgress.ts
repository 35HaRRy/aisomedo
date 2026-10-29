export type TourProgress = { version: 1; completed: string[]; dismissed: string[]; skipAll: boolean };
import { getDemoRuntime, recoveryStorage } from "../demo/runtime";
const memory = new Map<number, TourProgress>();
const unpersisted = new Set<number>();
const empty = (): TourProgress => ({ version: 1, completed: [], dismissed: [], skipAll: false });
const key = (clientId: number) => `aisomedo:promotion:v1:${clientId}`;

export function readTourProgress(clientId: number): TourProgress {
  if (getDemoRuntime()) {
    const raw = recoveryStorage()?.getItem(key(clientId)); return raw ? JSON.parse(raw) as TourProgress : empty();
  }
  if (unpersisted.has(clientId)) return memory.get(clientId) ?? empty();
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key(clientId)) ?? "null");
    if (value && typeof value === "object" && "version" in value && value.version === 1
      && "completed" in value && Array.isArray(value.completed) && value.completed.every(id => typeof id === "string")
      && "dismissed" in value && Array.isArray(value.dismissed) && value.dismissed.every(id => typeof id === "string")
      && "skipAll" in value && typeof value.skipAll === "boolean")
      return { version: 1, completed: [...value.completed], dismissed: [...value.dismissed], skipAll: value.skipAll };
    return empty();
  } catch { return memory.get(clientId) ?? empty(); }
}

export function writeTourProgress(clientId: number, progress: TourProgress): void {
  const value: TourProgress = { ...progress, completed: [...new Set(progress.completed)], dismissed: [...new Set(progress.dismissed)] };
  if (getDemoRuntime()) { recoveryStorage()?.setItem(key(clientId), JSON.stringify(value)); return; }
  memory.set(clientId, value);
  try { localStorage.setItem(key(clientId), JSON.stringify(value)); unpersisted.delete(clientId); }
  catch { unpersisted.add(clientId); }
}

export function resetTourProgress(clientId: number): void { writeTourProgress(clientId, empty()); }
