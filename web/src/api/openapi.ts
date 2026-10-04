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
  "/api/dashboard",
  "/api/media/upload-limits",
  "/api/media/uploads",
  "/api/media/uploads/{upload_id}",
  "/api/media/uploads/{upload_id}/abort",
  "/api/media/uploads/{upload_id}/complete",
  "/api/media/uploads/{upload_id}/conflicts/{target_media_id}/preview",
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
  "/api/packages/active/clear",
  "/api/packages/active/complete",
  "/api/packages/active/editor",
  "/api/packages/active/media/{media_id}/preview",
  "/api/packages/active/media/{media_id}/remove",
  "/api/packages/active/media/{media_id}/restore",
  "/api/packages/active/montage",
  "/api/packages/active/order",
  "/api/packages/active/publication",
  "/api/packages/active/publication/reconcile",
  "/api/packages/active/publication/recover",
  "/api/packages/active/publication/retry",
  "/api/packages/active/publish",
  "/api/packages/active/render",
  "/api/packages/active/render/preview",
  "/api/packages/active/selections",
  "/api/packages/active/trims",
  "/api/packages/recovered",
  "/api/packages/recovered/{folder_name}/import",
  "/api/packages/recovered/{folder_name}/resolve",
  "/api/packages/{folder_name}",
  "/api/packages/{folder_name}/artifacts",
  "/api/packages/{folder_name}/download",
  "/api/pairing/clients",
  "/api/pairing/clients/{client_id}/revoke",
  "/api/pairing/codes",
  "/api/pairing/me",
  "/api/pairing/me/push-token",
  "/api/pairing/validate",
  "/api/reviews/pending",
  "/api/reviews/{review_id}",
  "/api/reviews/{review_id}/approve",
  "/api/reviews/{review_id}/reschedule",
  "/api/reviews/{review_id}/skip",
  "/api/settings/branding",
  "/api/settings/branding/assets",
  "/api/settings/branding/assets/{asset_id}",
  "/api/settings/manual-publish",
  "/api/settings/plan",
  "/api/settings/reminders",
  "/api/setup",
  "/api/setup/cards/skip",
  "/api/setup/consent",
  "/api/setup/consent/accept",
  "/health",
  "/pub/{token}",
  "/ready",
];

export type AcceptanceIn = {
  "version"?: number | null;
};

export type AcceptanceOut = {
  "accepted_at": string;
  "version": number;
};

export type ActiveEditorOut = {
  "media": Array<EditorMediaOut>;
  "montage": MontageOut;
  "package": PackageOut;
  "render_preview_url"?: string | null;
  "render_revision"?: string | null;
  "render_stale": boolean;
  "render_status"?: "missing" | "stale" | "queued" | "processing" | "ready" | "failed";
};

export type ActivityEventOut = {
  "action": string;
  "actor": ClientRefOut | string;
  "details": Record<string, unknown>;
  "id": number;
  "occurred_at": string;
};

export type ActivityPageOut = {
  "events": Array<ActivityEventOut>;
  "next_cursor": number | null;
};

export type ApproveIn = {
  "version": number;
};

export type AttemptOut = {
  "candidates": Array<MetaCandidateOut>;
  "id": string;
  "status": string;
};

export type BrandingAssetOut = {
  "asset": string;
  "preview_url": string;
};

export type BrandingDefaultsOut = {
  "caption_template": string | null;
  "intro_asset": string | null;
  "intro_duration": number | null;
  "logo_asset": string | null;
  "outro_asset": string | null;
  "outro_duration": number | null;
};

export type BrandingPatchIn = {
  "caption_template"?: string | null;
  "intro_asset"?: string | null;
  "intro_duration"?: number | null;
  "logo_asset"?: string | null;
  "outro_asset"?: string | null;
  "outro_duration"?: number | null;
};

export type ClearPackageIn = {
  "confirmed": boolean;
  "expected_folder_name": string;
  "expected_package_id": number;
};

export type ClearPackageOut = {
  "folder_name": string;
  "upload_ids": Array<string>;
};

export type ClientOut = {
  "created_at": string;
  "created_by": string;
  "id": number;
  "kind": string;
  "last_seen_at": string | null;
  "name": string;
  "revoked_at": string | null;
};

export type ClientRefOut = {
  "id": number;
  "kind": string;
  "name": string;
};

export type CompletedMediaOut = {
  "artifacts": Array<PackageArtifactOut>;
  "content_type": string;
  "filename": string;
  "media_id": string;
  "preview_url": string | null;
  "processed": ProcessedMetadataOut;
  "removed_position"?: number | null;
  "size_bytes": number;
  "status": string;
  "uploaded_at": string;
};

export type CompletedPackageOut = {
  "artifacts": Array<PackageArtifactOut>;
  "caption": string | null;
  "folder_name": string;
  "media": Array<CompletedMediaOut>;
  "order": Array<string>;
  "render_revision": string | null;
};

export type ConsentOut = {
  "accepted_at": string | null;
  "text": string;
  "version": number;
};

export type DashboardActionOut = {
  "due_at": string;
  "occurrence_id": number;
  "package_folder": string | null;
  "review_id": number | null;
  "state": "review_ready" | "empty_package" | "preparing";
  "version": number | null;
};

export type DashboardInstagramOut = {
  "health": string;
  "username"?: string | null;
};

export type DashboardOut = {
  "generated_at": string;
  "instagram": DashboardInstagramOut;
  "next_slot": DashboardSlotOut | null;
  "package": PackageOut | null;
  "pending_actions": Array<DashboardActionOut>;
  "plan": PlanOut;
  "worker": DashboardWorkerOut;
};

export type DashboardSlotOut = {
  "due_at": string;
  "kind": string;
};

export type DashboardWorkerOut = {
  "phase": "idle" | "busy" | "stopped" | null;
  "status": "healthy" | "unhealthy" | "unknown";
};

export type EditorMediaOut = {
  "artifacts": Array<PackageArtifactOut>;
  "content_type": string;
  "effective_duration": number | null;
  "filename": string;
  "is_video": boolean;
  "media_id": string;
  "preview_url": string | null;
  "processed": ProcessedMetadataOut;
  "removed_position"?: number | null;
  "size_bytes": number;
  "source_duration": number | null;
  "status": string;
  "uploaded_at": string;
};

export type MetaCandidateOut = {
  "ig_user_id": string;
  "ig_username": string;
  "page_id"?: string | null;
  "page_name"?: string | null;
};

export type MontageClipOut = {
  "content_type": string;
  "effective_duration": number;
  "filename": string;
  "is_video": boolean;
  "media_id": string;
  "source_duration": number | null;
};

export type MontageOut = {
  "card_duration": number;
  "clips": Array<MontageClipOut>;
  "combined_duration": number;
  "duration_complete": boolean;
  "max_duration_seconds": number;
  "order": Array<string>;
  "over_limit": boolean;
  "required_action": string | null;
  "selections": Record<string, Array<VideoRangeOut>>;
  "trims": Record<string, VideoRangeOut>;
};

export type PackageArtifactOut = {
  "artifact_ref": string;
  "available": boolean;
  "content_type": string;
  "filename": string;
  "kind": "original" | "processed" | "render";
  "preview_url": string | null;
  "url": string | null;
};

export type PackageOut = {
  "created_at": string;
  "folder_name": string;
  "id": number;
  "status": string;
};

export type PlanIn = {
  "anchor_date"?: string | null;
  "anchor_time"?: string | null;
  "enabled"?: boolean;
};

export type PlanOut = {
  "anchor_date": string | null;
  "anchor_time": string | null;
  "enabled": boolean;
  "timezone": string;
};

export type ProcessedMetadataOut = {
  "content_type"?: string | null;
  "dimensions"?: Array<number> | null;
  "duration"?: number | null;
  "path"?: string | null;
  "size_bytes"?: number | null;
};

export type ReminderPolicyIn = {
  "delivery_end": string;
  "delivery_start": string;
  "interval_minutes": number;
  "timezone"?: string;
};

export type ReminderPolicyOut = {
  "delivery_end": string;
  "delivery_start": string;
  "interval_minutes": number;
  "timezone": string;
};

export type RenderIn = {
  "expected_folder_name": string;
  "retry"?: boolean;
};

export type RenderOut = {
  "render_revision": string;
  "stale": boolean;
};

export type RescheduleIn = {
  "new_due_at": string;
  "version": number;
};

export type ResolveConflictIn = {
  "apply_to_all"?: boolean;
  "confirmed_overwrite"?: boolean;
  "decision": string;
  "target_media_id"?: string | null;
};

export type ReviewDetailOut = {
  "next_regular_at": string | null;
  "preview_url": string | null;
  "render_ready": boolean;
  "review": ReviewOut;
};

export type ReviewOut = {
  "caption": string | null;
  "created_at": string;
  "id": number;
  "occurrence_id": number;
  "package_folder": string;
  "revision_digest": string;
  "status": string;
  "version": number;
};

export type SelectIn = {
  "ig_user_id": string;
};

export type SelectionIn = {
  "expected_folder_name": string;
  "photo_durations"?: Record<string, number> | null;
  "selections": Record<string, Array<VideoRangeOut>>;
};

export type SetupItemOut = {
  "complete": boolean;
  "key": string;
  "label": string;
  "required"?: boolean;
};

export type SetupOut = {
  "checklist": Array<SetupItemOut>;
  "ready": boolean;
};

export type SkipIn = {
  "confirmed"?: boolean;
  "version": number;
};

export type StartIn = {
  "return_uri"?: string | null;
};

export type StartOut = {
  "attempt_id": string;
  "auth_url": string;
};

export type StatusOut = {
  "connection_type"?: string;
  "expires_at"?: string | null;
  "health": string;
  "ig_user_id"?: string | null;
  "ig_username"?: string | null;
  "last_checked_at"?: string | null;
  "last_error"?: string | null;
  "last_refreshed_at"?: string | null;
  "page_id"?: string | null;
  "page_name"?: string | null;
};

export type UploadInitIn = {
  "content_type": string;
  "declared_size_bytes": number;
  "expected_package_id"?: number | null;
  "filename": string;
};

export type UploadLimitsOut = {
  "active_package_id"?: number | null;
  "max_file_bytes": number;
  "max_package_bytes": number;
};

export type UploadOut = {
  "conflicts"?: Array<Record<string, unknown>>;
  "declared_size_bytes": number;
  "error_reason"?: string | null;
  "package_id"?: number | null;
  "received_bytes": number;
  "received_ranges": Array<Array<number>>;
  "status": string;
  "upload_id": string;
};

export type ValidateIn = {
  "code": string;
  "kind": "device" | "browser";
  "name": string;
};

export type VideoRangeOut = {
  "end": number;
  "start": number;
};
