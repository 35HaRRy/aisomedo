import { useLayoutEffect } from "react";
import { act, render, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useDraft } from "./forms";

it("hydrates untouched fields before a loaded form becomes editable", () => {
  const editableIntervals: string[] = [];
  function Form({ source }: { source: { interval: string; start: string } | null }) {
    const state = useDraft(source, { interval: "", start: "" });
    useLayoutEffect(() => {
      if (source) editableIntervals.push(state.draft.interval);
    });
    return <input disabled={!source} value={state.draft.interval} readOnly />;
  }
  const view = render(<Form source={null} />);
  view.rerender(<Form source={{ interval: "360", start: "08:00" }} />);
  expect(editableIntervals.length).toBeGreaterThan(0);
  expect(editableIntervals.every(value => value === "360")).toBe(true);
});

it("preserves edits across source updates until explicitly reloaded", () => {
  const { result, rerender } = renderHook(({ source }) => useDraft(source, { interval: "", start: "" }), {
    initialProps: { source: { interval: "360", start: "08:00" } },
  });
  act(() => result.current.edit({ ...result.current.draft, start: "06:00" }));
  rerender({ source: { interval: "180", start: "09:00" } });
  expect(result.current.draft).toEqual({ interval: "360", start: "06:00" });
  expect(result.current.changed).toBe(true);
  act(() => result.current.reload());
  expect(result.current.draft).toEqual({ interval: "180", start: "09:00" });
  expect(result.current.changed).toBe(false);
});
