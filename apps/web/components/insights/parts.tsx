'use client';

/** Shared pieces of the Insights page: section headings, shop panels, linked numbers, money text. */
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Money as MoneyValue } from '@/lib/api/types';
import { EMPTY, toQuery } from '@/lib/explore';
import { barWidths, displayBrand, type BarRow, type UnitAmount } from '@/lib/insights';
import { formatAmount, formatMoney, isValidAmount, isValidMoney } from '@/lib/money';
import { useAuth } from '../auth-provider';
import { productHref } from '../explore/product-table';
import { monogram, RowThumb } from '../explore/row-thumb';
import { RetailerDot, retailerColor } from '../ui/retailer-dot';
import { Tip } from '../ui/tip';
import { useRetailerName } from '../use-meta';

type Item = { brand: string; name: string; id: string; image?: string | null };

/** Columns for one, two or three shops side by side (literal classes, so Tailwind keeps them). */
const COLS: Record<number, string> = { 1: '', 2: 'md:grid-cols-2', 3: 'md:grid-cols-3' };
export const cols = (n: number) => `grid gap-3.5 ${COLS[Math.min(n, 3)] ?? ''}`;

export const LINK = 'text-accent underline-offset-2 hover:underline';

/** A money value as text for a sentence, isolated so its digits and code keep their order in Arabic. */
export const moneyText = (m: MoneyValue, locale: string) =>
  `⁨${isValidMoney(m) ? formatMoney(m, locale === 'ar' ? 'ar' : 'en') : `${m.amount} ${m.currency}`}⁩`;

/** A price per ml or g the same way; its decimals need not be the currency's. */
export const unitText = (u: UnitAmount, locale: string) =>
  `⁨${isValidAmount(u.amount) ? formatAmount(u, locale === 'ar' ? 'ar' : 'en') : `${u.amount} ${u.currency}`}⁩`;

/** A count as one run of Latin digits that keeps its direction inside Arabic text. */
export function Num({ children }: { children: ReactNode }) {
  return (
    <bdi dir="ltr" className="tabular-nums">
      {children}
    </bdi>
  );
}

/** Rich-text tags: <l> opens the list a number counts, <b> is an unlinked figure. */
export const linkTag = (href: string) =>
  function NumberLink(chunks: ReactNode) {
    return (
      <Link href={href} className={LINK}>
        <Num>{chunks}</Num>
      </Link>
    );
  };
export const boldTag = (chunks: ReactNode) => (
  <b className="font-semibold text-ink">
    <Num>{chunks}</Num>
  </b>
);

export function Heading({ id, children, tip }: { id: string; children: ReactNode; tip?: ReactNode }) {
  return (
    <div className="flex items-center gap-1.5">
      <h2 id={id} className="text-[15px] font-semibold">
        {children}
      </h2>
      {tip && <Info text={tip} />}
    </div>
  );
}

/** The small circled "i" that carries a caveat; in the tab order like every tooltip. */
export function Info({ text, at = 'start' }: { text: ReactNode; at?: 'start' | 'end' }) {
  const t = useTranslations('insights');
  return (
    <Tip text={text} at={at} className="inline-flex align-middle text-sm font-normal">
      <span
        role="img"
        aria-label={t('info')}
        className="inline-grid size-4 place-items-center rounded-full border border-ink-3 font-serif text-[10px] leading-none font-semibold text-ink-2 italic"
      >
        i
      </span>
    </Tip>
  );
}

/** A shop's name with its colour dot, at the top of its column. */
export function ShopHead({ id }: { id: string }) {
  const name = useRetailerName();
  return (
    <h3 className="flex items-center gap-2 text-sm font-semibold">
      <RetailerDot id={id} />
      {name(id)}
    </h3>
  );
}

export function Panel({ children, top }: { children: ReactNode; top?: string }) {
  return (
    <article
      className={`panel px-4.5 py-4 ${top ? 'border-t-[3px]' : ''}`}
      style={top ? { borderTopColor: retailerColor(top) } : undefined}
    >
      {children}
    </article>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <p className="mt-3.5 mb-1.5 text-xs font-semibold text-ink-2">{children}</p>;
}

/** A plain-words note under a heading line, for a shop where the section has nothing to show. */
export function Off({ children }: { children: ReactNode }) {
  return <p className="mt-2.5 text-sm text-ink-2">{children}</p>;
}

export function useUnitName() {
  const t = useTranslations('insights');
  return (u: string) => (t.has(`ladder.unit.${u}`) ? t(`ladder.unit.${u}`) : u);
}

/**
 * A shop's listings with a price, the same count as its Products list with any price: the Glance
 * tile shows it and the discount bars divide by it, so both read one cached answer.
 */
export const pricedOptions = (api: ReturnType<typeof useAuth>['api'], shop: string) => ({
  queryKey: ['products', 'insights', shop, 'priced'],
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    api!.get('/api/v1/products', {
      query: { ...toQuery({ ...EMPTY, retailer: [shop], priceMin: '0' }, null), limit: 1 },
      signal,
    }),
  enabled: !!api,
});

export function usePricedCount(shop: string): number | undefined {
  const { api } = useAuth();
  return useQuery(pricedOptions(api, shop)).data?.data?.total;
}

/** One shop's line in a card's chart: a value and its words, or a quiet note where it has none. */
export type ChartRow = BarRow & { text?: ReactNode; note?: ReactNode };

/**
 * A card's chart: one full-width row per shop, its name, a bar in its colour and the words for
 * it. A shop whose number is not collected shows a note, never a zero bar. Bars are plain HTML so
 * they follow the page direction; the rows are read as text, the bars are decoration.
 */
export function Bars({ rows }: { rows: ChartRow[] }) {
  const name = useRetailerName();
  const width = barWidths(rows);
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-2 text-[13px]">
      {rows.map((r) => (
        <div key={r.id} className="contents">
          <span className="text-end leading-5 whitespace-nowrap text-ink">{name(r.id)}</span>
          {r.value === null ? (
            <span className="col-span-2 text-[12.5px] leading-5 text-ink-2">{r.note}</span>
          ) : (
            <>
              <span aria-hidden className="relative block h-5 min-w-0 rounded-[3px] bg-line">
                <span
                  data-shop={r.id}
                  className="absolute inset-y-0 start-0 min-w-[3px] rounded-[3px]"
                  style={{ width: `${width.get(r.id) ?? 0}%`, background: retailerColor(r.id) }}
                />
              </span>
              <span className="text-[12.5px] leading-5 whitespace-nowrap text-ink-2 tabular-nums">
                {r.text}
              </span>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * One idea card: its title (with an optional chip) and (i) note, one big number and its words,
 * one plain sentence, its chart, its products, and one "See all" at the foot.
 */
export function IdeaCard({
  id,
  title,
  chip,
  tip,
  big,
  unit,
  sentence,
  chart,
  children,
  more,
}: {
  id: string;
  title: ReactNode;
  chip?: ReactNode;
  tip: ReactNode;
  big: ReactNode;
  unit: ReactNode;
  sentence: ReactNode;
  chart: ReactNode;
  children?: ReactNode;
  more?: ReactNode;
}) {
  return (
    <article aria-labelledby={id} className="panel flex min-w-0 flex-col px-4.5 pt-4 pb-3.5">
      <div className="flex min-h-[22px] items-center gap-2">
        <h3 id={id} className="text-[15px] font-semibold">
          {title}
        </h3>
        {chip}
        <span className="ms-auto">
          <Info text={tip} at="end" />
        </span>
      </div>
      <p className="mt-3.5 mb-1.5 flex flex-wrap items-baseline gap-x-2 leading-none">
        <span className="text-[34px] font-bold tracking-tight tabular-nums max-sm:text-[30px]">{big}</span>
        <span className="text-sm font-medium text-ink-2">{unit}</span>
      </p>
      <p className="mb-4 text-sm text-ink-2">{sentence}</p>
      <figure className="mb-1.5 min-w-0">{chart}</figure>
      {children}
      {more && <p className="mt-auto pt-3.5 text-[13px]">{more}</p>}
    </article>
  );
}

/** The line above a card's products: a small caps label, then its detail. */
export function ListHead({ label, children }: { label: ReactNode; children?: ReactNode }) {
  return (
    <p className="mt-4 mb-2 truncate text-[12.5px] text-ink-2">
      <span className="text-xs font-semibold tracking-[.06em] uppercase rtl:text-[13px] rtl:tracking-normal rtl:normal-case">
        {label}
      </span>
      {children && <> · {children}</>}
    </p>
  );
}

/** One product on one line: its picture, brand and name (truncated, opening the product), a detail line. */
export function ItemRow({ item, shop, children }: { item: Item; shop: string; children: ReactNode }) {
  const locale = useLocale();
  return (
    <li className="grid h-14 grid-cols-[56px_minmax(0,1fr)] items-center gap-3">
      <RowThumb
        url={item.image}
        label={item.name}
        monogram={monogram(item.brand)}
        retailer={shop}
        px={56}
        cls="size-14 rounded-ctl border border-line bg-surface-2"
      />
      <div className="min-w-0 text-sm">
        <p className="truncate rtl:text-end" dir="ltr">
          <Link href={productHref(locale, item.id)} className="underline-offset-2 hover:underline">
            <b className="font-semibold">{displayBrand(item.brand)}</b> {item.name}
          </Link>
        </p>
        <p className="mt-0.5 truncate text-[12.5px] text-ink-2 tabular-nums">{children}</p>
      </div>
    </li>
  );
}
