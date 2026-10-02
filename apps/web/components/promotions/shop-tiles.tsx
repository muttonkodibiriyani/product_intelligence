'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { deepestCut, shareWidth } from '@/lib/promotions';
import { Known } from '../ui/known';
import { RetailerDot, retailerTone } from '../ui/retailer-dot';

/**
 * One tile per shop, from the API's `RetailerPromo`: its share of priced products on promotion
 * as the hero number, how many that is, the deepest cut in the list below, and a bar of the
 * share in the shop's colour. A shop whose discounts the API cannot measure (`reason` set,
 * `share` null) gets one plain state line in the same spot and the API's reason under it, with a
 * link to its current prices; never a caveat box, never a stubbed number, never 0%.
 */
export function ShopTiles({
  retailers,
  items,
  name,
}: {
  retailers: readonly Schemas['RetailerPromo'][];
  items: readonly Schemas['PromoItem'][];
  name: (id: string) => string;
}) {
  const t = useTranslations('promotions');
  if (retailers.length === 0) return null;
  return (
    <ul aria-label={t('shares')} className="grid gap-4 sm:grid-cols-2">
      {retailers.map((r, i) => (
        <li key={r.retailer} className="min-w-0 overflow-hidden panel">
          <i aria-hidden className={`block h-[3px] ${retailerTone(r.retailer, i)}`} />
          <Tile r={r} index={i} label={name(r.retailer)} cut={deepestCut(items, r.retailer)} />
        </li>
      ))}
    </ul>
  );
}

function Tile({
  r,
  index,
  label,
  cut,
}: {
  r: Schemas['RetailerPromo'];
  index: number;
  label: string;
  cut: string | null;
}) {
  const t = useTranslations('promotions');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const width = shareWidth(r.share);
  const who = (
    <span className="inline-flex items-center gap-1.5 font-medium text-ink">
      <RetailerDot id={r.retailer} index={index} />
      <span dir="auto">{label}</span>
    </span>
  );

  if (r.share === null) {
    return (
      <div className="px-5 pt-4 pb-5">
        <p className="text-[13px] text-ink-2">{who}</p>
        <p className="mt-2 text-lg leading-snug font-semibold">{t('notMeasuredShop')}</p>
        <p className="mt-2 text-sm text-ink-2">
          {r.reason ? <Known t={tr} v={r.reason} /> : t('noShare')}{' '}
          {t.rich('pricesIn', {
            shop: label,
            link: (chunks) => (
              <Link
                href={`/${locale}/explore/?retailer=${encodeURIComponent(r.retailer)}`}
                className="text-ink underline underline-offset-2 focus-visible:outline-2"
              >
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="px-5 pt-4 pb-5">
      <p className="text-[13px] text-ink-2">
        {who}
        <span aria-hidden> · </span>
        <span className="tabular-nums">{t('pricedCount', { n: formatCount(r.n, locale) })}</span>
      </p>
      <p className="mt-2 flex flex-wrap items-baseline gap-x-1.5">
        <bdi dir="ltr" className="text-[2rem] leading-none font-semibold tracking-tight tabular-nums">
          {`${r.share}%`}
        </bdi>
        <span className="text-sm text-ink-2">{t('onPromo')}</span>
      </p>
      <p className="mt-2 text-sm text-ink-2 tabular-nums">
        {t('onPromoCount', { total: r.onPromo, n: formatCount(r.onPromo, locale) })}
        {cut !== null && (
          <>
            {' '}
            {t.rich('deepest', {
              pct: cut,
              b: (chunks) => (
                <b className="font-semibold text-ink">
                  <bdi dir="ltr">{chunks}</bdi>
                </b>
              ),
            })}
          </>
        )}
      </p>
      {width !== null && (
        <div aria-hidden className="mt-3 h-1.5 overflow-hidden rounded-full bg-line-2">
          <i
            className={`block h-full rounded-full ${retailerTone(r.retailer, index)}`}
            style={{ width: `${width}%` }}
          />
        </div>
      )}
    </div>
  );
}
