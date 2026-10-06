'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { formatCount } from '@/lib/format';
import {
  EXCEPTIONS_SHOWN,
  fewRated,
  notCollected,
  oncePerName,
  perUnitMedian,
  pickSize,
  PICKS_SHOWN,
  PROMOS_ASKED,
  PROMOS_SHOWN,
  ratingOutOfFive,
  valueCategories,
  type Insights,
  type Ladder,
  type ValueCategory,
  type ValuePicks,
} from '@/lib/insights';
import { listedItems, notMeasured } from '@/lib/promotions';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { Known } from '../ui/known';
import { Money } from '../ui/money';
import { useRetailerName } from '../use-meta';
import { exploreHref, promotionsHref } from '../widgets/model';
import {
  cols,
  LINK,
  moneyText,
  unitText,
  linkTag,
  Heading,
  ShopHead,
  Panel,
  Label,
  Off,
  Warn,
  Cat,
  useUnitName,
  ProductRow,
} from './parts';

/**
 * The three ideas under the shop facts: best value, bigger sizes and deepest discounts. One module
 * with one entry point (`Ideas`), so the section can be redesigned and swapped without touching
 * the rest of the page.
 */
export function Ideas({ shops, data }: { shops: string[]; data: Insights }) {
  return (
    <>
      <ValueSection shops={shops} data={data} />
      <LadderSection shops={shops} rows={data.ladders} held={data.heldOutPct} />
      <PromoSection shops={shops} />
    </>
  );
}

// ---- Best value -----------------------------------------------------------------------------

function ValueSection({ shops, data }: { shops: string[]; data: Insights }) {
  const t = useTranslations('insights');
  return (
    <section aria-labelledby="ins-value" className="space-y-2.5">
      <Heading
        id="ins-value"
        tip={t('value.tip', { top: ratingOutOfFive(data.valueRatingPct), min: data.valueMinRatings })}
      >
        {t('value.title')}
      </Heading>
      <div className="space-y-4">
        {shops.map((s) => (
          <ValueShop
            key={s}
            shop={s}
            row={data.value.find((r) => r.retailer === s)}
            min={data.valueMinRatings}
          />
        ))}
      </div>
    </section>
  );
}

/** One shop's value picks: every qualifying category of its own, four across on a wide screen. */
function ValueShop({ shop, row, min }: { shop: string; row: ValuePicks | undefined; min: number }) {
  const t = useTranslations('insights');
  const tr = useTranslations('reasons');
  const name = useRetailerName();
  const cats = row && !row.reason ? valueCategories(row) : [];
  return (
    <div className="space-y-2">
      <ShopHead id={shop} />
      {!row || notCollected(row.reason) ? (
        <p className="text-sm text-ink-2">{t('value.off', { shop: name(shop) })}</p>
      ) : row.reason ? (
        <p className="text-sm text-ink-2">
          <Known t={tr} v={row.reason} />
        </p>
      ) : cats.length === 0 ? (
        <p className="text-sm text-ink-2">{t('value.none')}</p>
      ) : (
        <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
          {cats.map((c) => (
            <ValueCard key={c.category} shop={shop} c={c} min={min} />
          ))}
        </div>
      )}
    </div>
  );
}

function ValueCard({ shop, c, min }: { shop: string; c: ValueCategory; min: number }) {
  const t = useTranslations('insights');
  const locale = useLocale();
  const unitName = useUnitName();
  const perUnit = perUnitMedian(c);
  const picks = oncePerName(c.items).slice(0, PICKS_SHOWN);
  const line = { count: c.picks, num: formatCount(c.picks, locale) };
  return (
    <Panel>
      <p className="text-sm font-semibold">
        <Link href={exploreHref(locale, { retailer: [shop], category: [c.category] })} className={LINK}>
          <Cat k={c.category} />
        </Link>
      </p>
      <div className="mt-0.5 space-y-1 text-xs text-ink-2">
        <p>
          {perUnit
            ? t('value.lineUnit', {
                ...line,
                median: unitText(perUnit.median, locale),
                unit: unitName(perUnit.unit),
              })
            : t('value.lineShelf', { ...line, median: moneyText(c.median, locale) })}
        </p>
        {/* The category audit's notes: an amber "few rated", then what the rules left out. */}
        {fewRated(c) && (
          <p>
            <Warn>
              {t('value.fewRated', {
                rated: formatCount(c.rated, locale),
                priced: formatCount(c.priced, locale),
                min,
              })}
            </Warn>
          </p>
        )}
        {c.excluded > 0 && (
          <p>{t('value.excluded', { count: c.excluded, num: formatCount(c.excluded, locale) })}</p>
        )}
      </div>
      {picks.length === 0 ? (
        <Off>{t('value.none')}</Off>
      ) : (
        <ul className="mt-3 grid gap-2.5">
          {picks.map((p) => {
            const { size, unitPrice } = pickSize(p);
            return (
              <ProductRow key={p.id} item={p} shop={shop}>
                <b className="font-semibold text-ink">
                  <Money m={p.price} locale={locale} />
                </b>
                {size && (
                  <>
                    {' · '}
                    <bdi dir="ltr">{size.value}</bdi> {unitName(size.unit)}
                  </>
                )}
                {size &&
                  unitPrice &&
                  ` · ${t('value.per', { price: unitText(unitPrice, locale), unit: unitName(size.unit) })}`}
                {' · ★ '}
                <bdi dir="ltr">{`${p.rating}/${p.scale}`}</bdi>
                {' · '}
                {t('value.ratings', { count: p.ratingCount, num: formatCount(p.ratingCount, locale) })}
              </ProductRow>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

/** One product: its image (or the brand's monogram), brand, its name opening it, a detail line. */
// ---- Bigger sizes ---------------------------------------------------------------------------

function LadderSection({ shops, rows, held }: { shops: string[]; rows: Ladder[]; held: string }) {
  const t = useTranslations('insights');
  const heldOut = rows.filter((r) => shops.includes(r.retailer)).reduce((a, r) => a + r.heldOut, 0);
  return (
    <section aria-labelledby="ins-ladder" className="space-y-2.5">
      <Heading id="ins-ladder" tip={t('ladder.tip', { held, heldOut })}>
        {t('ladder.title')}
      </Heading>
      <div className={cols(shops.length)}>
        {shops.map((s) => (
          <LadderCard key={s} shop={s} row={rows.find((r) => r.retailer === s)} one={shops.length === 1} />
        ))}
      </div>
    </section>
  );
}

function LadderCard({ shop, row, one }: { shop: string; row: Ladder | undefined; one: boolean }) {
  const t = useTranslations('insights');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const unitName = useUnitName();
  const exceptions = oncePerName(row?.exceptions ?? []).slice(
    0,
    one ? EXCEPTIONS_SHOWN.one : EXCEPTIONS_SHOWN.all,
  );
  return (
    <Panel>
      <ShopHead id={shop} />
      {row?.reason ? (
        <Off>
          <Known t={tr} v={row.reason} />
        </Off>
      ) : !row || row.steps === 0 || row.medianSavingPct === null ? (
        <Off>{t('ladder.none', { shop: name(shop) })}</Off>
      ) : (
        <>
          <p className="mt-2.5 text-[17px] font-semibold">
            {t('ladder.head', { pct: `⁦${row.medianSavingPct}%⁩` })}
          </p>
          <p className="text-sm text-ink-2">
            {t('ladder.sub', {
              steps: formatCount(row.steps, locale),
              k: formatCount(row.notCheaper, locale),
            })}
          </p>
          {exceptions.length > 0 && (
            <>
              <Label>{t('ladder.exceptions')}</Label>
              <ul className={`grid gap-2.5 ${one ? 'lg:grid-cols-2 lg:gap-x-4.5' : ''}`}>
                {exceptions.map((x) => (
                  <ProductRow
                    key={`${x.smallerId},${x.largerId}`}
                    item={{ brand: x.brand, name: x.name, id: x.largerId }}
                    shop={shop}
                  >
                    <bdi dir="ltr">
                      {`${x.smallerValue} ${unitName(x.unit)} `}
                      <Money m={x.smallerPrice} locale={locale} />
                      {` → ${x.largerValue} ${unitName(x.unit)} `}
                      <Money m={x.largerPrice} locale={locale} />
                    </bdi>
                    {' · '}
                    <b className="font-semibold text-bad">
                      <bdi dir="ltr">{`+${x.unitChangePct}%`}</bdi>
                    </b>
                    {x.smallerOnSale && (
                      <>
                        {' · '}
                        <Warn>{t('ladder.onSale')}</Warn>
                      </>
                    )}
                  </ProductRow>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Panel>
  );
}

// ---- Deepest discounts ----------------------------------------------------------------------

function PromoSection({ shops }: { shops: string[] }) {
  const t = useTranslations('insights');
  return (
    <section aria-labelledby="ins-promo" className="space-y-2.5">
      <Heading id="ins-promo" tip={t('promo.tip')}>
        {t('promo.title')}
      </Heading>
      <div className={cols(shops.length)}>
        {shops.map((s) => (
          <PromoCard key={s} shop={s} one={shops.length === 1} />
        ))}
      </div>
    </section>
  );
}

/** One shop's deepest discounts, once per product name, and how many listings per category are on discount. */
function PromoCard({ shop, one }: { shop: string; one: boolean }) {
  const t = useTranslations('insights');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['promotions', 'insights', shop],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/promotions', { query: { retailer: [shop], limit: PROMOS_ASKED }, signal }),
    enabled: !!api,
  });
  const env = q.data;
  const reason = env ? notMeasured(env, shop) : null;
  const items = env?.data ? oncePerName(listedItems(env.data).items) : [];
  const shown = items.slice(0, one ? PROMOS_SHOWN.one : PROMOS_SHOWN.all);
  const groups = (env?.data?.retailers.find((r) => r.retailer === shop)?.groups ?? []).filter(
    (g) => g.kind === 'category' && g.key !== 'other' && g.n > 0,
  );
  return (
    <Panel>
      <ShopHead id={shop} />
      {q.isError ? (
        <div className="mt-2.5">
          <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
        </div>
      ) : !env ? (
        <Off>{t('loading')}</Off>
      ) : reason ? (
        <Off>{notCollected(reason) ? t('promo.off', { shop: name(shop) }) : <Known t={tr} v={reason} />}</Off>
      ) : shown.length === 0 ? (
        <Off>{t('promo.none', { shop: name(shop) })}</Off>
      ) : (
        <>
          {groups.length > 0 && (
            <>
              <Label>{t('promo.byCat')}</Label>
              <p className="text-[13px] text-ink-2">
                {groups.map((g, i) => (
                  <span key={g.key}>
                    {i > 0 && ' · '}
                    {t.rich('promo.cat', {
                      category: g.key,
                      num: formatCount(g.onPromo, locale),
                      n: formatCount(g.n, locale),
                      c: () => (
                        <Link
                          href={exploreHref(locale, { retailer: [shop], category: [g.key] })}
                          className={LINK}
                        >
                          <Cat k={g.key} />
                        </Link>
                      ),
                      l: linkTag(promotionsHref(locale, { retailer: shop, category: g.key })),
                    })}
                  </span>
                ))}
              </p>
            </>
          )}
          <ul className={`mt-3 grid gap-2.5 ${one ? 'lg:grid-cols-2 lg:gap-x-4.5' : ''}`}>
            {shown.map((i) => (
              <ProductRow key={i.id} item={i} shop={shop}>
                <b className="font-semibold text-ink">
                  <Money m={i.price} locale={locale} />
                </b>{' '}
                {t('promo.was', { price: moneyText(i.regular, locale) })}
                {' · '}
                <b className="font-semibold text-good">
                  <bdi dir="ltr">{`−${i.depthPct}%`}</bdi>
                </b>
              </ProductRow>
            ))}
          </ul>
          <p className="mt-3 text-sm">
            <Link href={promotionsHref(locale, { retailer: shop })} className={LINK}>
              {t('promo.all', { shop: name(shop) })}
            </Link>
          </p>
        </>
      )}
    </Panel>
  );
}
