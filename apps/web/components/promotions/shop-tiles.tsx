'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { deepestCut, listable, shareWidth } from '@/lib/promotions';
import { Known } from '../ui/known';
import { RetailerDot, retailerTone } from '../ui/retailer-dot';

/**
 * One tile per shop, from the API's `RetailerPromo`: its share of priced products on promotion
 * as the hero number, how many that is, the deepest cut in the list below, and a bar of the
 * share in the shop's colour. A shop whose discounts the API cannot measure (`reason` set,
 * `share` null) gets one plain state line in the same spot and the API's reason under it, with a
 * link to its current prices; never a caveat box, never a stubbed number, never 0%. A shop whose
 * share alone is withheld (partly covered, small cohort) shows the discounts it was observed with
 * as a count, never as a share, and says why the share is not shown.
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
    <div className="space-y-4">
      <RetailerComparison retailers={retailers} items={items} name={name} />
      <ul aria-label={t('shares')} className="grid gap-4 lg:grid-cols-3">
        {retailers.map((r, i) => (
          <li key={r.retailer} className="min-w-0 overflow-hidden panel">
            <i aria-hidden className={`block h-[3px] ${retailerTone(r.retailer, i)}`} />
            <Tile r={r} index={i} label={name(r.retailer)} cut={deepestCut(items, r.retailer)} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The same four facts in aligned columns, so the shops can be compared without reading tiles. */
function RetailerComparison({
  retailers,
  items,
  name,
}: {
  retailers: readonly Schemas['RetailerPromo'][];
  items: readonly Schemas['PromoItem'][];
  name: (id: string) => string;
}) {
  const t = useTranslations('promotions');
  const locale = useLocale();
  if (retailers.length < 2) return null;
  return (
    <section aria-labelledby="promotion-comparison-title" className="overflow-hidden panel">
      <div className="border-b border-line-2 px-5 py-3">
        <h2 id="promotion-comparison-title" className="text-sm font-semibold text-ink">
          {t('comparison')}
        </h2>
        <p className="mt-0.5 text-xs text-ink-2">{t('comparisonHint')}</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-2 text-xs text-ink-2">
            <tr>
              <th scope="col" className="th text-start">
                {t('shop')}
              </th>
              <th scope="col" className="th text-end">
                {t('discounted')}
              </th>
              <th scope="col" className="th text-end">
                {t('share')}
              </th>
              <th scope="col" className="th text-end">
                {t('deepestShort')}
              </th>
            </tr>
          </thead>
          <tbody>
            {retailers.map((r, index) => {
              const publishesDiscounts = listable(r);
              const cut = publishesDiscounts ? deepestCut(items, r.retailer) : null;
              return (
                <tr key={r.retailer} className="border-t border-line-2 first:border-t-0">
                  <th scope="row" className="px-4 py-2.5 text-start font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      <RetailerDot id={r.retailer} index={index} />
                      <span dir="auto">{name(r.retailer)}</span>
                    </span>
                  </th>
                  <td className="px-4 py-2.5 text-end tabular-nums">
                    {publishesDiscounts ? (
                      formatCount(r.onPromo, locale)
                    ) : (
                      <span className="text-ink-3">{t('withheld')}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-end font-semibold tabular-nums">
                    {!publishesDiscounts || r.share === null ? (
                      <span className="font-normal text-ink-3">{t('withheld')}</span>
                    ) : (
                      `${r.share}%`
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-end font-semibold tabular-nums">
                    {!publishesDiscounts ? (
                      <span className="font-normal text-ink-3">{t('withheld')}</span>
                    ) : cut === null ? (
                      <span aria-hidden>—</span>
                    ) : (
                      <bdi dir="ltr">−{cut}%</bdi>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
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

  if (r.share === null && listable(r)) {
    return (
      <div className="px-5 pt-4 pb-5">
        <p className="text-[13px] text-ink-2">{who}</p>
        <p className="mt-2 flex flex-wrap items-baseline gap-x-1.5">
          <bdi dir="ltr" className="text-[2rem] leading-none font-semibold tracking-tight tabular-nums">
            {formatCount(r.onPromo, locale)}
          </bdi>
          <span className="text-sm text-ink-2">{t('discountedSeen', { total: r.onPromo })}</span>
        </p>
        <p className="mt-2 text-sm text-ink-2 tabular-nums">
          {cut !== null &&
            t.rich('deepest', {
              pct: cut,
              b: (chunks) => (
                <b className="font-semibold text-ink">
                  <bdi dir="ltr">{chunks}</bdi>
                </b>
              ),
            })}{' '}
          {t('shareWithheld')} {r.reason && <Known t={tr} v={r.reason} />}
        </p>
        <PromoBreakdown r={r} index={index} />
      </div>
    );
  }

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
      <PromoBreakdown r={r} index={index} />
    </div>
  );
}

const BAND_EDGES = [0, 10, 20, 30, 40, 50] as const;

/** One shop's six fixed discount-depth bands plus its leading brands and categories. */
function PromoBreakdown({ r, index }: { r: Schemas['RetailerPromo']; index: number }) {
  const t = useTranslations('promotions');
  const locale = useLocale();
  // API 1.16 did not send these arrays. Missing means absent, never six invented zeroes.
  const bands = r.bands ?? [];
  const groups = r.groups ?? [];
  const max = Math.max(0, ...bands);
  if (bands.length === 0 && groups.length === 0) return null;
  return (
    <div className="mt-4 space-y-4 border-t border-line-2 pt-4">
      {bands.length > 0 && (
        <section aria-label={t('depthBands')}>
          <h3 className="text-xs font-semibold tracking-wide text-ink-2 uppercase">{t('depthBands')}</h3>
          <div className="mt-2 grid gap-1.5">
            {BAND_EDGES.map((edge, bandIndex) => {
              const n = bands[bandIndex] ?? 0;
              const next = BAND_EDGES[bandIndex + 1];
              const label = next
                ? t('bandRange', { min: edge, max: next - 1 })
                : t('bandOver', { min: edge });
              return (
                <div
                  key={edge}
                  data-depth-band={edge}
                  className="grid grid-cols-[3.5rem_1fr_auto] items-center gap-2 text-xs"
                >
                  <span className="text-ink-3">
                    <bdi dir="ltr">{label}</bdi>
                  </span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-line-2">
                    <i
                      aria-hidden
                      className={`block h-full rounded-full ${retailerTone(r.retailer, index)}`}
                      style={{ width: max === 0 ? '0%' : `${(n / max) * 100}%` }}
                    />
                  </span>
                  <span className="min-w-5 text-end font-medium tabular-nums">{formatCount(n, locale)}</span>
                </div>
              );
            })}
          </div>
        </section>
      )}
      {groups.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          <GroupRows kind="brand" groups={groups} />
          <GroupRows kind="category" groups={groups} />
        </div>
      )}
    </div>
  );
}

function GroupRows({
  kind,
  groups,
}: {
  kind: Schemas['PromoGroup']['kind'];
  groups: readonly Schemas['PromoGroup'][];
}) {
  const t = useTranslations('promotions');
  const locale = useLocale();
  const rows = groups.filter((group) => group.kind === kind).slice(0, 4);
  if (rows.length === 0) return null;
  return (
    <section aria-label={kind === 'brand' ? t('topBrands') : t('topCategories')}>
      <h3 className="text-xs font-semibold tracking-wide text-ink-2 uppercase">
        {kind === 'brand' ? t('topBrands') : t('topCategories')}
      </h3>
      <div className="mt-2 grid gap-1.5 text-xs">
        {rows.map((group) => (
          <div key={`${kind}:${group.key}`} className="flex min-w-0 items-baseline gap-2">
            <span className="min-w-0 flex-1 truncate text-ink" dir="auto" title={group.key}>
              {group.key}
            </span>
            <span className="shrink-0 text-ink-3 tabular-nums">
              {group.share === null
                ? t('groupCount', { n: formatCount(group.onPromo, locale) })
                : t('groupShare', { share: group.share })}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
