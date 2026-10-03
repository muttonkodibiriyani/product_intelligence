'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { CSSProperties, ReactNode } from 'react';
import type { Summary } from '@/lib/api/summary';
import type { CaveatView, Money as MoneyValue } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import { isValidPrice } from '@/lib/money';
import { navHref } from '@/lib/nav';
import { CountUp } from '../ui/count-up';
import { Known } from '../ui/known';
import { Money } from '../ui/money';
import { RetailerDot, retailerColor } from '../ui/retailer-dot';
import { Tip } from '../ui/tip';
import type { RetailerSummary } from '../widgets/kpis';
import {
  exploreHref,
  freshness,
  hasParents,
  importedOn,
  pct,
  promotions,
  promotionsHref,
} from '../widgets/model';
import { depthBands, share } from './model';
import type { ShopLaunches, ShopPromo } from './use-overview-data';

/*
 * The band at the top of the Overview: one catalogue tile per shop (products, brands,
 * categories, median, share on promotion, freshness), then promotions and launches across the
 * shops. Numbers, bars and chips do the talking; a caveat, a count behind a bar or an exact value
 * sits in a tooltip. Every figure is the API's own, a withheld one a chip, never 0. A tile opens
 * the list it counts.
 */
export function Band({
  rows,
  promo,
  launches,
}: {
  rows: readonly RetailerSummary[];
  promo: { shares: ReadonlyMap<string, ShopPromo>; loading: boolean };
  launches: readonly ShopLaunches[];
}) {
  const max = {
    brands: Math.max(0, ...rows.map((r) => r.data.brands ?? 0)),
    categories: Math.max(0, ...rows.map((r) => r.data.categories ?? 0)),
    median: Math.max(0, ...rows.map((r) => (r.data.medianPrice ? r.data.medianPrice.minor : 0))),
    promo: Math.max(0, ...rows.map((r) => Number(r.data.promoSharePct) || 0)),
  };
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {rows.map((r, i) => (
        <ShopTile key={r.retailer} row={r} index={i} max={max} />
      ))}
      <PromoTile rows={rows} promo={promo} />
      <LaunchTile rows={rows} launches={launches} />
    </ul>
  );
}

const side = (i: number): 0 | 1 => (i === 0 ? 0 : 1);

/** A tile: a shop's colour as its top rule, a lift on hover, and the head link covering it. */
function Tile({ id, color, children }: { id: string; color?: string; children: ReactNode }) {
  const style: CSSProperties | undefined = color ? { borderTopColor: color, borderTopWidth: 3 } : undefined;
  return (
    <li data-tile={id} style={style} className="panel lift flex min-w-0 flex-col gap-3 px-4 pt-3 pb-3.5">
      {children}
    </li>
  );
}

/** The tile's head: a dot, the name as the link that covers the tile, and a chip at the end. */
function Head({
  href,
  dot,
  chip,
  children,
}: {
  href: string;
  dot?: ReactNode;
  chip?: ReactNode;
  children: ReactNode;
}) {
  return (
    <p className="flex min-w-0 items-center gap-1.5 text-[13px] font-semibold">
      {dot}
      <Link
        href={href}
        className="min-w-0 truncate after:absolute after:inset-0 hover:underline focus-visible:outline-2"
      >
        {children}
      </Link>
      {chip && <span className="relative z-10 ms-auto shrink-0">{chip}</span>}
    </p>
  );
}

/** A short state chip ("Not measured", "Not yet") whose reason lives in its tooltip. */
function Chip({
  tip,
  tone = 'bg-surface-2 text-ink-2',
  children,
}: {
  tip: ReactNode;
  tone?: string;
  children: ReactNode;
}) {
  return (
    <Tip text={tip} at="end" className="relative z-10">
      <span className={`pill ${tone}`}>{children}</span>
    </Tip>
  );
}

/** One row of a tile: a label (or a shop), a bar sized against the tile's largest, the value. */
function Row({
  label,
  bar,
  color,
  mid,
  children,
}: {
  label: ReactNode;
  /** 0…100, or null for no bar (nothing to size, or a withheld value). */
  bar?: number | null;
  color?: string;
  /** Replaces the bar: a sparkline, a depth strip. */
  mid?: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <dt className="flex min-w-0 items-center gap-1.5 text-ink-2">{label}</dt>
      <dd className="min-w-0">
        {mid ?? (
          <span aria-hidden className="block h-1.5 overflow-hidden rounded-full bg-line-2">
            {bar !== null && bar !== undefined && bar > 0 && (
              <i
                className="grow block h-full rounded-full"
                style={{ width: `${bar}%`, background: color ?? 'var(--color-ink-3)' }}
              />
            )}
          </span>
        )}
      </dd>
      <dd className="relative z-10 flex justify-end text-end font-medium tabular-nums">{children}</dd>
    </>
  );
}

const Rows = ({ children }: { children: ReactNode }) => (
  <dl className="mt-auto grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-1.5 text-xs">
    {children}
  </dl>
);

/** The freshness chip: the API's status; an imported shop reads as a snapshot with its import date. */
function FreshChip({ data, caveats }: { data: Summary; caveats: readonly CaveatView[] }) {
  const t = useTranslations('widgets.kpi');
  const locale = useLocale();
  const f = freshness(data.freshness);
  const imported =
    f === 'snapshot'
      ? (importedOn(caveats, data.retailer) ?? data.freshness.cutoff)
      : importedOn(caveats, data.retailer);
  const k = imported ? 'snapshot' : f;
  const tone =
    k === 'fresh'
      ? 'bg-mint text-mint-ink'
      : k === 'aging'
        ? 'bg-butter text-butter-ink'
        : k === 'stale'
          ? 'bg-rose text-rose-ink'
          : 'bg-surface-2 text-ink';
  const tip = imported
    ? t('imported', { date: formatDate(imported, locale) })
    : k === 'unknown'
      ? t('unknown')
      : t('asOf', { date: formatDate(data.freshness.cutoff, locale) });
  return (
    <Chip tip={tip} tone={tone}>
      {t(k)}
    </Chip>
  );
}

/** A shop's catalogue: products as the hero, brands, categories, median and promotion share as rows. */
function ShopTile({
  row,
  index,
  max,
}: {
  row: RetailerSummary;
  index: number;
  max: { brands: number; categories: number; median: number; promo: number };
}) {
  const t = useTranslations('home.band');
  const tk = useTranslations('widgets.kpi');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const d = row.data;
  const color = retailerColor(row.retailer, side(index));
  const none = (reason: string) => <Chip tip={<Known t={tr} v={reason} />}>{tk('none')}</Chip>;
  const count = (v: number) => (
    <CountUp to={v} final={formatCount(v, locale)} format={(x) => formatCount(Math.round(x), locale)} />
  );
  const median: MoneyValue | null = d.medianPrice && isValidPrice(d.medianPrice) ? d.medianPrice : null;
  const promo = promotions(d);
  const prices = d.withheld.find((w) => w.section === 'prices')?.reason ?? 'field_not_collected';
  const hero = d.products === null ? none(prices) : count(d.products);
  return (
    <Tile id={`shop:${row.retailer}`} color={color}>
      <Head
        href={exploreHref(locale, { retailer: [row.retailer] })}
        dot={<RetailerDot id={row.retailer} index={side(index)} />}
        chip={<FreshChip data={d} caveats={row.caveats} />}
      >
        {row.name}
      </Head>
      <p className="flex flex-wrap items-baseline gap-x-1.5">
        <span className="text-[28px] leading-none font-semibold tracking-tight tabular-nums">
          {hasParents(row.caveats, row.retailer) ? (
            <Tip text={tk('productsParents')} className="relative z-10">
              <span className="underline decoration-dotted decoration-ink-3 underline-offset-4">{hero}</span>
            </Tip>
          ) : (
            hero
          )}
        </span>
        <span className="text-xs text-ink-2">{t('products')}</span>
      </p>
      <Rows>
        <Row label={t('brands')} bar={d.brands === null ? null : share(d.brands, max.brands)} color={color}>
          {d.brands === null ? none(prices) : count(d.brands)}
        </Row>
        <Row
          label={t('categories')}
          bar={d.categories === null ? null : share(d.categories, max.categories)}
          color={color}
        >
          {d.categories === null ? none(prices) : count(d.categories)}
        </Row>
        <Row label={t('median')} bar={median ? share(median.minor, max.median) : null} color={color}>
          {median ? <Money m={median} locale={locale} /> : none(prices)}
        </Row>
        <Row
          label={t('promo')}
          bar={promo.measured ? share(Number(promo.share), max.promo) : null}
          color={color}
        >
          {promo.measured ? (
            <CountUp
              to={Number(promo.share)}
              final={pct(promo.share, locale)}
              format={(x) => pct(x.toFixed(1), locale)}
            />
          ) : (
            none(promo.reason)
          )}
        </Row>
      </Rows>
    </Tile>
  );
}

/**
 * Promotions across the shops, from /promotions (the share and its counts per shop) and
 * /summary's depth bands: a bar per shop, a stacked strip of how deep the discounts run.
 */
function PromoTile({
  rows,
  promo,
}: {
  rows: readonly RetailerSummary[];
  promo: { shares: ReadonlyMap<string, ShopPromo>; loading: boolean };
}) {
  const t = useTranslations('home.band');
  const tk = useTranslations('widgets.kpi');
  const tp = useTranslations('widgets.promo');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const shops = rows.map((r, i) => {
    const p = promotions(r.data);
    const s = promo.shares.get(r.retailer);
    // The Promotions page's share when it has one; /summary's until then or when it has none.
    const value = s?.share ?? (p.measured ? p.share : null);
    const reason =
      s?.share === null ? (s.reason ?? (p.measured ? null : p.reason)) : p.measured ? null : p.reason;
    return { r, i, p, s, value, reason: value === null ? (reason ?? 'field_not_collected') : null };
  });
  const maxShare = Math.max(0, ...shops.map((x) => Number(x.value) || 0));
  const measured = shops.filter((x) => x.p.measured);
  return (
    <Tile id="promotions">
      <Head href={promotionsHref(locale, {})}>{t('promo')}</Head>
      <Rows>
        {shops.map(({ r, i, value, reason, s }) => (
          <Row
            key={r.retailer}
            label={
              <>
                <RetailerDot id={r.retailer} index={side(i)} />
                <span className="truncate">{r.name}</span>
              </>
            }
            bar={value === null ? null : share(Number(value), maxShare)}
            color={retailerColor(r.retailer, side(i))}
          >
            {value === null ? (
              <Chip tip={<Known t={tr} v={reason!} />}>{tk('none')}</Chip>
            ) : s?.share ? (
              <Tip text={t('promoOf', { onPromo: s.onPromo, n: s.n })} at="end" className="relative z-10">
                <span className="text-sm">
                  <CountUp
                    to={Number(value)}
                    final={pct(value, locale)}
                    format={(x) => pct(x.toFixed(1), locale)}
                  />
                </span>
              </Tip>
            ) : (
              <span className="text-sm">
                <CountUp
                  to={Number(value)}
                  final={pct(value, locale)}
                  format={(x) => pct(x.toFixed(1), locale)}
                />
              </span>
            )}
          </Row>
        ))}
      </Rows>
      {measured.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium text-ink-2">{t('depth')}</p>
          {measured.map(({ r, i, p }) => {
            if (!p.measured) return null;
            const { bands, total } = depthBands(p.depth);
            const color = retailerColor(r.retailer, side(i));
            const tip = (
              <span className="grid gap-0.5">
                <b>{r.name}</b>
                {bands.map((b) => (
                  <span key={b.band}>{t('depthOf', { band: tp('off', { band: b.band }), n: b.n })}</span>
                ))}
              </span>
            );
            return (
              <Tip key={r.retailer} text={tip} className="relative z-10 w-full">
                <span className="flex w-full items-center gap-1.5">
                  <RetailerDot id={r.retailer} index={side(i)} />
                  <span
                    role="img"
                    aria-label={t('depthStrip', { shop: r.name, n: total })}
                    className="grow flex h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-line-2"
                  >
                    {bands.map((b, ci) =>
                      b.n > 0 ? (
                        <i
                          key={b.band}
                          data-band={b.band}
                          className="block h-full"
                          style={{
                            flex: `${b.n} 0 0`,
                            background: color,
                            opacity: 0.35 + (0.65 * ci) / Math.max(1, bands.length - 1),
                          }}
                        />
                      ) : null,
                    )}
                  </span>
                </span>
              </Tip>
            );
          })}
          <p aria-hidden className="flex justify-between ps-3.5 text-[10px] text-ink-3 tabular-nums">
            {measured[0]!.p.measured && measured[0]!.p.depth.bands.map((b) => <span key={b}>{b}</span>)}
          </p>
        </div>
      )}
    </Tile>
  );
}

/**
 * New products in the last 30 days per shop, from /launches: a count and a sparkline of
 * launches per day; a shop without two collection days yet gets a "Not yet" chip, an imported
 * snapshot a "Snapshot" chip, each with its reason in the tooltip.
 */
function LaunchTile({
  rows,
  launches,
}: {
  rows: readonly RetailerSummary[];
  launches: readonly ShopLaunches[];
}) {
  const t = useTranslations('home.band');
  const tl = useTranslations('launches');
  const tk = useTranslations('widgets.kpi');
  const ts = useTranslations('state');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const maxTotal = Math.max(0, ...launches.map((l) => l.total ?? 0));
  const days = launches[0]?.perDay?.length ?? 30;
  return (
    <Tile id="launches">
      <Head
        href={navHref('launches', locale)}
        chip={<span className="text-[11px] font-normal text-ink-3">{t('days', { n: days })}</span>}
      >
        {t('launches')}
      </Head>
      <Rows>
        {rows.map((r, i) => {
          const l = launches.find((x) => x.shop.id === r.retailer);
          const color = retailerColor(r.retailer, side(i));
          const label = (
            <>
              <RetailerDot id={r.retailer} index={side(i)} />
              <span className="truncate">{r.name}</span>
            </>
          );
          if (!l || l.state === 'notReady')
            return (
              <Row key={r.retailer} label={label} bar={null}>
                {l?.shop.kind === 'imported' ? (
                  <Chip tip={tl('imported', { date: l.shop.date ? formatDate(l.shop.date, locale) : '' })}>
                    {tk('snapshot')}
                  </Chip>
                ) : (
                  <Chip tip={`${tl('ofMin', { n: l?.shop.days ?? 0, min: 2 })} · ${tl('notYetWhy')}`}>
                    {t('notYet')}
                  </Chip>
                )}
              </Row>
            );
          if (l.state === 'loading')
            return (
              <Row key={r.retailer} label={label} bar={null}>
                <span className="skeleton inline-block h-4 w-8" aria-hidden />
              </Row>
            );
          if (l.state === 'error' || l.total === null)
            return (
              <Row key={r.retailer} label={label} bar={null}>
                <Chip tip={l.env?.reason ? <Known t={tr} v={l.env.reason} /> : ts('notAvailable')}>
                  {ts('notAvailable')}
                </Chip>
              </Row>
            );
          return (
            <Row
              key={r.retailer}
              label={label}
              bar={l.perDay ? undefined : share(l.total, maxTotal)}
              color={color}
              mid={
                l.perDay ? (
                  <Sparkline days={l.perDay} color={color} label={t('spark', { shop: r.name, n: l.total })} />
                ) : undefined
              }
            >
              <span className="text-sm">
                <CountUp
                  to={l.total}
                  final={formatCount(l.total, locale)}
                  format={(x) => formatCount(Math.round(x), locale)}
                />
              </span>
            </Row>
          );
        })}
      </Rows>
    </Tile>
  );
}

/** Launches per day as a row of thin bars, the tallest the busiest day; grows in on first paint. */
function Sparkline({
  days,
  color,
  label,
}: {
  days: readonly { date: string; n: number }[];
  color: string;
  label: string;
}) {
  const max = Math.max(0, ...days.map((d) => d.n));
  return (
    <span role="img" aria-label={label} className="grow-y flex h-5 items-end gap-px">
      {days.map((d) => (
        <i
          key={d.date}
          title={`${d.date}: ${d.n}`}
          className="block min-w-0 flex-1 rounded-[1px]"
          style={{
            height: d.n > 0 && max > 0 ? `${Math.max(15, (d.n / max) * 100)}%` : '2px',
            background: color,
            opacity: d.n > 0 ? 1 : 0.25,
          }}
        />
      ))}
    </span>
  );
}
