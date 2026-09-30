import { describe, expect, it } from "vitest";

import {
  TOOLS,
  assortmentGaps,
  compare,
  coverageStatus,
  getProduct,
  indexTrend,
  reviewsSummary,
  searchProducts,
  toQuery,
} from "../src/tools/definitions.js";

describe("tool definitions", () => {
  it("has nine uniquely named, viewer-level, read-only tools", () => {
    expect(TOOLS.map((tool) => tool.name)).toEqual([
      "search_products",
      "get_product",
      "compare",
      "index_trend",
      "promotions",
      "assortment_gaps",
      "launches",
      "reviews_summary",
      "coverage_status",
    ]);
    for (const tool of TOOLS) {
      expect(tool.minRole).toBe("viewer");
      const request = tool.request(
        tool.input.parse(tool.name === "get_product" ? { id: "p1" } : {}) as never,
      );
      expect(request.path.startsWith("/v1/")).toBe(true);
      // The only POST is compare, which is a read with a structured body.
      expect(request.method === "GET" || tool.name === "compare").toBe(true);
    }
  });

  it("maps inputs to requests", () => {
    expect(
      searchProducts.request(
        searchProducts.input.parse({ q: "cream", brand: ["A", "B"], priceMax: "99.50" }),
      ),
    ).toEqual({
      method: "GET",
      path: "/v1/products",
      query: {
        q: ["cream"],
        brand: ["A", "B"],
        priceMax: ["99.50"],
        sort: ["name"],
        limit: ["10"],
      },
    });
    expect(getProduct.request({ id: "a/b" }).path).toBe("/v1/products/a%2Fb");
    expect(compare.request(compare.input.parse({ ids: ["p1", "p2"] }))).toEqual({
      method: "POST",
      path: "/v1/compare",
      body: { ids: ["p1", "p2"], limit: 10 },
    });
    expect(coverageStatus.request({})).toEqual({ method: "GET", path: "/v1/coverage" });
    expect(toQuery({ a: undefined, b: true, c: [1, 2] })).toEqual({ b: ["true"], c: ["1", "2"] });
  });

  it("rejects unknown keys, floats for money, SQL-ish and malformed values", () => {
    const bad: [{ input: { safeParse(v: unknown): { success: boolean } } }, unknown][] = [
      [searchProducts, { sql: "select 1" }],
      [searchProducts, { priceMin: 12.5 }],
      [searchProducts, { priceMin: "1e3" }],
      [searchProducts, { limit: 26 }],
      [searchProducts, { retailer: ["North Beauty"] }],
      [getProduct, { id: "p1; drop table" }],
      [compare, { ids: ["p1"] }],
      [compare, { ids: ["p1", "p2"], brand: ["A"] }],
      [compare, { retailers: ["north", "north"] }],
      [indexTrend, { from: "2026-09-15", to: "2026-09-01" }],
      [assortmentGaps, { missingAt: "north", presentAt: "north" }],
      [reviewsSummary, { ids: ["p1"], category: ["X"] }],
      [coverageStatus, { anything: 1 }],
    ];
    for (const [tool, input] of bad) {
      expect(tool.input.safeParse(input).success, JSON.stringify(input)).toBe(false);
    }
  });
});
