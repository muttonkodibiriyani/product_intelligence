'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Envelope, Schemas } from '@/lib/api/types';
import { parseCompare, toCompareSearch } from '@/lib/compare';
import { parseState, toSearch } from '@/lib/explore';
import { parseLaunches, toLaunchesSearch } from '@/lib/launches';
import { parsePromotions, toPromotionsSearch } from '@/lib/promotions';
import { formatCount, formatDate, loc } from '@/lib/format';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import type { BackTo } from '../explore/product-table';
import { EnvNotes } from '../ui/env-notes';
import { Size } from '../explore/product-table';
import { Known } from '../ui/known';
import { Money } from '../ui/money';
import { GapView, MatchLabel } from '../ui/pair';
import { useMeta, useRetailerName } from '../use-meta';
import { HistoryChart } from './history-chart';

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
        <p role="status" aria-busy className="text-ink-2">
          {t('loading')}
        </p>
      </div>
    );

  const env = q.data as Envelope<Schemas['ProductDetail']>;
  const d = env.data;
  return (
    <article aria-labelledby="product-title" className="space-y-8">
      <div className="space-y-3">
        {backLink}
        <EnvNotes env={env} />
        {d && (
          <header>
            {/* bdi isolates the text's own direction but keeps the block on the page's side. */}
            <p className="text-sm text-ink-2">
              <bdi>{d.card.brand}</bdi>
            </p>
            <h1 id="product-title" className="text-2xl font-semibold">
              <bdi>{d.card.name}</bdi>
            </h1>
            <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              {d.card.size && (
                <Fact k={t('size')}>
                  <Size size={d.card.size} />
                </Fact>
              )}
              {d.card.category.length > 0 && (
                <Fact k={t('category')}>
                  <span dir="auto">{d.card.category.join(' › ')}</span>
                </Fact>
              )}
            </dl>
          </header>
        )}
      </div>

      {d && (
        <>
          <Section title={t('offers', { date: formatDate(env.meta.cutoff, locale) })}>
            <Offers offers={d.offers} name={name} />
          </Section>
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
    <div className="flex gap-2">
      <dt className="text-ink-2">{k}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-base font-semibold">{title}</h2>
      {hint && <p className="mt-1 text-sm text-ink-2">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

const TH = 'px-3 py-2 font-medium text-ink-2 whitespace-nowrap';
const TD = 'px-3 py-2 align-top';

/** One row per retailer. Columns the dataset doesn't collect (per /meta) are left out, not zeroed. */
function Offers({ offers, name }: { offers: Schemas['OfferView'][]; name: (id: string) => string }) {
  const t = useTranslations('product');
  const ta = useTranslations('availability');
  const locale = useLocale();
  const caps = useMeta().data?.data?.capabilities;
  const show = { ratings: caps?.ratings ?? true, shades: caps?.shades ?? true, stock: caps?.stock ?? true };
  if (offers.length === 0) return <p className="text-ink-2">{t('noOffers')}</p>;
  return (
    <div className="relative overflow-x-auto rounded border border-line bg-surface">
      <table className="w-full text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${TH} text-start`}>
              {t('retailer')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {t('price')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {t('regular')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {t('promo')}
            </th>
            {show.stock && (
              <th scope="col" className={`${TH} text-start`}>
                {t('availability')}
              </th>
            )}
            {show.ratings && (
              <th scope="col" className={`${TH} text-start`}>
                {t('rating')}
              </th>
            )}
            <th scope="col" className={`${TH} text-start`}>
              {t('size')}
            </th>
            {show.shades && (
              <th scope="col" className={`${TH} text-end`}>
                {t('shades')}
              </th>
            )}
            <th scope="col" className={`${TH} text-start`}>
              {t('sku')}
            </th>
            <th scope="col" className={`${TH} text-start`}>
              {t('evidence')}
            </th>
          </tr>
        </thead>
        <tbody>
          {offers.map((o) => {
            const url = safeHttpUrl(o.evidence.url);
            return (
              <tr key={o.retailer} className="border-t border-line first:border-t-0">
                <th scope="row" className={`${TD} text-start font-medium whitespace-nowrap`}>
                  {name(o.retailer)}
                  {o.early && (
                    <span className="mt-0.5 block text-xs font-normal text-warn">{t('early')}</span>
                  )}
                </th>
                <td className={`${TD} text-end`}>
                  {o.price ? <Money m={o.price} locale={locale} /> : <Dash />}
                </td>
                <td className={`${TD} text-end`}>
                  {o.regular ? <Money m={o.regular} locale={locale} /> : <Dash />}
                </td>
                <td className={`${TD} text-end`}>
                  {o.promoPct ? <bdi dir="ltr" className="tabular-nums">{`${o.promoPct}%`}</bdi> : <Dash />}
                </td>
                {show.stock && (
                  <td className={TD}>{o.availability ? <Known t={ta} v={o.availability} /> : <Dash />}</td>
                )}
                {show.ratings && (
                  <td className={`${TD} whitespace-nowrap`}>
                    {o.rating ? (
                      <>
                        <span className="tabular-nums">
                          {t('ratingValue', { average: o.rating.average, scale: o.rating.scale })}
                        </span>
                        <span className="block text-xs text-ink-2">
                          {t('ratingCount', {
                            count: o.rating.count,
                            n: formatCount(o.rating.count, locale),
                          })}
                        </span>
                      </>
                    ) : (
                      <Dash />
                    )}
                  </td>
                )}
                <td className={`${TD} whitespace-nowrap`}>{o.size ? <Size size={o.size} /> : <Dash />}</td>
                {show.shades && <td className={`${TD} text-end tabular-nums`}>{o.shadeCount ?? <Dash />}</td>}
                <td className={TD}>
                  {o.sku ? (
                    <bdi dir="ltr" className="font-mono text-xs">
                      {o.sku}
                    </bdi>
                  ) : (
                    <Dash />
                  )}
                </td>
                <td className={`${TD} whitespace-nowrap`}>
                  <time dateTime={o.evidence.capturedAt} className="block text-xs text-ink-2">
                    {t('captured', { date: formatDate(o.evidence.capturedAt, locale, true) })}
                  </time>
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
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Pairs({ pairs, name }: { pairs: Schemas['PairGap'][]; name: (id: string) => string }) {
  const t = useTranslations('product');
  return (
    <div className="relative overflow-x-auto rounded border border-line bg-surface">
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
    <div className="relative overflow-x-auto rounded border border-line bg-surface">
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
              <td className={`${TD} text-end tabular-nums`}>{m.confidence ?? <Dash />}</td>
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
      <p role="status" aria-busy className="text-ink-2">
        {t('historyLoading')}
      </p>
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

function Dash() {
  return <span className="text-ink-2">–</span>;
}
