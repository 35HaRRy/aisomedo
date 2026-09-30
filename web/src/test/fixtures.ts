import type { ClientOut, DashboardOut } from "../api/openapi";

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
