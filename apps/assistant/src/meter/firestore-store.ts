/**
 * Firestore `UsageStore` (design §6, §9). Written only by the function's service account through
 * the Admin SDK; clients never write these collections.
 *
 * - `assistant_usage_counters/{key}`: `{spentMicros, reservedMicros, questions, updatedAt}`.
 *   The key is the counter scope, with each segment URI-encoded and joined by "|".
 * - `assistant_reservations/{id}`: the reservation record, with `expireAt` (90-day TTL).
 * - `assistant_config/current`: the kill switch, model, caps and limits (admin-written).
 *
 * Micro-USD amounts are stored as Firestore integers (int64). Reads outside the safe-integer
 * range fail the transaction, and the meter then refuses the call.
 */
import type { DocumentData, Firestore, Transaction } from "firebase-admin/firestore";

import type { Counter, CounterTx, ReservationRecord, UsageStore } from "./meter.js";

export const COLLECTIONS = {
  counters: "assistant_usage_counters",
  reservations: "assistant_reservations",
  config: "assistant_config",
} as const;

export const RESERVATION_TTL_DAYS = 90;

export function counterDocId(key: string): string {
  return key.split("/").map(encodeURIComponent).join("|");
}

function micros(value: unknown): bigint {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error("invalid stored micro-USD amount");
  }
  return BigInt(value);
}

function stored(value: bigint): number {
  if (value < 0n || value > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error("micro-USD amount out of range");
  }
  return Number(value);
}

function counterFrom(data: DocumentData): Counter {
  const questions = data.questions as unknown;
  if (typeof questions !== "number" || !Number.isSafeInteger(questions) || questions < 0) {
    throw new Error("invalid stored question count");
  }
  return {
    spent: micros(data.spentMicros),
    reserved: micros(data.reservedMicros),
    questions,
  };
}

function reservationFrom(data: DocumentData): ReservationRecord {
  const keys = data.keys as unknown;
  if (!Array.isArray(keys) || !keys.every((key) => typeof key === "string")) {
    throw new Error("invalid stored reservation");
  }
  return {
    id: String(data.id),
    keys,
    ceiling: micros(data.ceilingMicros),
    label: String(data.label),
    uid: String(data.uid),
    model: String(data.model),
    priceTableVersion: String(data.priceTableVersion),
    createdAt: String(data.createdAt),
    settled: data.settled === true,
    ...(data.actualMicros === undefined ? {} : { actual: micros(data.actualMicros) }),
    ...(data.failed === true ? { failed: true } : {}),
  };
}

export class FirestoreUsageStore implements UsageStore {
  constructor(private readonly db: Firestore) {}

  async readConfig(): Promise<unknown> {
    const snapshot = await this.db.collection(COLLECTIONS.config).doc("current").get();
    return snapshot.exists ? (snapshot.data() ?? null) : null;
  }

  transaction<T>(fn: (tx: CounterTx) => Promise<T>): Promise<T> {
    const counters = this.db.collection(COLLECTIONS.counters);
    const reservations = this.db.collection(COLLECTIONS.reservations);
    return this.db.runTransaction(async (transaction: Transaction) => {
      const tx: CounterTx = {
        async getCounters(keys) {
          if (keys.length === 0) return new Map();
          const refs = keys.map((key) => counters.doc(counterDocId(key)));
          const snapshots = await transaction.getAll(...refs);
          const found = new Map<string, Counter>();
          snapshots.forEach((snapshot, index) => {
            const key = keys[index];
            const data = snapshot.data();
            if (key !== undefined && data !== undefined) found.set(key, counterFrom(data));
          });
          return found;
        },
        putCounter(key, counter) {
          transaction.set(counters.doc(counterDocId(key)), {
            spentMicros: stored(counter.spent),
            reservedMicros: stored(counter.reserved),
            questions: counter.questions,
            updatedAt: new Date(),
          });
        },
        async getReservation(id) {
          const snapshot = await transaction.get(reservations.doc(id));
          const data = snapshot.data();
          return data === undefined ? null : reservationFrom(data);
        },
        putReservation(record) {
          const expireAt = new Date(record.createdAt);
          expireAt.setUTCDate(expireAt.getUTCDate() + RESERVATION_TTL_DAYS);
          transaction.set(reservations.doc(record.id), {
            id: record.id,
            keys: [...record.keys],
            ceilingMicros: stored(record.ceiling),
            label: record.label,
            uid: record.uid,
            model: record.model,
            priceTableVersion: record.priceTableVersion,
            createdAt: record.createdAt,
            settled: record.settled,
            ...(record.actual === undefined ? {} : { actualMicros: stored(record.actual) }),
            ...(record.failed === true ? { failed: true } : {}),
            expireAt,
          });
        },
      };
      return fn(tx);
    });
  }
}
