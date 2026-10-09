'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useMemo } from 'react';
import type { CaveatView } from '@/lib/api/types';
import { formatDate } from '@/lib/format';
import {
  freshnessOf,
  sourceFreshness,
  type CardField,
  type CellState,
  type FilterGap,
  type SourceFreshness,
} from '@/lib/source-freshness';
import { useMeta } from '../use-meta';

/** One tint per state; every state also has its own words, so colour is never the only cue. */
const TINT: Record<CellState, string> = {
  fresh: 'bg-mint text-mint-ink',
  stale: 'bg-butter text-butter-ink',
  unavailable: 'bg-rose text-rose-ink',
  not_observed: 'bg-surface-2 text-ink-2',
  conflict: 'bg-lav text-lav-ink',
  invalid: 'bg-rose text-rose-ink',
  no_offer: 'bg-surface-2 text-ink-2',
  no_price: 'bg-surface-2 text-ink-2',
};

/**
 * Every retailer's own source state from /meta (one cached request), with any caveats the page's
 * own response carried. Retailers are matched by exact id; nothing is borrowed across shops.
 */
const NONE: readonly CaveatView[] = [];

export function useSourceFreshness(caveats: readonly CaveatView[] = NONE): SourceFreshness[] | null {
  const meta = useMeta().data;
  return useMemo(
    () => (meta?.data ? sourceFreshness(meta.data, [...meta.caveats, ...caveats]) : null),
    [meta, caveats],
  );
}

/** The one-line explanation of a source state, in the user's language. */
export function useFreshnessDetail(): (s: SourceFreshness) => string {
  const t = useTranslations('freshness');
  const th = useTranslations('home');
  const locale = useLocale();
  return (s) => {
    const date = (d: string | null) => (d ? formatDate(d, locale) : t('dateNone'));
    const base =
      s.state === 'fresh'
        ? t('detail.fresh', { date: date(s.lastDate) })
        : s.state === 'stale'
          ? s.lastDate
            ? t('detail.stale', { date: date(s.lastDate), view: date(s.viewDate) })
            : t('detail.staleUndated')
          : s.state === 'unavailable'
            ? t('detail.unavailable', {
                status:
                  s.status && th.has(`status.${s.status}`) ? th(`status.${s.status}`) : (s.status ?? ''),
              })
            : t(`detail.${s.state}`);
    return s.importedOn ? `${base} ${t('imported', { date: date(s.importedOn) })}` : base;
  };
}

/** A state as a small labelled pill; `detail` adds the explanation for screen readers and hover. */
export function StateBadge({ state, detail }: { state: CellState; detail?: string }) {
  const t = useTranslations('freshness');
  return (
    <span data-evidence-state={state} title={detail} className={`pill max-w-full ${TINT[state]}`}>
      <span className="truncate">{t(`state.${state}`)}</span>
      {detail && <span className="sr-only">{`: ${detail}`}</span>}
    </span>
  );
}

/** One retailer's source state with its explanation. */
export function SourceBadge({ source }: { source: SourceFreshness }) {
  const detail = useFreshnessDetail();
  return <StateBadge state={source.state} detail={detail(source)} />;
}

/**
 * Every listed retailer's source state in one wrapping row, so a page never shows one shop's older
 * data beside another's as if both were current. `only` keeps the retailers a page shows.
 */
export function FreshnessStrip({
  sources,
  name,
  only,
}: {
  sources: readonly SourceFreshness[] | null;
  name: (id: string) => string;
  only?: readonly string[];
}) {
  const t = useTranslations('freshness');
  const detail = useFreshnessDetail();
  if (!sources) return null;
  const shown = only ? only.map((id) => freshnessOf(sources, id)) : sources;
  if (!shown.length) return null;
  return (
    <section aria-label={t('title')} className="text-xs">
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {shown.map((s) => (
          <li key={s.retailer} className="inline-flex min-w-0 max-w-full flex-wrap items-center gap-1.5">
            <span className="font-medium text-ink">{name(s.retailer)}</span>
            <StateBadge state={s.state} />
            <span className="text-ink-2">{detail(s)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** "Missing: brand, size" for a row's absent fields; the row itself always stays in the list. */
export function MissingFields({
  fields,
  className = '',
}: {
  fields: readonly CardField[];
  className?: string;
}) {
  const t = useTranslations('freshness');
  if (!fields.length) return null;
  return (
    <span data-missing-fields={fields.join(' ')} className={`block text-[11px] text-ink-3 ${className}`}>
      {t('missing', { fields: fields.map((f) => t(`field.${f}`)).join(t('listSep')) })}
    </span>
  );
}

/** Says which missing-data products the active server filters cannot match, instead of hiding them. */
export function FilterGapNote({ gaps }: { gaps: readonly FilterGap[] }) {
  const t = useTranslations('freshness');
  if (!gaps.length) return null;
  return (
    <p role="note" data-filter-gaps={gaps.join(' ')} className="max-w-prose text-xs text-ink-2">
      {t('filterGap', { fields: gaps.map((g) => t(`gap.${g}`)).join(t('listSep')) })}
    </p>
  );
}
