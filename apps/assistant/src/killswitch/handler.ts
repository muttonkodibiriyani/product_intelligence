/**
 * The budget-alert subscriber (design §9.4), framework-free so it is tested without the
 * Functions runtime. The deploy PR wraps it in a 2nd-gen `onMessagePublished` trigger with
 * retries on; a thrown error means "retry", and the policy's `maxAgeMs` ends the retries.
 */
import { type KillSwitchPolicy, type PubSubMessage, decide } from "./budget.js";
import type { ConfigSwitch } from "./switch.js";

export interface KillSwitchDeps {
  readonly policy: KillSwitchPolicy;
  readonly configSwitch: ConfigSwitch;
  readonly now?: (() => Date) | undefined;
  /** One structured line per message; never the message body, password or token. */
  readonly log: (entry: Readonly<Record<string, unknown>>) => void;
}

export async function handleBudgetMessage(
  message: PubSubMessage,
  deps: KillSwitchDeps,
): Promise<"disabled" | "ignored"> {
  const decision = decide(message, deps.policy, (deps.now ?? (() => new Date()))());
  if (decision.action === "ignore") {
    // Acknowledged either way: retrying an unusable budget amount cannot help.
    deps.log({
      severity: decision.reason === "invalid_budget" ? "ERROR" : "INFO",
      event: "kill_switch_ignored",
      reason: decision.reason,
      pct: decision.pct ?? null,
    });
    return "ignored";
  }
  if (decision.trigger === "currency_mismatch") {
    // Billing reports in a currency the policy was not set for: switch off and get attention.
    deps.log({ severity: "ERROR", event: "kill_switch_currency_mismatch", pct: decision.pct });
  }
  try {
    await deps.configSwitch.disable(decision.disabledBy);
  } catch (error) {
    deps.log({
      severity: "ERROR",
      event: "kill_switch_failed",
      pct: decision.pct,
      error: error instanceof Error ? error.message : "unknown",
    });
    throw error;
  }
  deps.log({
    severity: "WARNING",
    event: "kill_switch_disabled",
    trigger: decision.trigger,
    pct: decision.pct,
    disabledBy: decision.disabledBy,
  });
  return "disabled";
}
