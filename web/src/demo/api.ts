import { CONTRACT_VERSION, type PackageEditIn, type BrandingPatchIn } from "../api/openapi";
import { completedDetail, type DemoState, VIDEO } from "./seed";
import { handleDemoMedia } from "./media";

const json = (value: unknown, status = 200, headers: HeadersInit = {}) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json", ...headers } });
const error = (detail: string, status = 422) => json({ detail }, status);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const future = (value: unknown, boundary?: string | null) => typeof value === "string" && Date.parse(value) > Date.now() && (!boundary || Date.parse(value) < Date.parse(boundary));
export function notifyDemo(state: DemoState) {
  const versions: Record<string, number> = {};
  for (const key of ["dashboard", "settings", "setup", "publication", "completed", "activity", `package:${state.editor.package.id}`, "upload:all"]) {
    versions[key] = (state.versions.get(key) ?? 0) + 1; state.versions.set(key, versions[key]);
  }
  state.dashboard.generated_at = new Date().toISOString();
  for (const listener of state.listeners) listener(versions);
}
function changed(state: DemoState, value: unknown, action = "settings.updated") {
  state.activity.events.unshift({ id: (state.activity.events[0]?.id ?? 0) + 1, action, actor: state.client, details: {}, occurred_at: new Date().toISOString() });
  notifyDemo(state); return json(value);
}
function refreshMontage(state: DemoState) {
  const editor = state.editor, montage = editor.montage;
  montage.order = montage.order.filter(id => editor.media.some(m => m.media_id === id && m.status === "finalized"));
  for (const media of editor.media.filter(m => m.status === "finalized")) if (!montage.order.includes(media.media_id)) montage.order.push(media.media_id);
  montage.clips = montage.order.map(id => {
    const m = editor.media.find(m => m.media_id === id)!;
    const ranges = montage.selections[id];
    const duration = ranges?.length ? ranges.reduce((sum, range) => sum + range.end - range.start, 0) : m.effective_duration ?? 4;
    return { media_id: id, filename: m.filename, content_type: m.content_type, is_video: m.is_video, source_duration: m.source_duration, effective_duration: duration };
  });
  montage.combined_duration = montage.clips.reduce((sum, m) => sum + m.effective_duration, 0) + montage.card_duration;
  montage.over_limit = montage.combined_duration > montage.max_duration_seconds;
  editor.content_revision++; editor.view_revision++; editor.render_stale = true; editor.render_status = "stale";
}
function validEdits(state: DemoState, changes: unknown): changes is PackageEditIn["changes"] {
  return Array.isArray(changes) && changes.every(change => {
    if (!record(change) || !record(change.base) || !record(change.proposed) || typeof change.key !== "string") return false;
    const key = change.key;
    const m = state.editor.media.find(m => m.media_id === key.slice(key.indexOf(":") + 1) && m.status === "finalized");
    if (change.key === "order") return Array.isArray(change.proposed.ids) && change.proposed.ids.length === state.editor.montage.order.length
      && new Set(change.proposed.ids).size === change.proposed.ids.length && change.proposed.ids.every(id => state.editor.montage.order.includes(id));
    if (change.key.startsWith("photo:") && m && !m.is_video) return typeof change.proposed.seconds === "number" && Number.isFinite(change.proposed.seconds) && change.proposed.seconds >= 1 / 25;
    if (change.key.startsWith("video:") && m?.is_video) return Array.isArray(change.proposed.ranges) && change.proposed.ranges.every((r, i, rows) => record(r)
      && typeof r.start === "number" && typeof r.end === "number" && r.start >= 0 && r.end > r.start && r.end <= (m.source_duration ?? 0)
      && (i === 0 || r.start >= rows[i - 1].end));
    return false;
  });
}
export async function handleDemoRequest(state: DemoState, path: string, init: RequestInit, signal: AbortSignal): Promise<Response> {
  signal.throwIfAborted();
  const url = new URL(path, window.location.origin), p = url.pathname, method = init.method ?? "GET";
  let body: Record<string, unknown> = {};
  if (typeof init.body === "string") {
    try { const parsed: unknown = JSON.parse(init.body); if (!record(parsed)) return error("Object required"); body = parsed; }
    catch { return error("Invalid JSON"); }
  }
  const mediaResponse = handleDemoMedia(state, url, init, body);
  if (mediaResponse) {
    if (mediaResponse.ok && method !== "GET") notifyDemo(state);
    return mediaResponse;
  }
  if (method === "GET") {
    if (p === "/api/events") return demoEvents(state, signal);
    const reads: Record<string, unknown> = {
      "/api/compat": { api_version: CONTRACT_VERSION }, "/api/pairing/me": state.client,
      "/api/dashboard": state.dashboard, "/api/activity": state.activity, "/api/setup": state.setup,
      "/api/setup/consent": state.consent, "/api/settings/branding": state.branding, "/api/settings/plan": state.plan,
      "/api/settings/reminders": state.reminders, "/api/meta/status": state.instagram,
      "/api/packages": state.packages, "/api/media/upload-limits": { max_file_bytes: 50 * 1024 * 1024, max_package_bytes: 200 * 1024 * 1024, active_package_id: state.dashboard.package?.id ?? null },
    };
    if (p in reads) return json(reads[p]);
    if (p === "/api/packages/active/editor") return state.dashboard.package ? json(state.editor) : error("No active package", 404);
    const review = p.match(/^\/api\/reviews\/(\d+)$/);
    if (review) return state.reviews.has(+review[1]) ? json(state.reviews.get(+review[1])) : error("Review not found", 404);
    const completed = p.match(/^\/api\/packages\/([^/]+)$/);
    if (completed) { const value = state.completed.find(v => v.folder_name === decodeURIComponent(completed[1])); return value ? json(value) : error("Package not found", 404); }
  }
  if (p === "/api/settings/branding" && method === "PATCH") {
    if (Object.keys(body).some(key => !["caption_template", "logo_asset", "intro_asset", "outro_asset", "intro_duration", "outro_duration"].includes(key))) return error("Unknown branding field");
    for (const [key, value] of Object.entries(body)) {
      if (key.endsWith("duration") ? value !== null && (typeof value !== "number" || value < 0 || value > 10) : value !== null && typeof value !== "string") return error("Invalid branding value");
      if (key === "caption_template" && (typeof value !== "string" || !value.trim())) return error("Caption required");
      if (key.endsWith("asset") && value !== null && (typeof value !== "string" || !value.startsWith("/demo/") && !value.startsWith("blob:"))) return error("Demo asset required");
    }
    Object.assign(state.branding, body as BrandingPatchIn); return changed(state, state.branding);
  }
  if (p === "/api/settings/plan" && method === "PUT") {
    if (typeof body.enabled !== "boolean" || typeof body.anchor_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(body.anchor_date)
      || typeof body.anchor_time !== "string" || !/^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(body.anchor_time)) return error("Invalid plan");
    const date = new Date(`${body.anchor_date}T12:00:00Z`);
    if (Number.isNaN(date.getTime()) || date.getUTCDay() !== 1) return error("Monday required");
    Object.assign(state.plan, body);
    state.dashboard.next_slots = state.dashboard.next_slots?.filter(slot => slot.kind !== "regular") ?? [];
    state.dashboard.next_slot = null;
    if (state.plan.enabled) {
      let due = Date.parse(`${state.plan.anchor_date}T${state.plan.anchor_time!.length === 5 ? state.plan.anchor_time + ":00" : state.plan.anchor_time}+03:00`);
      if (!Number.isFinite(due)) return error("Invalid plan");
      const period = 14 * 86400000;
      if (due <= Date.now()) due += (Math.floor((Date.now() - due) / period) + 1) * period;
      const regular = { kind: "regular", occurrence_id: 4, due_at: new Date(due).toISOString() };
      state.dashboard.next_slots.push(regular); state.dashboard.next_slot = regular;
    }
    for (const detail of state.reviews.values()) detail.next_regular_at = state.dashboard.next_slot?.due_at ?? null;
    return changed(state, state.plan);
  }
  if (p === "/api/settings/reminders" && method === "PUT") {
    if (!Number.isInteger(body.interval_minutes) || Number(body.interval_minutes) < 15 || Number(body.interval_minutes) > 1440
      || typeof body.delivery_start !== "string" || typeof body.delivery_end !== "string"
      || ![body.delivery_start, body.delivery_end].every(t => /^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(t))
      || body.delivery_start >= body.delivery_end || body.timezone !== undefined && body.timezone !== "Europe/Istanbul") return error("Invalid reminders");
    Object.assign(state.reminders, body); return changed(state, state.reminders);
  }
  if (p === "/api/setup/consent/accept" && method === "POST") {
    if (body.version !== state.consent.version) return error("Consent changed", 409);
    state.consent.accepted_at = new Date().toISOString(); return changed(state, { version: state.consent.version, accepted_at: state.consent.accepted_at });
  }
  if (p === "/api/setup/cards/skip" && method === "POST") return changed(state, state.setup);
  if (p === "/api/packages/active/edits" && method === "PUT") {
    if (body.expected_package_id !== state.editor.package.id || body.expected_folder_name !== state.editor.package.folder_name
      || body.base_content_revision !== state.editor.content_revision) return error("Package changed", 409);
    const edits = body as unknown as PackageEditIn;
    if (!validEdits(state, edits.changes)) return error("Invalid edits");
    for (const change of edits.changes) {
      const id = change.key.slice(change.key.indexOf(":") + 1);
      if (change.key === "order") state.editor.montage.order = change.proposed.ids as string[];
      if (change.key.startsWith("photo:")) state.editor.media.find(m => m.media_id === id)!.effective_duration = change.proposed.seconds as number;
      if (change.key.startsWith("video:")) state.editor.montage.selections[id] = change.proposed.ranges as { start: number; end: number }[];
    }
    refreshMontage(state); return changed(state, state.editor, "package.edited");
  }
  const media = p.match(/^\/api\/packages\/active\/media\/([^/]+)\/(remove|restore)$/);
  if (["/api/packages/active/order", "/api/packages/active/selections"].includes(p) && method === "PUT") {
    if (body.expected_folder_name !== state.editor.package.folder_name || new Headers(init.headers).get("If-Match") !== `"${state.editor.package.id}:${state.editor.content_revision}"`) return error("Package changed", 409);
    const changes = p.endsWith("order") ? [{ key: "order", base: {}, proposed: { ids: body.order } }]
      : record(body.selections) ? Object.entries(body.selections).map(([id, ranges]) => ({ key: `video:${id}`, base: {}, proposed: { ranges } })) : null;
    if (!changes || !validEdits(state, changes)) return error("Invalid montage");
    if (p.endsWith("order")) state.editor.montage.order = body.order as string[];
    else {
      if (body.photo_durations !== undefined) {
        if (!record(body.photo_durations) || Object.entries(body.photo_durations).some(([id, seconds]) => typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 1 / 25 || !state.editor.media.some(m => m.media_id === id && !m.is_video))) return error("Invalid durations");
        for (const [id, seconds] of Object.entries(body.photo_durations)) state.editor.media.find(m => m.media_id === id)!.effective_duration = seconds as number;
      }
      state.editor.montage.selections = body.selections as Record<string, { start: number; end: number }[]>;
    }
    refreshMontage(state); return changed(state, state.editor.montage, "package.edited");
  }
  if (media && method === "POST") {
    const m = state.editor.media.find(m => m.media_id === decodeURIComponent(media[1]));
    if (!m) return error("Media not found", 404);
    if (new Headers(init.headers).get("If-Match") !== `"${state.editor.package.id}:${state.editor.content_revision}"`
      || url.searchParams.get("expected_folder_name") !== state.editor.package.folder_name) return error("Package changed", 409);
    m.status = media[2] === "remove" ? "removed" : "finalized";
    refreshMontage(state); return changed(state, state.editor.montage, "media.updated");
  }
  if (p === "/api/packages/active/clear" && method === "POST") {
    if (body.confirmed !== true || body.expected_package_id !== state.editor.package.id || body.expected_folder_name !== state.editor.package.folder_name
      || new Headers(init.headers).get("If-Match") !== `"${state.editor.package.id}:${state.editor.content_revision}"`) return error("Confirmation or package changed", 409);
    state.dashboard.package = null; state.dashboard.pending_actions = [];
    cancelPackageReviews(state, state.editor.package.folder_name);
    const upload_ids = [...state.uploads.keys()]; state.uploads.clear();
    return changed(state, { folder_name: state.editor.package.folder_name, upload_ids }, "package.cleared");
  }
  const decision = p.match(/^\/api\/reviews\/(\d+)\/(approve|skip|reschedule)$/);
  if (decision && method === "POST") {
    const detail = state.reviews.get(+decision[1]);
    if (!detail) return error("Review not found", 404);
    if (!["pending", "failed"].includes(detail.review.status) || body.version !== detail.review.version) return error("Review already handled or changed", 409);
    if (detail.review.package_folder !== state.dashboard.package?.folder_name || detail.review.package_folder !== state.editor.package.folder_name) return error("Review package changed", 409);
    const action = decision[2];
    if (action === "skip" && body.confirmed !== true || action === "reschedule" && !future(body.new_due_at, detail.next_regular_at)) return error("Invalid decision");
    if (action === "approve" && (!detail.render_ready || state.editor.render_stale)) return error("Render changed", 409);
    detail.review.status = action === "approve" ? "approved" : action === "skip" ? "skipped" : "rescheduled"; detail.review.version++;
    state.dashboard.pending_actions = state.dashboard.pending_actions.filter(v => v.review_id !== detail.review.id);
    if (action === "approve") {
      state.completed.unshift(completedDetail(state.editor, detail.review.caption ?? "Demo"));
      state.packages.unshift({ ...state.editor.package, status: "completed" }); state.dashboard.package = null;
      cancelPackageReviews(state, state.editor.package.folder_name);
    }
    if (action === "reschedule") state.dashboard.next_slots?.unshift({ kind: "oneoff", occurrence_id: detail.review.occurrence_id, due_at: body.new_due_at as string });
    return changed(state, action === "approve" ? { publication: { status: "published", error: null } } : { next_regular_at: detail.next_regular_at }, `review.${detail.review.status}`);
  }
  const occurrence = p.match(/^\/api\/dashboard\/occurrences\/(\d+)(\/decision)?$/);
  if (occurrence && (method === "PATCH" || method === "POST" && occurrence[2])) {
    const slot = state.dashboard.next_slots?.find(s => s.occurrence_id === +occurrence[1]);
    if (!slot || body.expected_due_at !== slot.due_at) return error("Occurrence changed", 409);
    if (method === "PATCH") {
      if (!future(body.new_due_at, state.dashboard.next_slot?.due_at)) return error("Invalid date");
      slot.due_at = body.new_due_at as string; return changed(state, slot);
    }
    if (!["review", "skip"].includes(String(body.action)) || body.action === "skip" && body.confirmed !== true) return error("Invalid occurrence decision");
    state.dashboard.next_slots = state.dashboard.next_slots!.filter(v => v !== slot);
    if (body.action === "review") createReview(state, +occurrence[1]);
    return changed(state, { ...slot, status: body.action === "review" ? "pending" : "skipped", package_folder: state.dashboard.package?.folder_name ?? null });
  }
  if (p === "/api/settings/manual-publish" && method === "POST") {
    const id = Math.max(...state.reviews.keys(), 4) + 1; createReview(state, id); return changed(state, { id });
  }
  return error("Unknown demo operation", 404);
}
function cancelPackageReviews(state: DemoState, folder: string) {
  for (const detail of state.reviews.values()) if (detail.review.package_folder === folder && ["pending", "failed"].includes(detail.review.status)) {
    detail.review.status = "cancelled"; detail.review.version++;
  }
  state.dashboard.pending_actions = state.dashboard.pending_actions.filter(action => action.package_folder !== folder);
}
function demoEvents(state: DemoState, signal: AbortSignal): Response {
  let cleanup = () => {};
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const emit = (event: string, data: unknown) => controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
      const listener = (versions: Record<string, number>) => emit("change", { event_id: `demo-${Date.now()}`, versions });
      const heartbeat = setInterval(() => emit("heartbeat", {}), 15000);
      const abort = () => { cleanup(); controller.close(); };
      cleanup = () => { clearInterval(heartbeat); state.listeners.delete(listener); signal.removeEventListener("abort", abort); };
      state.listeners.add(listener); signal.addEventListener("abort", abort, { once: true });
      emit("ready", { protocol: 1 });
    },
    cancel() { cleanup(); },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
}
function createReview(state: DemoState, id: number) {
  state.reviews.set(id, { review: { id, occurrence_id: id, package_folder: state.editor.package.folder_name, caption: state.branding.caption_template,
    status: "pending", version: 1, created_at: new Date().toISOString(), revision_digest: `demo-${state.editor.content_revision}` }, next_regular_at: state.dashboard.next_slot?.due_at ?? null, render_ready: true, preview_url: VIDEO });
  state.dashboard.pending_actions.push({ review_id: id, occurrence_id: id, version: 1, state: "review_ready", package_folder: state.editor.package.folder_name,
    due_at: new Date().toISOString() });
}
