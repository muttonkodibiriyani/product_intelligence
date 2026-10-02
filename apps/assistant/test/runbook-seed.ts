import { readFileSync } from "node:fs";

/**
 * The `assistant_config/current` seed from the enablement runbook (section 4 table), parsed so
 * tests run against the defaults the owner actually deploys, not a test override.
 */
const RUNBOOK = readFileSync(
  new URL("../../../docs/runbooks/assistant-enablement.md", import.meta.url),
  "utf8",
);

function seed(field: string): string {
  const row = new RegExp(`^\\| \`${field.replace(/\./g, "\\.")}\` \\| \\w+ \\| \`([^\`]+)\``, "m");
  const value = row.exec(RUNBOOK)?.[1];
  if (value === undefined) throw new Error(`runbook seed has no ${field}`);
  return value;
}

const count = (field: string): number => Number(seed(field));

export const RUNBOOK_LIMITS = {
  maxInputTokens: count("limits.maxInputTokens"),
  maxOutputTokens: count("limits.maxOutputTokens"),
  thinkingBudget: count("limits.thinkingBudget"),
  maxModelCallsPerQuestion: count("limits.maxModelCallsPerQuestion"),
};

export const RUNBOOK_CAPS = {
  monthUsd: seed("caps.monthUsd"),
  labelMonthUsd: { ci: seed("caps.labelMonthUsd.ci") },
  labelDayUsd: { chat: seed("caps.labelDayUsd.chat") },
  questionsPerUserDay: {
    viewer: count("caps.questionsPerUserDay.viewer"),
    admin: count("caps.questionsPerUserDay.admin"),
  },
};

export const RUNBOOK_MODEL = seed("model");
