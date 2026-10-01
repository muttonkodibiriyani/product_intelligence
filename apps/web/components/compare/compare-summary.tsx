'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { Known } from '../ui/known';
import { Money, Pct } from '../ui/money';

type Comparison = Schemas['Comparison'];
type Name = (id: string) => string;

const TH = 'px-3 py-2 text-start font-medium text-ink-2 whitespace-nowrap';
const TD = 'px-3 py-2 align-top tabular-nums';

/**
 * The pair's headline numbers. They cover every counted product, not only the rows on screen;
 * the rows below are the evidence, each with its own gap.
 */
export function Summary({
  data,
  cohort,
  name,
}: {
  data: Comparison;
  cohort: Schemas['Cohort'] | null;
  name: Name;
}) {
  const t = useTranslations('compare');
  const locale = useLocale();
  const s = data.summary;
  const pair = { base: name(data.base), other: name(data.other) };
  return (
    <section aria-labelledby="summary-title">
      <h2 id="summary-title" className="text-base font-semibold">
        {t('summary', pair)}
      </h2>
      <p className="mt-1 text-sm text-ink-2">{t('convention', pair)}</p>
      {!s ? (
        <p className="mt-3 rounded border border-line bg-surface px-3 py-2 text-sm">{t('noSummary')}</p>
      ) : (
        <dl className="mt-3 grid gap-px overflow-hidden rounded border border-line bg-line sm:grid-cols-2 xl:grid-cols-4">
          <Stat label={t('compared')} value={formatCount(s.n, locale)}>
            {cohort?.description && (
              <span lang="en" dir="ltr">
                {cohort.description}
              </span>
            )}
          </Stat>
          <Stat label={t('median')} value={<Pct v={s.medianGapPct} />}>
            {t('mean')} <Pct v={s.meanGapPct} />
          </Stat>
          <Stat
            label={t('cheaperAt')}
            value={
              <span className="flex flex-wrap gap-x-3">
                {[data.base, data.other].map((r) => (
                  <span key={r}>
                    {name(r)} <b className="font-semibold">{formatCount(s.cheaperCounts[r] ?? 0, locale)}</b>
                  </span>
                ))}
              </span>
            }
          >
            {t('equalCount', { n: formatCount(s.equalCount, locale), count: s.equalCount })}
          </Stat>
          <Stat
            label={t('basket', { n: formatCount(s.n, locale) })}
            value={
              <span className="flex flex-col">
                <span>
                  {pair.base} <Money m={s.basket.base} locale={locale} />
                </span>
                <span>
                  {pair.other} <Money m={s.basket.other} locale={locale} />
                </span>
              </span>
            }
          />
        </dl>
      )}
    </section>
  );
}

function Stat({ label, value, children }: { label: string; value: ReactNode; children?: ReactNode }) {
  return (
    <div className="bg-surface px-4 py-3">
      <dt className="text-xs font-medium text-ink-2">{label}</dt>
      <dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd>
      {children && <dd className="mt-1 text-xs text-ink-2">{children}</dd>}
    </div>
  );
}

/** What each retailer brought: products seen, products counted, and products only it sells. */
export function Sides({ data, name }: { data: Comparison; name: Name }) {
  const t = useTranslations('compare');
  const th = useTranslations('home');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const sides = [data.sides.base, data.sides.other];
  return (
    <section aria-labelledby="sides-title">
      <h2 id="sides-title" className="text-base font-semibold">
        {t('sides')}
      </h2>
      <div className="relative mt-3 overflow-x-auto rounded border border-line bg-surface">
        <table className="w-full text-sm">
          <thead className="border-b border-line">
            <tr>
              <th scope="col" className={TH}>
                {t('retailer')}
              </th>
              <th scope="col" className={TH}>
                {t('status')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('observed')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('counted')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('onlyHere')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sides.map((s, i) => (
              <tr key={i} className="border-t border-line first:border-t-0">
                <th scope="row" className={`${TD} min-w-32 text-start font-normal`}>
                  {name(s.retailer)}
                  <span className="ms-2 text-xs text-ink-2">{t(i === 0 ? 'base' : 'other')}</span>
                </th>
                <td className={`${TD} min-w-40`}>
                  <Known t={th} k="status" v={s.status} />
                  {s.reason && (
                    <span className="block text-xs text-ink-2">
                      <Known t={tr} v={s.reason} />
                    </span>
                  )}
                </td>
                <td className={`${TD} text-end`}>{formatCount(s.observed, locale)}</td>
                <td className={`${TD} text-end`}>{formatCount(s.counted, locale)}</td>
                <td className={`${TD} text-end`}>{formatCount(s.onlyHere, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-ink-2">{t('sidesHint')}</p>
    </section>
  );
}

/** One line per brand or category; a group too small to summarise says so instead of a number. */
export function Groups({
  data,
  name,
  onPick,
}: {
  data: Comparison;
  name: Name;
  onPick: (key: string) => void;
}) {
  const t = useTranslations('compare');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const by = data.groupBy === 'category' ? 'category' : 'brand';
  return (
    <section aria-labelledby="groups-title">
      <h2 id="groups-title" className="text-base font-semibold">
        {t(by === 'brand' ? 'groupsBrand' : 'groupsCategory')}
      </h2>
      <div className="relative mt-3 overflow-x-auto rounded border border-line bg-surface">
        <table className="w-full text-sm">
          <thead className="border-b border-line">
            <tr>
              <th scope="col" className={TH}>
                {t(by === 'brand' ? 'groupBrand' : 'groupCategory')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('products')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('median')}
              </th>
              <th scope="col" className={`${TH} text-end`}>
                {t('mean')}
              </th>
              <th scope="col" className={TH}>
                {t('cheaperAt')}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.groups.map((g) => (
              <tr key={g.key} className="border-t border-line first:border-t-0">
                <th scope="row" className={`${TD} text-start font-normal`}>
                  <button
                    type="button"
                    onClick={() => onPick(g.key)}
                    title={t('filterTo', { value: g.key })}
                    className="text-start text-accent hover:underline focus-visible:outline-2"
                  >
                    <bdi>{g.key}</bdi>
                  </button>
                </th>
                <td className={`${TD} text-end`}>{formatCount(g.n, locale)}</td>
                {g.summary ? (
                  <>
                    <td className={`${TD} text-end`}>
                      <Pct v={g.summary.medianGapPct} />
                    </td>
                    <td className={`${TD} text-end`}>
                      <Pct v={g.summary.meanGapPct} />
                    </td>
                    <td className={TD}>
                      {[data.base, data.other]
                        .map((r) => `${name(r)} ${formatCount(g.summary!.cheaperCounts[r] ?? 0, locale)}`)
                        .join(' · ')}
                    </td>
                  </>
                ) : (
                  <td colSpan={3} className={`${TD} min-w-48 text-ink-2`}>
                    {g.reason ? <Known t={tr} v={g.reason} /> : '–'}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
