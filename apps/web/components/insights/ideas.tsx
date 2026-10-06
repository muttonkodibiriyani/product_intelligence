'use client';

import { useQueries, useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { useState, type ReactNode } from 'react';
import { formatCount } from '@/lib/format';
import {
  CARD_ITEMS,
  fewRated,
  focusFirst,
  notCollected,
  oncePerName,
  perUnitMedian,
  pickSize,
  PROMOS_ASKED,
  ratingOutOfFive,
  sharePct,
  valueCategories,
  valueShare,
  type Insights,
  type Ladder,
  type LadderStep,
  type ValuePicks,
} from '@/lib/insights';
import { listable, listedItems } from '@/lib/promotions';
import { useAuth } from '../auth-provider';
import { Known } from '../ui/known';
import { Money } from '../ui/money';
import { useRetailerName } from '../use-meta';
import { exploreHref, promotionsHref } from '../widgets/model';
import {
  Bars,
  IdeaCard,
  ItemRow,
  LINK,
  ListHead,
  moneyText,
  Num,
  pricedOptions,
  unitText,
  useUnitName,
  type ChartRow,
} from './parts';

/**
 * Value, size steps and discounts: three cards about one shop (the one picked, else the first),
 * the other shops beside it in each card's chart for context. Each card has one big number, one
 * sentence, one bar per shop and a few products; counts, basis and exclusions are in its (i)
 * note. Bars compare shares or medians, never raw counts across catalogues of different sizes. A
 * shop whose number is not collected shows a quiet note, never a zero bar.
 */
export function Ideas({ focus, shops, data }: { focus: string; shops: string[]; data: Insights }) {
  const t = useTranslations('insights');
  const name = useRetailerName();
  const order = focusFirst(focus, shops);
  return (
    <section aria-labelledby="ins-ideas" className="space-y-2.5">
      <div>
        <h2 id="ins-ideas" className="text-[15px] font-semibold">
          {t('vsd.title', { shop: name(focus) })}
        </h2>
        <p className="text-sm text-ink-2">{t('vsd.sub', { shop: name(focus) })}</p>
      </div>
      <div className="grid items-stretch gap-3.5 min-[900px]:grid-cols-3">
        <ValueCard focus={focus} order={order} data={data} />
        <SizeCard focus={focus} order={order} rows={data.ladders} held={data.heldOutPct} />
        <PromoCard focus={focus} order={order} />
      </div>
    </section>
  );
}

/** Rich-text tag for a number in a sentence: one Latin run that keeps its order in Arabic. */
const n = (chunks: ReactNode) => <Num>{chunks}</Num>;

function useCatName() {
  const t = useTranslations('insights');
  return (k: string) => (t.has(`cat.${k}`) ? t(`cat.${k}`) : k);
}

// ---- Value ----------------------------------------------------------------------------------

function ValueCard({ focus, order, data }: { focus: string; order: string[]; data: Insights }) {
  const t = useTranslations('insights');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const catName = useCatName();
  const unitName = useUnitName();
  const [tab, setTab] = useState(0);
  const top = ratingOutOfFive(data.valueRatingPct);
  const min = data.valueMinRatings;
  const row = (s: string): ValuePicks | undefined => data.value.find((r) => r.retailer === s);
  const own = row(focus);
  const cats = own && !own.reason ? valueCategories(own) : [];
  const share = own && !own.reason ? valueShare(own) : null;
  const cat = cats[Math.min(tab, cats.length - 1)];

  const chart: ChartRow[] = order.map((s) => {
    const r = row(s);
    if (!r || r.reason)
      return {
        id: s,
        value: null,
        note: !r || notCollected(r.reason) ? t('value.off') : <Known t={tr} v={r.reason!} />,
      };
    const v = valueShare(r);
    if (v.pct === null) return { id: s, value: null, note: t('value.none') };
    return {
      id: s,
      value: Number(v.pct),
      text: t.rich('value.bar', {
        pct: v.pct,
        num: formatCount(v.picks, locale),
        rated: formatCount(v.rated, locale),
        n,
      }),
    };
  });
  const few = cats.filter(fewRated);
  const tip = t('value.tip', {
    top,
    min,
    few: cats.map((c) => `${catName(c.category)} ${c.rated}/${c.priced}`).join('; ') || t('value.nothing'),
    excluded:
      cats
        .filter((c) => c.excluded > 0)
        .map((c) => `${catName(c.category)} ${c.excluded}`)
        .join('; ') || t('value.nothing'),
  });
  const perUnit = cat ? perUnitMedian(cat) : null;

  return (
    <IdeaCard
      id="ins-value"
      title={t('value.title')}
      chip={
        few.length > 0 && (
          <span
            title={t('value.fewTip', {
              shop: name(focus),
              min,
              few: few.map((c) => `${catName(c.category)} ${c.rated}/${c.priced}`).join('; '),
            })}
            className="rounded-full border border-line bg-surface-2 px-2 text-xs text-ink-2"
          >
            {t('value.few')}
          </span>
        )
      }
      tip={tip}
      big={share ? <Num>{formatCount(share.picks, locale)}</Num> : '–'}
      unit={t('value.unit', { shop: name(focus) })}
      sentence={t('value.sentence', { top, min })}
      chart={<Bars rows={chart} />}
      more={
        cat && (
          <Link href={exploreHref(locale, { retailer: [focus], category: [cat.category] })} className={LINK}>
            {t('value.see', { category: catName(cat.category), shop: name(focus) })}
          </Link>
        )
      }
    >
      {cats.length > 0 && cat && (
        <>
          <div role="group" aria-label={t('value.title')} className="mt-4 flex flex-wrap gap-1">
            {cats.map((c, i) => (
              <button
                key={c.category}
                type="button"
                aria-pressed={c === cat}
                onClick={() => setTab(i)}
                className={`rounded-full border px-2.5 py-0.5 text-xs focus-visible:outline-2 ${
                  c === cat ? 'border-ink bg-ink text-white' : 'border-line text-ink-2 hover:text-ink'
                }`}
              >
                {catName(c.category)}
              </button>
            ))}
          </div>
          <ListHead label={catName(cat.category)}>
            {perUnit
              ? t('value.typicalUnit', {
                  median: unitText(perUnit.median, locale),
                  unit: unitName(perUnit.unit),
                })
              : t('value.typicalShelf', { median: moneyText(cat.median, locale) })}
          </ListHead>
          <ul className="grid gap-2.5">
            {oncePerName(cat.items)
              .slice(0, CARD_ITEMS.value)
              .map((p) => {
                const { size, unitPrice } = pickSize(p);
                const price = <Money m={p.price} locale={locale} />;
                return (
                  <ItemRow key={p.id} item={p} shop={focus}>
                    {perUnit && size && unitPrice ? (
                      <>
                        <b className="font-semibold text-ink">
                          {t('value.per', { price: unitText(unitPrice, locale), unit: unitName(size.unit) })}
                        </b>
                        {' · '}
                        {price}
                      </>
                    ) : (
                      <b className="font-semibold text-ink">{price}</b>
                    )}
                    {' · ★ '}
                    <Num>{p.scale === '5' ? p.rating : `${p.rating}/${p.scale}`}</Num>
                    {' · '}
                    {t('value.ratings', { count: p.ratingCount, num: formatCount(p.ratingCount, locale) })}
                  </ItemRow>
                );
              })}
          </ul>
        </>
      )}
    </IdeaCard>
  );
}

// ---- Size steps -----------------------------------------------------------------------------

const usable = (l: Ladder | undefined): l is Ladder & { medianSavingPct: string } =>
  !!l && !l.reason && l.steps > 0 && l.medianSavingPct !== null;

function SizeCard({
  focus,
  order,
  rows,
  held,
}: {
  focus: string;
  order: string[];
  rows: Ladder[];
  held: string;
}) {
  const t = useTranslations('insights');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const [all, setAll] = useState(false);
  const row = (s: string) => rows.find((r) => r.retailer === s);
  const own = row(focus);
  const ok = usable(own) ? own : null;
  const exceptions = oncePerName(ok?.exceptions ?? []);
  const shown = all ? exceptions : exceptions.slice(0, CARD_ITEMS.size);

  const chart: ChartRow[] = order.map((s) => {
    const l = row(s);
    if (usable(l))
      return {
        id: s,
        value: Number(l.medianSavingPct),
        text: t.rich('ladder.bar', {
          pct: l.medianSavingPct,
          count: l.steps,
          num: formatCount(l.steps, locale),
          n,
        }),
      };
    return { id: s, value: null, note: l?.reason ? <Known t={tr} v={l.reason} /> : t('ladder.none') };
  });

  return (
    <IdeaCard
      id="ins-ladder"
      title={t('ladder.title')}
      tip={t('ladder.tip', {
        held,
        heldOut: own?.heldOut ?? 0,
        shop: name(focus),
        steps: own?.steps ?? 0,
        k: own?.notCheaper ?? 0,
        listed: exceptions.length,
      })}
      big={ok ? <Num>{`${ok.medianSavingPct}%`}</Num> : '–'}
      unit={t('ladder.headline', { shop: name(focus) })}
      sentence={
        ok
          ? t.rich('ladder.sentence', {
              steps: ok.steps,
              num: formatCount(ok.steps, locale),
              k: formatCount(ok.notCheaper, locale),
              n,
            })
          : t('ladder.none')
      }
      chart={<Bars rows={chart} />}
      more={
        exceptions.length > CARD_ITEMS.size && (
          <button type="button" aria-expanded={all} onClick={() => setAll(!all)} className={LINK}>
            {all ? t('ladder.seeFewer') : t('ladder.seeAll', { count: exceptions.length })}
          </button>
        )
      }
    >
      {ok && shown.length > 0 && (
        <>
          <ListHead label={t('ladder.head')}>
            {t.rich('ladder.headCount', {
              shown: formatCount(shown.length, locale),
              total: formatCount(ok.notCheaper, locale),
              n,
            })}
          </ListHead>
          <ul className="grid gap-2.5">
            {shown.map((x) => (
              <StepRow key={`${x.smallerId},${x.largerId}`} x={x} shop={focus} />
            ))}
          </ul>
        </>
      )}
    </IdeaCard>
  );
}

/** A step that is not cheaper per unit, shown with the larger size's picture from its product. */
function StepRow({ x, shop }: { x: LadderStep; shop: string }) {
  const t = useTranslations('insights');
  const unitName = useUnitName();
  const { api } = useAuth();
  // The ladder carries no picture; the product's own card does (cached with the product page).
  const card = useQuery({
    queryKey: ['product', x.largerId],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/products/{product_id}', { params: { product_id: x.largerId }, signal }),
    enabled: !!api,
    retry: false,
  });
  const image = card.data?.data?.card.image ?? null;
  return (
    <ItemRow item={{ brand: x.brand, name: x.name, id: x.largerId, image }} shop={shop}>
      <b className="font-semibold text-bad">
        {t.rich('ladder.more', { pct: x.unitChangePct, unit: unitName(x.unit), n })}
      </b>
      {' · '}
      <Num>{`${x.smallerValue}→${x.largerValue}`}</Num> {unitName(x.unit)}
      {x.smallerOnSale && ` · ${t('ladder.onSale')}`}
    </ItemRow>
  );
}

// ---- Discounts ------------------------------------------------------------------------------

function PromoCard({ focus, order }: { focus: string; order: string[] }) {
  const t = useTranslations('insights');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  const { api } = useAuth();
  const promos = useQueries({
    queries: order.map((s) => ({
      queryKey: ['promotions', 'insights', s],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api!.get('/api/v1/promotions', { query: { retailer: [s], limit: PROMOS_ASKED }, signal }),
      enabled: !!api,
    })),
  });
  const priced = useQueries({ queries: order.map((s) => pricedOptions(api, s)) });

  const shop = (i: number) => {
    const s = order[i]!;
    const env = promos[i]?.data;
    const r = env?.data?.retailers.find((x) => x.retailer === s);
    const p = priced[i]?.data?.data?.total;
    const pct = r && listable(r) && p !== undefined ? sharePct(r.onPromo, p) : null;
    // Why a shop has no discount count: still loading, not collected, no original price seen,
    // or the API's own reason (a blocked shop is blocked, not "no original prices").
    const why = r?.reason ?? env?.reason ?? null;
    const note: ReactNode = !env ? (
      '–'
    ) : r && listable(r) ? null : notCollected(why) ? (
      t('promo.notCollected')
    ) : r && r.n === 0 && (r.reason === null || r.reason === 'retailer_partial') ? (
      t('promo.noOriginal')
    ) : (
      <Known t={tr} v={why ?? 'field_not_collected'} />
    );
    return { s, env, r: note === null ? r : undefined, priced: p, pct, note };
  };
  const shops = order.map((_, i) => shop(i));
  const own = shops[0]!;

  const chart: ChartRow[] = shops.map((x) =>
    x.note !== null || !x.r
      ? { id: x.s, value: null, note: x.note }
      : x.pct === null || x.priced === undefined
        ? {
            id: x.s,
            value: null,
            note: t.rich('promo.count', { count: x.r.onPromo, num: formatCount(x.r.onPromo, locale), n }),
          }
        : {
            id: x.s,
            value: Number(x.pct),
            text: t.rich('promo.bar', {
              pct: x.pct,
              num: formatCount(x.r.onPromo, locale),
              priced: formatCount(x.priced, locale),
              n,
            }),
          },
  );
  const items = own.r && own.env?.data ? oncePerName(listedItems(own.env.data).items) : [];
  const deepest = items.filter((i) => i.retailer === focus).slice(0, CARD_ITEMS.promo);

  return (
    <IdeaCard
      id="ins-promo"
      title={t('promo.title')}
      tip={t('promo.tip')}
      big={own.r ? <Num>{formatCount(own.r.onPromo, locale)}</Num> : '–'}
      unit={t('promo.unit', { shop: name(focus) })}
      sentence={
        !own.r
          ? own.note
          : own.pct !== null && own.priced !== undefined
            ? t.rich('promo.sentence', { pct: own.pct, priced: formatCount(own.priced, locale), n })
            : t('promo.sentenceCount')
      }
      chart={<Bars rows={chart} />}
      more={
        own.r &&
        own.r.onPromo > 0 && (
          <Link href={promotionsHref(locale, { retailer: focus })} className={LINK}>
            {t('promo.see', { num: formatCount(own.r.onPromo, locale) })}
          </Link>
        )
      }
    >
      {deepest.length > 0 ? (
        <>
          <ListHead label={t('promo.deepest')}>
            {t.rich('promo.depth', { pct: deepest[0]!.depthPct, n })}
          </ListHead>
          <ul className="grid gap-2.5">
            {deepest.map((i) => (
              <ItemRow key={i.id} item={i} shop={focus}>
                <b className="font-semibold text-ink">
                  <Money m={i.price} locale={locale} />
                </b>{' '}
                {t('promo.was', { price: moneyText(i.regular, locale) })}
                {' · '}
                <b className="font-semibold text-good">{t.rich('promo.depth', { pct: i.depthPct, n })}</b>
              </ItemRow>
            ))}
          </ul>
        </>
      ) : (
        own.r && <p className="mt-4 text-sm text-ink-2">{t('promo.none')}</p>
      )}
    </IdeaCard>
  );
}
