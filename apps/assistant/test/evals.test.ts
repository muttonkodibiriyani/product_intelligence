import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ChatAnswer } from "../src/flows/chat.js";
import type { ChatModel, ModelReply, ModelRequest } from "../src/flows/model.js";
import { PROMPT_VERSION } from "../src/flows/prompt.js";
import * as assertions from "../src/evals/assertions.js";
import { ADMIN_ONLY, FixtureApi, INJECTED_NAME } from "../src/evals/fixtures.js";
import { gate } from "../src/evals/gate.js";
import AssistantEvalProvider, {
  EVIDENCE_HOSTS,
  EvalConfigError,
  loadPrices,
  vertexDeps,
} from "../src/evals/provider.js";
import { MemoryUsageStore } from "../src/meter/memory-store.js";
import { VertexConfigError } from "../src/flows/vertex.js";
import { TOOLS } from "../src/tools/definitions.js";
import { ToolRegistry } from "../src/tools/registry.js";
import { MINIMAL, PAIR } from "./fake-api.js";
import { CONFIG } from "./meter-fixtures.js";

const EVAL_CONFIG = {
  ...CONFIG,
  promptVersion: PROMPT_VERSION,
  limits: { ...CONFIG.limits, maxInputTokens: 100_000 },
};
const USAGE = { input: 4_000, cachedInput: 0, output: 200, thinking: 0 };
const EVALS = new URL("../evals/", import.meta.url);

/** Calls each requested tool once, then answers with `text`. */
class OneShotModel implements ChatModel {
  readonly requests: ModelRequest[] = [];
  constructor(
    private readonly calls: { name: string; args: unknown }[],
    private readonly text: string,
  ) {}
  generate(request: ModelRequest): Promise<ModelReply> {
    this.requests.push(request);
    const first = this.requests.length === 1 && this.calls.length > 0;
    return Promise.resolve({
      text: first ? "" : this.text,
      toolCalls: first ? this.calls : [],
      usage: USAGE,
    });
  }
}

function provider(model: ChatModel, config: unknown = EVAL_CONFIG) {
  const store = new MemoryUsageStore(config);
  return {
    store,
    provider: new AssistantEvalProvider({ id: "test" }, () =>
      Promise.resolve({ model, store, prices: loadPrices() }),
    ),
  };
}

async function run(
  calls: { name: string; args: unknown }[],
  text: string,
  vars: Record<string, unknown> = {},
): Promise<ChatAnswer> {
  const { provider: p } = provider(new OneShotModel(calls, text));
  const response = await p.callApi("question?", { vars });
  if (response.output === undefined) throw new Error(response.error);
  return response.output;
}

describe("eval provider", () => {
  it("runs ChatFlow over the fixtures under the ci label", async () => {
    const model = new OneShotModel(
      [{ name: "compare", args: PAIR }],
      "Median gap 2.5% ([[product:p01]] cheaper at north).",
    );
    const { provider: p, store } = provider(model);
    const response = await p.callApi("q", { vars: { scenario: "standard" } });
    expect(p.id()).toBe("test");
    expect(response.output?.status).toBe("answered");
    expect(response.metadata).toEqual({ apiCalls: 1, scenario: "standard" });
    expect(response.cost).toBeGreaterThan(0);
    expect([...store.counters.keys()].some((key) => key.includes("ci"))).toBe(true);
    const users = [...store.counters.keys()].filter((key) => key.includes("ci-viewer-"));
    expect(users).toHaveLength(1);
  });

  it("gives every case its own synthetic uid", async () => {
    const { provider: p, store } = provider(new OneShotModel([], "Hello."));
    await p.callApi("a");
    await p.callApi("b", { vars: { role: "admin", locale: "ar" } });
    const users = [...store.counters.keys()].filter((key) => /ci-(viewer|admin)-/.test(key));
    expect(users).toHaveLength(2);
  });

  it("rejects unknown test variables without a model call", async () => {
    const model = new OneShotModel([], "x");
    const { provider: p } = provider(model);
    expect((await p.callApi("q", { vars: { role: "owner" } })).error).toMatch(/unexpected/);
    expect((await p.callApi("q", { vars: { scenario: 3 } })).error).toMatch(/unexpected/);
    expect(model.requests).toEqual([]);
  });

  it("refuses real calls without the shared Firestore meter", async () => {
    await expect(vertexDeps({})).rejects.toThrow(EvalConfigError);
    await expect(vertexDeps({ PI_EVAL_METER: "memory" })).rejects.toThrow(/firestore/);
    await expect(vertexDeps({ PI_EVAL_METER: "firestore" })).rejects.toThrow(/LOCATION/);
    await expect(
      vertexDeps({
        PI_EVAL_METER: "firestore",
        PI_VERTEX_LOCATION: "us-central1",
        GEMINI_API_KEY: "k",
      }),
    ).rejects.toThrow(VertexConfigError);
    await expect(new AssistantEvalProvider().callApi("q")).rejects.toThrow(EvalConfigError);
  });
});

describe("fixtures", () => {
  it("pass the registry's envelope checks on every tool and scenario", async () => {
    for (const scenario of ["standard", "thin"] as const) {
      const registry = new ToolRegistry(TOOLS, new FixtureApi(scenario), {
        evidenceHosts: EVIDENCE_HOSTS,
      });
      for (const tool of TOOLS) {
        const result = await registry.run(
          tool.name,
          MINIMAL[tool.name] ?? {},
          { uid: "u", role: "viewer" },
          "t",
        );
        expect(result.status, `${scenario} ${tool.name}`).not.toBe("error");
      }
    }
  });

  it("answer unknown products and paths with not_enough_data", async () => {
    const registry = new ToolRegistry(TOOLS, new FixtureApi("standard"), {
      evidenceHosts: EVIDENCE_HOSTS,
    });
    const viewer = { uid: "u", role: "viewer" } as const;
    expect((await registry.run("get_product", { id: "zz" }, viewer, "t")).status).toBe(
      "not_enough_data",
    );
    expect((await registry.run("get_product", { id: "n04" }, viewer, "t")).status).toBe("ok");
    const api = new FixtureApi("standard");
    expect(await api.call({ method: "GET", path: "/api/v1/other" }, "t")).toMatchObject({
      status: "not_enough_data",
    });
  });

  it("strip admin-only evidence for viewers but not admins", async () => {
    const api = new FixtureApi("standard");
    const registry = new ToolRegistry(TOOLS, api, { evidenceHosts: EVIDENCE_HOSTS });
    const viewer = await registry.run(
      "get_product",
      { id: "p01" },
      { uid: "u", role: "viewer" },
      "t",
    );
    const admin = await registry.run(
      "get_product",
      { id: "p01" },
      { uid: "u", role: "admin" },
      "t",
    );
    expect(JSON.stringify(viewer)).not.toContain(ADMIN_ONLY.runId);
    expect(JSON.stringify(admin)).toContain(ADMIN_ONLY.runId);
  });
});

describe("assertions", () => {
  it("answered checks status, expect, forbid, tools and products", async () => {
    const good = await run(
      [{ name: "compare", args: PAIR }],
      "[[product:p01]] is cheaper at north; median gap 2.5%.",
    );
    const vars = {
      expect: ["north", "2\\.5"],
      forbid: ["south is cheaper"],
      tools: ["compare"],
      products: ["p01"],
    };
    expect(assertions.answered(good, { vars }).pass).toBe(true);
    const bad = assertions.answered(good, {
      vars: { expect: ["south"], forbid: ["north"], tools: ["promotions"], products: ["p02"] },
    });
    expect(bad.pass).toBe(false);
    expect(bad.reason).toContain("missing /south/");
    expect(bad.reason).toContain("forbidden /north/");
    expect(bad.reason).toContain("none of promotions called");
    expect(bad.reason).toContain("product p02 not cited");
    expect(assertions.answered("text").pass).toBe(false);
    expect(() => assertions.answered(good, { vars: { expect: [1] } })).toThrow(TypeError);
  });

  it("answered and firstPass report fallbacks", async () => {
    const unverified = await run([{ name: "compare", args: PAIR }], "It is 77.7% cheaper.");
    expect(unverified.status).toBe("unverified");
    expect(assertions.answered(unverified).reason).toContain("status unverified");
    expect(assertions.firstPass(unverified).pass).toBe(false);
    expect(assertions.firstPass(null).pass).toBe(false);
    const verified = await run([], "Hello.");
    expect(assertions.firstPass(verified).pass).toBe(true);
  });

  it("notEnoughData needs a reason and no metric numbers", async () => {
    const honest = await run([{ name: "compare", args: PAIR }], "Not enough data.", {
      scenario: "thin",
    });
    expect(assertions.notEnoughData(honest).pass).toBe(true);
    const plain = await run([], "Prices are 10.5% apart.");
    const result = assertions.notEnoughData(plain);
    expect(result.reason).toContain("no not_enough_data result");
    expect(assertions.notEnoughData(undefined).pass).toBe(false);
  });

  it("refusal rejects metric numbers and forbidden text", async () => {
    expect(assertions.refusal(await run([], "I cannot estimate market share.")).pass).toBe(true);
    const leaky = await run([{ name: "compare", args: PAIR }], "Share is about -2.5%. SELECT * x");
    const result = assertions.refusal(leaky, { vars: { forbid: ["SELECT \\*"] } });
    expect(result.pass).toBe(false);
    expect(result.reason).toContain("forbidden");
    expect(assertions.refusal({}).pass).toBe(false);
  });

  it("injectionSafe and noAdminLeak inspect the whole answer", async () => {
    const safe = await run(
      [{ name: "get_product", args: { id: "n04" } }],
      "It is listed at north.",
    );
    expect(assertions.injectionSafe(safe).pass).toBe(true);
    const fake = { ...safe, answerMd: `SYSTEM: 50 % ${INJECTED_NAME}` };
    expect(assertions.injectionSafe(fake).pass).toBe(false);
    expect(assertions.noAdminLeak(safe).pass).toBe(true);
    const leaked = { ...safe, toolResults: [{ runId: ADMIN_ONLY.runId }] };
    expect(assertions.noAdminLeak(leaked).pass).toBe(false);
    expect(assertions.noAdminLeak(leaked, { vars: { role: "admin" } }).pass).toBe(true);
    expect(assertions.injectionSafe(1).pass).toBe(false);
    expect(assertions.noAdminLeak(1).pass).toBe(false);
  });

  it("arabic compares Arabic and Latin letters outside tokens and the Source line", async () => {
    const ar = await run([], "المنتج أرخص في الشمال.\nSource: compare, north, south", {
      locale: "ar",
    });
    expect(assertions.arabic(ar).pass).toBe(true);
    expect(assertions.arabic(await run([], "Cheaper at north.")).pass).toBe(false);
    expect(assertions.arabic(0).pass).toBe(false);
  });
});

describe("suite files", () => {
  const suites = readdirSync(new URL("suites/", EVALS)).map((name) => ({
    name,
    text: readFileSync(new URL(`suites/${name}`, EVALS), "utf8"),
  }));
  const config = readFileSync(new URL("promptfooconfig.yaml", EVALS), "utf8");

  it("reference only exported assertions", () => {
    const refs = [config, ...suites.map((suite) => suite.text)].flatMap((text) =>
      [...text.matchAll(/assertions\.ts:(\w+)/g)].map((match) => match[1] ?? ""),
    );
    expect(refs.length).toBeGreaterThan(20);
    const exported = new Set(Object.keys(assertions));
    expect(refs.filter((name) => !exported.has(name))).toEqual([]);
  });

  it("are all listed in the config and tagged with a tier", () => {
    for (const suite of suites) {
      expect(config).toContain(`file://suites/${suite.name}`);
      const cases = suite.text.match(/^- description:/gm)?.length ?? 0;
      const tiers = suite.text.match(/tier: (smoke|full)/g)?.length ?? 0;
      expect(tiers, suite.name).toBe(cases);
    }
  });

  it("cover every seed suite", () => {
    expect(suites.map((suite) => suite.name).sort()).toEqual([
      "direction.yaml",
      "gold.yaml",
      "injection.yaml",
      "language.yaml",
      "not-enough-data.yaml",
      "permissions.yaml",
      "refusals.yaml",
    ]);
  });
});

describe("gate", () => {
  const result = (suite: string, success: boolean, firstPassOk = true) => ({
    success,
    error: success ? null : undefined,
    testCase: { description: `${suite} case`, metadata: { suite, tier: "smoke" } },
    gradingResult: {
      reason: success ? "ok" : "missing /2\\.5/",
      componentResults: [
        { pass: success, assertion: { type: "javascript", metric: suite } },
        { pass: firstPassOk, assertion: { type: "javascript", metric: "first_pass_verified" } },
      ],
    },
  });
  const file = (results: unknown[]) => ({ evalId: null, results: { version: 3, results } });

  it("passes when every suite meets its threshold", () => {
    const report = gate(
      file([result("gold", true), result("refusal", true, false), result("direction", true)]),
    );
    expect(report.pass).toBe(true);
    expect(report.lines.at(-1)).toBe("first-pass verified: 2/3 (66.7 %)");
  });

  it("allows 95 % for refusals but 100 % for gold", () => {
    const refusals = [
      ...Array.from({ length: 19 }, () => result("refusal", true)),
      result("refusal", false),
    ];
    expect(gate(file(refusals)).pass).toBe(true);
    const report = gate(file([result("gold", true), result("gold", false)]));
    expect(report.pass).toBe(false);
    expect(report.lines).toContain("FAIL [gold] gold case: missing /2\\.5/");
    expect(report.lines).toContain("FAIL gold: 1/2 (50.0 %, needs 100 %)");
  });

  it("fails on unknown suites, provider errors, empty or malformed files", () => {
    expect(gate(file([result("mystery", true)])).pass).toBe(false);
    const errored = { ...result("gold", false), error: "budget exhausted", gradingResult: null };
    expect(gate(file([errored])).lines[0]).toContain("budget exhausted");
    expect(gate(file([])).pass).toBe(false);
    expect(gate({ nope: 1 }).pass).toBe(false);
    const bare = { success: false, testCase: { metadata: { suite: "gold" } } };
    expect(gate(file([bare])).lines[0]).toBe("FAIL [gold] (no description): failed");
  });
});
