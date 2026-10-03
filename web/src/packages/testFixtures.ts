import type { ActiveEditorOut, EditorMediaOut } from "../api/openapi";
import { client } from "../test/fixtures";

export function packageSnapshot(): ActiveEditorOut {
  const media: EditorMediaOut[] = ["a", "b"].map(id => ({
    media_id: id, filename: `${id}.mp4`, content_type: "video/mp4", size_bytes: 100,
    uploaded_at: "2026-10-02T10:00:00Z", status: "finalized", processed: { duration: 30 },
    is_video: true, source_duration: 30, effective_duration: 30,
    preview_url: `/api/packages/active/media/${id}/preview?expected_folder_name=02-10-2026%2013-00`,
    artifacts: [],
  }));
  return {
    package: { id: 1, folder_name: "02-10-2026 13-00", created_at: "2026-10-02T10:00:00Z", status: "active" },
    render_stale: false, media,
    montage: {
      order: ["a", "b"], selections: {}, trims: {}, clips: media.map(m => ({
        media_id: m.media_id, filename: m.filename, content_type: m.content_type,
        is_video: true, source_duration: 30, effective_duration: 30,
      })), combined_duration: 60, max_duration_seconds: 90, over_limit: false,
      required_action: null, card_duration: 0, duration_complete: true,
    },
  };
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

export function editorServer() {
  let snapshot = packageSnapshot();
  let writeStatus = 200;
  let pendingRead: Promise<Response> | null = null;
  const writes: { url: string; body: unknown }[] = [];
  const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
  const fetcher = async (url: string, init: RequestInit = {}) => {
    if (url === "/api/pairing/me") return json(client);
    if (url === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
    if (url === "/api/packages/active/editor") {
      if (pendingRead) { const read = pendingRead; pendingRead = null; return read; }
      return json(snapshot);
    }
    if (url.startsWith("/api/packages/active/")) {
      const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      writes.push({ url, body });
      if (writeStatus === 0) throw new TypeError("connection lost");
      if (writeStatus !== 200) return json({ detail: "fixture failure" }, writeStatus);
      if (url.endsWith("/selections")) snapshot.montage.selections = body.selections;
      if (url.endsWith("/order")) snapshot.montage.order = body.order;
      for (const media of snapshot.media) {
        if (url.includes(`/media/${media.media_id}/remove`)) media.status = "removed";
        if (url.includes(`/media/${media.media_id}/restore`)) media.status = "finalized";
      }
      snapshot.montage.order = snapshot.montage.order.filter(id => snapshot.media.some(m => m.media_id === id && m.status === "finalized"));
      for (const media of snapshot.media.filter(m => m.status === "finalized")) {
        if (!snapshot.montage.order.includes(media.media_id)) snapshot.montage.order.push(media.media_id);
      }
      snapshot.render_stale = true;
      return json(snapshot.montage);
    }
    throw new Error(`Unexpected editor request: ${url}`);
  };
  return {
    fetcher, writes, json,
    get snapshot() { return snapshot; },
    set snapshot(value: ActiveEditorOut) { snapshot = value; },
    set writeStatus(value: number) { writeStatus = value; },
    set pendingRead(value: Promise<Response>) { pendingRead = value; },
  };
}
