/** The planted facts the S6 eval cases rely on survive the real registry (fixtures → tools). */
import { describe, expect, it } from "vitest";

import { FixtureApi } from "../src/evals/fixtures.js";
import { TOOLS } from "../src/tools/definitions.js";
import { ToolRegistry, type ToolEnvelope } from "../src/tools/registry.js";

const VIEWER = { uid: "u", role: "viewer" } as const;

async function run(tool: string, input: unknown = {}) {
  const registry = new ToolRegistry(TOOLS, new FixtureApi("standard"), { evidenceHosts: [] });
  return (await registry.run(tool, input, VIEWER, "t")) as ToolEnvelope;
}

describe("S6 eval fixtures", () => {
  it.each([
    ["availability", {}, "25.0"],
    ["price_history", { id: "p01" }, "110.00"],
    ["price_ladder", { retailer: "north" }, "64.00"],
    ["brand_positioning", { retailer: "north" }, "58.75"],
    // API 1.14.0: the pair rule's suggestion for p02 (gold case "price suggestion").
    ["price_suggestions", { subject: "north", rival: "south" }, "41.00"],
  ])("%s answers with its planted figure", async (tool, input, figure) => {
    const result = await run(tool, input);
    expect(result.status).toBe("ok");
    expect(JSON.stringify(result.data)).toContain(figure);
  });

  it("withholds the south price sections as not_enough_data", async () => {
    const result = await run("price_ladder", { retailer: "south" });
    expect(result.status).toBe("not_enough_data");
    expect(result.notEnoughData?.reason).toBe("cohort_too_small");
  });

  it("keeps the south catalogue counts, which are not withheld", async () => {
    const result = await run("assortment_breadth", { retailer: "south" });
    expect(result.status).toBe("ok");
  });

  it("refuses history for an unknown product", async () => {
    expect((await run("price_history", { id: "zz9" })).status).toBe("not_enough_data");
  });
});
