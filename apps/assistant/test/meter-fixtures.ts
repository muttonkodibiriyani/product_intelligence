import { readFileSync } from "node:fs";

import type { AssistantConfig } from "../src/meter/config.js";
import { type PriceTable, Prices } from "../src/meter/prices.js";

export const PRICE_TABLE = JSON.parse(
  readFileSync(new URL("../config/prices.json", import.meta.url), "utf8"),
) as PriceTable;

export const prices = (): Prices => new Prices(PRICE_TABLE);

/** Ceiling with these limits on flash: 10k×0.30 + (1.5k+0.5k)×2.50 = 3000 + 5000 micro-USD. */
export const CONFIG: AssistantConfig = {
  enabled: true,
  model: "gemini-2.5-flash",
  promptVersion: "chat-1",
  priceTableVersion: PRICE_TABLE.version,
  caps: {
    monthUsd: "5.00",
    labelMonthUsd: { ci: "1.50" },
    labelDayUsd: { chat: "0.40" },
    questionsPerUserDay: { viewer: 40, admin: 150 },
  },
  limits: {
    maxInputTokens: 10_000,
    maxOutputTokens: 1_500,
    thinkingBudget: 500,
    maxModelCallsPerQuestion: 4,
  },
};

export const CEILING = 8_000n;
