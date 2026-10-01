/**
 * Chat history comes from the stored thread, never from the request (design §6; review S1 on
 * #63). A client could otherwise forge "model" turns, putting words in the assistant's mouth
 * that the next answer would build on. The callable accepts only a question, a locale and a
 * thread id (`ChatRequestSchema`, strict); the flow loads earlier turns from
 * `users/{uid}/assistant_threads/{threadId}/assistant_messages`, which only the function writes. The
 * path is under the caller's own uid, so a thread id from another user finds nothing.
 */
import type { Firestore } from "firebase-admin/firestore";
import { z } from "zod";

export const MAX_QUESTION_CHARS = 2_000;
export const MAX_HISTORY_TURNS = 10;
/** Longest stored assistant answer carried into the next prompt. */
export const MAX_HISTORY_ANSWER_CHARS = 4 * MAX_QUESTION_CHARS;

export interface HistoryTurn {
  readonly role: "user" | "model";
  readonly text: string;
}

export const THREAD_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** The whole callable request. Unknown keys (e.g. `history`, `turns`) are rejected. */
export const ChatRequestSchema = z
  .object({
    question: z.string().trim().min(1).max(MAX_QUESTION_CHARS),
    locale: z.enum(["en", "ar"]),
    threadId: z.string().regex(THREAD_ID).optional(),
  })
  .strict();
export type ChatRequest = z.infer<typeof ChatRequestSchema>;

export interface ThreadStore {
  /** The last `limit` turns of the caller's own thread, oldest first; [] when there is none. */
  history(uid: string, threadId: string, limit: number): Promise<readonly HistoryTurn[]>;
}

export const NO_THREADS: ThreadStore = { history: () => Promise.resolve([]) };

export class MemoryThreadStore implements ThreadStore {
  private readonly threads = new Map<string, HistoryTurn[]>();

  append(uid: string, threadId: string, turn: HistoryTurn): void {
    const key = `${uid}/${threadId}`;
    this.threads.set(key, [...(this.threads.get(key) ?? []), turn]);
  }

  history(uid: string, threadId: string, limit: number): Promise<readonly HistoryTurn[]> {
    return Promise.resolve((this.threads.get(`${uid}/${threadId}`) ?? []).slice(-limit));
  }
}

/** Stored message fields the history needs; anything else in the document is ignored. */
const StoredMessage = z.object({
  role: z.enum(["user", "assistant"]),
  text: z.string(),
});

export class FirestoreThreadStore implements ThreadStore {
  constructor(private readonly db: Firestore) {}

  async history(uid: string, threadId: string, limit: number): Promise<readonly HistoryTurn[]> {
    if (!THREAD_ID.test(threadId)) return [];
    const snapshot = await this.db
      .collection("users")
      .doc(uid)
      .collection("assistant_threads")
      .doc(threadId)
      .collection("assistant_messages")
      .orderBy("createdAt", "desc")
      .limit(limit)
      .get();
    // Malformed documents are skipped rather than trusted.
    return snapshot.docs
      .flatMap((doc): HistoryTurn[] => {
        const parsed = StoredMessage.safeParse(doc.data());
        if (!parsed.success) return [];
        const { role, text } = parsed.data;
        return [{ role: role === "user" ? "user" : "model", text }];
      })
      .reverse();
  }
}
