// GENERATED from backend/openapi.json — do not edit by hand.
// Regenerate: uv run --project backend python backend/scripts/generate_clients.py
export const CONTRACT_VERSION = "0.1.0";

export interface CompatInfo {
  api_version: string;
  android_min_version_code: number;
  android_current_version_code: number;
  update_url: string;
}

export const ANDROID_VERSION_HEADER = "X-Android-Version-Code";

export async function fetchCompat(baseUrl: string): Promise<CompatInfo> {
  const response = await fetch(`${baseUrl}/api/compat`);
  if (!response.ok) {
    throw new Error(`compat check failed: ${response.status}`);
  }
  return (await response.json()) as CompatInfo;
}

export const API_PATHS: readonly string[] = [
  "/api/activity",
  "/api/compat",
  "/api/media/uploads",
  "/api/media/uploads/{upload_id}",
  "/api/media/uploads/{upload_id}/abort",
  "/api/media/uploads/{upload_id}/complete",
  "/api/media/uploads/{upload_id}/ranges",
  "/api/media/uploads/{upload_id}/resolve",
  "/api/meta/instagram/token",
  "/api/meta/oauth/attempts/{attempt_id}",
  "/api/meta/oauth/attempts/{attempt_id}/select",
  "/api/meta/oauth/callback",
  "/api/meta/oauth/start",
  "/api/meta/status",
  "/api/packages",
  "/api/packages/active",
  "/api/packages/active/branding",
  "/api/packages/active/caption",
  "/api/packages/active/complete",
  "/api/packages/active/media/{media_id}/remove",
  "/api/packages/active/media/{media_id}/restore",
  "/api/packages/active/montage",
  "/api/packages/active/order",
  "/api/packages/active/publication",
  "/api/packages/active/publication/reconcile",
  "/api/packages/active/publication/recover",
  "/api/packages/active/publication/retry",
  "/api/packages/active/publish",
  "/api/packages/active/trims",
  "/api/packages/recovered",
  "/api/packages/recovered/{folder_name}/import",
  "/api/packages/recovered/{folder_name}/resolve",
  "/api/packages/{folder_name}",
  "/api/packages/{folder_name}/download",
  "/api/pairing/clients",
  "/api/pairing/clients/{client_id}/revoke",
  "/api/pairing/codes",
  "/api/pairing/me",
  "/api/pairing/me/push-token",
  "/api/pairing/validate",
  "/api/reviews/pending",
  "/api/reviews/{review_id}/approve",
  "/api/reviews/{review_id}/reschedule",
  "/api/reviews/{review_id}/skip",
  "/api/settings/branding",
  "/api/settings/manual-publish",
  "/api/settings/plan",
  "/api/settings/reminders",
  "/api/setup",
  "/api/setup/consent",
  "/api/setup/consent/accept",
  "/health",
  "/pub/{token}",
  "/ready",
];
