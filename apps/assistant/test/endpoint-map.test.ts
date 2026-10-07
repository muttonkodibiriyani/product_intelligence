/**
 * Every /api/v1 operation is either read by a tool or excluded with a reason (S6, coordinator
 * ruling 2026-10-01). A new endpoint fails this test until it gets a tool or an exclusion; tools
 * are never generated at runtime. The map is documented in docs/design/assistant-tools.md.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { TOOLS } from "../src/tools/definitions.js";
import { MINIMAL } from "./fake-api.js";

const OPENAPI = JSON.parse(
  readFileSync(new URL("../../../docs/contracts/pi-api.openapi.json", import.meta.url), "utf8"),
) as { paths: Record<string, Record<string, unknown>> };

/** Operations no tool reads, and why. Patterns match the OpenAPI path template. */
export const EXCLUDED: readonly { readonly pattern: RegExp; readonly reason: string }[] = [
  {
    pattern: /^\/api\/v1\/export\//,
    reason: "file downloads (CSV/XLSX) of reads the tools already make; not an answer",
  },
  {
    pattern: /^\/api\/v1\/admin\//,
    reason: "admin evidence views; the assistant serves viewers with the same tools",
  },
  {
    pattern: /^\/api\/v1\/matches$/,
    reason: "the match review queue (an operator workflow); compare covers approved matches",
  },
  {
    pattern: /^\/api\/v1\/meta$/,
    reason:
      "page bootstrap (attribute sets, labels, dates); coverage_status covers retailers and freshness",
  },
  {
    pattern: /^\/api\/v1\/insights$/,
    reason:
      "Insights page aggregates (brand price policy, size ladders) built from compare's counted pairs; compare answers the same questions",
  },
  {
    pattern: /^\/api\/v1\/findings$/,
    reason:
      "Insights page findings (ranked, worded by the page) built from the catalogues and compare's counted pairs; a tool can follow once the page settles",
  },
  {
    pattern: /^\/api\/v1\/catalogues\//,
    reason:
      "SKU galleries and identity links for the product page (display only); no prices or counts to answer with",
  },
];

const METHODS = ["get", "post", "put", "patch", "delete"];

const operations = Object.entries(OPENAPI.paths).flatMap(([path, item]) =>
  METHODS.filter((m) => m in item).map((m) => ({ method: m.toUpperCase(), path })),
);

const templateOf = (concrete: string): string | undefined =>
  Object.keys(OPENAPI.paths).find((template) =>
    new RegExp(`^${template.replace(/\{[^}]+\}/g, "[^/]+")}$`).test(concrete),
  );

const toolPaths = new Map<string, string[]>();
for (const tool of TOOLS) {
  const request = tool.request(tool.input.parse(MINIMAL[tool.name] ?? {}) as never);
  const template = templateOf(request.path);
  if (template) toolPaths.set(template, [...(toolPaths.get(template) ?? []), tool.name]);
}

describe("/api/v1 operations ↔ tools", () => {
  it("the API has only GET operations (the assistant never writes)", () => {
    expect(operations.filter((op) => op.method !== "GET")).toEqual([]);
  });

  it.each(operations.map((op) => [op.path]))("%s has a tool or an exclusion", (path) => {
    const excluded = EXCLUDED.filter((e) => e.pattern.test(path));
    const tools = toolPaths.get(path) ?? [];
    expect(
      tools.length > 0 || excluded.length > 0,
      `${path}: add a tool or an exclusion with a reason`,
    ).toBe(true);
    expect(tools.length > 0 && excluded.length > 0, `${path}: both a tool and excluded`).toBe(
      false,
    );
  });

  it("every tool reads a declared operation, and every exclusion still matches one", () => {
    expect([...toolPaths.values()].flat().sort()).toEqual(TOOLS.map((t) => t.name).sort());
    for (const { pattern } of EXCLUDED) {
      expect(
        operations.some((op) => pattern.test(op.path)),
        String(pattern),
      ).toBe(true);
    }
  });

  it("the documented map lists every tool and every exclusion", () => {
    const doc = readFileSync(
      new URL("../../../docs/design/assistant-tools.md", import.meta.url),
      "utf8",
    );
    for (const tool of TOOLS) expect(doc, tool.name).toContain(`\`${tool.name}\``);
    for (const { path } of operations) {
      expect(doc, path).toContain(`\`${path.replace("/api/v1", "")}\``);
    }
  });
});
