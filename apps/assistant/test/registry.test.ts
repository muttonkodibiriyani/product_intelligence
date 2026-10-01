import { describe, expect, it } from "vitest";

import { verifyAnswerNumbers } from "../src/guard/verifier.js";
import { TOOLS } from "../src/tools/definitions.js";
import { MAX_RESULT_CHARS, ToolRegistry, type ToolEnvelope } from "../src/tools/registry.js";
import { type AnyToolDef, callerRole, defineTool } from "../src/tools/types.js";
import { z } from "zod";
import {
  COMPARE_DATA,
  FakeApi,
  INJECTION,
  META,
  PAIR,
  PRODUCT_DATA,
  failing,
  okEnvelope,
} from "./fake-api.js";

const HOSTS = ["shop.north.example", "south.example"];
const VIEWER = { uid: "u1", role: "viewer" } as const;
const ADMIN = { uid: "u2", role: "admin" } as const;

function registry(api: FakeApi, tools: readonly AnyToolDef[] = TOOLS) {
  return new ToolRegistry(tools, api, { evidenceHosts: HOSTS });
}

describe("ToolRegistry", () => {
  it.each([
    ["viewer", "viewer"],
    ["admin", "admin"],
    ["killswitch", null],
    ["Admin", null],
    ["", null],
    [undefined, null],
    [["admin"], null],
  ])("maps only exact viewer|admin claims to a caller role (%j)", (claim, role) => {
    expect(callerRole(claim)).toBe(role);
  });

  it("fails closed for a role outside viewer/admin (e.g. the kill-switch account)", async () => {
    const api = new FakeApi(() => okEnvelope(COMPARE_DATA));
    const killSwitch = { uid: "ks", role: "killswitch" } as unknown as typeof VIEWER;
    expect(registry(api).available(killSwitch)).toEqual([]);
    const result = await registry(api).run("compare", PAIR, killSwitch, "tok");
    expect(result).toMatchObject({ status: "error", code: "forbidden" });
    expect(api.calls).toEqual([]);
  });

  it("forwards the caller's token and builds a citation from envelope meta", async () => {
    const api = new FakeApi(() => okEnvelope(COMPARE_DATA));
    const result = (await registry(api).run(
      "compare",
      { ...PAIR, ids: ["p01", "n04"] },
      VIEWER,
      "tok-1",
    )) as ToolEnvelope;
    expect(api.calls[0]?.idToken).toBe("tok-1");
    expect(result.status).toBe("ok");
    expect(result.citation).toEqual({
      tool: "compare",
      toolVersion: "4",
      apiVersion: "1.0.0",
      metricVersion: "m1",
      datasetGeneration: "gen-42",
      cutoff: META.cutoff,
      market: "AE",
      currency: "AED",
      filters: { ...PAIR, ids: ["p01", "n04"], limit: 25 },
      cohort: { description: { untrusted: "exact, reviewed, same-size matched pairs" }, n: 8 },
    });
    expect(api.calls[0]?.request).toEqual({
      method: "GET",
      path: "/api/v1/compare",
      query: { retailers: ["north,south"], limit: ["25"], id: ["p01", "n04"] },
    });
    expect(result.caveats).toEqual([
      {
        code: "retailer_partial",
        en: { untrusted: "East Store coverage is partial." },
        ar: { untrusted: "تغطية متجر الشرق جزئية." },
        params: { retailer: "east" },
      },
    ]);
  });

  it("keeps caveat params sanitised, so a count is quotable but caveat text never is", async () => {
    const api = new FakeApi(() =>
      okEnvelope(COMPARE_DATA, {
        caveats: [
          {
            code: "invalid_price_excluded",
            params: { retailer: "south", count: "2", note: INJECTION, "bad key": "1" },
            en: "7 prices at or below 0.01 were excluded.",
            ar: "استُبعد 7 أسعار.",
          },
        ],
      }),
    );
    const result = (await registry(api).run("compare", PAIR, VIEWER, "t")) as ToolEnvelope;
    const params = result.caveats[0]?.params as Record<string, unknown>;
    expect(params.retailer).toBe("south");
    expect(params.count).toBe("2");
    expect(Object.keys(params.note as object)).toEqual(["untrusted"]);
    expect(params).not.toHaveProperty("bad key");
    expect(verifyAnswerNumbers("2 prices were excluded as invalid", [result]).ok).toBe(true);
    // The count in the caveat's own text is not a source.
    expect(verifyAnswerNumbers("7 prices were excluded", [result]).ok).toBe(false);
  });

  it("passes an invalid_low price flag through and never supports a 0 price for it", async () => {
    const [north, south] = PRODUCT_DATA.offers;
    const flagged = { ...south, price: null, priceFlag: "invalid_low" };
    const api = new FakeApi(() =>
      okEnvelope(
        { ...PRODUCT_DATA, offers: [north, flagged] },
        {
          caveats: [
            {
              code: "invalid_price_excluded",
              params: { retailer: "south", count: "1" },
              en: "1 price at or below 0.01 was excluded.",
              ar: "استُبعد سعر واحد.",
            },
          ],
        },
      ),
    );
    const result = (await registry(api).run(
      "get_product",
      { id: "p01" },
      VIEWER,
      "t",
    )) as ToolEnvelope;
    const offers = (result.data as { offers: Record<string, unknown>[] }).offers;
    expect(offers[1]).toMatchObject({ retailer: "south", price: null, priceFlag: "invalid_low" });
    expect(verifyAnswerNumbers("South's price, 0.00 AED, is free", [result]).ok).toBe(false);
    expect(verifyAnswerNumbers("1 South price was withheld as invalid", [result]).ok).toBe(true);
  });

  it("rejects a caveat with more than MAX_CAVEAT_PARAMS params as upstream_invalid", async () => {
    const params = Object.fromEntries(Array.from({ length: 21 }, (_, i) => [`k${i}`, "1"]));
    const api = new FakeApi(() =>
      okEnvelope(COMPARE_DATA, { caveats: [{ code: "x", params, en: "", ar: "" }] }),
    );
    const result = await registry(api).run("compare", PAIR, VIEWER, "t");
    expect(result).toMatchObject({ status: "error", code: "upstream_invalid" });
  });

  it("reviewer #41 condition 1: wraps caveats, detail and cohort text as untrusted", async () => {
    const prose = { en: INJECTION, ar: INJECTION };
    const api = new FakeApi(() =>
      okEnvelope(undefined, {
        status: "not_enough_data",
        reason: "cohort_too_small",
        detail: prose,
        caveats: [{ code: "retailer_partial", ...prose }],
        cohort: { description: INJECTION, n: 3 },
      }),
    );
    const result = (await registry(api).run("compare", PAIR, VIEWER, "t")) as ToolEnvelope;
    expect(result.status).toBe("not_enough_data");
    const wrapped = [
      result.notEnoughData?.detail.en,
      result.notEnoughData?.detail.ar,
      result.caveats[0]?.en,
      result.caveats[0]?.ar,
      result.citation.cohort?.description,
    ];
    for (const item of wrapped) {
      expect(Object.keys(item ?? {})).toEqual(["untrusted"]);
      expect(item?.untrusted).not.toContain("\u200b");
      expect(item?.untrusted).not.toContain("](https://evil");
    }
    // Wrapped prose never supports a number: the injected "50%" stays unsupported.
    expect(verifyAnswerNumbers("50% cheaper", [result]).ok).toBe(false);
    expect(verifyAnswerNumbers("3 pairs", [result]).ok).toBe(true);
  });

  it("escapes injected retailer text and drops minor units", async () => {
    const api = new FakeApi(() => okEnvelope(COMPARE_DATA));
    const result = (await registry(api).run("compare", PAIR, VIEWER, "t")) as ToolEnvelope;
    const text = JSON.stringify(result.data);
    expect(text).not.toContain("​");
    expect(text).not.toContain("](https://evil");
    expect(text).toContain("\\\\!\\\\[x\\\\]");
    expect(text).not.toContain("minor");
  });

  it("filters evidence links in data and strips admin-only fields for viewers", async () => {
    const api = new FakeApi(() => okEnvelope(PRODUCT_DATA, { cohort: null }));
    const result = (await registry(api).run(
      "get_product",
      { id: "p01" },
      VIEWER,
      "t",
    )) as ToolEnvelope;
    expect(api.calls[0]?.request.path).toBe("/api/v1/products/p01");
    expect(result.citation.cohort).toBeNull();
    const offers = (result.data as { offers: { evidence: unknown }[] }).offers;
    expect(offers.map((offer) => offer.evidence)).toEqual([
      { capturedAt: "2026-09-15T08:00:00Z", url: "https://shop.north.example/p/p01" },
      { capturedAt: "2026-09-15T08:00:00Z", url: null },
    ]);
  });

  it("keeps admin-only evidence fields for admins", async () => {
    const api = new FakeApi(() => okEnvelope(PRODUCT_DATA));
    const result = (await registry(api).run(
      "get_product",
      { id: "p01" },
      ADMIN,
      "t",
    )) as ToolEnvelope;
    const offers = (result.data as { offers: { evidence: unknown }[] }).offers;
    expect(offers[0]?.evidence).toMatchObject({
      runId: "run-north-7",
      source: { untrusted: "north-listing" },
    });
  });

  it("end to end: the verifier accepts tool numbers and rejects injected ones", async () => {
    const api = new FakeApi(() => okEnvelope(COMPARE_DATA));
    const result = await registry(api).run("compare", PAIR, VIEWER, "t");
    expect(
      verifyAnswerNumbers(
        "North is cheaper on 4 of 8 pairs; basket 1,020.74 vs 980.50 AED. [[product:p01]] is 20.0% dearer at South: 100.00 vs 120.00.",
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
      data: null,
      cohort: null,
      caveats: [],
      meta: META,
    }));
    const result = (await registry(api).run(
      "assortment_gaps",
      { missingAt: "east", presentAt: "north" },
      VIEWER,
      "t",
    )) as ToolEnvelope;
    expect(result.status).toBe("not_enough_data");
    expect(result.notEnoughData?.reason).toBe("retailer_partial");
    expect(result.data).toBeUndefined();
  });

  it("keeps rows on not_enough_data (cohort below the minimum)", async () => {
    const api = new FakeApi(() => ({
      ...okEnvelope({ rows: [{ id: "p01", name: "Cream", gap: { pct: "-16.7" } }], summary: null }),
      status: "not_enough_data",
      reason: "cohort_too_small",
      detail: { en: "Fewer than five counted pairs.", ar: "…" },
    }));
    const result = (await registry(api).run("compare", PAIR, VIEWER, "t")) as ToolEnvelope;
    expect(result.notEnoughData?.reason).toBe("cohort_too_small");
    expect(result.data).toEqual({
      rows: [{ id: "p01", name: { untrusted: "Cream" }, gap: { pct: "-16.7" } }],
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
