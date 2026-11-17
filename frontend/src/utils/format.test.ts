import { describe, expect, it } from "vitest";

import { diffObjects, shortId, toCsvSafe } from "./format";

describe("diffObjects", () => {
  it("returns only changed fields, sorted", () => {
    expect(diffObjects({ a: 1, b: 2, c: { x: 1 } }, { a: 1, b: 3, c: { x: 2 }, d: true })).toEqual([
      { field: "b", before: 2, after: 3 },
      { field: "c", before: { x: 1 }, after: { x: 2 } },
      { field: "d", before: undefined, after: true },
    ]);
  });
  it("handles null snapshots", () => {
    expect(diffObjects(null, { a: 1 })).toEqual([{ field: "a", before: undefined, after: 1 }]);
  });
});

describe("helpers", () => {
  it("shortId", () => expect(shortId("12345678-aaaa")).toBe("12345678"));
  it("guards CSV injection", () => expect(toCsvSafe("=cmd()")).toBe("'=cmd()"));
});
