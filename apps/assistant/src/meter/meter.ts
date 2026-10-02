/**
 * Fail-closed spend meter (design §9): reserve → call → settle.
 *
 * - Before every model call, one store transaction checks that `spent + reserved + ceiling` stays
 *   within each applicable cap and adds the call's worst-case `ceiling` to `reserved`.
 * - After the call, the reservation is settled: `reserved -= ceiling`, `spent += actual`.
 * - If the call throws, the reservation is settled at the ceiling: a failed call may still have
 *   been billed.
 * - A reservation that is never settled (a crash) stays in `reserved`, i.e. counted at its
 *   ceiling.
 * - Any store failure, missing or invalid config, disabled kill switch, unknown model or price
 *   table mismatch refuses the call. Nothing reaches the model unmetered.
 *
 * Counters are keyed by scope. Money caps apply to the total-month and label keys. The user-day
 * key carries the question count (capped per role) and the spend for the cost panel.
 */
import type { Role } from "../tools/types.js";
import { type AssistantConfig, AssistantConfigSchema, capsOf, limitsOf } from "./config.js";
import { type MicroUsd, type Prices, type TokenUsage } from "./prices.js";

export interface Counter {
  readonly spent: MicroUsd;
  readonly reserved: MicroUsd;
  readonly questions: number;
}

export const EMPTY_COUNTER: Counter = { spent: 0n, reserved: 0n, questions: 0 };

export interface ReservationRecord {
  readonly id: string;
  readonly keys: readonly string[];
  readonly ceiling: MicroUsd;
  readonly label: string;
  readonly uid: string;
  readonly model: string;
  readonly priceTableVersion: string;
  readonly createdAt: string;
  readonly settled: boolean;
  readonly actual?: MicroUsd;
  readonly failed?: boolean;
}

/** One store transaction. Reads come before writes; the store retries on contention. */
export interface CounterTx {
  getCounters(keys: readonly string[]): Promise<Map<string, Counter>>;
  putCounter(key: string, counter: Counter): void;
  getReservation(id: string): Promise<ReservationRecord | null>;
  putReservation(record: ReservationRecord): void;
}

export interface UsageStore {
  transaction<T>(fn: (tx: CounterTx) => Promise<T>): Promise<T>;
  /** The raw `assistant_config/current` document, or null if it does not exist. */
  readConfig(): Promise<unknown>;
}

export type RefusalCode =
  | "disabled"
  | "config_invalid"
  | "price_table_mismatch"
  | "unknown_model"
  | "store_unavailable"
  | "question_cap"
  | "call_cap"
  | "month_cap"
  | "label_month_cap"
  | "label_day_cap"
  | "eval_above_live";

export class MeterRefusal extends Error {
  constructor(readonly code: RefusalCode) {
    super(`assistant meter refused: ${code}`);
    this.name = "MeterRefusal";
  }
}

export const counterKeys = {
  month: (month: string) => `total/${month}`,
  labelMonth: (label: string, month: string) => `label/${label}/${month}`,
  labelDay: (label: string, day: string) => `label/${label}/${day}`,
  userDay: (uid: string, day: string) => `user/${uid}/${day}`,
};

function utcDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** An open question: its config snapshot, call count and metered cost so far. */
export class Question {
  private calls = 0;
  private spentMicros = 0n;

  constructor(
    readonly config: AssistantConfig,
    readonly uid: string,
    readonly label: string,
    readonly day: string,
  ) {}

  get month(): string {
    return this.day.slice(0, 7);
  }

  /** Metered cost of this question so far (settled calls). */
  get spent(): MicroUsd {
    return this.spentMicros;
  }

  /** @internal Used by the meter. */
  claimCall(): void {
    if (this.calls >= this.config.limits.maxModelCallsPerQuestion) {
      throw new MeterRefusal("call_cap");
    }
    this.calls += 1;
  }

  /** @internal Used by the meter. */
  addSpent(micros: MicroUsd): void {
    this.spentMicros += micros;
  }
}

export interface MeteredCall<T> {
  readonly usage: TokenUsage;
  readonly value: T;
}

/**
 * Where the meter's config comes from. It is re-read before every call and throws a
 * `MeterRefusal` on anything it does not accept. The live function only ever uses
 * `liveConfig`; the eval provider passes its own source.
 */
export type ConfigSource = (store: UsageStore, prices: Prices) => Promise<AssistantConfig>;

/** `assistant_config/current`, checked fail-closed. */
export const liveConfig: ConfigSource = async (store, prices) => {
  const parsed = AssistantConfigSchema.safeParse(await store.readConfig());
  if (!parsed.success) throw new MeterRefusal("config_invalid");
  const config = parsed.data;
  if (!config.enabled) throw new MeterRefusal("disabled");
  if (config.priceTableVersion !== prices.version) {
    throw new MeterRefusal("price_table_mismatch");
  }
  if (!prices.has(config.model)) throw new MeterRefusal("unknown_model");
  return config;
};

export class Meter {
  constructor(
    private readonly store: UsageStore,
    private readonly prices: Prices,
    private readonly clock: () => Date = () => new Date(),
    private readonly newId: () => string = () => crypto.randomUUID(),
    private readonly source: ConfigSource = liveConfig,
  ) {}

  private async guard<T>(work: () => Promise<T>): Promise<T> {
    try {
      return await work();
    } catch (cause) {
      if (cause instanceof MeterRefusal) throw cause;
      throw new MeterRefusal("store_unavailable");
    }
  }

  /** Load and check the config. Every refusal here is fail-closed. */
  async config(): Promise<AssistantConfig> {
    return this.guard(() => this.source(this.store, this.prices));
  }

  /** Open a question: kill switch, config and the per-user daily question cap. */
  async startQuestion(caller: { uid: string; role: Role }, label: string): Promise<Question> {
    const config = await this.config();
    const day = utcDay(this.clock());
    const key = counterKeys.userDay(caller.uid, day);
    const cap = config.caps.questionsPerUserDay[caller.role] ?? 0;
    await this.guard(() =>
      this.store.transaction(async (tx) => {
        const counter = (await tx.getCounters([key])).get(key) ?? EMPTY_COUNTER;
        if (counter.questions >= cap) throw new MeterRefusal("question_cap");
        tx.putCounter(key, { ...counter, questions: counter.questions + 1 });
      }),
    );
    return new Question(config, caller.uid, label, day);
  }

  /** Reserve the ceiling, make the call, settle. `call` receives the limits it must respect. */
  async call<T>(
    question: Question,
    call: (limits: ReturnType<typeof limitsOf>, model: string) => Promise<MeteredCall<T>>,
  ): Promise<T> {
    // The kill switch is re-read before every call, so turning it off stops a question that
    // is already running at its next model call. Limits and caps stay the question's snapshot.
    await this.config();
    question.claimCall();
    const { config, label, uid, day, month } = question;
    const limits = limitsOf(config);
    const ceiling = this.prices.ceiling(config.model, limits);
    const caps = capsOf(config);

    const capped: [string, MicroUsd, RefusalCode][] = [
      [counterKeys.month(month), caps.month, "month_cap"],
    ];
    const labelMonthCap = caps.labelMonth.get(label);
    if (labelMonthCap !== undefined) {
      capped.push([counterKeys.labelMonth(label, month), labelMonthCap, "label_month_cap"]);
    }
    const labelDayCap = caps.labelDay.get(label);
    if (labelDayCap !== undefined) {
      capped.push([counterKeys.labelDay(label, day), labelDayCap, "label_day_cap"]);
    }
    // Uncapped keys are still counted, so the cost panel sees every label and user.
    const keys = [
      ...new Set([
        ...capped.map(([key]) => key),
        counterKeys.labelMonth(label, month),
        counterKeys.userDay(uid, day),
      ]),
    ];

    const record: ReservationRecord = {
      id: this.newId(),
      keys,
      ceiling,
      label,
      uid,
      model: config.model,
      priceTableVersion: this.prices.version,
      createdAt: this.clock().toISOString(),
      settled: false,
    };
    await this.guard(() =>
      this.store.transaction(async (tx) => {
        const counters = await tx.getCounters(keys);
        for (const [key, cap, code] of capped) {
          const counter = counters.get(key) ?? EMPTY_COUNTER;
          if (counter.spent + counter.reserved + ceiling > cap) throw new MeterRefusal(code);
        }
        for (const key of keys) {
          const counter = counters.get(key) ?? EMPTY_COUNTER;
          tx.putCounter(key, { ...counter, reserved: counter.reserved + ceiling });
        }
        tx.putReservation(record);
      }),
    );

    let result: MeteredCall<T>;
    try {
      result = await call(limits, config.model);
    } catch (cause) {
      await this.settle(record, ceiling, true);
      question.addSpent(ceiling);
      throw cause;
    }
    let actual: MicroUsd;
    try {
      actual = this.prices.cost(config.model, result.usage);
    } catch {
      actual = ceiling; // Unreadable usage: count the worst case.
    }
    // Usage above the limits (it should not happen) is still counted in full.
    await this.settle(record, actual, false);
    question.addSpent(actual);
    return result.value;
  }

  private async settle(
    record: ReservationRecord,
    actual: MicroUsd,
    failed: boolean,
  ): Promise<void> {
    // If settling fails the reservation stays counted at its ceiling (fail closed); the
    // answer is not lost because of bookkeeping.
    try {
      await this.store.transaction(async (tx) => {
        const current = await tx.getReservation(record.id);
        if (!current || current.settled) return;
        const counters = await tx.getCounters(current.keys);
        for (const key of current.keys) {
          const counter = counters.get(key) ?? EMPTY_COUNTER;
          const reserved = counter.reserved - current.ceiling;
          tx.putCounter(key, {
            ...counter,
            reserved: reserved < 0n ? 0n : reserved,
            spent: counter.spent + actual,
          });
        }
        tx.putReservation({ ...current, settled: true, actual, ...(failed ? { failed } : {}) });
      });
    } catch {
      // Deliberately swallowed: see above.
    }
  }
}
