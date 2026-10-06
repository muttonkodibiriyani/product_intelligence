/**
 * Eval mode (E1b, migration task 01a0fcc7): the committed `evals/eval-config.json` lets an
 * operator-run eval call a candidate model without touching `assistant_config/current`.
 *
 * The file is authored and changed only in a reviewed PR; nothing writes it at runtime. It holds
 * the candidate allowlist, the ci caps and the call limits. `PI_EVAL_MODEL` picks one candidate
 * per run. The effective config is built fail-closed from the file AND the live document, and
 * re-read before every call like the live one:
 *
 * - either source missing or invalid: refuse;
 * - `current.disabledBy` set: refuse. Under R4 no budget kill switch is deployed, so nothing sets
 *   it today; it is honoured, but it is not the cost bound;
 * - `current.enabled` is ignored: evals run before switch-on;
 * - the model must be allowlisted here AND priced in `prices.json`; there is no default;
 * - non-numeric fields shared with current (`priceTableVersion`) must equal it;
 * - numeric fields (the ci caps, every limit) must not exceed current's, or the meter refuses.
 *
 * The cost bound is the meter's counters: `label/ci/<month>` against the ci cap, and the shared
 * `total/<month>` against the live `current.caps.monthUsd`. Eval spend therefore uses up the
 * live month's headroom.
 *
 * Only the eval provider imports this module; the live function never does (import-boundary
 * test in `test/eval-config.test.ts`).
 */
import { readFileSync } from "node:fs";

import { z } from "zod";

import { type AssistantConfig, AssistantConfigSchema } from "../meter/config.js";
import { type ConfigSource, MeterRefusal } from "../meter/meter.js";
import { parseUsd } from "../meter/prices.js";

export const EVAL_LABEL = "ci";

const live = AssistantConfigSchema.shape;

export const EvalConfigSchema = z
  .object({
    $comment: z.string().optional(),
    /** Empty means no eval may call a model. */
    candidateModels: z.array(live.model).max(4),
    priceTableVersion: live.priceTableVersion,
    caps: z
      .object({
        labelMonthUsd: live.caps.shape.monthUsd,
        labelDayUsd: live.caps.shape.monthUsd.optional(),
      })
      .strict(),
    limits: live.limits,
  })
  .strict();

export type EvalConfig = z.infer<typeof EvalConfigSchema>;

/** The committed file, or null if it is missing or not JSON (the source then refuses). */
export function loadEvalConfig(
  url: URL = new URL("../../evals/eval-config.json", import.meta.url),
): unknown {
  try {
    return JSON.parse(readFileSync(url, "utf8")) as unknown;
  } catch {
    return null;
  }
}

const above = (value: string, cap: string): boolean => parseUsd(value) > parseUsd(cap);

/** The eval `ConfigSource` for one run: the file's settings, bounded by the live document. */
export function evalConfigSource(raw: unknown, model: string | undefined): ConfigSource {
  return async (store, prices): Promise<AssistantConfig> => {
    const file = EvalConfigSchema.safeParse(raw);
    const current = AssistantConfigSchema.safeParse(await store.readConfig());
    if (!file.success || !current.success) throw new MeterRefusal("config_invalid");
    const evals = file.data;
    const config = current.data;
    if (config.disabledBy !== undefined) throw new MeterRefusal("disabled");
    if (
      evals.priceTableVersion !== config.priceTableVersion ||
      evals.priceTableVersion !== prices.version
    ) {
      throw new MeterRefusal("price_table_mismatch");
    }
    if (model === undefined || !evals.candidateModels.includes(model) || !prices.has(model)) {
      throw new MeterRefusal("unknown_model");
    }
    // A live ci month cap is required; a live ci day cap only if the live document has one.
    const liveMonth = config.caps.labelMonthUsd[EVAL_LABEL];
    const liveDay = config.caps.labelDayUsd[EVAL_LABEL];
    const limits = Object.entries(evals.limits) as [keyof typeof evals.limits, number][];
    if (
      liveMonth === undefined ||
      above(evals.caps.labelMonthUsd, liveMonth) ||
      (liveDay !== undefined &&
        evals.caps.labelDayUsd !== undefined &&
        above(evals.caps.labelDayUsd, liveDay)) ||
      limits.some(([key, value]) => value > config.limits[key])
    ) {
      throw new MeterRefusal("eval_above_live");
    }
    const labelDayUsd = { ...config.caps.labelDayUsd };
    if (evals.caps.labelDayUsd !== undefined) labelDayUsd[EVAL_LABEL] = evals.caps.labelDayUsd;
    return {
      ...config,
      enabled: true,
      model,
      caps: {
        ...config.caps,
        labelMonthUsd: { ...config.caps.labelMonthUsd, [EVAL_LABEL]: evals.caps.labelMonthUsd },
        labelDayUsd,
      },
      limits: evals.limits,
    };
  };
}
