/** The /summary views (S6): thin projections, the envelope cohort cited, withheld never zero. */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { TOOLS } from "../src/tools/definitions.js";
import { ToolRegistry, type ToolEnvelope } from "../src/tools/registry.js";
import { FakeApi } from "./fake-api.js";

const VIEWER = { uid: "u", role: "viewer" } as const;
const SUMMARY = JSON.parse(
  readFileSync(
    new URL("../../../docs/contracts/golden/pi-api/summary.json", import.meta.url),
    "utf8",
  ),
) as { status: string; data: Record<string, unknown>; cohort: { n: number } };

async function run(tool: string, body: unknown, input: unknown = {}) {
  const api = new FakeApi(() => body);
  const result = (await new ToolRegistry(TOOLS, api, { evidenceHosts: [] }).run(
    tool,
    input,
    VIEWER,
    "t",
  )) as ToolEnvelope;
  return { result, api };
}

const withData = (data: Record<string, unknown>) => ({
  ...SUMMARY,
  data: { ...SUMMARY.data, ...data },
});

describe("/summary views", () => {
  it.each([
    ["price_ladder", ["ladder"]],
    ["price_distribution", ["priceHist", "medianPrice", "priced"]],
    ["brand_positioning", ["brandPrice"]],
    ["category_mix", ["categoryMix", "products"]],
    ["assortment_breadth", ["products", "priced", "brands", "categories"]],
  ])("%s keeps only the context and %j", async (tool, fields) => {
    const { result, api } = await run(tool, SUMMARY, { retailer: "north" });
    expect(api.calls[0]?.request).toEqual({
      method: "GET",
      path: "/api/v1/summary",
      query: { retailer: ["north"] },
    });
    expect(result.status).toBe("ok");
    expect(Object.keys(result.data as object).sort()).toEqual(
      ["retailer", "asOf", "currency", "freshness", ...fields].sort(),
    );
    expect(result.citation.tool).toBe(tool);
    expect(result.citation.cohort?.n).toBe(SUMMARY.cohort.n);
  });

  it("a withheld section is not_enough_data with the service's reason, not a zero", async () => {
    const body = withData({
      ladder: null,
      withheld: [{ section: "prices", reason: "cohort_too_small" }],
    });
    const { result } = await run("price_ladder", body);
    expect(result.status).toBe("not_enough_data");
    expect(result.notEnoughData?.reason).toBe("cohort_too_small");
    expect(result.notEnoughData?.detail.en.untrusted).toContain("withheld this part");
    expect(result.data).toMatchObject({ ladder: null });
  });

  it("other sections being withheld do not affect a view", async () => {
    const body = withData({
      promoDepth: null,
      withheld: [{ section: "promotions", reason: "field_not_collected" }],
    });
    expect((await run("price_ladder", body)).result.status).toBe("ok");
    expect((await run("assortment_breadth", body)).result.status).toBe("ok");
  });

  it("a section withheld as was_price_unverified keeps that reason", async () => {
    const body = withData({
      ladder: null,
      withheld: [{ section: "prices", reason: "was_price_unverified" }],
    });
    const { result } = await run("price_ladder", body);
    expect(result.notEnoughData?.reason).toBe("was_price_unverified");
  });

  it("an unknown withheld reason falls back to a closed reason", async () => {
    const body = withData({ brandPrice: null, withheld: [{ section: "prices", reason: "odd" }] });
    expect((await run("brand_positioning", body)).result.notEnoughData?.reason).toBe("no_match");
  });

  it("refuses inputs other than one retailer id", async () => {
    for (const input of [{ retailer: "North Shop" }, { retailer: ["north"] }, { q: "x" }]) {
      expect((await run("price_ladder", SUMMARY, input)).result.status).toBe("error");
    }
  });
});
