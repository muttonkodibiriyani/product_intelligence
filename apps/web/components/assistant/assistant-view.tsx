'use client';

import { useTranslations } from 'next-intl';
import { type KeyboardEvent, useId, useState } from 'react';
import { PageHeader } from '@/components/ui/page-header';
import { ASSISTANT_CONNECTED } from '@/lib/assistant';
import { STARTERS } from './starters';
import { type Ask, assistantClient } from '@/lib/assistant/client';
import { isPending, MAX_QUESTION_CHARS, type Turn, useAssistantChat } from '@/lib/assistant/use-chat';
import { AnswerView } from './answer-view';
import { ProgressChips } from './progress-chips';

/** The assistant's mark beside an answer: the nav's outlined star on an ink tile. */
function Mark() {
  return (
    <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-[8px] bg-ink">
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="#fff"
        strokeWidth={1.8}
        strokeLinejoin="round"
      >
        <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" />
      </svg>
    </span>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  const t = useTranslations('assistant');
  return (
    <li className="space-y-4">
      <div className="ms-auto w-fit max-w-[80%] rounded-[16px] rounded-ee-[4px] bg-ink px-3.5 py-2.5 text-sm text-white">
        <span className="sr-only">{t('thread.you')}: </span>
        <bdi className="whitespace-pre-wrap">{turn.question}</bdi>
      </div>
      <div className="grid grid-cols-[28px_1fr] gap-3">
        <Mark />
        <div className="min-w-0 space-y-2 pt-0.5">
          <span className="sr-only">{t('thread.assistant')}: </span>
          <ProgressChips steps={turn.progress} done={!isPending(turn)} />
          {isPending(turn) && turn.progress.length === 0 && (
            <p className="text-xs text-ink-2">{t('thread.working')}</p>
          )}
          {turn.answer && <AnswerView answer={turn.answer} id={turn.id} />}
          {turn.error && (
            <p role="alert" className="rounded-ctl bg-rose px-4 py-3 text-sm">
              {t(`error.${turn.error}`)}
            </p>
          )}
          {turn.stopped && <p className="text-xs text-ink-2">{t('thread.stopped')}</p>}
        </div>
      </div>
    </li>
  );
}

/**
 * The Ryzan AI page: a greeting and three starters until the first question, the thread, and a
 * composer that stays at the bottom. Until the assistant is connected the composer is off and
 * says so in one line; it never sends a question.
 */
export function AssistantView({
  connected = ASSISTANT_CONNECTED,
  client = assistantClient,
}: {
  connected?: boolean;
  client?: () => Promise<Ask>;
}) {
  const t = useTranslations('assistant');
  const inputId = useId();
  const noteId = useId();
  const [question, setQuestion] = useState('');
  const chat = useAssistantChat(client);
  const canSend = connected && !chat.pending && question.trim() !== '';
  const opening = chat.turns.length === 0;

  const submit = async () => {
    if (!canSend) return;
    const text = question;
    setQuestion('');
    if (!(await chat.send(text))) setQuestion(text);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <section
      aria-labelledby="assistant-title"
      className="mx-auto flex min-h-[calc(100vh-10rem)] max-w-[820px] flex-col"
    >
      <PageHeader id="assistant-title" title={t('title')} intro={t('intro')} />

      <div className="flex-1">
        {opening ? (
          <div className="py-10 sm:py-14">
            <h2 className="text-[22px] leading-tight font-semibold tracking-tight">{t('hello.title')}</h2>
            <p className="mt-1.5 max-w-prose text-sm text-ink-2">{t('hello.body')}</p>
          </div>
        ) : (
          <ol aria-label={t('thread.label')} className="space-y-6 py-2">
            {chat.turns.map((turn) => (
              <TurnView key={turn.id} turn={turn} />
            ))}
          </ol>
        )}
        <p aria-live="polite" className="sr-only">
          {chat.pending ? t('thread.working') : opening ? '' : t('thread.ready')}
        </p>
      </div>

      <div className="sticky bottom-[3.75rem] z-10 bg-page pt-3 pb-3 lg:bottom-0 lg:pb-4">
        {opening && (
          <ul aria-label={t('starters')} className="mb-2.5 flex flex-wrap gap-1.5">
            {STARTERS.map((key) => (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => setQuestion(t(`q.${key}`))}
                  className="pill cursor-pointer border border-line bg-surface py-1 font-normal whitespace-normal text-start text-ink-2 hover:border-ink-3 hover:text-ink focus-visible:outline-2"
                >
                  {t(`q.${key}`)}
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          className="panel p-2.5"
        >
          <label htmlFor={inputId} className="sr-only">
            {t('composer.label')}
          </label>
          <textarea
            id={inputId}
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={MAX_QUESTION_CHARS}
            placeholder={t('composer.placeholder')}
            aria-describedby={connected ? undefined : noteId}
            className="field min-h-10 w-full resize-y border-0 bg-transparent px-1 shadow-none focus-visible:outline-2"
          />
          <div className="mt-1.5 flex items-center gap-2">
            {!connected && (
              <span id={noteId} className="text-xs text-warn">
                {t('composer.disabled')}
              </span>
            )}
            <span className="flex-1" />
            {chat.pending && (
              <button type="button" onClick={chat.stop} className="btn focus-visible:outline-2">
                {t('composer.stop')}
              </button>
            )}
            <button
              type="submit"
              disabled={!canSend}
              aria-label={t('composer.send')}
              className="btn btn-primary size-[34px] shrink-0 p-0 disabled:cursor-not-allowed focus-visible:outline-2"
            >
              <svg
                aria-hidden
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
