import { useEffect, useState } from "react";
import { ApiError } from "./api/client";
import { startLiveRefresh } from "./live";
import { useSession } from "./session";

export function useLiveData<T>(load: (signal: AbortSignal) => Promise<T>, enabled = true) {
  const { invalidate } = useSession();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const offline = () => setError(true);
    window.addEventListener("offline", offline);
    if (!navigator.onLine) setError(true);
    const stop = startLiveRefresh(async signal => {
      try {
        const value = await load(signal);
        if (!active || signal.aborted) return;
        setData(value); setError(false); setUpdatedAt(new Date().toISOString());
      } catch (failure) {
        if (!active || signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 401) invalidate();
        else setError(true);
      }
    });
    return () => { active = false; stop(); window.removeEventListener("offline", offline); };
  }, [load, enabled, attempt, invalidate]);
  return { data, error, updatedAt, retry: () => setAttempt(value => value + 1) };
}
