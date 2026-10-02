'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Bucket, CategoryCompare } from '@/lib/api/category-compare';
import type { Envelope, Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { formatMoney, isValidPrice } from '@/lib/money';
import { Known } from '../ui/known';
import { Pct } from '../ui/money';
import { Skeleton } from '../ui/skeleton';
import { exploreHref, type PairState } from '../widgets/model';
import { RetailerDot } from './pair-picker';

type Comparison = Schemas['Comparison'];
type Name = (id: string) => string;

const GOOD = { color: 'var(--color-good, #187a43)', background: 'var(--color-good-soft, #e3f4ea)' };

/**
 * The honest empty state: no product is matched for this pair yet (or the API gave a reason the
 * pair cannot be compared at all), what each side has so far, and where the numbers that do
 * exist are: the category medians, which need no product matching, and the full product list.
 */
export function CompareEmpty({
  env,
  data,
  pair,
  name,
  category,
}: {
  env: Envelope<Comparison>;
  data: Comparison | null;
  pair: { base: string; other: string };
  name: Name;
  /** /category-compare for the same pair; the panel is left out while it is not ready. */
  category: PairState<CategoryCompare>;
}) {
  const t = useTranslations('compare.empty');
  const th = useTranslations('home');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const base = name(pair.base);
  const other = name(pair.other);
  const matched = env.data?.summary?.n ?? data?.sides.base.counted ?? 0;
  const sides = data ? ([data.sides.base, data.sides.other] as const) : null;
  // The API has no count of candidate pairs yet; the listed rows waiting for a reviewer stand in,
  // but only when every row is listed, so the number is never a floor shown as a total.
  const awaiting =
    data && !data.truncated ? data.rows.filter((r) => r.excludedReason === 'match_unreviewed').length : null;
  const detail = env.detail ? (locale === 'ar' ? env.detail.ar : env.detail.en) : null;

  return (
    <div className="space-y-5">
      <section
        aria-labelledby="empty-title"
        className="panel mx-auto max-w-2xl px-6 py-8 text-center sm:px-8"
      >
        <span
          aria-hidden
          className="mx-auto mb-4 grid size-14 place-items-center rounded-card bg-surface-2 text-ink-2"
        >
          <svg
            width="26"
            height="26"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          >
            <rect x="3" y="5" width="7" height="14" rx="2" />
            <rect x="14" y="5" width="7" height="14" rx="2" />
            <path d="M10 12h4" strokeDasharray="1.5 2" />
          </svg>
        </span>
        <h2 id="empty-title" className="text-lg font-semibold tracking-tight text-balance">
          {matched > 0
            ? t('tooFew', { n: formatCount(matched, locale), count: matched, base, other })
            : t('title', { base, other })}
        </h2>
        <p className="mt-2 text-sm text-ink-2">
          {env.reason ? (
            <>
              {t('reason')} <Known t={tr} v={env.reason} />
              {detail && ` ${detail}`}
            </>
          ) : (
            t('body')
          )}
        </p>
        {sides && (
          <ul className="mt-5 grid gap-2.5 text-start text-sm sm:grid-cols-2">
            {sides.map((s, i) => (
              <Tile key={s.retailer} mark={<RetailerDot id={s.retailer} side={i as 0 | 1} />}>
                <b className="font-semibold">{name(s.retailer)}</b>
                <span className="block text-xs text-ink-2">
                  {t('seen', { n: formatCount(s.observed, locale), count: s.observed })}
                  {s.status !== 'supported' && (
                    <>
                      {' · '}
                      <Known t={th} k="status" v={s.status} />
                    </>
                  )}
                  {s.reason && (
                    <>
                      {' '}
                      <Known t={tr} v={s.reason} />
                    </>
                  )}
                </span>
              </Tile>
            ))}
            {awaiting !== null && (
              <Tile>
                <b className="font-semibold">{t('awaiting')}</b>
                <span className="block text-xs text-ink-2 tabular-nums">
                  {formatCount(awaiting, locale)} · {t('awaitingHint')}
                </span>
              </Tile>
            )}
            <Tile>
              <b className="font-semibold">{t('matched')}</b>
              <span className="block text-xs text-ink-2 tabular-nums">{formatCount(matched, locale)}</span>
            </Tile>
          </ul>
        )}
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Link href={`/${locale}/prices/`} className="btn btn-primary focus-visible:outline-2">
            {t('prices')}
          </Link>
          <Link href={exploreHref(locale, {})} className="btn focus-visible:outline-2">
            {t('browse')}
          </Link>
        </div>
      </section>

      {category.kind === 'loading' && (
        <div className="panel px-5 py-4" aria-busy>
          <Skeleton kind="table" rows={4} />
        </div>
      )}
      {category.kind === 'ready' && <Peek data={category.data} pair={pair} name={name} />}
    </div>
  );
}

function Tile({ mark, children }: { mark?: ReactNode; children: ReactNode }) {
  return (
    <li className="flex items-center gap-3 rounded-ctl border border-line px-3 py-2.5">
      {mark}
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/** The category medians the Prices page already has for this pair: the comparison that exists today. */
function Peek({
  data,
  pair,
  name,
}: {
  data: CategoryCompare;
  pair: { base: string; other: string };
  name: Name;
}) {
  const t = useTranslations('compare.empty');
  const tb = useTranslations('widgets.buckets');
  const locale = useLocale();
  const lc = locale === 'ar' ? 'ar' : 'en';
  const label = (b: Bucket) => b.label?.[lc] || tb(`name.${b.key}`);
  const median = (b: Bucket, id: string) => {
    const s = b.sides[id];
    return s && s.status === 'ok' && isValidPrice(s.median) ? (
      formatMoney(s.median, lc)
    ) : (
      <span className="text-ink-2">{t('tooFewSide')}</span>
    );
  };
  const chip = (b: Bucket) => {
    if (b.status !== 'ok' || b.gapPct === null) return <span className="text-ink-2">–</span>;
    if (b.cheaper === 'same') return <span className="pill bg-surface-2 text-ink-2">{tb('same')}</span>;
    const who = b.cheaper ?? (b.gapPct.startsWith('-') ? pair.other : pair.base);
    return (
      <span className="pill" style={GOOD}>
        {name(who)}
      </span>
    );
  };
  return (
    <section aria-labelledby="peek-title" className="panel">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 pt-4">
        <h2 id="peek-title" className="text-base font-semibold">
          {t('peekTitle')}
        </h2>
        <p className="text-sm text-ink-2">{t('peekHint')}</p>
        <Link
          href={`/${locale}/prices/`}
          className="ms-auto text-sm text-accent hover:underline focus-visible:outline-2"
        >
          {t('peekAll', { n: formatCount(data.buckets.length, locale) })} ›
        </Link>
      </header>
      <div className="relative mt-3 overflow-x-auto pb-2">
        <table className="w-full text-sm">
          <thead className="border-b border-line">
            <tr>
              <th scope="col" className="th text-start">
                {t('category')}
              </th>
              {[pair.base, pair.other].map((id, i) => (
                <th key={id} scope="col" className="th text-end whitespace-nowrap">
                  <RetailerDot id={id} side={i as 0 | 1} /> {t('median', { shop: name(id) })}
                </th>
              ))}
              <th scope="col" className="th text-end">
                {t('difference')}
              </th>
              <th scope="col" className="th text-start">
                {t('cheaper')}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.buckets.map((b) => (
              <tr key={b.key} className="border-t border-line-2 first:border-t-0">
                <th scope="row" className="px-3 py-2 text-start font-medium">
                  {label(b)}
                </th>
                <td className="px-3 py-2 text-end tabular-nums">{median(b, pair.base)}</td>
                <td className="px-3 py-2 text-end tabular-nums">{median(b, pair.other)}</td>
                <td className="px-3 py-2 text-end tabular-nums">
                  {b.gapPct !== null ? <Pct v={b.gapPct} /> : <span className="text-ink-2">–</span>}
                </td>
                <td className="px-3 py-2">{chip(b)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
