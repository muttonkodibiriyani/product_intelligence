'use client';

import { useLocale, useTranslations } from 'next-intl';
import { sampleAnswer } from '@/lib/assistant/sample';
import { useSummaryData } from '../widgets/use-summary';
import { AnswerView } from './answer-view';

/**
 * A labelled sample of the answer layout, built by the page from a live /api/v1/summary response
 * (no model call). Shows nothing while loading, on error, or when the response has no counts.
 */
export function SampleAnswer() {
  const t = useTranslations('assistant.sample');
  const badge = useTranslations('assistant.samples');
  const locale = useLocale() === 'ar' ? 'ar' : 'en';
  const s = useSummaryData();
  const answer = s.kind === 'ready' ? sampleAnswer(s.env, (key, values) => t(key, values), locale) : null;
  if (!answer) return null;
  return (
    <section aria-labelledby="assistant-sample" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="assistant-sample" className="text-sm font-medium">
          {t('title')}
        </h2>
        <span className="pill bg-lav text-lav-ink">{badge('badge')}</span>
      </div>
      <p className="text-xs text-ink-2">{t('hint')}</p>
      <div className="ms-auto w-fit max-w-[85%] rounded-card bg-surface-2 px-3 py-2 text-sm">
        {t('question')}
      </div>
      <div className="panel p-4">
        <AnswerView answer={answer} id="sample" />
      </div>
    </section>
  );
}
