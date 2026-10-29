import type { UploadInitIn } from "../api/openapi";
import { demoMedia, VIDEO, type DemoState } from "./seed";
import { registerDemoFile } from "./assets";

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const error = (detail: string, status = 422) => json({ detail }, status);
export function handleDemoMedia(state: DemoState, url: URL, init: RequestInit, body: Record<string, unknown>): Response | null {
  const p = url.pathname, method = init.method ?? "GET";
  if (p === "/api/settings/branding/assets" && method === "POST") {
    if (!(init.body instanceof Blob) || init.body.size > 10 * 1024 * 1024 || !/^(image\/(png|jpeg)|video\/)/.test(init.body.type)) return error("Invalid asset");
    const asset = registerDemoFile(init.body); return json({ asset, preview_url: asset });
  }
  if (p === "/api/media/uploads" && method === "POST") {
    if (typeof body.filename !== "string" || !body.filename.trim() || typeof body.content_type !== "string" || !/^(image|video)\//.test(body.content_type)
      || !Number.isSafeInteger(body.declared_size_bytes) || Number(body.declared_size_bytes) <= 0 || Number(body.declared_size_bytes) > 50 * 1024 * 1024) return error("Invalid upload");
    if (body.expected_package_id != null && body.expected_package_id !== state.dashboard.package?.id) return error("Package changed", 409);
    if ([...state.uploads.values()].reduce((sum, u) => sum + u.declared_size_bytes, 0) + Number(body.declared_size_bytes) > 200 * 1024 * 1024) return error("Package capacity exceeded", 413);
    if (!state.dashboard.package) {
      state.editor.package = { id: state.editor.package.id + 10, folder_name: `Demo · Yeni Paket ${state.editor.package.id + 10}`, created_at: new Date().toISOString(), status: "active" };
      state.dashboard.package = state.editor.package; state.editor.media = []; state.editor.montage.order = []; state.editor.montage.clips = [];
      state.editor.montage.combined_duration = 0; state.editor.render_status = "missing"; state.editor.render_stale = true;
    }
    const id = `demo-upload-${state.uploads.size + 1}`;
    const conflicts = state.editor.media.filter(m => m.status === "finalized" && m.filename === body.filename).map(m => ({ ...m, processed: { content_type: m.is_video ? "video/mp4" : "image/jpeg" } }));
    const upload = { upload_id: id, declared_size_bytes: Number(body.declared_size_bytes), received_bytes: 0, received_ranges: [],
      status: conflicts.length ? "conflict" : "receiving", package_id: state.editor.package.id, conflicts };
    state.uploads.set(id, upload); state.uploadInputs.set(id, body as UploadInitIn); state.uploadData.set(id, []);
    return json(upload);
  }
  const uploadPath = p.match(/^\/api\/media\/uploads\/([^/]+)(?:\/(ranges|complete|resolve))?$/);
  if (uploadPath) {
    const id = decodeURIComponent(uploadPath[1]), upload = state.uploads.get(id), input = state.uploadInputs.get(id);
    if (!upload || !input) return error("Upload not found", 404);
    if (method === "GET" && !uploadPath[2]) return json(upload);
    if (method === "POST" && uploadPath[2] === "resolve") {
      if (upload.status !== "conflict") return error("Conflict changed", 409);
      if (!["keep_both", "keep_selected", "keep_target"].includes(String(body.decision))) return error("Invalid conflict decision");
      if (body.decision === "keep_selected") {
        if (body.confirmed_overwrite !== true || !upload.conflicts?.some(m => m.media_id === body.target_media_id)) return error("Confirmation required");
        state.editor.media = state.editor.media.filter(m => m.media_id !== body.target_media_id);
        state.editor.montage.order = state.editor.montage.order.filter(id => id !== body.target_media_id);
      }
      upload.status = body.decision === "keep_target" ? "skipped" : "receiving"; upload.conflicts = [];
      return json(upload);
    }
    if (method === "PUT" && uploadPath[2] === "ranges") {
      if (upload.status !== "receiving" || Number(url.searchParams.get("offset")) !== upload.received_bytes) return error("Offset changed", 409);
      if (!(init.body instanceof Blob) || !init.body.size || upload.received_bytes + init.body.size > upload.declared_size_bytes
        || !/^[a-f0-9]{64}$/.test(url.searchParams.get("checksum_sha256") ?? "")) return error("Invalid chunk");
      state.uploadData.get(id)!.push(init.body);
      const offset = upload.received_bytes; upload.received_bytes += init.body.size; upload.received_ranges.push([offset, upload.received_bytes]);
      return json(upload);
    }
    if (method === "POST" && uploadPath[2] === "complete") {
      if (upload.status === "finalized") return json(upload);
      if (upload.status !== "receiving" || upload.received_bytes !== upload.declared_size_bytes) return error("Incomplete upload", 409);
      const media = demoMedia(id, input.content_type.startsWith("video/"), new Date().toISOString());
      const blob = new Blob(state.uploadData.get(id), { type: input.content_type });
      const preview = typeof URL.createObjectURL === "function" ? registerDemoFile(blob) : media.preview_url!;
      media.filename = input.filename; media.content_type = input.content_type; media.size_bytes = input.declared_size_bytes;
      media.preview_url = preview; media.original_url = preview; media.processed.content_type = input.content_type;
      media.artifacts = [{ kind: "original", available: true, filename: input.filename, content_type: input.content_type, url: preview, preview_url: preview, artifact_ref: id }];
      state.editor.media.push(media); state.editor.montage.order.push(id);
      state.editor.montage.clips.push({ media_id: id, filename: input.filename, content_type: input.content_type, is_video: media.is_video,
        source_duration: media.source_duration, effective_duration: media.effective_duration! });
      state.editor.montage.combined_duration += media.effective_duration!; state.editor.montage.over_limit = state.editor.montage.combined_duration > 90;
      state.editor.content_revision++; state.editor.view_revision++; state.editor.render_stale = true; state.editor.render_status = "stale";
      upload.status = "finalized"; state.uploadData.delete(id); return json(upload);
    }
  }
  if (p === "/api/packages/active/render" && method === "POST") {
    if (body.expected_folder_name !== state.editor.package.folder_name || new Headers(init.headers).get("If-Match") !== `"${state.editor.package.id}:${state.editor.content_revision}"`) return error("Package changed", 409);
    if (!state.editor.montage.order.length || state.editor.montage.over_limit) return error("Invalid montage");
    state.editor.render_revision = `demo-render-${state.editor.content_revision}`; state.editor.render_status = "ready";
    state.editor.render_stale = false; state.editor.render_preview_url = VIDEO; state.editor.render_duration = 6; state.editor.view_revision++;
    for (const detail of state.reviews.values()) if (detail.review.status === "pending" && detail.review.package_folder === state.editor.package.folder_name) {
      detail.render_ready = true; detail.preview_url = VIDEO; detail.review.revision_digest = state.editor.render_revision;
    }
    return json({ render_revision: state.editor.render_revision, stale: false });
  }
  const section = p.match(/^\/api\/packages\/active\/media\/([^/]+)\/sections\/retry$/);
  if (section && method === "POST") {
    const m = state.editor.media.find(m => m.media_id === decodeURIComponent(section[1]));
    if (!m?.is_video || body.expected_package_id !== state.editor.package.id || body.expected_folder_name !== state.editor.package.folder_name
      || body.expected_generation !== m.section_preview?.generation) return error("Section changed", 409);
    m.section_preview = { generation: `demo-${state.editor.content_revision}`, duration: m.effective_duration, status: "ready", url: VIDEO };
    return json(state.editor);
  }
  if (p === "/api/meta/oauth/start" && method === "POST") return json({ attempt_id: "demo-attempt", auth_url: "https://demo.invalid/" });
  if (p === "/api/meta/oauth/attempts/demo-attempt" && method === "GET") return json({ id: "demo-attempt", status: "completed", candidates: state.candidates });
  if (p === "/api/meta/oauth/attempts/demo-attempt/select" && method === "POST" || p === "/api/meta/instagram/token" && method === "POST") {
    const candidate = state.candidates.find(c => c.ig_user_id === body.ig_user_id) ?? (p.endsWith("token") ? state.candidates[0] : undefined);
    if (!candidate) return error("Unknown demo account");
    state.instagram = { health: "healthy", ig_username: candidate.ig_username, ig_user_id: candidate.ig_user_id, connection_type: "demo" };
    state.dashboard.instagram = { health: "healthy", username: candidate.ig_username }; return json(state.instagram);
  }
  return null;
}
