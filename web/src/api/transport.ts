import { demoGeneration, getDemoRuntime } from "../demo/runtime";
import { isDemoHash } from "../demo/routing";

export async function transportFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const runtime = getDemoRuntime();
  if (runtime) return runtime.fetch(path, init);
  if (isDemoHash(window.location.hash)) throw new Error("Demo runtime unavailable");
  const controller = new AbortController();
  const generation = demoGeneration();
  const cancel = () => controller.abort();
  const routeChanged = () => { if (isDemoHash(window.location.hash) || getDemoRuntime()) cancel(); };
  init.signal?.throwIfAborted();
  init.signal?.addEventListener("abort", cancel, { once: true });
  window.addEventListener("hashchange", routeChanged);
  try {
    const response = await fetch(path, { ...init, signal: controller.signal });
    if (demoGeneration() !== generation || getDemoRuntime() || isDemoHash(window.location.hash)) controller.abort();
    controller.signal.throwIfAborted();
    return response;
  } finally {
    init.signal?.removeEventListener("abort", cancel);
    window.removeEventListener("hashchange", routeChanged);
  }
}
