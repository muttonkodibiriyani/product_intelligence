'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Bucket, CategoryCompare, Side } from '@/lib/api/category-compare';
import type { Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { isValidPrice } from '@/lib/money';
import { navHref } from '@/lib/nav';
import { errorText } from '../error-notice';
import { Card } from '../ui/card';
import { Reason } from '../ui/known';
import { Money, Pct } from '../ui/money';
import { RetailerDot, retailerColor } from '../ui/retailer-dot';
import { Tip } from '../ui/tip';
import type { PairState } from '../widgets/use-compare';
import {
  bucketCheaper,
  categoryLines,
  gapWidth,
  groupLeader,
  groupOk,
  matchedRead,
  widestGap,
  type CategoryLine,
} from './model';

type Pair = { base: string; other: string; name: (id: string) => string };
type Group = Schemas['Group'];

/**
 * The whole-range read when the API sent one: a `not_enough_data` body still carries every
 * bucket with its counts, so it is drawn (as too few) rather than called "not available".
 */
export function categoryData(state: PairState<CategoryCompare>): CategoryCompare | null {
  if (state.kind === 'ready') return state.data;
  if (state.kind === 'empty') return state.env?.data ?? null;
  return null;
}

/**
 * Whether the card has a row to show once both calls settled: a category the API computed a
 * range gap for, or one whose matched pairs it summarised. The Overview gives the row to the
 * matched basket when it has none, so no empty box is drawn.
 */
export function hasCategoryRows(state: PairState<CategoryCompare>, groups: readonly Group[] | null): boolean {
  if (state.kind === 'loading' || state.kind === 'error') return true;
  return categoryLines(categoryData(state)?.buckets ?? [], groups ?? []).shown.length > 0;
}

/**
 * Where each shop is cheaper, category by category. Two reads side by side, never mixed: each
 * shop's typical price over its whole range in the category (the API's median, so it reflects
 * what each shop stocks, and it is never called cheaper), and on the same products how often each
 * shop is cheaper (the matched pairs, /compare grouped by category). The title is the matched
 * finding. A figure below the API's minimum is a dash with its count in a tooltip; a category
 * with neither read is folded into one last row; with no category at all the card is not drawn.
 */
export function CategoryHeadToHead({
  state,
  groups,
  pair,
  span = 12,
}: {
  state: PairState<CategoryCompare>;
  /** /compare's per-category groups for the pair; null when that read is not available. */
  groups: readonly Group[] | null;
  pair: Pair;
  /** Its width on the Overview's 12-column grid: two thirds beside the basket, else the full row. */
  span?: 8 | 12;
}) {
  const t = useTranslations('widgets.categories');
  const te = useTranslations('errors');
  const locale = useLocale();
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const data = categoryData(state);
  const lines = categoryLines(data?.buckets ?? [], groups ?? []);
  const read = matchedRead(lines.shown, pair.base, pair.other);
  const title =
    read.compared === 0
      ? t('title')
      : read.base === 0 && read.other === 0
        ? t('allEven', { n: read.compared })
        : read.base === read.other
          ? t('tie', { k: read.base, n: read.compared, base, other })
          : t('lead', {
              shop: read.base > read.other ? base : other,
              k: Math.max(read.base, read.other),
              n: read.compared,
            });
  const currency = data?.buckets.map((b) => side(b, pair.base)?.median?.currency).find(Boolean) ?? null;
  const unmapped = data?.unmapped.reduce((a, u) => a + u.n, 0) ?? 0;
  const common = {
    id: 'w-categories',
    title,
    meta: read.compared > 0 ? <span className="font-normal text-ink-3">{t('title')}</span> : undefined,
    tools: (
      <>
        {data && (
          <Tip
            at="end"
            text={[
              t('note', { base, other }),
              data.minN > 0 ? t('minN', { n: data.minN }) : '',
              unmapped > 0 ? t('unmapped', { n: unmapped }) : '',
              currency ? t('inCurrency', { currency }) : '',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            <span className="pill bg-surface-2 text-ink-2" data-info>
              {t('about')}
            </span>
          </Tip>
        )}
        <Link href={navHref('prices', locale)} className="btn text-sm focus-visible:outline-2">
          {t('open')}
        </Link>
      </>
    ),
    flush: true,
    skeleton: 'table' as const,
    span,
  };
  if (state.kind === 'loading') return <Card {...common} state="loading" />;
  if (state.kind === 'error')
    return (
      <Card
        {...common}
        state="error"
        reason={
          <span className="flex flex-wrap items-center gap-3">
            {errorText(te, state.error)}
            <button type="button" onClick={state.retry} className="btn focus-visible:outline-2">
              {te('retry')}
            </button>
          </span>
        }
      />
    );
  // Nothing to compare in any category: no card at all, never an empty box.
  if (lines.shown.length === 0) return null;
  return (
    <Card {...common}>
      <Body lines={lines} minN={data?.minN ?? null} matched={groups !== null} pair={pair} />
    </Card>
  );
}

function Body({
  lines,
  minN,
  matched,
  pair,
}: {
  lines: ReturnType<typeof categoryLines>;
  minN: number | null;
  /** Whether /compare's groups arrived: without them the matched column is left out. */
  matched: boolean;
  pair: Pair;
}) {
  const t = useTranslations('widgets.categories');
  const locale = useLocale();
  const lc = locale === 'ar' ? 'ar' : 'en';
  const base = pair.name(pair.base);
  const other = pair.name(pair.other);
  const name = (l: CategoryLine) => l.bucket?.label?.[lc] || t(`name.${l.key}`);
  const min = minN ?? 5;
  // The widest gap on the table, so every bar is read against the same scale.
  const maxGap = widestGap(lines.shown.flatMap((l) => (l.bucket ? [l.bucket] : [])));
  const dash = (tip: string) => (
    <Tip at="end" text={tip}>
      <span className="text-ink-3">–</span>
    </Tip>
  );

  /**
   * A side's typical price with its product count under it; below the minimum, blocked or not
   * sent, a dash with the reason (and the API's own count) in its tooltip.
   */
  const typical = (b: Bucket | null, id: string) => {
    const s = b ? side(b, id) : null;
    if (s?.status === 'ok' && s.median && isValidPrice(s.median))
      return (
        <span className="grid justify-items-end gap-0.5">
          <Money m={s.median} locale={locale} />
          <span className="text-[11px] text-ink-3 tabular-nums">
            <span className="sr-only">{pair.name(id)} </span>
            {t('n', { n: formatCount(s.n, locale) })}
          </span>
        </span>
      );
    if (s?.status === 'blocked')
      return (
        <span className="text-xs text-ink-2">
          <Reason v={s.reason ?? 'retailer_blocked'} />
        </span>
      );
    return dash(s ? t('tooFew', { n: s.n, min }) : t('sideMissing'));
  };

  /**
   * The range gap as the API sent it: a bar off the zero line toward the side with the lower
   * typical price, in that shop's colour, and a chip with the shop's dot and the signed number.
   */
  const gap = (b: Bucket | null) => {
    const who = b ? bucketCheaper(b, pair.base, pair.other) : null;
    if (!b || who === null)
      return (
        <span className="text-xs text-ink-2">
          {b?.status === 'no_gap' && b.gapReason ? <Reason v={b.gapReason} /> : '–'}
        </span>
      );
    if (who === 'same')
      return (
        <span className="inline-flex items-center gap-2">
          <span className="gapbar" aria-hidden />
          <span className="pill bg-surface-2 text-ink-2">{t('same')}</span>
        </span>
      );
    // Negative means `other` is lower: the fill runs to the start side, in `other`'s colour.
    const otherLower = who === pair.other;
    return (
      <span className="inline-flex items-center gap-2">
        <span className="gapbar" aria-hidden>
          <i
            className="grow"
            data-shop={who}
            data-at={otherLower ? 'start' : 'end'}
            style={{
              width: `${gapWidth(b.gapPct!, maxGap)}%`,
              background: retailerColor(who, otherLower ? 1 : 0),
              transformOrigin: otherLower ? '100% 50%' : '0 50%',
            }}
          />
        </span>
        <span className="pill gap-1.5 bg-surface-2 text-sm font-medium tabular-nums">
          <RetailerDot id={who} index={otherLower ? 1 : 0} />
          <Pct v={b.gapPct!} />
          <span className="sr-only">{t('lowerAt', { shop: pair.name(who) })}</span>
        </span>
      </span>
    );
  };

  /** On the same products: the shop cheaper on more of the category's pairs, k of n, counts in a tip. */
  const same = (g: Group | null) => {
    if (!groupOk(g)) return dash(t('fewMatches', { n: g?.n ?? 0, min }));
    const { a, b, e, n, who } = groupLeader(g, pair.base, pair.other);
    const note = t('matchedNote', { base, other, a, b, e });
    if (who === 'even')
      return (
        <Tip at="end" text={note}>
          <span className="text-ink-2 tabular-nums">{t('matchedEven', { k: a, n })}</span>
        </Tip>
      );
    const index = who === pair.base ? 0 : 1;
    return (
      <Tip at="end" text={note}>
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap tabular-nums">
          <RetailerDot id={who} index={index} />
          <span className="font-medium">{pair.name(who)}</span>
          <span className="text-ink-2">{t('matchedLead', { k: Math.max(a, b), n })}</span>
        </span>
      </Tip>
    );
  };

  /** One folded category in the "not enough data" tip: each side's priced count and the matches. */
  const thinLine = (l: CategoryLine) => {
    const parts = [pair.base, pair.other].flatMap((id) => {
      const s = l.bucket ? side(l.bucket, id) : null;
      return s ? [t('priced', { shop: pair.name(id), n: s.n })] : [];
    });
    if (matched) parts.push(t('matches', { n: l.group?.n ?? 0 }));
    return `${name(l)}: ${parts.join(' · ')}`;
  };

  const cols = matched ? 5 : 4;
  return (
    // Positioned, so the sr-only labels inside are clipped by this scroll box, not the page.
    <div className="relative overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>
            <td className="ps-5" />
            <th scope="colgroup" colSpan={3} className="th text-start">
              <Tip text={t('typicalNote')}>
                <span className="underline decoration-dotted underline-offset-4">{t('typical')}</span>
              </Tip>
            </th>
            {matched && <td />}
          </tr>
          <tr>
            <th scope="col" className="th ps-5 text-start">
              {t('category')}
            </th>
            <th scope="col" className="th text-end whitespace-nowrap">
              <RetailerDot id={pair.base} index={0} /> {base}
            </th>
            <th scope="col" className="th text-end whitespace-nowrap">
              <RetailerDot id={pair.other} index={1} /> {other}
            </th>
            <th scope="col" className="th text-start">
              {t('gap')}
            </th>
            {matched && (
              <th scope="col" className="th pe-5 text-start whitespace-nowrap">
                {t('matched')}
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {lines.shown.map((l) => (
            <tr key={l.key} className="border-t border-line-2">
              <th scope="row" className="ps-5 py-2 text-start font-medium">
                {name(l)}
              </th>
              <td className="py-2 pe-3 text-end tabular-nums">{typical(l.bucket, pair.base)}</td>
              <td className="py-2 pe-3 text-end tabular-nums">{typical(l.bucket, pair.other)}</td>
              <td className={`py-2 ${matched ? 'pe-3' : 'pe-5'}`}>{gap(l.bucket)}</td>
              {matched && <td className="py-2 pe-5">{same(l.group)}</td>}
            </tr>
          ))}
          {lines.thin.length > 0 && (
            <tr className="border-t border-line-2">
              <td colSpan={cols} className="ps-5 pe-5 py-2 text-xs text-ink-2">
                <Tip
                  text={
                    <span className="grid gap-0.5">
                      {lines.thin.map((l) => (
                        <span key={l.key}>{thinLine(l)}</span>
                      ))}
                    </span>
                  }
                >
                  <span className="underline decoration-dotted underline-offset-4">
                    {t('thin', { n: lines.thin.length })}
                  </span>
                </Tip>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** A bucket's side for a retailer, or null when the API left it out: not a count of zero. */
function side(b: Bucket, id: string): Side | null {
  return b.sides[id] ?? null;
}
