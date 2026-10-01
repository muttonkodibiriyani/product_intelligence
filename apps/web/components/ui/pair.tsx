'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { Known } from './known';
import { Money, Pct } from './money';

/**
 * One pair's gap as the API computed it: other minus base, signed, with who is cheaper in words.
 * An uncounted pair says why instead of showing a number.
 */
export function GapView({ pair, name }: { pair: Schemas['PairGap']; name: (id: string) => string }) {
  const t = useTranslations('gap');
  const locale = useLocale();
  const g = pair.gap;
  if (g)
    return (
      <span className="flex flex-col gap-0.5">
        <span className="flex flex-wrap gap-x-2">
          <Money m={g.amount} locale={locale} signed />
          <span className="text-ink-2">
            <Pct v={g.pct} />
          </span>
        </span>
        <span className="text-xs text-ink-2">
          {g.cheaper === 'equal'
            ? t('equal')
            : t(g.cheaper === 'other' ? 'otherCheaper' : 'otherDearer', { other: name(pair.other) })}
        </span>
      </span>
    );
  if (pair.excludedReason)
    return (
      <span className="flex flex-col gap-0.5">
        <span className="text-ink-2">{t('notCounted')}</span>
        <span className="text-xs text-ink-2">
          <Known t={t} k="excluded" v={pair.excludedReason} />
        </span>
      </span>
    );
  return <span className="text-ink-2">–</span>;
}

/** "Exact · approved": the match type and where it is in review. */
export function MatchLabel({ m }: { m: Schemas['CardMatch'] }) {
  const t = useTranslations('match');
  return (
    <span className="whitespace-nowrap">
      <Known t={t} k="class" v={m.matchClass} />
      <span className="text-ink-2">
        {' · '}
        <Known t={t} k="review" v={m.reviewState} />
      </span>
    </span>
  );
}
