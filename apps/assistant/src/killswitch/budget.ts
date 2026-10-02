/**
 * Cloud Billing budget notifications (Pub/Sub, schema 1.0) and the kill-switch decision
 * (design §9.4). The switch is a backstop: budget data lags spend by hours, so the meter's caps
 * are the bound and this only catches spend the meter cannot see.
 *
 * The decision is pure. A fresh, well-formed message from the configured budget turns the
 * assistant off when its month-to-date cost has reached the threshold share of the budget, however
 * large the cost. It fails closed on surprises about money: a currency other than the configured
 * one also turns it off (the threshold can no longer be trusted). Messages that are malformed,
 * stale or from another budget are ignored: the topic only accepts the billing service's
 * publisher, and a false "off" is cheap but still an outage. A budget amount below one cent is
 * ignored without retry (no percentage exists) and logged at ERROR.
 */
import { z } from "zod";

/** A publish time further ahead of our clock than this is not trusted. */
const CLOCK_SKEW_MS = 5 * 60_000;

/** The message body Cloud Billing publishes (only the fields used here). */
export const BudgetNotificationSchema = z.object({
  budgetDisplayName: z.string().max(200),
  // No upper bound: a runaway cost must switch off, not look malformed.
  costAmount: z.number().finite().min(0),
  // Checked in decide(): below one cent there is no percentage to compute.
  budgetAmount: z.number().finite(),
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
  /**
   * ISO 4217 code of the billing account; budget amounts are always in it. Deploy config, set
   * from what the owner verifies at enablement (design §9.4), never assumed.
   */
  readonly currency: string;
  /** Whole percent of the budget at which to switch off: 90 for the 90 % project threshold. */
  readonly thresholdPct: number;
  /** Messages older than this are ignored (Pub/Sub retries end; last month's late alerts too). */
  readonly maxAgeMs: number;
}

export type Decision =
  | {
      readonly action: "disable";
      readonly trigger: DisableTrigger;
      readonly disabledBy: string;
      readonly pct: number;
    }
  | { readonly action: "ignore"; readonly reason: IgnoreReason; readonly pct?: number };

/** Why it switched off: the threshold, or a currency it cannot compare (fail closed). */
export type DisableTrigger = "threshold" | "currency_mismatch";

export type IgnoreReason =
  "malformed" | "other_budget" | "stale" | "invalid_budget" | "below_threshold";

/** The disabledBy pattern in infra/firestore.rules allows at most three digits. */
const MAX_PCT = 999;

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

  const cost = cents(notification.costAmount);
  const budget = cents(notification.budgetAmount);
  if (!Number.isFinite(budget) || budget < 1) return { action: "ignore", reason: "invalid_budget" };
  // cost may overflow to Infinity for an absurd amount; that still switches off, at 999 %.
  const pct = Math.min(MAX_PCT, Math.floor((cost * 100) / budget));
  const month = notification.costIntervalStart.slice(0, 7);
  const disable = (trigger: DisableTrigger): Decision => ({
    action: "disable",
    trigger,
    disabledBy: `budget_alert:${String(pct)}%:${month}`,
    pct,
  });

  if (notification.currencyCode !== policy.currency) return disable("currency_mismatch");
  if (cost * 100 < budget * policy.thresholdPct) {
    return { action: "ignore", reason: "below_threshold", pct };
  }
  return disable("threshold");
}
