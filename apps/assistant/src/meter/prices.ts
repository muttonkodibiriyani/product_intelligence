/**
 * Model price table and cost arithmetic (design §9). All money is integer micro-USD (`bigint`);
 * prices are committed as decimal strings (USD per 1 M tokens) and never pass through floats.
 */
import { readFileSync } from "node:fs";

import { z } from "zod";

/** Integer micro-USD. */
export type MicroUsd = bigint;

export const MICROS_PER_USD = 1_000_000n;
const TOKENS_PER_PRICE_UNIT = 1_000_000n;

const USD_TEXT = /^(\d{1,6})(?:\.(\d{1,6}))?$/;

/** Parse a non-negative USD decimal string (≤ 6 dp) into micro-USD. */
export function parseUsd(text: string): MicroUsd {
  const match = USD_TEXT.exec(text);
  if (!match) throw new Error(`invalid USD amount ${JSON.stringify(text)}`);
  const [, whole = "0", fraction = ""] = match;
  return BigInt(whole) * MICROS_PER_USD + BigInt(fraction.padEnd(6, "0"));
}

/** Format micro-USD as a USD decimal string with 6 dp. */
export function formatUsd(micros: MicroUsd): string {
  const sign = micros < 0n ? "-" : "";
  const abs = micros < 0n ? -micros : micros;
  const fraction = (abs % MICROS_PER_USD).toString().padStart(6, "0");
  return `${sign}${(abs / MICROS_PER_USD).toString()}.${fraction}`;
}

const usdText = z.string().regex(USD_TEXT, "USD decimal text, ≤ 6 dp");

const ModelPricesSchema = z
  .object({
    /** USD per 1 M uncached input tokens. */
    input: usdText,
    /** USD per 1 M output tokens, thinking included. */
    output: usdText,
    /** USD per 1 M cached input tokens. */
    cachedInput: usdText,
  })
  .strict();

export const PriceTableSchema = z
  .object({
    version: z.string().regex(/^[A-Za-z0-9._-]{1,64}$/),
    currency: z.literal("USD"),
    source: z.string().max(500),
    models: z.record(z.string().regex(/^[a-z0-9.-]{1,64}$/), ModelPricesSchema),
  })
  .strict();

export type PriceTable = z.infer<typeof PriceTableSchema>;

interface ModelPricesMicros {
  readonly input: MicroUsd;
  readonly output: MicroUsd;
  readonly cachedInput: MicroUsd;
}

export class UnknownModelError extends Error {
  constructor(model: string) {
    super(`no price for model ${JSON.stringify(model)}`);
    this.name = "UnknownModelError";
  }
}

/** Token counts as reported by Gemini `usageMetadata`. `cachedInput` is part of `input`. */
export interface TokenUsage {
  readonly input: number;
  readonly cachedInput: number;
  readonly output: number;
  readonly thinking: number;
}

/** Upper bounds for one model call; the ceiling is costed from these. */
export interface CallLimits {
  readonly maxInputTokens: number;
  readonly maxOutputTokens: number;
  readonly thinkingBudget: number;
}

function tokens(value: number, what: string): bigint {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`invalid ${what} token count`);
  return BigInt(value);
}

/** ⌈tokens × price ÷ 1 M⌉ in micro-USD, so metered cost never rounds below actual. */
function charge(count: bigint, pricePerMillion: MicroUsd): MicroUsd {
  return (count * pricePerMillion + TOKENS_PER_PRICE_UNIT - 1n) / TOKENS_PER_PRICE_UNIT;
}

export class Prices {
  readonly version: string;
  private readonly models: ReadonlyMap<string, ModelPricesMicros>;

  constructor(table: PriceTable) {
    const parsed = PriceTableSchema.parse(table);
    this.version = parsed.version;
    this.models = new Map(
      Object.entries(parsed.models).map(([model, prices]) => [
        model,
        {
          input: parseUsd(prices.input),
          output: parseUsd(prices.output),
          cachedInput: parseUsd(prices.cachedInput),
        },
      ]),
    );
  }

  has(model: string): boolean {
    return this.models.has(model);
  }

  private get(model: string): ModelPricesMicros {
    const prices = this.models.get(model);
    if (!prices) throw new UnknownModelError(model);
    return prices;
  }

  /** Actual cost of one call. */
  cost(model: string, usage: TokenUsage): MicroUsd {
    const prices = this.get(model);
    const input = tokens(usage.input, "input");
    const cached = tokens(usage.cachedInput, "cached input");
    if (cached > input) throw new Error("cached input exceeds input");
    return (
      charge(input - cached, prices.input) +
      charge(cached, prices.cachedInput) +
      charge(tokens(usage.output, "output") + tokens(usage.thinking, "thinking"), prices.output)
    );
  }

  /** Worst-case cost of one call within `limits` (all input uncached). */
  ceiling(model: string, limits: CallLimits): MicroUsd {
    const prices = this.get(model);
    return (
      charge(tokens(limits.maxInputTokens, "max input"), prices.input) +
      charge(
        tokens(limits.maxOutputTokens, "max output") +
          tokens(limits.thinkingBudget, "thinking budget"),
        prices.output,
      )
    );
  }
}

/** The committed table, `config/prices.json` (the same relative path from `src/` and `lib/`). */
export function loadPrices(): Prices {
  const url = new URL("../../config/prices.json", import.meta.url);
  return new Prices(JSON.parse(readFileSync(url, "utf8")) as PriceTable);
}
