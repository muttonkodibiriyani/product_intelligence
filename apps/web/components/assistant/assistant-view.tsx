'use client';

import { useTranslations } from 'next-intl';
import { useId, useState } from 'react';
import { ASSISTANT_CONNECTED, SUGGESTED } from '@/lib/assistant';

/** The Ryzan AI Assistant page. Until the assistant is connected it never sends a question. */
export function AssistantView({ connected = ASSISTANT_CONNECTED }: { connected?: boolean }) {
  const t = useTranslations('assistant');
  const inputId = useId();
  const noteId = useId();
  const [question, setQuestion] = useState('');

  return (
    <section aria-labelledby="assistant-title" className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 id="assistant-title" className="text-xl font-semibold">
          {t('title')}
        </h1>
        <p className="mt-1 max-w-prose text-sm text-ink-2">{t('intro')}</p>
      </div>

      {!connected && (
        <div role="status" className="rounded border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">{t('connect.title')}</h2>
            <span className="rounded bg-surface-2 px-2 py-0.5 text-xs text-ink-2">{t('connect.status')}</span>
          </div>
          <p className="mt-2 max-w-prose text-sm text-ink-2">{t('connect.body')}</p>
        </div>
      )}

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-medium">{t('samples.title')}</h2>
          <span className="rounded border border-line px-2 py-0.5 text-xs text-ink-2">
            {t('samples.badge')}
          </span>
        </div>
        <p className="text-xs text-ink-2">{t('samples.hint')}</p>
        <ul className="flex flex-wrap gap-2">
          {SUGGESTED.map((key) => (
            <li key={key}>
              <button
                type="button"
                onClick={() => setQuestion(t(`q.${key}`))}
                className="rounded-full border border-line bg-surface px-3 py-1 text-sm hover:bg-surface-2 focus-visible:outline-2"
              >
                {t(`q.${key}`)}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <form
        onSubmit={(e) => e.preventDefault()}
        className="flex flex-col gap-2 rounded border border-line bg-surface p-3"
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
            placeholder={t('composer.placeholder')}
            aria-describedby={connected ? undefined : noteId}
            className="min-h-10 flex-1 resize-y rounded border border-line bg-surface px-2 py-1 text-sm focus-visible:outline-2"
          />
          <button
            type="submit"
            disabled={!connected || question.trim() === ''}
            className="rounded bg-ink px-3 py-1.5 text-sm font-medium text-surface disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2"
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
