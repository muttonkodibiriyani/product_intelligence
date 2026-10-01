import { describe, expect, it } from "vitest";

import { type KillSwitchPolicy, type PubSubMessage, decide } from "../src/killswitch/budget.js";
import { handleBudgetMessage } from "../src/killswitch/handler.js";
import { KillSwitchError, RulesScopedSwitch } from "../src/killswitch/switch.js";
import { AssistantConfigSchema } from "../src/meter/config.js";
import { CONFIG } from "./meter-fixtures.js";

const NOW = new Date("2026-10-20T12:00:00Z");
const POLICY: KillSwitchPolicy = {
  budgetId: "budget-1",
  currency: "USD",
  thresholdPct: 90,
  maxAgeMs: 6 * 3600_000,
};

function message(
  body: Record<string, unknown> = {},
  overrides: { [K in keyof PubSubMessage]?: PubSubMessage[K] | undefined } = {},
): PubSubMessage {
  const data = {
    budgetDisplayName: "pi-monthly-25usd",
    alertThresholdExceeded: 0.9,
    costAmount: 22.5,
    costIntervalStart: "2026-10-01T07:00:00Z",
    budgetAmount: 25,
    budgetAmountType: "SPECIFIED_AMOUNT",
    currencyCode: "USD",
    ...body,
  };
  return {
    data: Buffer.from(JSON.stringify(data)).toString("base64"),
    attributes: { budgetId: "budget-1", schemaVersion: "1.0", billingAccountId: "x" },
    publishTime: "2026-10-20T11:00:00Z",
    ...overrides,
  } as PubSubMessage;
}

describe("decide", () => {
  it("switches off at exactly the threshold, with the month and percent", () => {
    expect(decide(message(), POLICY, NOW)).toEqual({
      action: "disable",
      trigger: "threshold",
      disabledBy: "budget_alert:90%:2026-10",
      pct: 90,
    });
  });

  it("compares in cents, so a cent below the threshold is ignored", () => {
    expect(decide(message({ costAmount: 22.49 }), POLICY, NOW)).toEqual({
      action: "ignore",
      reason: "below_threshold",
      pct: 89,
    });
  });

  it.each([900_000, 10_000_000, 1e300])(
    "fails closed on runaway cost %d: switches off, percent capped at 999 for the rules pattern",
    (costAmount) => {
      expect(decide(message({ costAmount }), POLICY, NOW)).toMatchObject({
        action: "disable",
        trigger: "threshold",
        disabledBy: "budget_alert:999%:2026-10",
      });
    },
  );

  it("works in the configured currency, whatever it is", () => {
    const aed = { ...POLICY, currency: "AED" };
    const body = { currencyCode: "AED", budgetAmount: 92, costAmount: 184 };
    expect(decide(message(body), aed, NOW)).toMatchObject({ action: "disable", pct: 200 });
    expect(decide(message({ ...body, costAmount: 9 }), aed, NOW)).toMatchObject({
      action: "ignore",
      reason: "below_threshold",
    });
  });

  it.each([
    ["AED at 200 %", { currencyCode: "AED", costAmount: 50 }, 200],
    ["EUR below the threshold", { currencyCode: "EUR", costAmount: 5 }, 20],
  ])("fails closed on a currency the policy was not set for (%s)", (_name, body, pct) => {
    expect(decide(message(body), POLICY, NOW)).toEqual({
      action: "disable",
      trigger: "currency_mismatch",
      disabledBy: `budget_alert:${String(pct)}%:2026-10`,
      pct,
    });
  });

  it.each([
    ["other_budget", message({}, { attributes: { budgetId: "other", schemaVersion: "1.0" } })],
    ["malformed", message({}, { attributes: { budgetId: "budget-1", schemaVersion: "2.0" } })],
    ["malformed", message({}, { attributes: undefined })],
    ["malformed", message({}, { publishTime: undefined })],
    ["stale", message({}, { publishTime: "2026-10-20T05:59:59Z" })],
    ["malformed", message({}, { publishTime: "2026-10-20T12:05:01Z" })],
    ["malformed", message({}, { data: Buffer.from("not json").toString("base64") })],
    ["malformed", message({}, { data: undefined })],
    ["malformed", message({ costAmount: "22.50" })],
    ["malformed", message({ costAmount: -1 })],
    ["invalid_budget", message({ budgetAmount: 0 })],
    ["invalid_budget", message({ budgetAmount: 0.004 })],
    ["invalid_budget", message({ budgetAmount: -25 })],
    ["invalid_budget", message({ budgetAmount: 1e307 })],
  ])("ignores %s messages", (reason, input) => {
    expect(decide(input, POLICY, NOW)).toMatchObject({ action: "ignore", reason });
  });
});

describe("handleBudgetMessage", () => {
  function deps(fail = false) {
    const disabled: string[] = [];
    const logs: Record<string, unknown>[] = [];
    return {
      disabled,
      logs,
      deps: {
        policy: POLICY,
        now: () => NOW,
        log: (entry: Readonly<Record<string, unknown>>) => logs.push({ ...entry }),
        configSwitch: {
          disable: (by: string) => {
            if (fail) return Promise.reject(new KillSwitchError("write", 403));
            disabled.push(by);
            return Promise.resolve();
          },
        },
      },
    };
  }

  it("disables once over the threshold and logs without the body", async () => {
    const { disabled, logs, deps: d } = deps();
    await expect(handleBudgetMessage(message({ costAmount: 23 }), d)).resolves.toBe("disabled");
    expect(disabled).toEqual(["budget_alert:92%:2026-10"]);
    expect(logs).toEqual([
      {
        severity: "WARNING",
        event: "kill_switch_disabled",
        trigger: "threshold",
        pct: 92,
        disabledBy: "budget_alert:92%:2026-10",
      },
    ]);
    expect(JSON.stringify(logs)).not.toContain("pi-monthly");
  });

  it("ignores below the threshold without touching the config", async () => {
    const { disabled, logs, deps: d } = deps();
    await expect(handleBudgetMessage(message({ costAmount: 5 }), d)).resolves.toBe("ignored");
    expect(disabled).toEqual([]);
    expect(logs).toEqual([
      { severity: "INFO", event: "kill_switch_ignored", reason: "below_threshold", pct: 20 },
    ]);
  });

  it("acks an unusable budget amount without retrying, logged at ERROR", async () => {
    const { disabled, logs, deps: d } = deps();
    await expect(handleBudgetMessage(message({ budgetAmount: 0.004 }), d)).resolves.toBe("ignored");
    expect(disabled).toEqual([]);
    expect(logs).toEqual([
      { severity: "ERROR", event: "kill_switch_ignored", reason: "invalid_budget", pct: null },
    ]);
  });

  it("switches off on a currency mismatch and logs it at ERROR", async () => {
    const { disabled, logs, deps: d } = deps();
    await expect(
      handleBudgetMessage(message({ currencyCode: "AED", costAmount: 5 }), d),
    ).resolves.toBe("disabled");
    expect(disabled).toEqual(["budget_alert:20%:2026-10"]);
    expect(logs[0]).toEqual({ severity: "ERROR", event: "kill_switch_currency_mismatch", pct: 20 });
    expect(logs[1]).toMatchObject({ event: "kill_switch_disabled", trigger: "currency_mismatch" });
  });

  it("rethrows a failed write so Pub/Sub retries", async () => {
    const { logs, deps: d } = deps(true);
    await expect(handleBudgetMessage(message(), d)).rejects.toThrow("write failed (HTTP 403)");
    expect(logs[0]).toMatchObject({ severity: "ERROR", event: "kill_switch_failed", pct: 90 });
  });

  it("uses the real clock by default", async () => {
    const { deps: d } = deps();
    const old = message({}, { publishTime: "2020-01-01T00:00:00Z" });
    await expect(handleBudgetMessage(old, { ...d, now: undefined })).resolves.toBe("ignored");
  });
});

describe("RulesScopedSwitch", () => {
  const TARGET = { projectId: "demo-pi", apiKey: "web-key" };
  const ACCOUNT = { email: "ks@example.test", password: "pw" };

  function fakeFetch(responses: Response[]) {
    const calls: { url: string; init: RequestInit }[] = [];
    const doFetch = (url: string, init?: RequestInit): Promise<Response> => {
      calls.push({ url, init: init ?? {} });
      const next = responses.shift();
      return next ? Promise.resolve(next) : Promise.reject(new Error(`network ${url}`));
    };
    return { calls, doFetch: doFetch as unknown as typeof fetch };
  }

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  it("signs in, then patches only enabled and disabledBy on an existing document", async () => {
    const { calls, doFetch } = fakeFetch([json({ idToken: "id-1" }), json({})]);
    await new RulesScopedSwitch(TARGET, ACCOUNT, doFetch).disable("budget_alert:91%:2026-10");

    expect(calls).toHaveLength(2);
    const [signIn, write] = calls;
    expect(signIn?.url).toBe(
      "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=web-key",
    );
    expect(JSON.parse(signIn?.init.body as string)).toEqual({
      email: "ks@example.test",
      password: "pw",
      returnSecureToken: true,
    });

    const url = new URL(write?.url ?? "");
    expect(url.pathname).toBe(
      "/v1/projects/demo-pi/databases/(default)/documents/assistant_config/current",
    );
    expect(url.searchParams.getAll("updateMask.fieldPaths")).toEqual(["enabled", "disabledBy"]);
    expect(url.searchParams.get("currentDocument.exists")).toBe("true");
    expect(write?.init.method).toBe("PATCH");
    expect(write?.init.redirect).toBe("error");
    expect((write?.init.headers as Record<string, string>).Authorization).toBe("Bearer id-1");
    expect(JSON.parse(write?.init.body as string)).toEqual({
      fields: {
        enabled: { booleanValue: false },
        disabledBy: { stringValue: "budget_alert:91%:2026-10" },
      },
    });
  });

  it.each([
    ["sign-in refused", [json({ error: { message: "INVALID_PASSWORD" } }, 400)], "sign_in", 400],
    ["no id token", [json({})], "sign_in", 200],
    ["not json", [new Response("<html>", { status: 200 })], "sign_in", 200],
    ["write denied by rules", [json({ idToken: "t" }), json({}, 403)], "write", 403],
    ["sign-in network error", [], "sign_in", null],
    ["write network error", [json({ idToken: "t" })], "write", null],
  ])("%s → KillSwitchError", async (_name, responses, step, status) => {
    const { doFetch } = fakeFetch(responses);
    const error = await new RulesScopedSwitch(TARGET, ACCOUNT, doFetch)
      .disable("budget_alert:91%:2026-10")
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(KillSwitchError);
    expect(error).toMatchObject({ step, status });
    expect((error as Error).message).not.toContain("web-key");
  });
});

describe("config", () => {
  it("accepts the kill switch's disabledBy and nothing free-form", () => {
    const off = { ...CONFIG, enabled: false, disabledBy: "budget_alert:92%:2026-10" };
    expect(AssistantConfigSchema.safeParse(off).success).toBe(true);
    expect(AssistantConfigSchema.safeParse({ ...off, disabledBy: "someone" }).success).toBe(false);
  });
});
