import { describe, expect, it } from "vitest";

import { parseDecimal } from "../src/guard/decimal.js";
import { divide, unitPriceView } from "../src/tools/unit-price.js";

const money = (amount: string) => ({ amount, minor: 0, currency: "XXX" });

function card(
  id: string,
  size: { value: string; unit: string } | null,
  prices: Record<string, string | null>,
) {
  return {
    id,
    brand: { untrusted: "Brand" },
    size,
    prices: Object.fromEntries(
      Object.entries(prices).map(([key, amount]) => [key, amount === null ? null : money(amount)]),
    ),
  };
}

const ASC = { order: "asc", rows: 10 } as const;

function rowsOf(view: { data: unknown }) {
  return (view.data as { rows: { id: string; retailer: string; perUnit: string; per: string }[] })
    .rows;
}

describe("divide", () => {
  it("divides exactly and rounds half away from zero", () => {
    expect(divide(parseDecimal("100.00"), parseDecimal("30"), 4)).toBe("3.3333");
    expect(divide(parseDecimal("2"), parseDecimal("3"), 4)).toBe("0.6667");
    expect(divide(parseDecimal("1"), parseDecimal("8"), 2)).toBe("0.13");
    expect(divide(parseDecimal("0.10"), parseDecimal("1000"), 4)).toBe("0.0001");
    expect(divide(parseDecimal("129.00"), parseDecimal("50"), 4)).toBe("2.5800");
  });
});

describe("unitPriceView", () => {
  it("converts L, cl, kg and mg exactly and ranks cheapest first", () => {
    const view = unitPriceView(
      {
        items: [
          card("a", { value: "1", unit: "L" }, { north: "50.00" }),
          card("b", { value: "50", unit: "ml" }, { north: "129.00" }),
          card("c", { value: "10", unit: " cl " }, { south: "30.00" }),
        ],
        total: 3,
      },
      ASC,
    );
    expect(rowsOf(view).map((row) => [row.id, row.perUnit, row.per])).toEqual([
      ["a", "0.0500", "ml"],
      ["c", "0.3000", "ml"],
      ["b", "2.5800", "ml"],
    ]);
    const grams = unitPriceView(
      {
        items: [
          card("k", { value: "0.5", unit: "kg" }, { north: "10.00" }),
          card("m", { value: "500", unit: "mg" }, { north: "10.00" }),
        ],
        total: 2,
      },
      { ...ASC, per: "g" },
    );
    expect(rowsOf(grams).map((row) => row.perUnit)).toEqual(["0.0200", "20.0000"]);
  });

  it("excludes and counts products without a size, a metric unit or a price", () => {
    const view = unitPriceView(
      {
        items: [
          card("none", null, { north: "10.00" }),
          card("zero", { value: "0", unit: "ml" }, { north: "10.00" }),
          card("oz", { value: "1.7", unit: "fl oz" }, { north: "10.00" }),
          card("solid", { value: "30", unit: "g" }, { north: "10.00" }),
          card("unpriced", { value: "30", unit: "ml" }, { north: null }),
          card("ok", { value: "30", unit: "ml" }, { north: "15.00", south: "12.00" }),
        ],
        total: 240,
      },
      { ...ASC, per: "ml" },
    );
    expect(view.data).toMatchObject({
      total: 2,
      scanned: 6,
      matching: 240,
      truncated: false,
      excluded: { noSize: 2, unitNotMetric: 1, otherMeasure: 1, noPrice: 1 },
    });
    // One row per priced retailer.
    expect(rowsOf(view).map((row) => [row.retailer, row.perUnit])).toEqual([
      ["south", "0.4000"],
      ["north", "0.5000"],
    ]);
  });

  it("orders desc, keeps ml and g apart, and limits the rows", () => {
    const items = [
      card("g1", { value: "10", unit: "g" }, { north: "1.00" }),
      card("m1", { value: "10", unit: "ml" }, { north: "1.00" }),
      card("m2", { value: "10", unit: "ml" }, { north: "5.00" }),
      card("m3", { value: "10", unit: "ml" }, { north: "3.00" }),
    ];
    const view = unitPriceView({ items, total: 4 }, { order: "desc", rows: 3 });
    expect(rowsOf(view).map((row) => row.id)).toEqual(["m2", "m3", "m1"]);
    expect(view.data).toMatchObject({ total: 4, truncated: true });
  });

  it("passes anything that is not a products page through unchanged", () => {
    expect(unitPriceView({ error: "x" }, ASC)).toEqual({ data: { error: "x" } });
    expect(unitPriceView({ items: "x" }, ASC)).toEqual({ data: { items: "x" } });
  });
});
