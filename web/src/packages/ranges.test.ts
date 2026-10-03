import { expect, it } from "vitest";
import { addRangeAtPlayhead, proposedDuration, retainedDuration, validateRanges } from "./ranges";
import { packageSnapshot } from "./testFixtures";

it("retains approved source windows for sixteen seconds", () => {
  const ranges = [{ start: 0, end: 5 }, { start: 10, end: 15 }, { start: 24, end: 30 }];
  expect(retainedDuration(ranges, 30)).toBe(16);
  const snapshot = packageSnapshot(); snapshot.media = [snapshot.media[0]];
  expect(proposedDuration(snapshot, { a: ranges })).toBe(16);
});

it("whole-video mode and photos/cards use authoritative durations, removed media is excluded", () => {
  const snapshot = packageSnapshot();
  snapshot.media[1] = { ...snapshot.media[1], is_video: false, effective_duration: 3 };
  snapshot.montage.card_duration = 2;
  expect(proposedDuration(snapshot, {})).toBe(35);
  snapshot.media[0].status = "removed";
  expect(proposedDuration(snapshot, {})).toBe(5);
  expect(retainedDuration([], 30)).toBe(30);
});

it.each([
  [{ start: 0, end: 0.01 }], [{ start: -1, end: 5 }], [{ start: 5, end: 5 }],
  [{ start: 0, end: 31 }], [{ start: NaN, end: 2 }], [{ start: 0, end: Infinity }],
  [{ start: 0, end: 5 }, { start: 4, end: 6 }],
].map(ranges => [ranges]))("rejects invalid or overlapping ranges %j", ranges => expect(validateRanges(ranges, 30)).not.toBeNull());

it("accepts adjacency and one-frame arithmetic roundoff", () => {
  expect(validateRanges([{ start: 10, end: 10.04 }, { start: 10.04, end: 11 }], 30)).toBeNull();
});

it("unknown duration or invalid selections never invent a total", () => {
  const snapshot = packageSnapshot(); snapshot.media[0].source_duration = null;
  expect(proposedDuration(snapshot, {})).toBeNull();
  snapshot.media[0].source_duration = 30;
  expect(proposedDuration(snapshot, { a: [{ start: 0, end: 31 }] })).toBeNull();
});

it("adds at playhead only within a usable unselected gap", () => {
  const ranges = [{ start: 0, end: 5 }, { start: 10, end: 15 }];
  expect(addRangeAtPlayhead(ranges, 7, 30)).toEqual([ranges[0], { start: 7, end: 8 }, ranges[1]]);
  expect(addRangeAtPlayhead(ranges, 9.5, 30)).toEqual([ranges[0], { start: 9.5, end: 10 }, ranges[1]]);
  expect(addRangeAtPlayhead(ranges, 3, 30)).toBeNull();
  expect(addRangeAtPlayhead([], 29.99, 30)).toBeNull();
  expect(addRangeAtPlayhead([], 29.96, 30)).toEqual([{ start: 29.96, end: 30 }]);
});
