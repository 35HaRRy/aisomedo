import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ActivitySummary } from "./ActivitySummary";

it("shows overwrite filename and removed target in audit, safely as text", () => {
  render(<ActivitySummary data={{ next_cursor: null, events: [{ id: 1, action: "media.overwritten", actor: "worker",
    occurred_at: "2026-10-01T07:00:00Z", details: { filename: "<script>dojo.jpg</script>", target_media_id: "old-media", media_id: "new-media" } }] }} />);
  expect(screen.getByRole("heading", { name: "Mevcut medyanın üzerine yazıldı" })).toBeInTheDocument();
  expect(screen.getByText("<script>dojo.jpg</script>")).toBeInTheDocument();
  expect(screen.getByText(/old-media/)).toBeInTheDocument();
  expect(screen.getByText(/new-media/)).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
});
