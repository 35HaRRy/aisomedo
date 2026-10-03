import type { ActiveEditorOut, ClientOut, DashboardOut, SetupOut } from "../api/openapi";

export function setupState(unfinished?: string): SetupOut {
  return { ready: !unfinished, checklist: ["pairing", "instagram", "schedule", "consent", "logo", "caption_template", "cards"].map(key => ({ key, label: key, complete: key !== unfinished && key !== "cards", required: key !== "cards" })) };
}

export const client: ClientOut = {
  id: 1, name: "Dojo bilgisayarı", kind: "browser", created_at: "2026-08-03T07:00:00Z",
  created_by: "cli", last_seen_at: null, revoked_at: null,
};
export function dashboard(): DashboardOut {
  return {
    generated_at: "2026-08-03T07:00:00Z",
    package: { id: 1, folder_name: "03-08-2026 10-00", created_at: "2026-08-03T07:00:00Z", status: "active" },
    next_slot: { kind: "regular", due_at: "2026-08-17T07:00:00Z" },
    pending_actions: [],
    plan: { anchor_date: "2026-08-03", anchor_time: "10:00:00", enabled: true, timezone: "Europe/Istanbul" },
    instagram: { health: "healthy", username: "dojo" },
    worker: { status: "healthy", phase: "idle" },
  };
}

export function emptyEditor(): ActiveEditorOut {
  return { package: dashboard().package!, render_stale: true, media: [], montage: {
    order: [], trims: {}, selections: {}, clips: [], combined_duration: 0,
    max_duration_seconds: 90, over_limit: false, required_action: null,
    card_duration: 0, duration_complete: true,
  } };
}
