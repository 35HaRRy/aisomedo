import type { ActivityPageOut, ClientOut, DashboardOut, ValidateIn, SetupOut, ConsentOut, AcceptanceOut, BrandingDefaultsOut, BrandingPatchIn, BrandingAssetOut, PlanIn, PlanOut, StatusOut, StartOut, AttemptOut, UploadLimitsOut, UploadInitIn, UploadOut } from "./openapi";

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly detail?: string) { super(`api:${status}`); }
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
      headers: { ...(typeof init.body === "string" ? { "Content-Type": "application/json" } : {}), ...init.headers },
    });
    if (controller.signal.aborted) throw new DOMException("", "AbortError");
    if (!response.ok) {
      let detail: string | undefined;
      try {
        const body: unknown = await response.json();
        if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") detail = body.detail;
      } catch { /* Status survives malformed/non-JSON responses. */ }
      if (controller.signal.aborted) throw new DOMException("", "AbortError");
      throw new ApiError(response.status, detail);
    }
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
  uploadLimits: (signal?: AbortSignal) => request<UploadLimitsOut>("/api/media/upload-limits", { signal }),
  startUpload: (body: UploadInitIn, signal?: AbortSignal) => request<UploadOut>("/api/media/uploads", { method: "POST", body: JSON.stringify(body), signal }),
  uploadStatus: (id: string, signal?: AbortSignal) => request<UploadOut>(`/api/media/uploads/${encodeURIComponent(id)}`, { signal }),
  uploadRange: (id: string, offset: number, checksum: string, body: Blob, signal?: AbortSignal) => request<UploadOut>(`/api/media/uploads/${encodeURIComponent(id)}/ranges?offset=${offset}&checksum_sha256=${encodeURIComponent(checksum)}`, { method: "PUT", body, headers: { "Content-Type": "application/octet-stream" }, signal }),
  completeUpload: (id: string, signal?: AbortSignal) => request<UploadOut>(`/api/media/uploads/${encodeURIComponent(id)}/complete`, { method: "POST", signal }),
  me: (signal?: AbortSignal) => request<ClientOut>("/api/pairing/me", { signal }),
  pair: async (body: ValidateIn, signal?: AbortSignal): Promise<void> => {
    await request("/api/pairing/validate", { method: "POST", body: JSON.stringify(body), signal });
  },
  dashboard: (signal?: AbortSignal) => request<DashboardOut>("/api/dashboard", { signal }),
  activity: (signal?: AbortSignal) => request<ActivityPageOut>("/api/activity?limit=20", { signal }),
  setup: (signal?: AbortSignal) => request<SetupOut>("/api/setup", { signal }),
  consent: (signal?: AbortSignal) => request<ConsentOut>("/api/setup/consent", { signal }),
  acceptConsent: (version: number, signal?: AbortSignal) => request<AcceptanceOut>("/api/setup/consent/accept", { method: "POST", body: JSON.stringify({ version }), signal }),
  skipCards: (signal?: AbortSignal) => request<SetupOut>("/api/setup/cards/skip", { method: "POST", signal }),
  branding: (signal?: AbortSignal) => request<BrandingDefaultsOut>("/api/settings/branding", { signal }),
  patchBranding: (body: BrandingPatchIn, signal?: AbortSignal) => request<BrandingDefaultsOut>("/api/settings/branding", { method: "PATCH", body: JSON.stringify(body), signal }),
  plan: (signal?: AbortSignal) => request<PlanOut>("/api/settings/plan", { signal }),
  savePlan: (body: PlanIn, signal?: AbortSignal) => request<PlanOut>("/api/settings/plan", { method: "PUT", body: JSON.stringify(body), signal }),
  instagram: (signal?: AbortSignal) => request<StatusOut>("/api/meta/status", { signal }),
  connectInstagramToken: (token: string, signal?: AbortSignal) => request<StatusOut>("/api/meta/instagram/token", { method: "POST", body: JSON.stringify({ access_token: token }), signal }),
  startOAuth: (signal?: AbortSignal) => request<StartOut>("/api/meta/oauth/start", { method: "POST", body: JSON.stringify({}), signal }),
  oauthAttempt: (id: string | number, signal?: AbortSignal) => request<AttemptOut>(`/api/meta/oauth/attempts/${encodeURIComponent(id)}`, { signal }),
  selectInstagramAccount: (id: string | number, igUserId: string, signal?: AbortSignal) => request<StatusOut>(`/api/meta/oauth/attempts/${encodeURIComponent(id)}/select`, { method: "POST", body: JSON.stringify({ ig_user_id: igUserId }), signal }),
  uploadBranding: (file: File, signal?: AbortSignal) => request<BrandingAssetOut>("/api/settings/branding/assets", { method: "POST", body: file, signal }),
};
