/** Foreground single-flight refresh. No work survives its subscription. */
export function startLiveRefresh(refresh: (signal: AbortSignal) => Promise<void>): () => void {
  let stopped = false;
  let controller: AbortController | null = null;
  let deferred = false;
  let immediate: number | undefined;
  const available = () => !stopped && !document.hidden && navigator.onLine;
  const run = async () => {
    if (!available()) return;
    if (controller) return;
    const current = new AbortController();
    controller = current;
    try { await refresh(current.signal); }
    catch { /* Consumer presents errors; a failed read must not stop future ticks. */ }
    finally {
      controller = null;
      if (deferred && available()) { deferred = false; wake(); }
    }
  };
  const wake = () => {
    if (!available()) { controller?.abort(); return; }
    if (immediate !== undefined) return;
    immediate = window.setTimeout(() => {
      immediate = undefined;
      if (controller) deferred = true;
      else void run();
    }, 0);
  };
  const timer = window.setInterval(() => void run(), 5000);
  document.addEventListener("visibilitychange", wake);
  window.addEventListener("focus", wake);
  window.addEventListener("online", wake);
  window.addEventListener("offline", wake);
  void run();
  return () => {
    stopped = true;
    controller?.abort();
    clearInterval(timer);
    clearTimeout(immediate);
    document.removeEventListener("visibilitychange", wake);
    window.removeEventListener("focus", wake);
    window.removeEventListener("online", wake);
    window.removeEventListener("offline", wake);
  };
}
