/**
 * In-memory `UsageStore` for tests and local evals. Transactions are serialised and applied
 * atomically: writes are buffered and committed only if the callback resolves.
 */
import type { Counter, CounterTx, ReservationRecord, UsageStore } from "./meter.js";

export class MemoryUsageStore implements UsageStore {
  readonly counters = new Map<string, Counter>();
  readonly reservations = new Map<string, ReservationRecord>();
  private queue: Promise<unknown> = Promise.resolve();

  constructor(public config: unknown = null) {}

  readConfig(): Promise<unknown> {
    return Promise.resolve(structuredClone(this.config));
  }

  transaction<T>(fn: (tx: CounterTx) => Promise<T>): Promise<T> {
    const run = async (): Promise<T> => {
      const counterWrites = new Map<string, Counter>();
      const reservationWrites = new Map<string, ReservationRecord>();
      const tx: CounterTx = {
        getCounters: (keys) =>
          Promise.resolve(
            new Map(
              keys.flatMap((key) => {
                const counter = this.counters.get(key);
                return counter ? [[key, counter] as const] : [];
              }),
            ),
          ),
        putCounter: (key, counter) => counterWrites.set(key, counter),
        getReservation: (id) => Promise.resolve(this.reservations.get(id) ?? null),
        putReservation: (record) => reservationWrites.set(record.id, record),
      };
      const result = await fn(tx);
      for (const [key, counter] of counterWrites) this.counters.set(key, counter);
      for (const [id, record] of reservationWrites) this.reservations.set(id, record);
      return result;
    };
    const next = this.queue.then(run, run);
    this.queue = next.catch(() => undefined);
    return next;
  }
}
