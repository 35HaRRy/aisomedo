import { expect, it } from "vitest";
import { firstIncompleteRequired } from "./state";

it("selects first required incomplete step from backend checklist", () => {
  expect(firstIncompleteRequired([
    { key: "pairing", label: "", complete: true, required: true },
    { key: "instagram", label: "", complete: false, required: true },
    { key: "consent", label: "", complete: false, required: true },
  ])).toBe("instagram");
});
it("does not require optional cards", () => {
  expect(firstIncompleteRequired([{ key: "cards", label: "", complete: false, required: false }])).toBeNull();
});
