import { describe, expect, it } from "vitest";

import {
  TOOLS,
  assortmentGaps,
  compare,
  coverageStatus,
  getProduct,
  indexTrend,
  promotions,
  reviewsSummary,
  searchProducts,
  toQuery,
} from "../src/tools/definitions.js";
import { MINIMAL, PAIR } from "./fake-api.js";

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
      expect(tool.version).toBe("2");
      const request = tool.request(tool.input.parse(MINIMAL[tool.name] ?? {}) as never);
      expect(request.path.startsWith("/api/v1/")).toBe(true);
      expect(request.method).toBe("GET");
      expect(request.body).toBeUndefined();
    }
  });

  it("maps inputs to requests", () => {
    expect(
      searchProducts.request(
        searchProducts.input.parse({ q: "cream", brand: ["A", "B"], priceMax: "99.50" }),
      ),
    ).toEqual({
      method: "GET",
      path: "/api/v1/products",
      query: {
        q: ["cream"],
        brand: ["A", "B"],
        priceMax: ["99.50"],
        sort: ["name"],
        limit: ["10"],
      },
    });
    expect(getProduct.request({ id: "a.b:c" }).path).toBe("/api/v1/products/a.b%3Ac");
    expect(
      compare.request(
        compare.input.parse({ ...PAIR, ids: ["p1", "p2"], date: "2026-09-30", groupBy: "brand" }),
      ),
    ).toEqual({
      method: "GET",
      path: "/api/v1/compare",
      query: {
        retailers: ["north,south"],
        id: ["p1", "p2"],
        date: ["2026-09-30"],
        groupBy: ["brand"],
      },
    });
    expect(coverageStatus.request({})).toEqual({
      method: "GET",
      path: "/api/v1/coverage",
      query: {},
    });
    expect(reviewsSummary.request(reviewsSummary.input.parse({ ids: ["p1", "p2"] }))).toEqual({
      method: "GET",
      path: "/api/v1/reviews-summary",
      query: { id: ["p1", "p2"] },
    });
    expect(promotions.request(promotions.input.parse({ minPct: 10, retailer: ["north"] }))).toEqual(
      {
        method: "GET",
        path: "/api/v1/promotions",
        query: { retailer: ["north"], minPct: ["10"] },
      },
    );
    expect(toQuery({ a: undefined, b: true, c: [1, 2] })).toEqual({ b: ["true"], c: ["1", "2"] });
    expect(indexTrend.request(indexTrend.input.parse(PAIR))).toEqual({
      method: "GET",
      path: "/api/v1/index",
      query: { retailers: ["north,south"] },
    });
  });

  it("rejects unknown keys, floats for money, SQL-ish and malformed values", () => {
    const bad: [{ input: { safeParse(v: unknown): { success: boolean } } }, unknown][] = [
      [searchProducts, { sql: "select 1" }],
      [searchProducts, { priceMin: 12.5 }],
      [searchProducts, { priceMin: "1e3" }],
      [searchProducts, { limit: 26 }],
      [searchProducts, { retailer: ["North Beauty"] }],
      [getProduct, { id: "p1; drop table" }],
      [compare, {}],
      [compare, { ...PAIR, ids: [] }],
      [compare, { ...PAIR, ids: ["p1", "p2"], brand: ["A"] }],
      [compare, { ...PAIR, groupBy: "retailer" }],
      [compare, { ...PAIR, limit: 10 }],
      [compare, { retailers: { base: "north", other: "north" } }],
      [compare, { retailers: ["north", "south"] }],
      [indexTrend, {}],
      [indexTrend, { ...PAIR, from: "2026-09-15", to: "2026-09-01" }],
      [assortmentGaps, { missingAt: "north", presentAt: "north" }],
      [assortmentGaps, { missingAt: "north" }],
      [promotions, { minPct: 10.5 }],
      [reviewsSummary, { ids: ["p1"], category: ["X"] }],
      [coverageStatus, { anything: 1 }],
    ];
    for (const [tool, input] of bad) {
      expect(tool.input.safeParse(input).success, JSON.stringify(input)).toBe(false);
    }
  });
});
