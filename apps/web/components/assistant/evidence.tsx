'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { useId } from 'react';
import { toolKey } from '@/lib/assistant/answer';
import { type EvidenceCard, type EvidenceShare, evidenceTotal, sourceLink } from './evidence-model';
import type { Citation, ToolEnvelope } from '@/lib/assistant/types';
import { formatCount, formatDate } from '@/lib/format';
import { shareWidth } from '@/lib/promotions';
import { productHref } from '../explore/product-table';
import { useRetailerName } from '../use-meta';
import { Known } from '../ui/known';
import { ProductCard, useVerdictChip } from '../ui/product-card';
import { RetailerDot, retailerTone } from '../ui/retailer-dot';

/** Products a tool returned, as the Products page's cards; each opens the product. */
export function EvidenceCards({ cards }: { cards: readonly EvidenceCard[] }) {
  const t = useTranslations('assistant.answer');
  const locale = useLocale();
  const name = useRetailerName();
  const chip = useVerdictChip(name);
  if (cards.length === 0) return null;
  return (
    <ul aria-label={t('products')} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {cards.map((c) => (
        <li key={c.id} className="min-w-0">
          <ProductCard
            href={productHref(locale, c.id)}
            brand={c.brand}
            name={c.name}
            size={c.size}
            category={c.category}
            lines={c.lines.map((l) => ({ ...l, label: name(l.retailer) }))}
            chip={chip(c.verdict)}
          />
        </li>
      ))}
    </ul>
  );
}

/**
 * One tile per shop: its share of priced products on promotion as the number, how many priced,
 * a bar in the shop's colour. A shop the API cannot measure gets one plain line and the reason.
 */
export function ShareTiles({ shares }: { shares: readonly EvidenceShare[] }) {
  const t = useTranslations('assistant.share');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const name = useRetailerName();
  if (shares.length === 0) return null;
  return (
    <ul aria-label={t('label')} className="grid gap-2 sm:grid-cols-2">
      {shares.map((s, i) => {
        const width = shareWidth(s.share);
        return (
          <li key={s.retailer} className="min-w-0 rounded-ctl border border-line bg-surface px-3 py-2.5">
            <p className="text-xs text-ink-3">
              <span className="inline-flex items-center gap-1.5 font-medium text-ink">
                <RetailerDot id={s.retailer} index={i} />
                <span dir="auto">{name(s.retailer)}</span>
              </span>
              <span aria-hidden> · </span>
              <span className="tabular-nums">{t('priced', { n: formatCount(s.n, locale) })}</span>
            </p>
            {s.share === null ? (
              <p className="mt-1.5 text-sm text-ink-2">
                {t('notMeasured')} {s.reason && <Known t={tr} v={s.reason} />}
              </p>
            ) : (
              <>
                <p className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5">
                  <bdi dir="ltr" className="text-xl leading-tight font-semibold tracking-tight tabular-nums">
                    {`${s.share}%`}
                  </bdi>
                  <span className="text-xs text-ink-2">{t('onPromo')}</span>
                </p>
                {width !== null && (
                  <div aria-hidden className="mt-2 h-1 overflow-hidden rounded-full bg-line-2">
                    <i
                      className={`block h-full rounded-full ${retailerTone(s.retailer, i)}`}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                )}
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * "From" and one pill per citation: the page's name, what the tool was scoped to, how many
 * records, the data's date; it opens the page with the same filters. No ids, no raw timestamps.
 */
export function SourcePills({
  citations,
  toolResults,
}: {
  citations: readonly Citation[];
  toolResults: readonly ToolEnvelope[];
}) {
  const t = useTranslations('assistant.answer');
  const id = useId();
  if (citations.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
      <span id={id}>{t('from')}</span>
      <ol aria-labelledby={id} className="contents">
        {citations.map((c, i) => {
          const result = toolResults.find((r) => sameSource(r.citation, c));
          return (
            <li key={i} className="contents">
              <SourcePill c={c} total={result ? evidenceTotal(result) : null} />
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** The tool result a citation came from: the same tool run with the same input. */
const sameSource = (a: Citation, b: Citation) =>
  a.tool === b.tool && a.cutoff === b.cutoff && JSON.stringify(a.filters) === JSON.stringify(b.filters);

/** The pill's text: page · scope · count · date. Exported for the label test. */
export function useSourceLabel() {
  const t = useTranslations('assistant.answer');
  const nav = useTranslations('app.nav');
  const tool = useTranslations('assistant.tools');
  const locale = useLocale();
  const name = useRetailerName();
  return (c: Citation, total: number | null) => {
    const link = sourceLink(c, locale);
    const page = link ? nav(link.page === 'dataset' ? 'status' : link.page) : tool(toolKey(c.tool));
    const parts: string[] = [];
    if (link) {
      if (
        link.retailers.length === 2 &&
        (c.tool === 'compare' || c.tool === 'index_trend' || c.tool === 'category_compare')
      )
        parts.push(t('vs', { base: name(link.retailers[0]!), other: name(link.retailers[1]!) }));
      else if (link.retailers.length > 0) parts.push(link.retailers.map((r) => name(r)).join(', '));
      for (const v of [...link.brand, ...link.category]) parts.push(v);
    }
    if (c.tool === 'compare' && c.cohort)
      parts.push(t('matched', { total: c.cohort.n, n: formatCount(c.cohort.n, locale) }));
    else if (total !== null) parts.push(t('records', { total, n: formatCount(total, locale) }));
    parts.push(formatDate(c.cutoff, locale));
    return { page, detail: parts.join(' · '), href: link?.href ?? null };
  };
}

function SourcePill({ c, total }: { c: Citation; total: number | null }) {
  const label = useSourceLabel()(c, total);
  const cls =
    'inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-0.5 text-ink-2';
  const body = (
    <>
      <b className="font-medium text-ink">{label.page}</b>
      <span className="truncate">{label.detail}</span>
    </>
  );
  return label.href ? (
    <Link href={label.href} className={`${cls} hover:border-ink-3 focus-visible:outline-2`}>
      {body}
    </Link>
  ) : (
    <span className={cls}>{body}</span>
  );
}
