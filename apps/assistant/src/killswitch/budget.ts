/**
 * Cloud Billing budget notifications (Pub/Sub, schema 1.0) and the kill-switch decision
 * (design §9.4). The switch is a backstop: budget data lags spend by hours, so the meter's caps
 * are the bound and this only catches spend the meter cannot see.
 *
 * The decision is pure. A message turns the assistant off only when it is fresh, comes from the
 * configured budget, is in USD, and its month-to-date cost has reached the threshold share of the
 * budget. Anything malformed or unexpected is ignored and logged, never acted on: the topic only
 * accepts the billing service's publisher, and a false "off" is cheap but still an outage.
 */
import { z } from "zod";

/** A publish time further ahead of our clock than this is not trusted. */
const CLOCK_SKEW_MS = 5 * 60_000;

const money = z.number().finite().min(0).max(1_000_000);

/** The message body Cloud Billing publishes (only the fields used here). */
export const BudgetNotificationSchema = z.object({
  budgetDisplayName: z.string().max(200),
  costAmount: money,
  budgetAmount: money.positive(),
  costIntervalStart: z.string().regex(/^\d{4}-\d{2}-\d{2}T/),
  currencyCode: z.string().regex(/^[A-Z]{3}$/),
});

export type BudgetNotification = z.infer<typeof BudgetNotificationSchema>;

const AttributesSchema = z.object({
  budgetId: z.string().min(1).max(200),
  schemaVersion: z.literal("1.0"),
});

/** A Pub/Sub message as the trigger hands it over: base64 data, attributes, publish time. */
export interface PubSubMessage {
  readonly data?: string;
  readonly attributes?: Readonly<Record<string, string>>;
  readonly publishTime?: string;
}

export interface KillSwitchPolicy {
  /** The budget whose alerts may switch the assistant off (deploy config, not a literal). */
  readonly budgetId: string;
  /** Whole percent of the budget at which to switch off: 90 for the 90 % project threshold. */
  readonly thresholdPct: number;
  /** Messages older than this are ignored (Pub/Sub retries end; last month's late alerts too). */
  readonly maxAgeMs: number;
}

export type Decision =
  | { readonly action: "disable"; readonly disabledBy: string; readonly pct: number }
  | { readonly action: "ignore"; readonly reason: IgnoreReason; readonly pct?: number };

export type IgnoreReason = "malformed" | "other_budget" | "currency" | "stale" | "below_threshold";

/** Integer cents, so the threshold comparison has no floating-point edge. */
function cents(amount: number): number {
  return Math.round(amount * 100);
}

export function decide(message: PubSubMessage, policy: KillSwitchPolicy, now: Date): Decision {
  const attributes = AttributesSchema.safeParse(message.attributes ?? {});
  if (!attributes.success) return { action: "ignore", reason: "malformed" };
  if (attributes.data.budgetId !== policy.budgetId) {
    return { action: "ignore", reason: "other_budget" };
  }

  const published = Date.parse(message.publishTime ?? "");
  if (Number.isNaN(published) || published - now.getTime() > CLOCK_SKEW_MS) {
    return { action: "ignore", reason: "malformed" };
  }
  if (now.getTime() - published > policy.maxAgeMs) return { action: "ignore", reason: "stale" };

  let body: unknown;
  try {
    body = JSON.parse(Buffer.from(message.data ?? "", "base64").toString("utf8"));
  } catch {
    return { action: "ignore", reason: "malformed" };
  }
  const parsed = BudgetNotificationSchema.safeParse(body);
  if (!parsed.success) return { action: "ignore", reason: "malformed" };
  const notification = parsed.data;
  if (notification.currencyCode !== "USD") return { action: "ignore", reason: "currency" };

  const cost = cents(notification.costAmount);
  const budget = cents(notification.budgetAmount);
  const pct = Math.min(999, Math.floor((cost * 100) / budget));
  if (cost * 100 < budget * policy.thresholdPct) {
    return { action: "ignore", reason: "below_threshold", pct };
  }
  const month = notification.costIntervalStart.slice(0, 7);
  return { action: "disable", disabledBy: `budget_alert:${String(pct)}%:${month}`, pct };
}
