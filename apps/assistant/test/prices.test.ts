import { describe, expect, it } from "vitest";

import { Prices, UnknownModelError, formatUsd, parseUsd } from "../src/meter/prices.js";
import { CEILING, CONFIG, PRICE_TABLE, prices } from "./meter-fixtures.js";

describe("USD parsing", () => {
  it("parses decimal text into micro-USD without floats", () => {
    expect(parseUsd("5")).toBe(5_000_000n);
    expect(parseUsd("0.40")).toBe(400_000n);
    expect(parseUsd("0.000001")).toBe(1n);
    expect(parseUsd("123456.123456")).toBe(123_456_123_456n);
  });

  it("rejects floats' friends: exponents, signs, >6 dp", () => {
    for (const bad of ["1e3", "-1", "0.0000001", "", "1.", ".5", "NaN"]) {
      expect(() => parseUsd(bad)).toThrow();
    }
  });

  it("formats micro-USD", () => {
    expect(formatUsd(7_250n)).toBe("0.007250");
    expect(formatUsd(5_000_000n)).toBe("5.000000");
    expect(formatUsd(-1n)).toBe("-0.000001");
  });
});

describe("Prices", () => {
  it("costs a call, charging cached input at the cached rate and thinking as output", () => {
    // (15000-5000)×0.30 + 5000×0.03 + (800+300)×2.50 = 3000 + 150 + 2750 micro-USD
    expect(
      prices().cost("gemini-2.5-flash", {
        input: 15_000,
        cachedInput: 5_000,
        output: 800,
        thinking: 300,
      }),
    ).toBe(5_900n);
  });

  it("rounds each charge up to the next micro-USD", () => {
    // 1 token × 0.30 USD/M = 0.3 micro-USD → 1
    expect(
      prices().cost("gemini-2.5-flash", { input: 1, cachedInput: 0, output: 0, thinking: 0 }),
    ).toBe(1n);
  });

  it("computes the ceiling from the limits", () => {
    expect(prices().ceiling(CONFIG.model, CONFIG.limits)).toBe(CEILING);
  });

  it("refuses unknown models and bad token counts", () => {
    const table = prices();
    expect(() => table.cost("other", { input: 1, cachedInput: 0, output: 0, thinking: 0 })).toThrow(
      UnknownModelError,
    );
    expect(() =>
      table.cost(CONFIG.model, { input: 1, cachedInput: 2, output: 0, thinking: 0 }),
    ).toThrow(/cached/);
    expect(() =>
      table.cost(CONFIG.model, { input: 1.5, cachedInput: 0, output: 0, thinking: 0 }),
    ).toThrow(/input/);
    expect(() =>
      table.ceiling(CONFIG.model, { maxInputTokens: -1, maxOutputTokens: 1, thinkingBudget: 0 }),
    ).toThrow();
  });

  it("validates the committed price table", () => {
    expect(table()).toBeInstanceOf(Prices);
    expect(() => new Prices({ ...PRICE_TABLE, models: { x: { input: 0.3 } } } as never)).toThrow();
    function table(): Prices {
      return new Prices(PRICE_TABLE);
    }
  });
});
