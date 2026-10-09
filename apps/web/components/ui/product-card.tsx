'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Money as MoneyValue, Schemas } from '@/lib/api/types';
import type { CardField, CellState } from '@/lib/source-freshness';
import { priceState, type Priced } from '@/lib/money';
import type { Verdict } from '@/lib/verdict';
import { monogram, RowThumb } from '../explore/row-thumb';
import { MissingFields, StateBadge } from './freshness';
import { Known } from './known';
import { Money } from './money';
import { RetailerDot } from './retailer-dot';
import { Tip } from './tip';

/** One shop's line on a card: its name, then its price (or why there is none). */
export type PriceLine = {
  /** The retailer id: it picks the dot's colour. */
  retailer: string;
  /** The shop's display name; never the id. */
  label: string;
  price?: MoneyValue | null;
  priceFlag?: Priced['priceFlag'];
  /** The regular price the shop showed before the discount, struck through (promotions). */
  was?: MoneyValue | null;
  /** The exact amount saved, shown only when the API supplied it (promotions). */
  saved?: MoneyValue | null;
  /** The discount depth as the API wrote it ("37.5"), shown as −37.5%. */
  off?: string | null;
  /** No offer of this shop was observed for the product: never read as "out of stock" or "removed". */
  notSold?: boolean;
  /** The evidence state of this shop's line when it is not the dataset's latest (lib/source-freshness). */
  evidence?: CellState | null;
  /** This shop's size when the pair's sizes differ (PairGap.sizeLabels). */
  size?: string | null;
};

export type ChipTone = 'good' | 'bad' | 'neutral' | 'warn';
export type Chip = { tone: ChipTone; label: ReactNode };

const TONE: Record<ChipTone, string> = {
  good: 'verdict verdict-good',
  bad: 'verdict verdict-bad',
  warn: 'verdict verdict-warn',
  neutral: 'verdict',
};

/**
 * A product as a card: the picture first (the brand's monogram when there is none), the brand,
 * the name on at most two lines, the size, then one price line per shop; a verdict chip sits on
 * the picture. The whole card opens `href`. Used by Products, and by Promotions (now, was, −%)
 * and the assistant's answers with the same props.
 */
export function ProductCard({
  href,
  image,
  imageRetailer,
  brand,
  name,
  size,
  category,
  lines,
  chip,
  matchReview,
  missing,
}: {
  href: string;
  image?: string | null;
  /** A single-retailer card must bind its image to that retailer's exact allowlisted host. */
  imageRetailer?: string;
  /** The brand; a list the API sends without one (promotions) has no brand line and no monogram. */
  brand?: string | null;
  name: string;
  size?: Schemas['Size'] | null;
  /** The product's category, shown after the size. */
  category?: string | null;
  lines: readonly PriceLine[];
  chip?: Chip | null;
  /** The card's match as the API sent it; "unreviewed" shows a label under the size. */
  matchReview?: Schemas['MatchReview'] | null;
  /** The fields the product lacks, each labelled; the card is shown all the same. */
  missing?: readonly CardField[];
}) {
  const t = useTranslations('productCard');
  return (
    <div className="group relative flex h-full min-w-0 flex-col overflow-hidden panel transition-shadow hover:shadow-pop focus-within:shadow-pop">
      <div className="relative border-b border-line-2 bg-[#fafafb]">
        {chip && <span className={`absolute top-2 start-2 z-[1] ${TONE[chip.tone]}`}>{chip.label}</span>}
        <RowThumb
          url={image}
          label={t('noImage')}
          monogram={brand ? monogram(brand) : undefined}
          retailer={imageRetailer}
          px={320}
          cls="aspect-square w-full rounded-none p-3"
        />
      </div>
      <div className="flex flex-1 flex-col gap-0.5 p-3">
        {brand && (
          <span className="truncate text-[11px] tracking-[0.06em] text-ink-3 uppercase" dir="auto">
            {brand}
          </span>
        )}
        <Link
          href={href}
          dir="auto"
          className="line-clamp-2 text-[13px] leading-snug font-medium text-ink after:absolute after:inset-0 group-hover:underline focus-visible:outline-2"
        >
          {name.trim() ? name : <span className="text-ink-3">{t('noName')}</span>}
        </Link>
        {(size || category) && (
          <span className="truncate text-xs text-ink-3">
            {size && <SizeText size={size} />}
            {size && category && ' · '}
            {category && <span dir="auto">{category}</span>}
          </span>
        )}
        {/* Above the card's full-size link, so the label's explanation opens on hover and focus. */}
        <MatchReviewLabel review={matchReview} className="relative z-[1] mt-1" />
        {missing && <MissingFields fields={missing} />}
        <dl className="mt-auto grid gap-1 pt-2 text-[13px]">
          {lines.map((l, i) => (
            <div key={l.retailer} className="flex flex-wrap items-center gap-1.5">
              <dt className="flex min-w-0 items-center gap-1.5">
                <RetailerDot id={l.retailer} index={i} />
                <span className="truncate">{l.label}</span>
                {l.size && (
                  <bdi dir="ltr" className="text-ink-3 tabular-nums">
                    {l.size}
                  </bdi>
                )}
              </dt>
              <dd className="ms-auto text-end font-medium tabular-nums">
                <LinePrice line={l} />
                {l.evidence && l.evidence !== 'fresh' && !l.notSold && (
                  <span className="mt-0.5 block">
                    <StateBadge state={l.evidence} />
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

/**
 * "Unreviewed match" on a product the API counts as sold at both shops through an exact match no
 * reviewer has confirmed yet (ruling A); its explanation is a tooltip. Nothing for a reviewed match
 * or an unmatched product.
 */
export function MatchReviewLabel({
  review,
  hint,
  side,
  className = '',
}: {
  review: Schemas['MatchReview'] | null | undefined;
  /** Where the page counts unreviewed matches differently, it says so here. */
  hint?: string;
  side?: 'below' | 'above';
  className?: string;
}) {
  const t = useTranslations('productCard');
  if (review !== 'unreviewed') return null;
  return (
    <Tip text={hint ?? t('unreviewedMatchHint')} side={side} className={`w-fit ${className}`}>
      <span className="inline-block rounded-[4px] bg-butter px-1.5 py-px text-[11px] font-medium text-warn">
        {t('unreviewedMatch')}
      </span>
    </Tip>
  );
}

/** "50 ml": the value and unit as the API sent them, read left to right in both languages. */
export function SizeText({ size }: { size: Schemas['Size'] }) {
  return (
    <bdi dir="ltr" className="tabular-nums">
      {size.value} {size.unit}
    </bdi>
  );
}

/**
 * The price on a line: "Not sold", "Price under review" (never the placeholder number), the
 * price with its was-price and discount when the API sent them, or "No price".
 */
function LinePrice({ line }: { line: PriceLine }) {
  const t = useTranslations('productCard');
  const tp = useTranslations('price');
  const tpr = useTranslations('product');
  const locale = useLocale();
  const quiet = 'font-normal text-ink-3';
  if (line.notSold) return <span className={quiet}>{t('notSold')}</span>;
  if (priceState(line) === 'review') return <span className={quiet}>{tp('underReview')}</span>;
  if (!line.price) return <span className={quiet}>{tpr('noPrice')}</span>;
  return (
    <span className="inline-flex flex-wrap items-baseline justify-end gap-x-1.5">
      <Money m={line.price} locale={locale} />
      {line.was && (
        <s className="text-xs font-normal text-ink-3">
          <span className="sr-only">{t('was')} </span>
          <Money m={line.was} locale={locale} />
        </s>
      )}
      {line.saved && (
        <span className="text-xs font-semibold text-ink-2">
          {t('save')} <Money m={line.saved} locale={locale} />
        </span>
      )}
      {line.off && (
        <span className="verdict verdict-good">
          <bdi dir="ltr">{t('off', { pct: line.off })}</bdi>
        </span>
      )}
    </span>
  );
}

/** A verdict (lib/verdict.ts) as a chip: its words in the user's language, with the shop's name. */
export function useVerdictChip(name: (id: string) => string): (v: Verdict | null | undefined) => Chip | null {
  const t = useTranslations('productCard');
  const tp = useTranslations('price');
  const tg = useTranslations('gap');
  return (v) => {
    if (!v) return null;
    switch (v.kind) {
      case 'cheaper':
        return { tone: 'good', label: t('cheaper', { shop: name(v.retailer), pct: v.pct }) };
      case 'dearer':
        return { tone: 'good', label: t('dearer', { shop: name(v.retailer), pct: v.pct }) };
      case 'same':
        return { tone: 'neutral', label: t('same') };
      case 'sizes':
        return { tone: 'neutral', label: t('sizesDiffer') };
      case 'review':
        return { tone: 'warn', label: tp('underReview') };
      case 'excluded':
        return { tone: 'neutral', label: <Known t={tg} k="excluded" v={v.reason} /> };
    }
  };
}
