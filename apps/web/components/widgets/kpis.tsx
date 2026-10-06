'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Summary } from '@/lib/api/summary';
import { num } from '@/lib/api/summary';
import type { Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import type { CaveatView } from '@/lib/api/types';
import { pct } from './model';

/** One retailer's /summary, fetched with an explicit `?retailer=`, and the caveats scoped to it. */
export interface RetailerSummary {
  retailer: string;
  name: string;
  data: Summary;
  caveats: readonly CaveatView[];
}

/**
 * The head-to-head numbers for one pair, on the matched set only: how many comparable pairs, the
 * median gap on them, and who is cheaper how often. Every tile names the pair count, so none reads
 * as a full-catalogue comparison. A null summary is too few pairs, never zero.
 */
export function PairKpis({
  data,
  pair,
  locale,
  href,
}: {
  data: Schemas['Comparison'];
  pair: { base: string; other: string; name: (id: string) => string };
  locale: string;
  href: string;
}) {
  const t = useTranslations('widgets.kpi');
  const tr = useTranslations('reasons');
  const s = data.summary;
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const reason = data.sides.base.reason ?? data.sides.other.reason;
  const none = <None>{reason && tr.has(reason) ? tr(reason) : t('none')}</None>;
  const gap = s ? num(s.medianGapPct) : NaN;
  return (
    <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
      <PairTile k={t('pairs')} href={href} tone="bg-lav" sub={t('pairsOf', { base, other })}>
        <Row>{s ? formatCount(s.n, locale) : none}</Row>
      </PairTile>
      <PairTile
        k={t('index')}
        href={href}
        tone="bg-sky"
        sub={s ? t('indexOf', { other, base, n: formatCount(s.n, locale) }) : undefined}
      >
        <Row>
          {s && Number.isFinite(gap) ? (
            // The sign stays in front of the number in Arabic too.
            <span
              dir="ltr"
              className={`inline-block ${gap > 0 ? 'text-blush-ink' : gap < 0 ? 'text-sky-ink' : ''}`}
            >
              {gap > 0 ? '+' : ''}
              {pct(s.medianGapPct, locale)}
            </span>
          ) : (
            none
          )}
        </Row>
      </PairTile>
      <PairTile
        k={t('cheaper')}
        href={href}
        tone="bg-mint"
        sub={s ? t('same', { n: formatCount(s.equalCount, locale) }) : undefined}
      >
        {s ? (
          <>
            <Row name={base}>{wins(s.cheaperCounts[pair.base], locale)}</Row>
            <Row name={other}>{wins(s.cheaperCounts[pair.other], locale)}</Row>
          </>
        ) : (
          <Row>{none}</Row>
        )}
      </PairTile>
    </dl>
  );
}

/** A retailer's wins; a count the API did not send is unknown, shown as a dash, never 0. */
const wins = (n: number | undefined, locale: string) =>
  typeof n === 'number' ? formatCount(n, locale) : <None>–</None>;

function PairTile({
  k,
  href,
  tone,
  sub,
  children,
}: {
  k: string;
  href: string;
  tone: string;
  sub?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="panel relative min-w-0 overflow-hidden px-4 pt-4 pb-3.5">
      <span aria-hidden className={`absolute inset-x-0 top-0 h-1 ${tone}`} />
      <dt className="text-[13px] font-semibold text-ink-2">
        <Link href={href} className="after:absolute after:inset-0 hover:underline focus-visible:outline-2">
          {k}
        </Link>
      </dt>
      <div className="mt-1.5 space-y-1.5">{children}</div>
      {sub && <dd className="mt-1 text-xs text-ink-2">{sub}</dd>}
    </div>
  );
}

/** One retailer's value in a tile; the name only when the tile holds more than one. */
function Row({ name, sub, children }: { name?: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <dd className="min-w-0">
      {name && <span className="block truncate text-xs font-medium text-ink-2">{name}</span>}
      <span className="block text-2xl leading-tight font-bold tracking-tight tabular-nums">{children}</span>
      {sub && <span className="mt-0.5 block text-xs text-ink-2">{sub}</span>}
    </dd>
  );
}

const None = ({ children }: { children: ReactNode }) => (
  <span className="text-base font-medium text-ink-2">{children}</span>
);
