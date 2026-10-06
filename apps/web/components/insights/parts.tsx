'use client';

/** Shared pieces of the Insights page: section headings, shop panels, linked numbers, money text. */
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Money as MoneyValue } from '@/lib/api/types';
import { type UnitAmount } from '@/lib/insights';
import { formatAmount, formatMoney, isValidAmount, isValidMoney } from '@/lib/money';
import { productHref } from '../explore/product-table';
import { monogram, RowThumb } from '../explore/row-thumb';
import { Known } from '../ui/known';
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

/** The amber tag for a caveat that changes how to read the line beside it. */
export function Warn({ children }: { children: ReactNode }) {
  return <span className="rounded-[4px] bg-butter px-1.5 text-butter-ink">{children}</span>;
}

/** The shop's own category in the user's language, else as the shop names it. */
export function Cat({ k }: { k: string }) {
  const t = useTranslations('insights');
  return <Known t={t} k="cat" v={k} />;
}

export function useUnitName() {
  const t = useTranslations('insights');
  return (u: string) => (t.has(`ladder.unit.${u}`) ? t(`ladder.unit.${u}`) : u);
}

export function ProductRow({ item, shop, children }: { item: Item; shop: string; children: ReactNode }) {
  const locale = useLocale();
  return (
    <li className="grid grid-cols-[56px_1fr] items-start gap-2.5">
      <RowThumb
        url={item.image}
        label={item.name}
        monogram={monogram(item.brand)}
        retailer={shop}
        px={56}
        cls="size-14 rounded-ctl border border-line bg-surface-2"
      />
      <div className="min-w-0 text-sm">
        <p className="text-xs font-semibold text-ink-2">{item.brand}</p>
        <p>
          <Link href={productHref(locale, item.id)} className="underline-offset-2 hover:underline">
            {item.name}
          </Link>
        </p>
        <p className="text-xs text-ink-2">{children}</p>
      </div>
    </li>
  );
}
