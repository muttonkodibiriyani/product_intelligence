/**
 * The tools against the published service-layer contract (docs/contracts/, owned by the Deep
 * Coder): every request uses a declared GET path and declared parameters, every required
 * parameter is sent, the sanitiser's source-text list covers every `x-pi-source-text` field,
 * and every golden response passes through the registry. These files are read at test time
 * only; nothing under src/ depends on them (ADR-0007).
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { SOURCE_TEXT_KEYS, STRUCTURAL_KEYS } from "../src/guard/sanitise.js";
import { verifyAnswerNumbers } from "../src/guard/verifier.js";
import { TOOLS } from "../src/tools/definitions.js";
import {
  ToolRegistry,
  type ToolEnvelope,
  type ToolResult,
  truncation,
} from "../src/tools/registry.js";
import { FakeApi, MINIMAL } from "./fake-api.js";

const VIEWER_CALLER = { uid: "u", role: "viewer" } as const;

const CONTRACTS = new URL("../../../docs/contracts/", import.meta.url);

interface Parameter {
  readonly name: string;
  readonly in: string;
  readonly required?: boolean;
}
interface OpenApi {
  readonly paths: Record<string, Record<string, { readonly parameters?: Parameter[] }>>;
  readonly components: { readonly schemas: Record<string, unknown> };
}

const OPENAPI = JSON.parse(
  readFileSync(new URL("pi-api.openapi.json", CONTRACTS), "utf8"),
) as OpenApi;

function golden(name: string): unknown {
  return JSON.parse(readFileSync(new URL(`golden/pi-api/${name}.json`, CONTRACTS), "utf8"));
}

/** The OpenAPI path template matching a concrete request path. */
function operationFor(path: string): { template: string; parameters: Parameter[] } | undefined {
  for (const [template, item] of Object.entries(OPENAPI.paths)) {
    const pattern = new RegExp(`^${template.replace(/\{[^}]+\}/g, "[^/]+")}$`);
    if (pattern.test(path) && item.get) {
      return { template, parameters: item.get.parameters ?? [] };
    }
  }
  return undefined;
}

describe("tools vs pi-api.openapi.json", () => {
  it("every tool sends a declared GET with declared parameters and all required ones", () => {
    for (const tool of TOOLS) {
      const request = tool.request(tool.input.parse(MINIMAL[tool.name] ?? {}) as never);
      const operation = operationFor(request.path);
      expect(operation, `${tool.name} ${request.path}`).toBeDefined();
      const query = operation?.parameters.filter((p) => p.in === "query") ?? [];
      const declared = new Set(query.map((p) => p.name));
      for (const key of Object.keys(request.query ?? {})) {
        expect(declared.has(key), `${tool.name}: ${key}`).toBe(true);
      }
      for (const required of query.filter((p) => p.required === true)) {
        expect(Object.keys(request.query ?? {}), tool.name).toContain(required.name);
      }
    }
  });

  it("every input key a tool can send is a declared parameter", () => {
    for (const tool of TOOLS) {
      const shape = (tool.input as unknown as { _def: { schema?: unknown } })._def;
      const object = (shape.schema ?? tool.input) as { shape?: Record<string, unknown> };
      const operation = operationFor(
        tool.request(tool.input.parse(MINIMAL[tool.name] ?? {}) as never).path,
      );
      const declared = new Set(operation?.parameters.map((p) => p.name));
      expect(Object.keys(object.shape ?? {}).length, tool.name).toBeGreaterThan(0);
      for (const key of Object.keys(object.shape ?? {})) {
        // `ids` travels as the repeated `id`; a path id travels in the path.
        const sent = key === "ids" ? "id" : key;
        if (tool.name === "get_product" && key === "id") continue;
        expect(declared.has(sent), `${tool.name}.${key}`).toBe(true);
      }
    }
  });

  it("the sanitiser wraps every x-pi-source-text field", () => {
    const marked = new Set<string>();
    for (const schema of Object.values(OPENAPI.components.schemas)) {
      const properties = (schema as { properties?: Record<string, unknown> }).properties ?? {};
      for (const [key, value] of Object.entries(properties)) {
        if (JSON.stringify(value).includes('"x-pi-source-text":true')) marked.add(key);
      }
    }
    expect(marked.size).toBeGreaterThan(5);
    for (const key of marked) {
      const isUrl = /(?:^url|Url)$/.test(key);
      expect(isUrl || SOURCE_TEXT_KEYS.has(key), key).toBe(true);
      expect(STRUCTURAL_KEYS.has(key), key).toBe(false);
    }
  });
});

/** Golden response → the tool that reads it, with a valid input. */
const GOLDENS: readonly [string, string, unknown][] = [
  ["products", "search_products", {}],
  ["products-filtered", "search_products", {}],
  ["products-gap", "search_products", {}],
  ["product", "get_product", { id: "p01" }],
  ["compare", "compare", MINIMAL.compare],
  ["compare-blocked", "compare", MINIMAL.compare],
  ["compare-limited", "compare", MINIMAL.compare],
  ["index", "index_trend", MINIMAL.index_trend],
  ["promotions", "promotions", {}],
  ["assortment-gaps", "assortment_gaps", MINIMAL.assortment_gaps],
  ["launches", "launches", {}],
  ["reviews-summary", "reviews_summary", {}],
  ["coverage", "coverage_status", {}],
];

describe("golden responses through the registry", () => {
  it.each(GOLDENS)("%s via %s", async (name, tool, input) => {
    const body = golden(name) as { status: string };
    const registry = new ToolRegistry(TOOLS, new FakeApi(() => body), { evidenceHosts: [] });
    const result: ToolResult = await registry.run(tool, input, { uid: "u", role: "viewer" }, "t");
    expect(result.status, JSON.stringify(result)).toBe(body.status);
    const envelope = result as ToolEnvelope;
    const text = JSON.stringify(envelope);
    expect(text).not.toContain('"minor"');
    expect(text).not.toContain('"runId"');
    expect(text).not.toMatch(/"url":"(?!null)/);
  });
});

describe("a cut list (API 1.1.0 limit)", () => {
  it("adds shown and a truncated caveat, so 'top N of total' passes the verifier", async () => {
    const body = golden("compare-limited");
    const registry = new ToolRegistry(TOOLS, new FakeApi(() => body), { evidenceHosts: [] });
    const result = (await registry.run(
      "compare",
      MINIMAL.compare,
      VIEWER_CALLER,
      "t",
    )) as ToolEnvelope;
    expect(result.data).toMatchObject({ total: 15, truncated: true, shown: 3 });
    expect(result.caveats.at(-1)).toEqual({
      code: "truncated",
      en: {
        untrusted:
          "Only the first 3 of 15 rows are listed, the row limit. Any summary is computed over all rows, not only the listed ones; its n is what it counted.",
      },
      ar: {
        untrusted:
          "تُعرض أول 3 من أصل 15 صفًا فقط بسبب حد الصفوف. أي ملخص محسوب على جميع الصفوف لا على المعروضة فقط، وقيمة n فيه هي ما احتُسب.",
      },
    });
    expect(verifyAnswerNumbers("Top 3 of 15 pairs.", [result]).ok).toBe(true);
  });

  it.each(["compare", "promotions", "launches"])(
    "%s adds nothing when not truncated",
    async (name) => {
      const body = golden(name === "compare" ? "compare" : name);
      const registry = new ToolRegistry(TOOLS, new FakeApi(() => body), { evidenceHosts: [] });
      const input = name === "compare" ? MINIMAL.compare : {};
      const result = (await registry.run(name, input, VIEWER_CALLER, "t")) as ToolEnvelope;
      expect(result.caveats.map((caveat) => caveat.code)).not.toContain("truncated");
      expect(result.data).not.toHaveProperty("shown");
    },
  );
});

describe("truncation", () => {
  it.each([
    [{ rows: [1, 2], total: 9, truncated: true }, "rows", { shown: 2, total: 9 }],
    [{ rows: [1, 2], total: 2, truncated: false }, "rows", null],
    [{ rows: [1, 2], total: 9, truncated: true }, undefined, null],
    [{ rows: [1, 2], total: "9", truncated: true }, "rows", null],
    [{ items: [1], total: 9, truncated: true }, "rows", null],
    [{ rows: [1], total: 9, truncated: "true" }, "rows", null],
    [null, "rows", null],
    [[1, 2], "rows", null],
  ])("%j via %s → %j", (data, key, expected) => {
    expect(truncation(data, key)).toEqual(expected);
  });
});
