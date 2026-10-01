'use client';

import { useTranslations } from 'next-intl';
import { type KeyboardEvent, useId, useState } from 'react';
import { PageHeader } from '@/components/ui/page-header';
import { ASSISTANT_CONNECTED, SUGGESTED } from '@/lib/assistant';
import { type Ask, assistantClient } from '@/lib/assistant/client';
import { isPending, MAX_QUESTION_CHARS, type Turn, useAssistantChat } from '@/lib/assistant/use-chat';
import { AnswerView } from './answer-view';
import { ProgressChips } from './progress-chips';
import { SampleAnswer } from './sample-answer';

function TurnView({ turn }: { turn: Turn }) {
  const t = useTranslations('assistant');
  return (
    <li className="space-y-2">
      <div className="ms-auto w-fit max-w-[85%] rounded-card bg-surface-2 px-3 py-2 text-sm">
        <span className="sr-only">{t('thread.you')}: </span>
        <bdi className="whitespace-pre-wrap">{turn.question}</bdi>
      </div>
      <div className="panel space-y-2 p-4">
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
    </li>
  );
}

/** The Ryzan AI Assistant page. Until the assistant is connected it never sends a question. */
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
    <section aria-labelledby="assistant-title" className="mx-auto max-w-3xl space-y-6">
      <PageHeader id="assistant-title" title={t('title')} intro={t('intro')} />

      {!connected && (
        <div role="status" className="panel p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">{t('connect.title')}</h2>
            <span className="pill bg-butter text-butter-ink">{t('connect.status')}</span>
          </div>
          <p className="mt-2 max-w-prose text-sm text-ink-2">{t('connect.body')}</p>
        </div>
      )}

      {chat.turns.length > 0 && (
        <ol aria-label={t('thread.label')} className="space-y-4">
          {chat.turns.map((turn) => (
            <TurnView key={turn.id} turn={turn} />
          ))}
        </ol>
      )}
      <p aria-live="polite" className="sr-only">
        {chat.pending ? t('thread.working') : chat.turns.length > 0 ? t('thread.ready') : ''}
      </p>

      {chat.turns.length === 0 && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-medium">{t('samples.title')}</h2>
            <span className="pill bg-lav text-lav-ink">{t('samples.badge')}</span>
          </div>
          <p className="text-xs text-ink-2">{t('samples.hint')}</p>
          <ul className="flex flex-wrap gap-2">
            {SUGGESTED.map((key) => (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => setQuestion(t(`q.${key}`))}
                  className="btn focus-visible:outline-2"
                >
                  {t(`q.${key}`)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {chat.turns.length === 0 && <SampleAnswer />}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="panel flex flex-col gap-2 p-3"
      >
        <label htmlFor={inputId} className="text-xs font-medium text-ink-2">
          {t('composer.label')}
        </label>
        <div className="flex items-end gap-2">
          <textarea
            id={inputId}
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={MAX_QUESTION_CHARS}
            placeholder={t('composer.placeholder')}
            aria-describedby={connected ? undefined : noteId}
            className="field min-h-10 flex-1 resize-y focus-visible:outline-2"
          />
          {chat.pending && (
            <button type="button" onClick={chat.stop} className="btn focus-visible:outline-2">
              {t('composer.stop')}
            </button>
          )}
          <button
            type="submit"
            disabled={!canSend}
            className="btn btn-primary disabled:cursor-not-allowed focus-visible:outline-2"
          >
            {t('composer.send')}
          </button>
        </div>
        {!connected && (
          <p id={noteId} className="text-xs text-ink-2">
            {t('composer.disabled')}
          </p>
        )}
      </form>

      <p className="text-xs text-ink-2">{t('promises')}</p>
    </section>
  );
}
