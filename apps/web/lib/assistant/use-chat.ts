'use client';

import { useLocale } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';
import { type Ask, assistantClient, type ChatError, chatErrorKey } from './client';
import type { ChatAnswer, ChatProgress } from './types';

/** apps/assistant `MAX_QUESTION_CHARS`. */
export const MAX_QUESTION_CHARS = 2_000;

export interface Turn {
  readonly id: string;
  readonly question: string;
  readonly progress: readonly ChatProgress[];
  readonly answer?: ChatAnswer;
  readonly error?: ChatError;
  /** Stopped by the user before an answer arrived: no answer and no error note. */
  readonly stopped?: boolean;
}

export const isPending = (turn: Turn): boolean => !turn.answer && !turn.error && !turn.stopped;

/** A thread id the callable accepts (`^[A-Za-z0-9_-]{1,64}$`). */
const newId = (): string => crypto.randomUUID();

/**
 * One chat thread on this page. One question at a time; progress chips stream in while it runs,
 * and only the server's final (verified or labelled) answer is kept. Leaving the page stops it.
 */
export function useAssistantChat(client: () => Promise<Ask> = assistantClient) {
  const locale = useLocale() === 'ar' ? 'ar' : 'en';
  const [turns, setTurns] = useState<readonly Turn[]>([]);
  const threadId = useRef<string>(null);
  const running = useRef<AbortController>(null);

  useEffect(() => () => running.current?.abort(), []);

  const update = (id: string, change: (turn: Turn) => Turn) =>
    setTurns((all) => all.map((t) => (t.id === id ? change(t) : t)));

  const send = useCallback(
    async (text: string): Promise<boolean> => {
      const question = text.trim();
      if (!question || question.length > MAX_QUESTION_CHARS || running.current) return false;
      const controller = new AbortController();
      running.current = controller;
      const id = newId();
      threadId.current ??= newId();
      setTurns((all) => [...all, { id, question, progress: [] }]);
      try {
        const ask = await client();
        const answer = await ask(
          { question, locale, threadId: threadId.current },
          {
            signal: controller.signal,
            onProgress: (p) => update(id, (t) => ({ ...t, progress: [...t.progress, p] })),
          },
        );
        if (!controller.signal.aborted) update(id, (t) => ({ ...t, answer }));
      } catch (e) {
        update(id, (t) =>
          controller.signal.aborted ? { ...t, stopped: true } : { ...t, error: chatErrorKey(e) },
        );
      } finally {
        if (running.current === controller) running.current = null;
      }
      return true;
    },
    [client, locale],
  );

  const stop = useCallback(() => {
    const controller = running.current;
    if (!controller) return;
    controller.abort();
    running.current = null;
    setTurns((all) => all.map((t) => (isPending(t) ? { ...t, stopped: true } : t)));
  }, []);

  const pending = turns.some(isPending);
  return { turns, send, stop, pending };
}
