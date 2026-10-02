import { describe, expect, it } from "vitest";

import { MemoryUsageStore } from "../src/meter/memory-store.js";
import {
  type CounterTx,
  Meter,
  MeterRefusal,
  type RefusalCode,
  type UsageStore,
  counterKeys,
} from "../src/meter/meter.js";
import type { TokenUsage } from "../src/meter/prices.js";
import { CEILING, CONFIG, prices } from "./meter-fixtures.js";

const NOW = new Date("2026-09-30T12:00:00Z");
const VIEWER = { uid: "user1", role: "viewer" as const };
const USAGE: TokenUsage = { input: 10_000, cachedInput: 0, output: 1_000, thinking: 0 }; // 5500

function setup(config: unknown = CONFIG) {
  const store = new MemoryUsageStore(config);
  let id = 0;
  const meter = new Meter(
    store,
    prices(),
    () => NOW,
    () => `r${String((id += 1))}`,
  );
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

describe("kill switch and config", () => {
  it.each([
    ["missing config", null, "config_invalid"],
    ["invalid config", { enabled: true }, "config_invalid"],
    ["unknown key", { ...CONFIG, extra: 1 }, "config_invalid"],
    ["float cap", { ...CONFIG, caps: { ...CONFIG.caps, monthUsd: 5 } }, "config_invalid"],
    ["disabled", { ...CONFIG, enabled: false }, "disabled"],
    ["price table mismatch", { ...CONFIG, priceTableVersion: "old" }, "price_table_mismatch"],
    ["unpriced model", { ...CONFIG, model: "gemini-9" }, "unknown_model"],
  ])("refuses on %s", async (_name, config, code) => {
    const { meter } = setup(config);
    expect(await refusal(meter.startQuestion(VIEWER, "chat"))).toBe(code);
  });

  it("re-reads the kill switch before every call (review #51)", async () => {
    const { store, meter } = setup();
    const question = await meter.startQuestion(VIEWER, "chat");
    let calls = 0;
    const call = () => {
      calls += 1;
      return Promise.resolve({ usage: USAGE, value: "ok" });
    };
    await meter.call(question, call);
    store.config = { ...CONFIG, enabled: false };
    expect(await refusal(meter.call(question, call))).toBe("disabled");
    store.config = null;
    expect(await refusal(meter.call(question, call))).toBe("config_invalid");
    expect(calls).toBe(1);
  });

  it("caps maxInputTokens at the 200k base price tier (review #51)", async () => {
    const config = { ...CONFIG, limits: { ...CONFIG.limits, maxInputTokens: 200_001 } };
    const { meter } = setup(config);
    expect(await refusal(meter.startQuestion(VIEWER, "chat"))).toBe("config_invalid");
  });

  it("refuses when the store is unreachable", async () => {
    const broken: UsageStore = {
      readConfig: () => Promise.reject(new Error("down")),
      transaction: () => Promise.reject(new Error("down")),
    };
    const meter = new Meter(broken, prices(), () => NOW);
    expect(await refusal(meter.startQuestion(VIEWER, "chat"))).toBe("store_unavailable");
  });
});

describe("reserve → call → settle", () => {
  it("reserves the ceiling before the call and settles the actual cost", async () => {
    const { store, meter } = setup();
    const question = await meter.startQuestion(VIEWER, "chat");
    const month = counterKeys.month("2026-09");
    const value = await meter.call(question, (limits, model) => {
      expect(model).toBe(CONFIG.model);
      expect(limits).toEqual({
        maxInputTokens: 10_000,
        maxOutputTokens: 1_500,
        thinkingBudget: 500,
      });
      expect(store.counters.get(month)).toEqual({ spent: 0n, reserved: CEILING, questions: 0 });
      return Promise.resolve({ usage: USAGE, value: "answer" });
    });
    expect(value).toBe("answer");
    expect(question.spent).toBe(5_500n);
    for (const key of [
      month,
      counterKeys.labelDay("chat", "2026-09-30"),
      counterKeys.labelMonth("chat", "2026-09"),
    ]) {
      expect(store.counters.get(key)).toEqual({ spent: 5_500n, reserved: 0n, questions: 0 });
    }
    expect(store.counters.get(counterKeys.userDay("user1", "2026-09-30"))).toEqual({
      spent: 5_500n,
      reserved: 0n,
      questions: 1,
    });
    expect(store.reservations.get("r1")).toMatchObject({
      settled: true,
      actual: 5_500n,
      ceiling: CEILING,
      priceTableVersion: CONFIG.priceTableVersion,
    });
  });

  it("settles a failed call at the ceiling and rethrows", async () => {
    const { store, meter } = setup();
    const question = await meter.startQuestion(VIEWER, "chat");
    await expect(
      meter.call(question, () => Promise.reject(new Error("vertex 500"))),
    ).rejects.toThrow("vertex 500");
    expect(store.counters.get(counterKeys.month("2026-09"))?.spent).toBe(CEILING);
    expect(store.reservations.get("r1")).toMatchObject({ settled: true, failed: true });
    expect(question.spent).toBe(CEILING);
  });

  it("counts unreadable usage at the ceiling", async () => {
    const { store, meter } = setup();
    const question = await meter.startQuestion(VIEWER, "chat");
    await meter.call(question, () =>
      Promise.resolve({ usage: { ...USAGE, input: Number.NaN }, value: 1 }),
    );
    expect(store.counters.get(counterKeys.month("2026-09"))?.spent).toBe(CEILING);
  });

  it("keeps an unsettled reservation counted when settling fails", async () => {
    const store = new MemoryUsageStore(CONFIG);
    let transactions = 0;
    const flaky: UsageStore = {
      readConfig: () => store.readConfig(),
      transaction: <T>(fn: (tx: CounterTx) => Promise<T>) =>
        (transactions += 1) === 3 ? Promise.reject(new Error("down")) : store.transaction(fn),
    };
    const meter = new Meter(
      flaky,
      prices(),
      () => NOW,
      () => "r1",
    );
    const question = await meter.startQuestion(VIEWER, "chat");
    await meter.call(question, () => Promise.resolve({ usage: USAGE, value: 1 }));
    expect(store.counters.get(counterKeys.month("2026-09"))).toMatchObject({
      spent: 0n,
      reserved: CEILING,
    });
    expect(store.reservations.get("r1")?.settled).toBe(false);
  });
});

describe("caps", () => {
  it("refuses before the call when the monthly slice would be passed", async () => {
    const { store, meter } = setup();
    store.counters.set(counterKeys.month("2026-09"), {
      spent: 5_000_000n - CEILING + 1n,
      reserved: 0n,
      questions: 0,
    });
    const question = await meter.startQuestion(VIEWER, "chat");
    let called = false;
    expect(
      await refusal(
        meter.call(question, () => {
          called = true;
          return Promise.resolve({ usage: USAGE, value: 1 });
        }),
      ),
    ).toBe("month_cap");
    expect(called).toBe(false);
  });

  it("counts reservations in flight against the cap", async () => {
    const { store, meter } = setup();
    store.counters.set(counterKeys.labelDay("chat", "2026-09-30"), {
      spent: 0n,
      reserved: 400_000n - CEILING + 1n,
      questions: 0,
    });
    const question = await meter.startQuestion(VIEWER, "chat");
    expect(
      await refusal(meter.call(question, () => Promise.resolve({ usage: USAGE, value: 1 }))),
    ).toBe("label_day_cap");
  });

  it("enforces the CI label's monthly cap", async () => {
    const { store, meter } = setup();
    store.counters.set(counterKeys.labelMonth("ci", "2026-09"), {
      spent: 1_500_000n,
      reserved: 0n,
      questions: 0,
    });
    const question = await meter.startQuestion({ uid: "ci", role: "admin" }, "ci");
    expect(
      await refusal(meter.call(question, () => Promise.resolve({ usage: USAGE, value: 1 }))),
    ).toBe("label_month_cap");
  });

  it("allows spend exactly up to a cap", async () => {
    const { store, meter } = setup();
    store.counters.set(counterKeys.month("2026-09"), {
      spent: 5_000_000n - CEILING,
      reserved: 0n,
      questions: 0,
    });
    const question = await meter.startQuestion(VIEWER, "chat");
    await expect(
      meter.call(question, () => Promise.resolve({ usage: USAGE, value: 1 })),
    ).resolves.toBe(1);
  });

  it("caps questions per user per day by role", async () => {
    const { store, meter } = setup({
      ...CONFIG,
      caps: { ...CONFIG.caps, questionsPerUserDay: { viewer: 1, admin: 2 } },
    });
    await meter.startQuestion(VIEWER, "chat");
    expect(await refusal(meter.startQuestion(VIEWER, "chat"))).toBe("question_cap");
    await meter.startQuestion({ uid: "a", role: "admin" }, "chat");
    await meter.startQuestion({ uid: "a", role: "admin" }, "chat");
    expect(store.counters.get(counterKeys.userDay("a", "2026-09-30"))?.questions).toBe(2);
  });

  it("caps model calls per question", async () => {
    const { meter } = setup({
      ...CONFIG,
      limits: { ...CONFIG.limits, maxModelCallsPerQuestion: 1 },
    });
    const question = await meter.startQuestion(VIEWER, "chat");
    await meter.call(question, () => Promise.resolve({ usage: USAGE, value: 1 }));
    expect(
      await refusal(meter.call(question, () => Promise.resolve({ usage: USAGE, value: 1 }))),
    ).toBe("call_cap");
  });

  it("never lets concurrent calls overshoot a cap", async () => {
    const { store, meter } = setup();
    // Room for exactly three ceilings in the chat daily cap.
    store.counters.set(counterKeys.labelDay("chat", "2026-09-30"), {
      spent: 400_000n - 3n * CEILING,
      reserved: 0n,
      questions: 0,
    });
    const questions = await Promise.all(
      Array.from({ length: 6 }, (_, i) =>
        meter.startQuestion({ uid: `u${String(i)}`, role: "viewer" }, "chat"),
      ),
    );
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const results = Promise.allSettled(
      questions.map((question) =>
        meter.call(question, async () => {
          await gate;
          return { usage: USAGE, value: 1 };
        }),
      ),
    );
    await new Promise((resolve) => setTimeout(resolve, 10));
    release();
    const settled = await results;
    expect(settled.filter((result) => result.status === "fulfilled")).toHaveLength(3);
    const day = store.counters.get(counterKeys.labelDay("chat", "2026-09-30"));
    expect(day?.reserved).toBe(0n);
    expect((day?.spent ?? 0n) <= 400_000n).toBe(true);
  });
});
