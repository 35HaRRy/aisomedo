import type { ActivityPageOut, ClientOut, DashboardOut, ValidateIn } from "./openapi";

export class ApiError extends Error {
  constructor(public readonly status: number) { super(`api:${status}`); }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (init.signal?.aborted) throw new DOMException("", "AbortError");
  init.signal?.addEventListener("abort", cancel, { once: true });
  const timeout = window.setTimeout(cancel, 10000);
  try {
    const response = await fetch(path, {
      ...init, credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
    });
    if (controller.signal.aborted) throw new DOMException("", "AbortError");
    if (!response.ok) throw new ApiError(response.status);
    return response.status === 204 ? undefined as T : await response.json() as T;
  } catch (error) {
    if (init.signal?.aborted) throw new DOMException("", "AbortError");
    throw error instanceof ApiError ? error : new ApiError(0);
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", cancel);
  }
}

export const api = {
  me: (signal?: AbortSignal) => request<ClientOut>("/api/pairing/me", { signal }),
  pair: async (body: ValidateIn, signal?: AbortSignal): Promise<void> => {
    await request("/api/pairing/validate", { method: "POST", body: JSON.stringify(body), signal });
  },
  dashboard: (signal?: AbortSignal) => request<DashboardOut>("/api/dashboard", { signal }),
  activity: (signal?: AbortSignal) => request<ActivityPageOut>("/api/activity?limit=20", { signal }),
};
