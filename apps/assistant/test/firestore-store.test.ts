/**
 * The Firestore adapter against a minimal in-memory fake of the Admin SDK surface it uses
 * (collection/doc refs, runTransaction with get/getAll/set). Real transaction semantics are the
 * SDK's; this checks the mapping and the fail-closed parsing.
 */
import type { Firestore } from "firebase-admin/firestore";
import { describe, expect, it } from "vitest";

import { FirestoreUsageStore, counterDocId } from "../src/meter/firestore-store.js";
import { Meter, MeterRefusal, counterKeys } from "../src/meter/meter.js";
import { CONFIG, prices } from "./meter-fixtures.js";

type Data = Record<string, unknown>;

class FakeRef {
  constructor(
    readonly db: FakeFirestore,
    readonly path: string,
  ) {}
  get(): Promise<FakeSnapshot> {
    return Promise.resolve(new FakeSnapshot(this.db.docs.get(this.path)));
  }
}

class FakeSnapshot {
  constructor(private readonly value: Data | undefined) {}
  get exists(): boolean {
    return this.value !== undefined;
  }
  data(): Data | undefined {
    return this.value === undefined ? undefined : structuredClone(this.value);
  }
}

class FakeFirestore {
  readonly docs = new Map<string, Data>();
  collection(name: string) {
    return { doc: (id: string) => new FakeRef(this, `${name}/${id}`) };
  }
  async runTransaction<T>(fn: (tx: unknown) => Promise<T>): Promise<T> {
    const writes = new Map<string, Data>();
    const tx = {
      get: (ref: FakeRef) => ref.get(),
      getAll: (...refs: FakeRef[]) => Promise.all(refs.map((ref) => ref.get())),
      set: (ref: FakeRef, data: Data) => writes.set(ref.path, data),
    };
    const result = await fn(tx);
    for (const [path, data] of writes) this.docs.set(path, data);
    return result;
  }
}

function setup() {
  const fake = new FakeFirestore();
  const store = new FirestoreUsageStore(fake as unknown as Firestore);
  const meter = new Meter(
    store,
    prices(),
    () => new Date("2026-09-30T12:00:00Z"),
    () => "r1",
  );
  return { fake, store, meter };
}

describe("FirestoreUsageStore", () => {
  it("encodes counter keys as single document ids", () => {
    expect(counterDocId("user/a b|c/2026-09-30")).toBe("user|a%20b%7Cc|2026-09-30");
  });

  it("treats a missing config document as off", async () => {
    const { meter } = setup();
    await expect(meter.startQuestion({ uid: "u", role: "viewer" }, "chat")).rejects.toThrow(
      MeterRefusal,
    );
  });

  it("meters a call end to end with integer micro-USD documents", async () => {
    const { fake, meter } = setup();
    fake.docs.set("assistant_config/current", structuredClone(CONFIG));
    const question = await meter.startQuestion({ uid: "u", role: "viewer" }, "chat");
    await meter.call(question, () =>
      Promise.resolve({
        usage: { input: 10_000, cachedInput: 0, output: 1_000, thinking: 0 },
        value: 1,
      }),
    );
    const month = fake.docs.get(
      `assistant_usage_counters/${counterDocId(counterKeys.month("2026-09"))}`,
    );
    expect(month).toMatchObject({ spentMicros: 5_500, reservedMicros: 0, questions: 0 });
    const reservation = fake.docs.get("assistant_reservations/r1");
    expect(reservation).toMatchObject({ settled: true, actualMicros: 5_500, ceilingMicros: 8_000 });
    expect((reservation?.expireAt as Date).toISOString()).toBe("2026-12-29T12:00:00.000Z");
  });

  it("fails closed on corrupt stored amounts", async () => {
    const { fake, meter } = setup();
    fake.docs.set("assistant_config/current", structuredClone(CONFIG));
    fake.docs.set(
      `assistant_usage_counters/${counterDocId(counterKeys.userDay("u", "2026-09-30"))}`,
      { spentMicros: 1.5, reservedMicros: 0, questions: 0 },
    );
    await expect(meter.startQuestion({ uid: "u", role: "viewer" }, "chat")).rejects.toMatchObject({
      code: "store_unavailable",
    });
  });
});
