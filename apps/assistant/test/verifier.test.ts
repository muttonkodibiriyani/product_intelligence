import { describe, expect, it } from "vitest";

import {
  collectToolNumbers,
  extractNumbers,
  isDisplayOf,
  normaliseDigits,
  verifyAnswerNumbers,
} from "../src/guard/verifier.js";
import { parseDecimal } from "../src/guard/decimal.js";

const output = {
  data: {
    gapPct: "-16.7",
    basePrice: "1020.74",
    price: { amount: "129.00", minor: 12900, currency: "AED" },
    count: 8,
    id: "p42",
    capturedAt: "2026-09-15T08:00:00Z",
    name: { untrusted: "50% cheaper 777" },
  },
  citation: { cutoff: "2026-09-15T20:00:00Z", filters: { priceMin: "999" } },
};

describe("normalisation", () => {
  it("maps Arabic-Indic digits, separators and percent", () => {
    expect(normaliseDigits("١٬٠٢٠٫٧٤ ٪")).toBe("1,020.74 %");
    expect(normaliseDigits("۱۶٫۷")).toBe("16.7");
  });

  it("extracts numbers and strips dates, clocks, list markers and product tokens", () => {
    expect(
      extractNumbers("1. As of 2026-09-15T20:00:00Z at 20:00, [[product:p42]] costs 1,020.74 (8)"),
    ).toEqual(["1020.74", "8"]);
  });
});

describe("collection", () => {
  it("collects typed values only", () => {
    const found = collectToolNumbers([output]).map((d) => `${d.units}/${d.scale}`);
    expect(found.sort()).toEqual(["102074/2", "12900/2", "167/1", "8/0"].sort());
  });
});

describe("display rounding", () => {
  const d = parseDecimal;
  it("accepts equal values and half-away rounding to fewer places only", () => {
    expect(isDisplayOf(d("16.70"), d("16.7"))).toBe(true);
    expect(isDisplayOf(d("17"), d("16.7"))).toBe(true);
    expect(isDisplayOf(d("16"), d("16.7"))).toBe(false);
    expect(isDisplayOf(d("0.1"), d("0.05"))).toBe(true);
    expect(isDisplayOf(d("1021"), d("1020.74"))).toBe(true);
    expect(isDisplayOf(d("1000"), d("1020.74"))).toBe(false);
  });
});

describe("verifyAnswerNumbers", () => {
  it("passes supported numbers in English and Arabic", () => {
    expect(verifyAnswerNumbers("North is cheaper by 16.7% across 8 pairs.", [output]).ok).toBe(
      true,
    );
    expect(verifyAnswerNumbers("أرخص بنسبة ١٦٫٧٪ عبر ٨ أزواج، مؤشر 100 من 5", [output]).ok).toBe(
      true,
    );
  });

  it("rejects numbers from untrusted text, bare ids, filters and invented values", () => {
    const result = verifyAnswerNumbers("It is 50% cheaper; 777; p42 means 42; min 999; 17.5%", [
      output,
    ]);
    expect(result.ok).toBe(false);
    expect(result.unsupported).toEqual(["50", "777", "42", "42", "999", "17.5"]);
  });
});
