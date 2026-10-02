import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  EVAL_LABEL,
  EvalConfigSchema,
  evalConfigSource,
  loadEvalConfig,
} from "../src/evals/eval-config.js";
import { MemoryUsageStore } from "../src/meter/memory-store.js";
import { Meter, MeterRefusal, type RefusalCode, counterKeys } from "../src/meter/meter.js";
import { Prices } from "../src/meter/prices.js";
import { CONFIG, PRICE_TABLE, prices } from "./meter-fixtures.js";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const NOW = new Date("2026-09-30T12:00:00Z");
const MONTH = "2026-09";
const CALLER = { uid: "ci-viewer-run-1", role: "viewer" as const };
const USAGE = { input: 1_000, cachedInput: 0, output: 100, thinking: 0 };

/** A fake 3.x-style id with fixture prices: never real 3.x numbers. */
const CANDIDATE = "gemini-3.0-flash-fixture";
const PRICED = new Prices({
  ...PRICE_TABLE,
  models: {
    ...PRICE_TABLE.models,
    [CANDIDATE]: { input: "1.00", output: "2.00", cachedInput: "0.10" },
  },
});

/** The live document before switch-on: `enabled` is false, which evals ignore. */
const LIVE = { ...CONFIG, enabled: false };
const FILE = {
  candidateModels: [CANDIDATE, "gemini-3.0-unpriced"],
  priceTableVersion: PRICE_TABLE.version,
  caps: { labelMonthUsd: "1.00" },
  limits: { ...CONFIG.limits, maxOutputTokens: 1_000 },
};

/** `model` is explicit: `undefined` is the PI_EVAL_MODEL-unset case, not a default. */
function setup(live: unknown, file: unknown, model: string | undefined) {
  const store = new MemoryUsageStore(live);
  const meter = new Meter(store, PRICED, () => NOW, undefined, evalConfigSource(file, model));
  return { store, meter };
}

async function refusal(promise: Promise<unknown>): Promise<RefusalCode> {
  try {
    await promise;
  } catch (cause) {
    if (cause instanceof MeterRefusal) return cause.code;
    throw cause;
  }
  throw new Error("expected a refusal");
}

const ok = (model: string) => Promise.resolve({ usage: USAGE, value: model });

describe("the committed evals/eval-config.json", () => {
  it("is valid, priced against prices.json and allows no model until the prices PR", () => {
    const raw = loadEvalConfig();
    const file = EvalConfigSchema.parse(raw);
    expect(file.priceTableVersion).toBe(PRICE_TABLE.version);
    for (const model of file.candidateModels) expect(prices().has(model)).toBe(true);
    expect(raw).toEqual(
      JSON.parse(readFileSync(join(ROOT, "evals", "eval-config.json"), "utf8")) as unknown,
    );
  });

  it("loads as null (and the meter refuses) when missing or not JSON", () => {
    expect(loadEvalConfig(new URL("file:///nonexistent/eval-config.json"))).toBeNull();
    expect(loadEvalConfig(new URL("../package.json", import.meta.url))).not.toBeNull();
  });
});

describe("eval config source", () => {
  it("runs the candidate under the ci label on the shared counters, live switch ignored", async () => {
    const { store, meter } = setup(LIVE, FILE, CANDIDATE);
    const question = await meter.startQuestion(CALLER, EVAL_LABEL);
    expect(await meter.call(question, (_limits, model) => ok(model))).toBe(CANDIDATE);
    for (const key of [counterKeys.labelMonth(EVAL_LABEL, MONTH), counterKeys.month(MONTH)]) {
      expect(store.counters.get(key)?.spent).toBeGreaterThan(0n);
    }
    expect(store.config).toEqual(LIVE);
  });

  it("builds the effective config from the file, bounded by the live document", async () => {
    const live = { ...LIVE, caps: { ...LIVE.caps, labelDayUsd: { chat: "0.40", ci: "0.30" } } };
    const config = await evalConfigSource(FILE, CANDIDATE)(new MemoryUsageStore(live), PRICED);
    expect(config).toEqual({
      ...live,
      enabled: true,
      model: CANDIDATE,
      caps: { ...live.caps, labelMonthUsd: { ci: "1.00" } },
      limits: FILE.limits,
    });
  });

  it.each<[string, unknown, unknown, string | undefined, RefusalCode]>([
    ["a missing eval file", LIVE, null, CANDIDATE, "config_invalid"],
    ["an invalid eval file", LIVE, { ...FILE, model: CANDIDATE }, CANDIDATE, "config_invalid"],
    ["a missing live document", null, FILE, CANDIDATE, "config_invalid"],
    ["an invalid live document", { enabled: true }, FILE, CANDIDATE, "config_invalid"],
    [
      "disabledBy set",
      { ...LIVE, disabledBy: "budget_alert:100%:2026-09" },
      FILE,
      CANDIDATE,
      "disabled",
    ],
    ["PI_EVAL_MODEL unset", LIVE, FILE, undefined, "unknown_model"],
    ["a priced model not allowlisted", LIVE, FILE, "gemini-2.5-pro", "unknown_model"],
    ["an allowlisted model not in prices.json", LIVE, FILE, "gemini-3.0-unpriced", "unknown_model"],
    [
      "the file's price table differing from current (string: must equal)",
      LIVE,
      { ...FILE, priceTableVersion: "2026-10-13" },
      CANDIDATE,
      "price_table_mismatch",
    ],
    [
      "current's price table differing from prices.json",
      { ...LIVE, priceTableVersion: "old" },
      { ...FILE, priceTableVersion: "old" },
      CANDIDATE,
      "price_table_mismatch",
    ],
    [
      "a limit above current (numeric: must not exceed)",
      LIVE,
      { ...FILE, limits: { ...FILE.limits, maxOutputTokens: CONFIG.limits.maxOutputTokens + 1 } },
      CANDIDATE,
      "eval_above_live",
    ],
    [
      "a ci month cap above current",
      LIVE,
      { ...FILE, caps: { labelMonthUsd: "1.51" } },
      CANDIDATE,
      "eval_above_live",
    ],
    [
      "no live ci month cap",
      { ...LIVE, caps: { ...LIVE.caps, labelMonthUsd: {} } },
      FILE,
      CANDIDATE,
      "eval_above_live",
    ],
    [
      "a ci day cap above current's",
      { ...LIVE, caps: { ...LIVE.caps, labelDayUsd: { ci: "0.10" } } },
      { ...FILE, caps: { labelMonthUsd: "1.00", labelDayUsd: "0.20" } },
      CANDIDATE,
      "eval_above_live",
    ],
  ])("refuses on %s", async (_name, live, file, model, code) => {
    const { meter } = setup(live, file, model);
    expect(await refusal(meter.startQuestion(CALLER, EVAL_LABEL))).toBe(code);
  });

  it.each<[string, string, string, RefusalCode]>([
    ["the ci counter", counterKeys.labelMonth(EVAL_LABEL, MONTH), "1.00", "label_month_cap"],
    ["the shared total", counterKeys.month(MONTH), CONFIG.caps.monthUsd, "month_cap"],
  ])("refuses once %s reaches its cap", async (_name, key, capUsd, code) => {
    const { store, meter } = setup(LIVE, FILE, CANDIDATE);
    const spent = BigInt(Math.round(Number(capUsd) * 1_000_000));
    store.counters.set(key, { spent, reserved: 0n, questions: 0 });
    const question = await meter.startQuestion(CALLER, EVAL_LABEL);
    let calls = 0;
    const call = (_limits: unknown, model: string) => {
      calls += 1;
      return ok(model);
    };
    expect(await refusal(meter.call(question, call))).toBe(code);
    expect(calls).toBe(0);
  });

  it("re-reads both sources before every call", async () => {
    const { store, meter } = setup(LIVE, FILE, CANDIDATE);
    const question = await meter.startQuestion(CALLER, EVAL_LABEL);
    await meter.call(question, (_limits, model) => ok(model));
    store.config = { ...LIVE, disabledBy: "budget_alert:100%:2026-09" };
    expect(await refusal(meter.call(question, (_limits, model) => ok(model)))).toBe("disabled");
  });
});

/** Relative imports (static and dynamic) of one source file, resolved to `.ts` paths. */
function imports(file: string): string[] {
  const text = readFileSync(file, "utf8");
  return [...text.matchAll(/(?:from|import)\s*\(?\s*["'](\.{1,2}\/[^"']+)["']/g)].map((match) =>
    resolve(dirname(file), (match[1] ?? "").replace(/\.js$/, ".ts")),
  );
}

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile())
    .map((entry) => join(entry.parentPath, entry.name));
}

const FORBIDDEN = ["eval-config", "evalConfigSource", "PI_EVAL_MODEL"];

describe("import boundary: the live function never reaches the eval config", () => {
  it("holds for every source file reachable from src/index.ts and src/functions/**", () => {
    const src = join(ROOT, "src");
    const queue = [join(src, "index.ts"), ...files(join(src, "functions"))];
    const seen = new Set<string>();
    while (queue.length > 0) {
      const file = queue.pop() ?? "";
      if (seen.has(file)) continue;
      seen.add(file);
      queue.push(...imports(file));
    }
    expect(seen.size).toBeGreaterThan(10);
    const reached = [...seen].map((file) => relative(src, file));
    expect(reached.filter((file) => file.startsWith("evals"))).toEqual([]);
    for (const file of seen) {
      const text = readFileSync(file, "utf8");
      expect(
        FORBIDDEN.filter((word) => text.includes(word)),
        file,
      ).toEqual([]);
    }
  });

  it("holds for the built lib", { timeout: 120_000 }, () => {
    const out = mkdtempSync(join(ROOT, ".lib-boundary-"));
    try {
      execFileSync(
        process.execPath,
        [
          join(ROOT, "node_modules", "typescript", "bin", "tsc"),
          "-p",
          "tsconfig.build.json",
          "--outDir",
          out,
        ],
        { cwd: ROOT, stdio: "pipe" },
      );
      const emitted = files(out).filter((file) => file.endsWith(".js"));
      expect(emitted.some((file) => file.endsWith(join("functions", "runtime.js")))).toBe(true);
      expect(emitted.filter((file) => relative(out, file).startsWith("evals"))).toEqual([]);
      for (const file of emitted) {
        const text = readFileSync(file, "utf8");
        expect(
          FORBIDDEN.filter((word) => text.includes(word)),
          file,
        ).toEqual([]);
      }
    } finally {
      rmSync(out, { recursive: true, force: true });
    }
  });
});
