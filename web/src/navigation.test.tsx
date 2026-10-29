import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useNavigation } from "./navigation";

it("keeps demo prefix and query through guarded navigation and cancels Back", async () => {
  window.location.hash = "#/demo/package?review=7";
  let allowed = true;
  const { result, unmount } = renderHook(() => useNavigation(async () => allowed));
  expect(result.current.reviewId).toBe(7);
  await act(async () => { await result.current.navigate("#/settings"); });
  expect(window.location.hash).toBe("#/demo/settings");
  allowed = false;
  await act(async () => { window.location.hash = "#/demo/package"; window.dispatchEvent(new Event("hashchange")); });
  expect(window.location.hash).toBe("#/demo/settings");
  expect(result.current.area).toBe("settings");
  unmount(); window.location.hash = "";
});
