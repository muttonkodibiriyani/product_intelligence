import { describe, expect, it } from "vitest";

import { parseDecimal } from "../src/guard/decimal.js";
import { divide, unitPriceView } from "../src/tools/unit-price.js";

const money = (amount: string, currency = "XXX") => ({ amount, minor: 0, currency });

/** A counted gap between two retailers: pi_metrics' reviewed exact same-size match. */
const sameSize = (base: string, other: string) => ({
  base,
  other,
  gap: { pct: "1.0", cheaper: "base", amount: money("1.00") },
  excludedReason: null,
});

function card(
  id: string,
  size: { value: string; unit: string } | null,
  prices: Record<string, string | null>,
  gap: unknown = null,
) {
  return {
    id,
    brand: { untrusted: "Brand" },
    size,
    gap,
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
          card(
            "ok",
            { value: "30", unit: "ml" },
            { north: "15.00", south: "12.00" },
            sameSize("north", "south"),
          ),
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
      partial: true,
      excluded: { noSize: 2, unitNotMetric: 1, otherMeasure: 1, noPrice: 1, sizeUnproven: 0 },
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
    expect(view.data).toMatchObject({ total: 4, truncated: true, partial: false });
  });

  it("passes anything that is not a products page through unchanged", () => {
    expect(unitPriceView({ error: "x" }, ASC)).toEqual({ data: { error: "x" } });
    expect(unitPriceView({ items: "x" }, ASC)).toEqual({ data: { items: "x" } });
  });

  it("never ranks across currencies and always carries the currency (review M1)", () => {
    const items = [
      { ...card("a", { value: "100", unit: "ml" }, {}), prices: { north: money("100.00", "AED") } },
      { ...card("b", { value: "100", unit: "ml" }, {}), prices: { south: money("30.00", "USD") } },
      { ...card("c", { value: "100", unit: "ml" }, {}), prices: { east: money("50.00", "AED") } },
    ];
    const view = unitPriceView({ items, total: 3 }, ASC);
    const rows = (view.data as { rows: { id: string; currency: string; perUnit: string }[] }).rows;
    expect(rows.map((row) => [row.id, row.currency, row.perUnit])).toEqual([
      ["c", "AED", "0.5000"],
      ["a", "AED", "1.0000"],
      ["b", "USD", "0.3000"],
    ]);
  });

  it("uses the card's size only where it provably applies to the price (review M2)", () => {
    const ml = { value: "50", unit: "ml" };
    const view = unitPriceView(
      {
        items: [
          card("single", ml, { north: "10.00", south: null }),
          card("pair", ml, { north: "10.00", south: "12.00" }, sameSize("south", "north")),
          card("nogap", ml, { north: "10.00", south: "12.00" }),
          card(
            "mismatch",
            ml,
            { north: "10.00", south: "12.00" },
            {
              ...sameSize("north", "south"),
              gap: null,
              excludedReason: "size_mismatch",
            },
          ),
          card("otherpair", ml, { north: "10.00", south: "12.00" }, sameSize("north", "east")),
          card(
            "three",
            ml,
            { north: "10.00", south: "12.00", east: "11.00" },
            sameSize("north", "south"),
          ),
        ],
        total: 6,
      },
      ASC,
    );
    expect(rowsOf(view).map((row) => `${row.id}@${row.retailer}`)).toEqual([
      "pair@north",
      "single@north",
      "pair@south",
    ]);
    expect(view.data).toMatchObject({ excluded: { sizeUnproven: 4 } });
  });
});
