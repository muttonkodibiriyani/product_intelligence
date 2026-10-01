/**
 * `assistant_config/current` (design §6, §9): the kill switch, model, caps and call limits.
 * A missing or invalid document means the assistant is off; there is no default that spends.
 */
import { z } from "zod";

import { ROLES } from "../tools/types.js";
import { type CallLimits, type MicroUsd, parseUsd } from "./prices.js";

const usd = z.string().regex(/^\d{1,6}(?:\.\d{1,6})?$/, "USD decimal text");
const label = z.string().regex(/^[a-z][a-z0-9_]{0,31}$/);
const tokenCount = z.number().int().min(1).max(1_000_000);

/** Largest prompt the price table prices correctly (base tier of every listed model). */
export const MAX_INPUT_TOKENS = 200_000;

export const AssistantConfigSchema = z
  .object({
    enabled: z.boolean(),
    /** Set by the budget-alert kill switch when it turns the assistant off (design §9.4). */
    disabledBy: z
      .string()
      .regex(/^budget_alert:\d{1,3}%:\d{4}-\d{2}$/)
      .optional(),
    model: z.string().regex(/^[a-z0-9.-]{1,64}$/),
    promptVersion: z.string().regex(/^[A-Za-z0-9._-]{1,64}$/),
    /** Must equal the loaded price table's version, so a price change is a deliberate act. */
    priceTableVersion: z.string().regex(/^[A-Za-z0-9._-]{1,64}$/),
    caps: z
      .object({
        /** All assistant Gemini spend in a UTC month, every label included (the $5 slice). */
        monthUsd: usd,
        labelMonthUsd: z.record(label, usd).default({}),
        labelDayUsd: z.record(label, usd).default({}),
        questionsPerUserDay: z.record(z.enum(ROLES), z.number().int().min(0).max(10_000)),
      })
      .strict(),
    limits: z
      .object({
        /**
         * At most 200k: Gemini Pro bills prompts above 200k tokens at a higher tier, and the
         * price table models only the base tier, so the cap keeps every call inside it.
         */
        maxInputTokens: tokenCount.max(MAX_INPUT_TOKENS),
        maxOutputTokens: tokenCount,
        thinkingBudget: z.number().int().min(0).max(100_000),
        maxModelCallsPerQuestion: z.number().int().min(1).max(10),
      })
      .strict(),
  })
  .strict();

export type AssistantConfig = z.infer<typeof AssistantConfigSchema>;

export interface Caps {
  readonly month: MicroUsd;
  readonly labelMonth: ReadonlyMap<string, MicroUsd>;
  readonly labelDay: ReadonlyMap<string, MicroUsd>;
}

export function capsOf(config: AssistantConfig): Caps {
  const toMap = (record: Record<string, string>): Map<string, MicroUsd> =>
    new Map(Object.entries(record).map(([key, value]) => [key, parseUsd(value)]));
  return {
    month: parseUsd(config.caps.monthUsd),
    labelMonth: toMap(config.caps.labelMonthUsd),
    labelDay: toMap(config.caps.labelDayUsd),
  };
}

export function limitsOf(config: AssistantConfig): CallLimits {
  const { maxInputTokens, maxOutputTokens, thinkingBudget } = config.limits;
  return { maxInputTokens, maxOutputTokens, thinkingBudget };
}
