import { describe, expect, it } from "vitest";

import {
  collectToolNumbers,
  collectToolTimes,
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

  it("strips only tool dates, tool clocks, sequential list markers and product tokens", () => {
    const times = collectToolTimes([output]);
    expect(
      extractNumbers(
        "1. As of 2026-09-15T20:00:00Z at 20:00 on 2026-09-15, [[product:p42]] costs 1,020.74 (8)",
        times,
      ),
    ).toEqual(["1020.74", "8"]);
    expect(extractNumbers("1. a\n2. b\n3) c", times)).toEqual([]);
    expect(extractNumbers("1. a\n3. b", times)).toEqual(["3"]);
  });

  it("keeps dates, clocks and markers no tool returned", () => {
    const times = collectToolTimes([output]);
    expect(extractNumbers("Price 2099-12-31", times)).toEqual(["2099", "12", "31"]);
    expect(extractNumbers("12:30 AED", times)).toEqual(["12", "30"]);
    expect(extractNumbers("37. cheaper", times)).toEqual(["37"]);
  });

  it("takes only cutoff from a citation, never the echoed filters (review #51)", () => {
    const probe = {
      data: { price: "129.00" },
      citation: {
        cutoff: "2026-09-15T20:00:00Z",
        filters: { from: "2026-08-12T11:45:00Z", nested: { to: "2026-07-01" } },
      },
      filters: { from: "2026-06-30T09:15:00Z" },
    };
    const times = collectToolTimes([probe]);
    expect([...times.dates].some((d) => d.startsWith("2026-08-12"))).toBe(false);
    expect([...times.dates].some((d) => d.startsWith("2026-07-01"))).toBe(false);
    expect([...times.dates].some((d) => d.startsWith("2026-06-30"))).toBe(false);
    expect([...times.clocks]).toEqual(["20:00", "20:00:00"]);
    expect(verifyAnswerNumbers("11:45 AED cheaper", [probe]).ok).toBe(false);
    expect(verifyAnswerNumbers("Price 2026-08-12", [probe]).ok).toBe(false);
    expect(verifyAnswerNumbers("As of 2026-09-15 20:00, 129.00 AED", [probe]).ok).toBe(true);
  });

  it("does not collect times from untrusted text", () => {
    const times = collectToolTimes([{ data: { note: { untrusted: "2099-12-31T12:30:00Z" } } }]);
    expect(times.dates.size + times.clocks.size).toBe(0);
  });
});

describe("reviewer #41 condition 3", () => {
  it.each(["Price 2099-12-31", "12:30 AED", "37. cheaper"])("rejects %j", (answer) => {
    expect(verifyAnswerNumbers(answer, [output]).ok).toBe(false);
  });

  it("accepts the tool's own cutoff date and time", () => {
    expect(verifyAnswerNumbers("As of 2026-09-15 20:00, 129.00 AED", [output]).ok).toBe(true);
  });
});

describe("reviewer #41 condition 2", () => {
  const cited = {
    data: { price: "129.00" },
    citation: {
      apiVersion: "2.5",
      metricVersion: "3",
      toolVersion: "4",
      endpoint: "compare",
      scope: "uae",
      datasetGeneration: "7",
      filters: { priceMin: "999" },
      cohort: { description: { untrusted: "11 products" }, n: 12 },
    },
  };

  it("never lets citation versions support a number", () => {
    for (const answer of ["2.5 AED", "3 AED", "4 AED", "7 AED", "999 AED", "11 products"]) {
      expect(verifyAnswerNumbers(answer, [cited]).ok, answer).toBe(false);
    }
  });

  it("counts only cohort.n from the citation", () => {
    expect(verifyAnswerNumbers("12 products at 129.00 AED", [cited]).ok).toBe(true);
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

  it("lets only the closing Source line quote the echoed filters (2026-10-03 false fail)", () => {
    const listed = {
      data: { rows: [{ price: "129.00" }, { price: "99.00" }], total: 2 },
      citation: { cutoff: "2026-09-15T20:00:00Z", filters: { limit: 10, priceMax: "150" } },
    };
    const source =
      "Source: search_products, filters limit 10, priceMax 150, n 2, cutoff 2026-09-15.";
    expect(verifyAnswerNumbers(`Cheapest is 99.00 of 2.\n${source}`, [listed]).ok).toBe(true);
    expect(verifyAnswerNumbers(`Cheapest is 99.00.\n**Source:** limit 10`, [listed]).ok).toBe(true);
    // A filter value in the body is still the model's own number, not a result.
    expect(verifyAnswerNumbers(`The top 10 cost under 150.\n${source}`, [listed])).toEqual({
      ok: false,
      unsupported: ["10", "150"],
    });
    // Only the last Source line is exempt, and it still may not invent numbers.
    expect(verifyAnswerNumbers("Source: limit 10\nSource: n 7", [listed])).toEqual({
      ok: false,
      unsupported: ["10", "7"],
    });
  });

  it("accepts a list's length as a count", () => {
    const listed = { data: { rows: [{ id: "p1" }, { id: "p2" }, { id: "p3" }] } };
    expect(verifyAnswerNumbers("3 products match.", [listed]).ok).toBe(true);
    expect(verifyAnswerNumbers("4 products match.", [listed]).ok).toBe(false);
  });
});
