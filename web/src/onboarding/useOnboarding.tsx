import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { SetupOut } from "../api/openapi";
import { startLiveRefresh } from "../live";
import { useSession } from "../session";

interface Onboarding {
  setup: SetupOut | null;
  error: boolean;
  refresh(): Promise<void>;
  save<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T>;
}
const Context = createContext<Onboarding | null>(null);
export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { invalidate } = useSession();
  const [setup, setSetup] = useState<SetupOut | null>(null);
  const [error, setError] = useState(false);
  const alive = useRef(true);
  const read = useRef<AbortController | null>(null);
  const writes = useRef(new Set<AbortController>());
  const refresh = useCallback(async () => {
    read.current?.abort();
    const controller = new AbortController(); read.current = controller;
    try {
      const value = await api.setup(controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      setSetup(value); setError(false);
    } catch (failure) {
      if (!alive.current || controller.signal.aborted) return;
      if (failure instanceof ApiError && failure.status === 401) invalidate();
      else setError(true);
      throw failure;
    }
  }, [invalidate]);
  const save = useCallback(async <T,>(operation: (signal: AbortSignal) => Promise<T>) => {
    const controller = new AbortController();
    if (!alive.current) throw new DOMException("", "AbortError");
    writes.current.add(controller); read.current?.abort();
    try {
      const result = await operation(controller.signal);
      if (!alive.current || controller.signal.aborted) throw new DOMException("", "AbortError");
      try { await refresh(); }
      catch (failure) { if (failure instanceof ApiError && failure.status === 401) throw failure; }
      if (!alive.current || controller.signal.aborted) throw new DOMException("", "AbortError");
      return result;
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401 && alive.current) invalidate();
      throw failure;
    } finally { writes.current.delete(controller); }
  }, [invalidate, refresh]);
  useEffect(() => {
    alive.current = true;
    const offline = () => setError(true);
    window.addEventListener("offline", offline);
    const stop = startLiveRefresh(async signal => {
      if (writes.current.size) return;
      const cancel = () => read.current?.abort();
      signal.addEventListener("abort", cancel, { once: true });
      try { await refresh(); } finally { signal.removeEventListener("abort", cancel); }
    });
    return () => {
      alive.current = false; stop(); read.current?.abort();
      writes.current.forEach(controller => controller.abort());
      window.removeEventListener("offline", offline);
    };
  }, [refresh]);
  return <Context.Provider value={{ setup, error, refresh, save }}>{children}</Context.Provider>;
}
export function useOnboarding(): Onboarding {
  const value = useContext(Context);
  if (!value) throw new Error("OnboardingProvider required");
  return value;
}
