import { describe, expect, it } from "vitest";

import {
  TOOLS,
  assortmentGaps,
  compare,
  coverageStatus,
  getProduct,
  indexTrend,
  launches,
  promotions,
  reviewsSummary,
  searchProducts,
  toQuery,
} from "../src/tools/definitions.js";
import { MINIMAL, PAIR } from "./fake-api.js";

const NEW_IN_S6 = new Set([
  "price_history",
  "availability",
  "price_ladder",
  "price_distribution",
  "brand_positioning",
  "category_mix",
  "assortment_breadth",
  // API 1.8.0 (#148).
  "category_compare",
  // Derived from /products sizes (2026-10-03).
  "price_per_unit",
  // API 1.13.0 (pair price suggestions).
  "price_suggestions",
]);

const VERSION_BUMPS: Readonly<Record<string, string>> = { get_product: "3", compare: "4" };

describe("tool definitions", () => {
  it("has nineteen uniquely named, viewer-level, read-only tools", () => {
    expect(TOOLS.map((tool) => tool.name)).toEqual([
      "search_products",
      "price_per_unit",
      "get_product",
      "compare",
      "index_trend",
      "promotions",
      "assortment_gaps",
      "launches",
      "reviews_summary",
      "coverage_status",
      "price_history",
      "availability",
      "price_ladder",
      "price_distribution",
      "brand_positioning",
      "category_mix",
      "assortment_breadth",
      "category_compare",
      "price_suggestions",
    ]);
    for (const tool of TOOLS) {
      expect(tool.minRole).toBe("viewer");
      // v3 adds the row limit to the three list tools (API 1.1.0); API 1.5.2's price floor adds
      // priceFlag to get_product (v3) and gapHist to compare (v4).
      expect(tool.version).toBe(
        VERSION_BUMPS[tool.name] ??
          (NEW_IN_S6.has(tool.name) ? "1" : tool.listKey === undefined ? "2" : "3"),
      );
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
        limit: ["25"],
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
        query: { retailer: ["north"], limit: ["25"], minPct: ["10"] },
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
      [compare, { ...PAIR, limit: 26 }],
      [compare, { ...PAIR, limit: 0 }],
      [promotions, { limit: 2.5 }],
      [launches, { limit: 500 }],
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
