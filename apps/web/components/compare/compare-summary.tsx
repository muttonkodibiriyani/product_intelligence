'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Money as MoneyValue, Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { formatMoney, isValidMoney } from '@/lib/money';
import { Card } from '../ui/card';
import { Known } from '../ui/known';
import { Money, Pct } from '../ui/money';
import { minus, retailerTone, sign, verdict as whoWins } from './model';
import { RetailerDot } from './pair-picker';

type Comparison = Schemas['Comparison'];
type Name = (id: string) => string;

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-top tabular-nums';

/**
 * The answer first: one sentence saying who is cheaper on how many of the matched products, the
 * basket in money, a tally bar, and three facts beside it. Every number is the API's summary
 * (which covers every matched product, not only the rows listed below).
 */
export function Verdict({
  data,
  name,
}: {
  data: Comparison & { summary: Schemas['CompareSummary'] };
  name: Name;
}) {
  const t = useTranslations('compare.verdict');
  const tf = useTranslations('compare.facts');
  const locale = useLocale();
  const lc = locale === 'ar' ? 'ar' : 'en';
  const s = data.summary;
  const base = name(data.base);
  const other = name(data.other);
  const n = formatCount(s.n, locale);
  const v = whoWins(s, data.base, data.other);
  const baseWins = s.cheaperCounts[data.base] ?? 0;
  const otherWins = s.cheaperCounts[data.other] ?? 0;

  const tail = (shop: string, k: number, equal: number) =>
    k > 0 && equal > 0
      ? t('tailBoth', { shop, k: formatCount(k, locale), n: formatCount(equal, locale), count: equal })
      : k > 0
        ? t('tailOther', { shop, k: formatCount(k, locale) })
        : equal > 0
          ? t('tailEqual', { n: formatCount(equal, locale), count: equal })
          : t('tailNone');
  const headline =
    v.kind === 'allSame'
      ? t('allSame', { n, count: s.n, base, other })
      : v.kind === 'tie'
        ? t('tie', { base, other, k: formatCount(v.k, locale), n, count: s.n }) + tail('', 0, v.equal)
        : t('lead', {
            shop: name(v.leader === 'base' ? data.base : data.other),
            k: formatCount(v.k, locale),
            n,
            count: s.n,
          }) + tail(name(v.leader === 'base' ? data.other : data.base), v.trailing, v.equal);

  const diff = minus(s.basket.other, s.basket.base);
  const money = (m: MoneyValue) => (isValidMoney(m) ? formatMoney(m, lc) : `${m.amount} ${m.currency}`);
  const basket =
    diff && diff.minor === 0
      ? t('basketSame', { n, baseTotal: money(s.basket.base) })
      : t('basket', {
          n,
          base,
          other,
          baseTotal: money(s.basket.base),
          otherTotal: money(s.basket.other),
          diff: diff
            ? money({ ...diff, amount: diff.amount.replace(/^-/, ''), minor: Math.abs(diff.minor) })
            : '–',
        });

  const gapSign = sign(s.medianGapPct);
  const diffSign = diff ? (diff.minor > 0 ? 1 : diff.minor < 0 ? -1 : 0) : 0;
  const pair = { base, other };
  const parts = [
    { id: data.base, side: 0 as const, n: baseWins, label: t('cheaperAt', { shop: base }) },
    { id: null, side: null, n: s.equalCount, label: t('same') },
    { id: data.other, side: 1 as const, n: otherWins, label: t('cheaperAt', { shop: other }) },
  ];

  return (
    <section aria-labelledby="verdict-title" className="grid gap-4 lg:grid-cols-[3fr_2fr]">
      <div className="panel px-5 py-4">
        <h2 id="verdict-title" className="text-xl font-semibold tracking-tight text-balance sm:text-[22px]">
          {headline}
        </h2>
        <p className="mt-2 text-sm text-ink-2">
          {basket} {t('scope', { n, total: formatCount(data.total, locale) })}
        </p>
        <div
          className="mt-4"
          role="img"
          aria-label={`${t('tally')}: ${parts.map((p) => `${p.label} ${formatCount(p.n, locale)}`).join(', ')}`}
        >
          <div className="flex h-2 overflow-hidden rounded-full bg-line-2">
            {parts.map(
              (p, i) =>
                p.n > 0 && (
                  <span
                    key={i}
                    className="h-full"
                    style={{
                      flex: `${p.n} 0 0`,
                      background: p.id ? retailerTone(p.id, p.side) : 'var(--color-line-3)',
                    }}
                  />
                ),
            )}
          </div>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2" aria-hidden>
            {parts.map((p, i) => (
              <li key={i} className="inline-flex items-center gap-1.5 tabular-nums">
                {p.id ? (
                  <RetailerDot id={p.id} side={p.side} />
                ) : (
                  <span className="inline-block size-2.5 rounded-full bg-line-3" />
                )}
                {p.label} <b className="font-semibold text-ink">{formatCount(p.n, locale)}</b>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <dl className="panel grid grid-cols-1 divide-y divide-line-2 sm:grid-cols-3 sm:divide-x sm:divide-y-0 lg:grid-cols-1 lg:divide-x-0 lg:divide-y">
        <Fact
          label={tf('matched')}
          value={n}
          note={tf('matchedOf', { total: formatCount(data.total, locale) })}
        />
        <Fact
          label={tf('gap')}
          value={<Pct v={s.medianGapPct} />}
          note={tf(gapSign > 0 ? 'gapAbove' : gapSign < 0 ? 'gapBelow' : 'gapSame', pair)}
        />
        <Fact
          label={tf('basket')}
          value={
            diff ? (
              <Money
                m={{ ...diff, amount: diff.amount.replace(/^-/, ''), minor: Math.abs(diff.minor) }}
                locale={locale}
              />
            ) : (
              '–'
            )
          }
          note={tf(diffSign > 0 ? 'basketAbove' : diffSign < 0 ? 'basketBelow' : 'basketSame', pair)}
        />
      </dl>
    </section>
  );
}

function Fact({ label, value, note }: { label: string; value: ReactNode; note: ReactNode }) {
  return (
    <div className="px-5 py-3">
      <dt className="text-xs text-ink-2">{label}</dt>
      <dd className="mt-0.5 text-xl font-semibold tracking-tight tabular-nums">{value}</dd>
      <dd className="text-xs text-ink-2">{note}</dd>
    </div>
  );
}

/** What each shop brought: how many of its products in this view are matched to the other. */
export function Coverage({ data, name }: { data: Comparison; name: Name }) {
  const t = useTranslations('compare.coverage');
  const th = useTranslations('home');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const sides = [data.sides.base, data.sides.other] as const;
  return (
    <Card id="coverage" title={t('title')}>
      <ul className="space-y-3 text-sm">
        {sides.map((s, i) => {
          const other = name(sides[1 - i]!.retailer);
          const rest = Math.max(0, s.observed - s.counted);
          return (
            <li key={s.retailer} className="flex gap-3">
              <span className="pt-1.5">
                <RetailerDot id={s.retailer} side={i as 0 | 1} />
              </span>
              <div className="min-w-0">
                <b className="font-semibold">{name(s.retailer)}</b>
                {s.status !== 'supported' && (
                  <span className="ms-2 pill bg-surface-2 text-xs text-ink-2">
                    <Known t={th} k="status" v={s.status} />
                  </span>
                )}
                <p className="text-ink-2">
                  {t('line', {
                    matched: formatCount(s.counted, locale),
                    seen: formatCount(s.observed, locale),
                    shop: name(s.retailer),
                    other,
                  })}{' '}
                  {t('rest', { n: formatCount(rest, locale), count: rest, shop: name(s.retailer) })}
                  {s.reason && (
                    <>
                      {' '}
                      <Known t={tr} v={s.reason} />
                    </>
                  )}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/** The rule a pair has to pass to be matched, and the API's own words for the set it counted. */
export function About({ cohort }: { cohort: Schemas['Cohort'] | null }) {
  const t = useTranslations('compare.about');
  return (
    <Card id="about-matched" title={t('title')}>
      <p className="text-sm text-ink-2">{t('body')}</p>
      {cohort?.description && (
        <p className="mt-2 text-xs text-ink-2">
          {t('cohort')}{' '}
          <span lang="en" dir="ltr">
            {cohort.description}
          </span>
        </p>
      )}
    </Card>
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
    <Card id="groups" title={t(by === 'brand' ? 'groupsBrand' : 'groupsCategory')} flush>
      <div className="relative overflow-x-auto px-2">
        <table className="w-full text-sm">
          <thead className="border-b border-line">
            <tr>
              <th scope="col" className={`${TH} text-start`}>
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
              <th scope="col" className={`${TH} text-start`}>
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
    </Card>
  );
}
