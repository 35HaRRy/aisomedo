import type { ActiveEditorOut, ActivityPageOut, AttemptOut, BrandingDefaultsOut, ClientOut, CompletedPackageOut, ConsentOut, DashboardOut, EditorMediaOut, PackageArtifactOut, PackageOut, PlanOut, ReminderPolicyOut, ReviewDetailOut, SetupOut, StatusOut, UploadOut, UploadInitIn } from "../api/openapi";

export const PHOTO = "/demo/training.svg";
export const VIDEO = "/demo/training.webm";
export function demoMedia(id: string, video: boolean, now: string): EditorMediaOut {
  const url = video ? VIDEO : PHOTO;
  const artifact: PackageArtifactOut = { artifact_ref: id, available: true, content_type: video ? "video/webm" : "image/svg+xml",
    filename: video ? "antrenman.webm" : "antrenman.jpg", kind: "original", url, preview_url: url };
  return { media_id: id, filename: artifact.filename, content_type: video ? "video/mp4" : "image/jpeg", size_bytes: 4096,
    uploaded_at: now, status: "finalized", processed: { content_type: artifact.content_type, duration: video ? 6 : null, dimensions: [720, 1280] },
    is_video: video, source_duration: video ? 6 : null, effective_duration: video ? 6 : 4,
    preview_url: url, original_url: url, thumbnail_url: PHOTO, artifacts: [artifact],
    section_preview: video ? { status: "ready", generation: "seed", duration: 6, url: VIDEO } : null };
}
export function completedDetail(editor: ActiveEditorOut, caption: string): CompletedPackageOut {
  return { folder_name: editor.package.folder_name, caption, media: structuredClone(editor.media), order: [...editor.montage.order], render_revision: "demo-render",
    artifacts: [{ artifact_ref: "reel", available: true, content_type: "video/webm", filename: "demo-reel.webm", kind: "render", preview_url: VIDEO, url: VIDEO }] };
}
export interface DemoState {
  client: ClientOut; setup: SetupOut; consent: ConsentOut; branding: BrandingDefaultsOut; plan: PlanOut;
  reminders: ReminderPolicyOut; instagram: StatusOut; dashboard: DashboardOut; editor: ActiveEditorOut;
  completed: CompletedPackageOut[]; packages: PackageOut[]; reviews: Map<number, ReviewDetailOut>; activity: ActivityPageOut;
  candidates: AttemptOut["candidates"]; uploads: Map<string, UploadOut>; uploadInputs: Map<string, UploadInitIn>;
  uploadData: Map<string, Blob[]>;
  versions: Map<string, number>; listeners: Set<(versions: Record<string, number>) => void>;
}
export function createDemoState(now: Date): DemoState {
  const at = (days: number) => new Date(now.getTime() + days * 86400000).toISOString();
  const monday = new Date(now);
  monday.setUTCDate(monday.getUTCDate() + ((8 - monday.getUTCDay()) % 7 || 7) + 7);
  monday.setUTCHours(7, 0, 0, 0);
  const regular = monday.toISOString();
  const pkg: PackageOut = { id: 1, folder_name: "Demo · Aktif Paket", status: "active", created_at: at(-1) };
  const media = [demoMedia("photo-1", false, at(-1)), demoMedia("video-1", true, at(-1))];
  const plan: PlanOut = { enabled: true, anchor_date: regular.slice(0, 10), anchor_time: "10:00:00", timezone: "Europe/Istanbul" };
  const editor: ActiveEditorOut = { package: pkg, content_revision: 1, view_revision: 1, media, render_stale: false,
    render_status: "ready", render_revision: "demo-render", render_preview_url: VIDEO, render_duration: 10,
    montage: { order: media.map(m => m.media_id), clips: media.map(m => ({ media_id: m.media_id, filename: m.filename, content_type: m.content_type,
      is_video: m.is_video, source_duration: m.source_duration, effective_duration: m.effective_duration! })), selections: {}, trims: {},
      combined_duration: 10, max_duration_seconds: 90, over_limit: false, duration_complete: true, required_action: null, card_duration: 0 } };
  const packages = [2, 3].map(id => ({ id, folder_name: `Demo · Antrenman ${id}`, created_at: at(-id * 7), status: "completed" }));
  const reviews = new Map<number, ReviewDetailOut>([1, 2].map(id => [id, {
    review: { id, occurrence_id: id, package_folder: id === 1 ? pkg.folder_name : packages[0].folder_name,
      caption: "Birlikte çalış, birlikte geliş. #Demo", created_at: at(-id), revision_digest: `demo-${id}`, version: 1, status: id === 1 ? "pending" : "approved" },
    next_regular_at: regular, render_ready: true, preview_url: VIDEO,
  }]));
  const next_slots = [{ kind: "oneoff", occurrence_id: 3, due_at: at(1) }, { kind: "regular", occurrence_id: 4, due_at: regular }];
  return { client: { id: 900001, name: "Örnek Stüdyo", kind: "browser", created_by: "demo", created_at: at(-1), last_seen_at: at(0), revoked_at: null },
    setup: { ready: true, checklist: ["pairing", "instagram", "schedule", "consent", "logo", "caption_template", "cards"].map(key => ({ key, label: key, complete: true, required: key !== "cards" })) },
    consent: { version: 1, text: "Demo medya rızası. Tüm kişiler ve kayıtlar temsilidir.", accepted_at: at(-1) },
    branding: { caption_template: "Birlikte çalış, birlikte geliş. #Demo", logo_asset: PHOTO, intro_asset: PHOTO, outro_asset: PHOTO, intro_duration: 2, outro_duration: 2 },
    plan, reminders: { interval_minutes: 360, delivery_start: "08:00:00", delivery_end: "22:00:00", timezone: "Europe/Istanbul" },
    instagram: { health: "healthy", ig_username: "ornek_studyo_demo", ig_user_id: "demo-account-1", connection_type: "demo" },
    dashboard: { generated_at: at(0), package: pkg, plan, instagram: { health: "healthy", username: "ornek_studyo_demo" }, worker: { status: "healthy", phase: "idle" },
      manual_review_allowed: true, next_slot: next_slots[1], next_slots,
      pending_actions: [{ occurrence_id: 1, review_id: 1, version: 1, package_folder: pkg.folder_name, state: "review_ready", due_at: at(-0.01) }] },
    editor, packages, completed: packages.map(p => completedDetail({ ...editor, package: p }, `${p.folder_name} · Temsili yayın`)), reviews,
    activity: { next_cursor: null, events: [1, 2].map(id => ({ id, action: id === 1 ? "review.created" : "publication.succeeded", actor: "demo",
      details: { review_id: id }, occurred_at: at(-id) })) },
    candidates: [1, 2].map(id => ({ ig_user_id: `demo-account-${id}`, ig_username: `ornek_studyo_demo_${id}` })),
    uploads: new Map(), uploadInputs: new Map(), uploadData: new Map(), versions: new Map(), listeners: new Set() };
}
