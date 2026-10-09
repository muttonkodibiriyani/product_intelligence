'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { CaveatView, Envelope, Schemas } from '@/lib/api/types';
import { parseCompare, toCompareSearch } from '@/lib/compare';
import { parseState, toSearch } from '@/lib/explore';
import { parseLaunches, toLaunchesSearch } from '@/lib/launches';
import { parsePromotions, toPromotionsSearch } from '@/lib/promotions';
import { formatCount, formatDate, loc } from '@/lib/format';
import { columns, sourceFields, whyMissing, type OfferField, type Why } from '@/lib/product-detail';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import type { BackTo } from '../explore/product-table';
import { Card } from '../ui/card';
import { productHref, Size } from '../explore/product-table';
import { RowThumb } from '../explore/row-thumb';
import { Known } from '../ui/known';
import { Price } from '../ui/money';
import { MatchReviewLabel } from '../ui/product-card';
import { GapView, MatchLabel } from '../ui/pair';
import { Loading, Skeleton } from '../ui/skeleton';
import { useMeta, useRetailerName } from '../use-meta';
import { importedOn } from '../widgets/model';
import { HistoryChart } from './history-chart';
import { CatalogueGallery } from './catalogue-gallery';
import { offerPriceDate, ULTA_RETAILER, UltaOfferPriceDate } from './offer-price-date';
import { sourceObservationDate } from '../ui/as-of';

/** The contract's product id pattern; anything else is not sent to the API. */
const PRODUCT_ID = /^[A-Za-z0-9._:-]{1,200}$/;

/** Only a plain web link from a retailer page is made clickable; it opens without a referrer. */
export function safeHttpUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null;
  } catch {
    return null;
  }
}

/** Each list that links here, rebuilt from its own parsed state so Back is never a free URL. */
const BACKS: Record<
  BackTo | 'explore',
  { path: string; search: (sp: URLSearchParams) => string; label: string }
> = {
  explore: { path: 'explore', search: (sp) => toSearch(parseState(sp)), label: 'back' },
  compare: { path: 'compare', search: (sp) => toCompareSearch(parseCompare(sp)), label: 'backCompare' },
  overlap: {
    path: 'compare/overlap',
    search: (sp) => toCompareSearch(parseCompare(sp)),
    label: 'backOverlap',
  },
  promotions: {
    path: 'promotions',
    search: (sp) => toPromotionsSearch(parsePromotions(sp)),
    label: 'backPromotions',
  },
  launches: { path: 'launches', search: (sp) => toLaunchesSearch(parseLaunches(sp)), label: 'backLaunches' },
};

export function ProductView() {
  const t = useTranslations('product');
  const locale = useLocale();
  const sp = useSearchParams();
  const { api } = useAuth();
  const name = useRetailerName();
  const id = sp.get('id') ?? '';
  const valid = PRODUCT_ID.test(id);
  // Only the list's own filters are carried back, rebuilt from parsed state: never a free URL.
  const from = new URLSearchParams(sp.get('from') ?? '');
  const backTo = sp.get('back') ?? '';
  const to = Object.hasOwn(BACKS, backTo) ? BACKS[backTo as BackTo] : BACKS.explore;
  const back = `/${locale}/${to.path}/${to.search(from)}`;

  const q = useQuery({
    queryKey: ['product', id],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/products/{product_id}', { params: { product_id: id }, signal }),
    enabled: !!api && valid,
  });

  const backLink = (
    <Link href={back} className="text-sm text-accent hover:underline focus-visible:outline-2">
      <span aria-hidden>{locale === 'ar' ? '→ ' : '← '}</span>
      {t(to.label)}
    </Link>
  );

  if (!valid)
    return (
      <div className="space-y-3">
        {backLink}
        <p className="text-ink-2">{t('missingId')}</p>
      </div>
    );
  if (q.isError)
    return (
      <div className="space-y-3">
        {backLink}
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      </div>
    );
  if (!q.data)
    return (
      <div className="space-y-3">
        {backLink}
        <Loading>{t('loading')}</Loading>
      </div>
    );

  const env = q.data as Envelope<Schemas['ProductDetail']>;
  const d = env.data;
  return (
    <article aria-labelledby="product-title" className="space-y-6">
      <div className="space-y-3">
        {backLink}
        {d && (
          <header className="flex items-start gap-4">
            <RowThumb
              url={d.card.image}
              label={t('noImage')}
              px={96}
              cls="size-24 shrink-0 rounded-card border border-line-2 bg-surface"
            />
            <div className="min-w-0">
              {/* bdi isolates the text's own direction but keeps the block on the page's side. */}
              <p className="text-[13px] font-bold tracking-wide text-ink-2 uppercase">
                <Link
                  href={`/${locale}/explore/${toSearch({ ...parseState(new URLSearchParams()), brand: [d.card.brand] })}`}
                  className="hover:text-accent hover:underline focus-visible:outline-2"
                >
                  <bdi>{d.card.brand}</bdi>
                </Link>
              </p>
              <h1 id="product-title" className="mt-1 text-[28px] leading-tight font-bold tracking-tight">
                <bdi>{d.card.name}</bdi>
              </h1>
              <MatchReviewLabel review={d.card.matchReview} className="mt-2" />
              <dl className="mt-3 flex flex-wrap gap-2 text-sm">
                <Fact k={t('size')}>
                  {d.card.size || d.card.sizeLabel ? (
                    <OfferSize o={d.card} />
                  ) : (
                    <span className="text-ink-2">{t('state.notPublished')}</span>
                  )}
                </Fact>
                <Fact k={t('category')}>
                  {d.card.category.length > 0 ? (
                    <span dir="auto">{d.card.category.join(' › ')}</span>
                  ) : (
                    <span className="text-ink-2">{t('state.notPublished')}</span>
                  )}
                </Fact>
                <Fact k={t('productId')}>
                  <bdi dir="ltr" className="font-mono text-xs">
                    {d.card.id}
                  </bdi>
                </Fact>
              </dl>
            </div>
          </header>
        )}
      </div>

      {d && (
        <>
          {/* An imported offer has no capture date, so the heading only dates collected offers. */}
          <Section
            title={
              d.offers.some((o) => importedOn(env.caveats, o.retailer))
                ? t('offersUndated')
                : t('offers', { date: formatDate(env.meta.cutoff, locale) })
            }
          >
            <Offers
              offers={d.offers}
              name={name}
              caveats={env.caveats}
              backTo={backTo !== 'explore' && Object.hasOwn(BACKS, backTo) ? (backTo as BackTo) : undefined}
              from={sp.get('from') ?? ''}
            />
          </Section>
          {[...new Set(d.offers.filter((o) => o.retailer === 'ulta_ae' && o.sku).map((o) => o.sku!))].map(
            (sku) => (
              <CatalogueGallery key={sku} sku={sku} />
            ),
          )}
          {d.pairs.length > 0 && (
            <Section title={t('pairs')} hint={t('pairsHint')}>
              <Pairs pairs={d.pairs} name={name} />
            </Section>
          )}
          {d.card.matches.length > 0 && (
            <Section title={t('matches')}>
              <Matches matches={d.card.matches} name={name} />
            </Section>
          )}
          <Section title={t('history')}>
            <History id={id} name={name} />
          </Section>
        </>
      )}
    </article>
  );
}

function Fact({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex gap-1.5 rounded-full bg-surface-2 px-3 py-1">
      <dt className="text-ink-2">{k}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <Card title={title} question={hint} flush>
      {children}
    </Card>
  );
}

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-top';

type Offer = Schemas['OfferView'];

/**
 * One attribute of an offer: its label, the field whose absence `whyMissing` explains, and how a
 * present value reads. Adding an attribute is one entry here.
 */
interface Row {
  id: string;
  label: string;
  field?: OfferField;
  value: (o: Offer) => ReactNode;
}

/**
 * Every attribute the API serves for the offers, retailers side by side: one column per offer,
 * one row per attribute. A missing value says why (not published, not measured), never 0 or blank.
 */
function Offers({
  offers,
  name,
  caveats,
  backTo,
  from,
}: {
  offers: Offer[];
  name: (id: string) => string;
  caveats: readonly CaveatView[];
  /** The list this page was opened from, carried to another size's page. */
  backTo: BackTo | undefined;
  from: string;
}) {
  const t = useTranslations('product');
  const ta = useTranslations('availability');
  const tc = useTranslations('channel');
  const locale = useLocale();
  const meta = useMeta().data?.data;
  const caps = meta?.capabilities;
  const sources = meta?.sources;
  const ultaSourceDate = sourceObservationDate(meta, ULTA_RETAILER);
  if (offers.length === 0) return <p className="px-5 pb-3 text-ink-2">{t('noOffers')}</p>;
  const ctx = (o: Offer) => meta?.contexts.find((c) => c.id === o.context);

  const groups: { id: string; title: string; rows: Row[] }[] = [
    {
      id: 'price',
      title: t('groupPrice'),
      rows: [
        {
          id: 'price',
          label: t('price'),
          field: 'price',
          value: (o) => <Price of={o} locale={locale} />,
        },
        {
          id: 'regular',
          label: t('regular'),
          field: 'regular',
          value: (o) => <Price of={{ price: o.regular }} locale={locale} />,
        },
        // Never filled yet: the row says the member price is not collected, not that there is none.
        { id: 'member', label: t('member'), field: 'member', value: () => null },
        {
          id: 'promo',
          label: t('promo'),
          field: 'promo',
          value: (o) => <bdi dir="ltr" className="tabular-nums">{`${o.promoPct}%`}</bdi>,
        },
      ],
    },
    {
      id: 'listing',
      title: t('groupListing'),
      rows: [
        {
          id: 'availability',
          label: t('availability'),
          field: 'availability',
          value: (o) => <Known t={ta} v={o.availability!} />,
        },
        {
          id: 'rating',
          label: t('rating'),
          field: 'rating',
          value: ({ rating: r }) => (
            <>
              <span className="tabular-nums">
                {t('ratingValue', { average: r!.average, scale: r!.scale })}
              </span>
              <span className="block text-xs text-ink-2">
                {t('ratingCount', { count: r!.count, n: formatCount(r!.count, locale) })}
              </span>
            </>
          ),
        },
        { id: 'size', label: t('size'), field: 'size', value: (o) => <OfferSize o={o} /> },
        {
          id: 'shades',
          label: t('shades'),
          field: 'shades',
          value: (o) => <span className="tabular-nums">{formatCount(o.shadeCount!, locale)}</span>,
        },
        {
          id: 'sku',
          label: t('sku'),
          field: 'sku',
          value: (o) => (
            <bdi dir="ltr" className="font-mono text-xs break-all">
              {o.sku}
            </bdi>
          ),
        },
        {
          id: 'channel',
          label: t('channel'),
          value: (o) => {
            const where = loc(ctx(o)?.location?.label, locale);
            return (
              <>
                <Known t={tc} v={o.channel} />
                {where && (
                  <span dir="auto" className="block text-xs text-ink-2">
                    {where}
                  </span>
                )}
              </>
            );
          },
        },
      ],
    },
    {
      id: 'content',
      title: t('groupContent'),
      rows: [
        { id: 'images', label: t('images'), field: 'images', value: (o) => <Gallery o={o} /> },
        { id: 'variants', label: t('variants'), field: 'variants', value: (o) => <Variants o={o} /> },
        {
          id: 'otherSizes',
          label: t('otherSizes'),
          field: 'otherSizes',
          value: (o) => <OtherSizes o={o} back={backTo} from={from} />,
        },
      ],
    },
    {
      id: 'evidence',
      title: t('evidence'),
      rows: [
        {
          id: 'evidence',
          label: t('lastSeen'),
          value: (o) => (
            <>
              {/* This row is always rendered, including when the latest-day price is null. */}
              <UltaOfferPriceDate offer={o} sourceDate={ultaSourceDate} retailerName={name(o.retailer)} />
              <Evidence
                o={o}
                name={name}
                importedAt={importedOn(caveats, o.retailer)}
                ultaPriceDate={offerPriceDate(o, ultaSourceDate)}
              />
            </>
          ),
        },
      ],
    },
  ];

  const cols = columns(offers);
  return (
    <div className="relative overflow-x-auto px-2">
      <table className="w-full table-fixed text-sm" data-offer-sheet>
        <caption className="sr-only">{t('sheetCaption')}</caption>
        <colgroup>
          <col className="w-28 sm:w-44" />
          {/* Chromium honours a col's min-width in a fixed table (Firefox and WebKit don't): on a
              390px phone, 112 + 2 × 112 fits; 2 × 128 overflowed by 28px. */}
          {cols.map(({ offer: o }) => (
            <col key={o.context} className="min-w-28 sm:min-w-32" />
          ))}
        </colgroup>
        <thead className="border-b border-line">
          <tr>
            <td />
            {cols.map(({ offer: o, multi }) => (
              <th key={o.context} scope="col" className={`${TH} text-start align-bottom`}>
                <span className="whitespace-normal">{name(o.retailer)}</span>
                {multi && (
                  <span dir="auto" className="block text-xs font-normal text-ink-2">
                    {loc(ctx(o)?.label, locale) || o.context}
                  </span>
                )}
                {o.early && (
                  <span className="mt-0.5 block text-xs font-normal whitespace-normal text-warn">
                    {t('early')}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        {groups.map((g) => (
          <tbody key={g.id} className="border-t border-line first-of-type:border-t-0">
            <tr>
              <th
                scope="colgroup"
                colSpan={cols.length + 1}
                className="px-3 pt-4 pb-1 text-start text-xs font-semibold tracking-wide text-ink-2 uppercase"
              >
                {g.title}
              </th>
            </tr>
            {g.rows.map((r) => (
              <tr key={r.id} data-attr={r.id} className="border-t border-line-2 first:border-t-0">
                <th scope="row" className={`${TD} text-start font-normal text-ink-2`}>
                  {r.label}
                </th>
                {cols.map(({ offer: o }) => {
                  const why =
                    r.field && whyMissing(r.field, o, caveats, caps, sourceFields(sources, o.retailer));
                  return (
                    <td key={o.context} className={`${TD} break-words`}>
                      {why ? <Missing why={why} /> : r.value(o)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

/** "Not published" and, under it, why: a missing value's cell. */
function Missing({ why }: { why: Why }) {
  const t = useTranslations('product');
  return (
    <span className="block text-ink-2" data-missing={why.reason}>
      {t(`state.${why.state}`)}
      <span className="block text-xs">{t(`why.${why.reason}`)}</span>
    </span>
  );
}

/** The measured size, or the retailer's own label ("M", in its system) when that is all there is. */
function OfferSize({
  o,
}: {
  o: { size: Offer['size']; sizeLabel?: string | null; sizeSystem?: string | null };
}) {
  return (
    <>
      {o.size && <Size size={o.size} />}
      {o.sizeLabel && (
        <span className={o.size ? 'block text-xs text-ink-2' : undefined}>
          <bdi>{o.sizeLabel}</bdi>
          {o.sizeSystem && (
            <>
              {' '}
              <bdi className="text-ink-2">({o.sizeSystem})</bdi>
            </>
          )}
        </span>
      )}
    </>
  );
}

/** At most this many pictures in a cell; the count says how many the page has. */
const GALLERY_MAX = 4;

/** The offer's own gallery as the retailer page (or its catalogue) lists it, in its order. */
function Gallery({ o }: { o: Offer }) {
  const t = useTranslations('product');
  const locale = useLocale();
  const { items, source } = o.content.images;
  return (
    <>
      <span className="flex flex-wrap gap-1.5">
        {items.slice(0, GALLERY_MAX).map((img, i) => (
          <RowThumb
            key={img.url}
            url={img.url}
            label={t('imageN', { n: i + 1 })}
            cls="size-12 rounded-ctl border border-line-2 bg-surface"
          />
        ))}
      </span>
      <span className="mt-1 block text-xs text-ink-2">
        {t('imageCount', { count: items.length, n: formatCount(items.length, locale) })}
        {source && (
          <>
            {' · '}
            <Known t={t} k="imageSource" v={source} />
          </>
        )}
      </span>
    </>
  );
}

/** The retailer's own listings grouped into the offer (its shades), each as the page states it. */
function Variants({ o }: { o: Offer }) {
  const t = useTranslations('product');
  const locale = useLocale();
  const items = o.content.variants.items;
  return (
    <details>
      <summary className="cursor-pointer text-accent">
        {t('variantCount', { count: items.length, n: formatCount(items.length, locale) })}
      </summary>
      <ul className="mt-1 space-y-1">
        {items.map((v) => (
          <li key={v.sku} data-variant>
            {v.shade.state === 'observed' ? (
              <bdi>{v.shade.text}</bdi>
            ) : (
              <span className="text-ink-2">
                <Known t={t} k="content" v={v.shade.state} />
              </span>
            )}
            <bdi dir="ltr" className="block font-mono text-xs break-all text-ink-2">
              {v.sku}
              {v.gtin.state === 'observed' && v.gtin.barcode && ` · ${v.gtin.barcode}`}
            </bdi>
            {!(v.gtin.state === 'observed' && v.gtin.barcode) && (
              <span data-gtin-state={v.gtin.state} className="block text-xs text-ink-3">
                {t('gtinAbsent')}:{' '}
                {v.gtin.state === 'observed' ? (
                  t('gtinUnreadable')
                ) : (
                  <Known t={t} k="content" v={v.gtin.state} />
                )}
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * This retailer's other sizes of the same item, from its own product family: links to those
 * products, never a claim that another retailer's size is the same item.
 */
function OtherSizes({ o, back, from }: { o: Offer; back: BackTo | undefined; from: string }) {
  const locale = useLocale();
  return (
    <ul className="space-y-1">
      {o.content.sizes.map((s) => (
        <li key={s.productId}>
          <Link
            href={productHref(locale, s.productId, from, back)}
            className="text-accent hover:underline focus-visible:outline-2"
          >
            {s.size || s.sizeLabel ? (
              <OfferSize o={s} />
            ) : (
              <bdi dir="ltr" className="font-mono text-xs break-all">
                {s.productId}
              </bdi>
            )}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** When the offer was seen (or imported, with no capture date), and the page it was seen on. */
function Evidence({
  o,
  name,
  importedAt,
  ultaPriceDate,
}: {
  o: Offer;
  name: (id: string) => string;
  importedAt: string | null;
  ultaPriceDate: ReturnType<typeof offerPriceDate>;
}) {
  const t = useTranslations('product');
  const locale = useLocale();
  const url = safeHttpUrl(o.evidence.url);
  return (
    <>
      {/* Ulta's offer-level import day wins over its source-wide latest-import caveat. */}
      {ultaPriceDate ? (
        ultaPriceDate.date ? (
          <time dateTime={ultaPriceDate.date} className="block break-words text-xs text-ink-2">
            {t('imported', { date: formatDate(ultaPriceDate.date, locale) })}
          </time>
        ) : (
          <span className="block break-words text-xs font-semibold text-warn">
            {t('importDateUnavailable')}
          </span>
        )
      ) : importedAt ? (
        <time dateTime={importedAt} className="block text-xs text-ink-2">
          {t('imported', { date: formatDate(importedAt, locale) })}
        </time>
      ) : (
        <time dateTime={o.evidence.capturedAt} className="block text-xs text-ink-2">
          {t('captured', { date: formatDate(o.evidence.capturedAt, locale, true) })}
        </time>
      )}
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          referrerPolicy="no-referrer"
          className="text-accent hover:underline focus-visible:outline-2"
        >
          {t('source')}
          <span className="sr-only"> ({name(o.retailer)})</span>
        </a>
      ) : (
        <span className="text-xs text-ink-2">{t('noSource')}</span>
      )}
    </>
  );
}

function Pairs({ pairs, name }: { pairs: Schemas['PairGap'][]; name: (id: string) => string }) {
  const t = useTranslations('product');
  return (
    <div className="relative overflow-x-auto px-2">
      <table className="w-full max-w-3xl text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${TH} text-start`}>
              {t('pairBase')}
            </th>
            <th scope="col" className={`${TH} text-start`}>
              {t('pairOther')}
            </th>
            <th scope="col" className={`${TH} text-start`}>
              {t('pairGap')}
            </th>
          </tr>
        </thead>
        <tbody>
          {pairs.map((p) => (
            <tr key={`${p.base}-${p.other}`} className="border-t border-line first:border-t-0">
              <td className={`${TD} whitespace-nowrap`}>{name(p.base)}</td>
              <td className={`${TD} whitespace-nowrap`}>{name(p.other)}</td>
              <td className={TD}>
                <GapView pair={p} name={name} />
                {p.sizeLabels && (
                  <span className="mt-0.5 block text-xs text-ink-2">
                    {t('pairSizes', { base: p.sizeLabels[0], other: p.sizeLabels[1] })}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Matches({ matches, name }: { matches: Schemas['CardMatch'][]; name: (id: string) => string }) {
  const t = useTranslations('product');
  const tm = useTranslations('match');
  return (
    <div className="relative overflow-x-auto px-2">
      <table className="w-full max-w-3xl text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${TH} text-start`}>
              {t('retailer')}
            </th>
            <th scope="col" className={`${TH} text-start`}>
              {t('matchClass')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {t('matchConfidence')}
            </th>
          </tr>
        </thead>
        <tbody>
          {matches.map((m) => (
            <tr key={`${m.a}-${m.b}`} className="border-t border-line first:border-t-0">
              <td className={`${TD} whitespace-nowrap`}>{tm('between', { a: name(m.a), b: name(m.b) })}</td>
              <td className={TD}>
                <MatchLabel m={m} />
              </td>
              <td className={`${TD} text-end tabular-nums`}>
                {m.confidence ?? <span className="text-ink-2">{t('state.notMeasured')}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function History({ id, name }: { id: string; name: (id: string) => string }) {
  const t = useTranslations('product');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['history', id],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/products/{product_id}/history', { params: { product_id: id }, signal }),
    enabled: !!api,
  });
  if (q.isError) return <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data)
    return (
      <div aria-busy>
        <Skeleton kind="chart" />
        <p role="status" className="mt-3 text-sm text-ink-2">
          {t('historyLoading')}
        </p>
      </div>
    );
  const env = q.data;
  if (!env.data)
    return (
      <p className="text-ink-2">
        {(env.reason && (loc(env.detail, locale) || <Known t={tr} v={env.reason} />)) || t('historyEmpty')}
      </p>
    );
  return <HistoryChart series={env.data.series} name={name} />;
}
