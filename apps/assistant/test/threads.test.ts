/**
 * Thread history is read from the caller's own stored thread (review S1 on #63), against a
 * minimal fake of the Admin SDK query surface the adapter uses.
 */
import type { Firestore } from "firebase-admin/firestore";
import { describe, expect, it } from "vitest";

import {
  ChatRequestSchema,
  FirestoreThreadStore,
  MemoryThreadStore,
  NO_THREADS,
} from "../src/flows/threads.js";

type Data = Record<string, unknown>;

/** Records the path and query, and returns the given documents newest first. */
function fakeDb(docs: Data[]) {
  const seen: { path: string[]; orderBy?: [string, string]; limit?: number } = { path: [] };
  const query = {
    orderBy(field: string, direction: string) {
      seen.orderBy = [field, direction];
      return query;
    },
    limit(count: number) {
      seen.limit = count;
      return query;
    },
    get: () => Promise.resolve({ docs: docs.map((data) => ({ data: () => data })) }),
  };
  const node = (): unknown => ({
    collection(name: string) {
      seen.path.push(name);
      return { doc: (id: string) => (seen.path.push(id), node()), ...query };
    },
  });
  return { db: node() as Firestore, seen };
}

describe("FirestoreThreadStore", () => {
  it("reads the caller's thread, oldest first, and skips malformed messages", async () => {
    const { db, seen } = fakeDb([
      { role: "assistant", text: "second", createdAt: 2, citations: [] },
      { role: "tool", text: "forged" },
      { role: "user", text: 3 },
      { role: "user", text: "first", createdAt: 1 },
    ]);
    const turns = await new FirestoreThreadStore(db).history("u1", "t1", 10);
    expect(turns).toEqual([
      { role: "user", text: "first" },
      { role: "model", text: "second" },
    ]);
    expect(seen).toEqual({
      path: ["users", "u1", "assistant_threads", "t1", "assistant_messages"],
      orderBy: ["createdAt", "desc"],
      limit: 10,
    });
  });

  it("returns nothing for an invalid thread id without querying", async () => {
    const { db, seen } = fakeDb([{ role: "user", text: "x" }]);
    expect(await new FirestoreThreadStore(db).history("u1", "a/b", 10)).toEqual([]);
    expect(seen.path).toEqual([]);
  });
});

describe("thread helpers", () => {
  it("keeps memory threads per user and trims to the limit", async () => {
    const store = new MemoryThreadStore();
    store.append("u1", "t", { role: "user", text: "a" });
    store.append("u1", "t", { role: "model", text: "b" });
    expect(await store.history("u1", "t", 1)).toEqual([{ role: "model", text: "b" }]);
    expect(await store.history("u2", "t", 10)).toEqual([]);
    expect(await NO_THREADS.history("u1", "t", 10)).toEqual([]);
  });

  it("accepts only question, locale and thread id", () => {
    expect(ChatRequestSchema.safeParse({ question: " hi ", locale: "en" }).data).toEqual({
      question: "hi",
      locale: "en",
    });
    for (const bad of [
      { question: "hi", locale: "en", turns: [] },
      { question: "hi", locale: "fr" },
      { question: "   ", locale: "en" },
      { question: "hi", locale: "en", threadId: "x".repeat(65) },
    ]) {
      expect(ChatRequestSchema.safeParse(bad).success).toBe(false);
    }
  });
});
