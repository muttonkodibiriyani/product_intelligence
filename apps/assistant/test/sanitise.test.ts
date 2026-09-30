import { describe, expect, it } from "vitest";

import { sanitiseData } from "../src/guard/sanitise.js";

const hosts = ["shop.example"];

describe("sanitiseData", () => {
  it("keeps decimals, dates, colours and structural identifiers", () => {
    expect(
      sanitiseData(
        {
          price: "12.50",
          date: "2026-09-15",
          at: "2026-09-15T08:00:00Z",
          hex: "#aa1122",
          status: "ok",
          retailer: "north",
          count: 3,
          flag: true,
          none: null,
        },
        hosts,
      ),
    ).toEqual({
      price: "12.50",
      date: "2026-09-15",
      at: "2026-09-15T08:00:00Z",
      hex: "#aa1122",
      status: "ok",
      retailer: "north",
      count: 3,
      flag: true,
      none: null,
    });
  });

  it("wraps every other string, including unknown new fields", () => {
    expect(sanitiseData({ newField: "hello *world*", status: "not ok!" }, hosts)).toEqual({
      newField: { untrusted: "hello \\*world\\*" },
      status: { untrusted: "not ok\\!" },
    });
  });

  it("always wraps source-text keys, even numeric-looking values", () => {
    expect(sanitiseData({ name: "50", brand: "2026-01-01" }, hosts)).toEqual({
      name: { untrusted: "50" },
      brand: { untrusted: "2026-01-01" },
    });
  });

  it("filters URLs", () => {
    expect(
      sanitiseData({ url: "https://evil.example/", imageUrl: "https://shop.example/i.png" }, hosts),
    ).toEqual({ url: null, imageUrl: "https://shop.example/i.png" });
  });

  it("re-sanitises pre-wrapped values and drops text-shaped keys", () => {
    expect(
      sanitiseData({ x: { untrusted: "<b>" }, "Aurel Cream": 3, ok_key: [1, "a"] }, hosts),
    ).toEqual({ x: { untrusted: "\\<b\\>" }, ok_key: [1, { untrusted: "a" }] });
  });

  it("bounds depth and drops non-JSON values", () => {
    let deep: unknown = "leaf";
    for (let i = 0; i < 12; i += 1) deep = { d: deep };
    expect(JSON.stringify(sanitiseData(deep, hosts))).not.toContain("leaf");
    expect(sanitiseData(Number.POSITIVE_INFINITY, hosts)).toBeNull();
    expect(sanitiseData(() => 1, hosts)).toBeNull();
  });
});
