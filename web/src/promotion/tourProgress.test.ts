import { beforeEach, expect, it, vi } from "vitest";
import { readTourProgress, resetTourProgress, writeTourProgress } from "./tourProgress";

beforeEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

it("persists completed steps, dismissed tours and skip-all separately per paired client", () => {
  writeTourProgress(901, { version: 1, completed: ["dashboard.overview"], dismissed: ["package"], skipAll: true });
  expect(readTourProgress(901)).toEqual({ version: 1, completed: ["dashboard.overview"], dismissed: ["package"], skipAll: true });
  expect(readTourProgress(902).skipAll).toBe(false);
  resetTourProgress(901);
  expect(readTourProgress(901)).toEqual({ version: 1, completed: [], dismissed: [], skipAll: false });
});

it.each(['broken', '{"version":2}', '{"version":1,"completed":[4],"dismissed":[],"skipAll":false}', '{"version":1,"completed":[],"dismissed":[],"skipAll":"yes"}'])("ignores corrupt or incompatible state: %s", raw => {
  localStorage.setItem("aisomedo:promotion:v1:903", raw);
  expect(readTourProgress(903)).toEqual({ version: 1, completed: [], dismissed: [], skipAll: false });
});

it("keeps session suppression when storage reads and writes are denied", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
  writeTourProgress(904, { version: 1, completed: [], dismissed: [], skipAll: true });
  expect(readTourProgress(904).skipAll).toBe(true);
  resetTourProgress(904);
  expect(readTourProgress(904).skipAll).toBe(false);
});

it("keeps the new preference if writes fail but reads still succeed", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
  writeTourProgress(905, { version: 1, completed: [], dismissed: [], skipAll: true });
  expect(readTourProgress(905).skipAll).toBe(true);
});
