import { describe, expect, it } from "vitest";

import { verifyAnswerNumbers } from "../src/guard/verifier.js";
import { TOOLS } from "../src/tools/definitions.js";
import { MAX_RESULT_CHARS, ToolRegistry, type ToolEnvelope } from "../src/tools/registry.js";
import { type AnyToolDef, defineTool } from "../src/tools/types.js";
import { z } from "zod";
import { COMPARE_DATA, FakeApi, INJECTION, META, failing, okEnvelope } from "./fake-api.js";

const HOSTS = ["shop.north.example", "south.example"];
const VIEWER = { uid: "u1", role: "viewer" } as const;
const ADMIN = { uid: "u2", role: "admin" } as const;

function registry(api: FakeApi, tools: readonly AnyToolDef[] = TOOLS) {
  return new ToolRegistry(tools, api, { evidenceHosts: HOSTS });
}

describe("ToolRegistry", () => {
  it("forwards the caller's token and builds a citation from envelope meta", async () => {
    const api = new FakeApi(() => okEnvelope(COMPARE_DATA));
    const result = (await registry(api).run(
      "compare",
      { ids: ["p01", "n04"] },
      VIEWER,
      "tok-1",
    )) as ToolEnvelope;
    expect(api.calls[0]?.idToken).toBe("tok-1");
    expect(result.status).toBe("ok");
    expect(result.citation).toEqual({
      tool: "compare",
      toolVersion: "1",
      apiVersion: "v1.0.0",
      metricVersion: null,
      datasetGeneration: "gen-42",
      cutoff: META.cutoff,
      market: "AE",
      currency: "AED",
      filters: { ids: ["p01", "n04"], limit: 10 },
      cohort: { description: "exact, reviewed, same-size matched pairs", n: 8 },
    });
  });

  it("escapes injected retailer text and filters evidence for viewers", async () => {
    const api = new FakeApi(() => okEnvelope(COMPARE_DATA));
    const result = (await registry(api).run("compare", {}, VIEWER, "t")) as ToolEnvelope;
    const text = JSON.stringify(result.data);
    expect(text).not.toContain("​");
    expect(text).not.toContain("](https://evil");
    expect(text).toContain("\\\\!\\\\[x\\\\]");
    expect(result.evidence).toEqual([
      {
        productId: "p01",
        retailer: "north",
        url: "https://shop.north.example/p/p01",
        capturedAt: "2026-09-15T08:00:00Z",
      },
      { productId: "p01", retailer: "south", url: null, capturedAt: "2026-09-15T08:00:00Z" },
    ]);
  });

  it("keeps admin-only evidence fields for admins", async () => {
    const api = new FakeApi(() => okEnvelope(COMPARE_DATA));
    const result = (await registry(api).run("compare", {}, ADMIN, "t")) as ToolEnvelope;
    expect(result.evidence[0]).toMatchObject({ runId: "run-north-7", source: "north-listing" });
  });

  it("end to end: the verifier accepts tool numbers and rejects injected ones", async () => {
    const api = new FakeApi(() => okEnvelope(COMPARE_DATA));
    const result = await registry(api).run("compare", {}, VIEWER, "t");
    expect(
      verifyAnswerNumbers(
        "North is cheaper on 4 of 8 pairs; basket 1,020.74 vs 980.50 AED, North dearer by 4.1%. [[product:p01]] is 16.7% cheaper at North.",
        [result],
      ).ok,
    ).toBe(true);
    expect(verifyAnswerNumbers(INJECTION, [result]).unsupported).toEqual(["50"]);
  });

  it("passes not_enough_data through with its reason", async () => {
    const api = new FakeApi(() => ({
      status: "not_enough_data",
      reason: "retailer_partial",
      detail: { en: "East coverage is partial, so absence cannot be claimed.", ar: "…" },
      cohort: { description: "none", n: 0 },
      caveats: [],
      evidence: [],
      meta: META,
    }));
    const result = (await registry(api).run(
      "assortment_gaps",
      { missingAt: "east" },
      VIEWER,
      "t",
    )) as ToolEnvelope;
    expect(result.status).toBe("not_enough_data");
    expect(result.notEnoughData?.reason).toBe("retailer_partial");
    expect(result.data).toBeUndefined();
  });

  it("keeps rows on not_enough_data (cohort below the minimum)", async () => {
    const api = new FakeApi(() => ({
      ...okEnvelope({ rows: [{ id: "p01", name: "Cream", gapPct: "-16.7" }], summary: null }),
      status: "not_enough_data",
      reason: "cohort_too_small",
      detail: { en: "Fewer than five counted pairs.", ar: "…" },
    }));
    const result = (await registry(api).run("compare", {}, VIEWER, "t")) as ToolEnvelope;
    expect(result.notEnoughData?.reason).toBe("cohort_too_small");
    expect(result.data).toEqual({
      rows: [{ id: "p01", name: { untrusted: "Cream" }, gapPct: "-16.7" }],
      summary: null,
    });
  });

  it("returns typed errors", async () => {
    const ok = new FakeApi(() => okEnvelope({}));
    await expect(registry(ok).run("run_sql", {}, VIEWER, "t")).resolves.toMatchObject({
      code: "unknown_tool",
    });
    await expect(
      registry(ok).run("search_products", { limit: 99 }, VIEWER, "t"),
    ).resolves.toMatchObject({
      code: "invalid_input",
    });
    expect(ok.calls).toHaveLength(0);
    const cases: [number, string][] = [
      [401, "unauthenticated"],
      [403, "forbidden"],
      [422, "invalid_input"],
      [404, "not_found"],
      [409, "stale_cursor"],
      [429, "rate_limited"],
      [503, "upstream_unavailable"],
      [0, "upstream_unavailable"],
    ];
    for (const [status, code] of cases) {
      await expect(
        registry(failing(status)).run("coverage_status", {}, VIEWER, "t"),
      ).resolves.toMatchObject({ code });
    }
    const bad = new FakeApi(() => ({ status: "ok", meta: META }));
    await expect(registry(bad).run("coverage_status", {}, VIEWER, "t")).resolves.toMatchObject({
      code: "upstream_invalid",
    });
    const noReason = new FakeApi(() => ({ ...okEnvelope({}), status: "not_enough_data" }));
    await expect(registry(noReason).run("coverage_status", {}, VIEWER, "t")).resolves.toMatchObject(
      {
        code: "upstream_invalid",
      },
    );
    const huge = new FakeApi(() =>
      okEnvelope({ rows: Array.from({ length: 2000 }, () => "12.50") }),
    );
    const tooLarge = await registry(huge).run("coverage_status", {}, VIEWER, "t");
    expect(tooLarge).toMatchObject({ code: "output_too_large" });
    expect(MAX_RESULT_CHARS).toBe(16_000);
  });

  it("rethrows non-API failures", async () => {
    const api = new FakeApi(() => {
      throw new TypeError("bug");
    });
    await expect(registry(api).run("coverage_status", {}, VIEWER, "t")).rejects.toThrow("bug");
  });

  it("gates tools by role and rejects duplicate names", async () => {
    const adminOnly = defineTool({
      name: "admin_tool",
      version: "1",
      description: "x",
      minRole: "admin",
      input: z.object({}).strict(),
      request: () => ({ method: "GET", path: "/v1/admin" }),
    });
    const api = new FakeApi(() => okEnvelope({}));
    const reg = registry(api, [...TOOLS, adminOnly]);
    expect(reg.available(VIEWER).map((tool) => tool.name)).not.toContain("admin_tool");
    expect(reg.available(ADMIN).map((tool) => tool.name)).toContain("admin_tool");
    await expect(reg.run("admin_tool", {}, VIEWER, "t")).resolves.toMatchObject({
      code: "forbidden",
    });
    await expect(reg.run("admin_tool", {}, ADMIN, "t")).resolves.toMatchObject({ status: "ok" });
    expect(() => registry(api, [adminOnly, adminOnly])).toThrow("duplicate");
  });
});
