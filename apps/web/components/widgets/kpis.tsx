'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Summary } from '@/lib/api/summary';
import { formatCount, formatDate } from '@/lib/format';
import { formatMoney } from '@/lib/money';
import { exploreHref, freshness, pct, promotions, promotionsHref } from './model';

/** The headline numbers; the promotion share only once regular prices are collected. Each tile opens the list it counts. */
export function KpiWidget({ data, locale }: { data: Summary; locale: string }) {
  const t = useTranslations('widgets.kpi');
  const lc = locale === 'ar' ? 'ar' : 'en';
  const f = freshness(data.freshness);
  const promo = promotions(data);
  const all = exploreHref(locale, {});
  // A null count is withheld by /summary, not zero.
  const count = (v: number | null) => (v === null ? <None>{t('none')}</None> : formatCount(v, locale));
  return (
    <dl
      className={`grid grid-cols-2 gap-4 sm:grid-cols-3 ${promo.measured ? 'xl:grid-cols-6' : 'xl:grid-cols-5'}`}
    >
      <Tile k={t('products')} href={all} tone="bg-lav">
        {count(data.products)}
      </Tile>
      <Tile k={t('brands')} href={all} tone="bg-sky">
        {count(data.brands)}
      </Tile>
      <Tile k={t('categories')} href={all} tone="bg-mint">
        {count(data.categories)}
      </Tile>
      <Tile k={t('median')} href={exploreHref(locale, { sort: 'price_asc' })} tone="bg-butter">
        {data.medianPrice ? formatMoney(data.medianPrice, lc) : <None>{t('none')}</None>}
      </Tile>
      {promo.measured && (
        <Tile k={t('promo')} href={promotionsHref(locale, {})} tone="bg-blush" sub={t('promoOf')}>
          {pct(promo.share, locale)}
        </Tile>
      )}
      <Tile
        k={t('freshness')}
        href="#dataset"
        tone={
          f === 'fresh' ? 'bg-mint' : f === 'aging' ? 'bg-butter' : f === 'stale' ? 'bg-rose' : 'bg-surface-2'
        }
        sub={
          <>
            {t('asOf', { date: formatDate(data.freshness.cutoff, locale) })}
            {' · '}
            {t('age', { days: data.freshness.ageDays })}
          </>
        }
      >
        <span
          className={`pill text-base ${
            f === 'fresh'
              ? 'bg-mint text-mint-ink'
              : f === 'aging'
                ? 'bg-butter text-butter-ink'
                : f === 'stale'
                  ? 'bg-rose text-rose-ink'
                  : 'bg-surface-2'
          }`}
        >
          {t(f)}
        </span>
      </Tile>
    </dl>
  );
}

function Tile({
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
      <dd className="mt-1.5 text-2xl font-bold tracking-tight tabular-nums">{children}</dd>
      {sub && <dd className="mt-0.5 text-xs text-ink-2">{sub}</dd>}
    </div>
  );
}

const None = ({ children }: { children: ReactNode }) => (
  <span className="text-base font-medium text-ink-2">{children}</span>
);
