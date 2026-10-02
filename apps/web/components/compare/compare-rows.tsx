'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { useId, useState, type ReactNode } from 'react';
import type { Schemas } from '@/lib/api/types';
import { formatCount } from '@/lib/format';
import { productHref } from '../explore/product-table';
import { RowThumb } from '../explore/row-thumb';
import { Known } from '../ui/known';
import { Money, Price } from '../ui/money';
import { pct } from '../widgets/model';
import { excludedGroups, gapShare, onlySide, splitRows, unpricedSide } from './model';
import { RetailerDot } from './pair-picker';

type Comparison = Schemas['Comparison'];
type PairRow = Schemas['PairRow'];
type Matched = PairRow & { gap: Schemas['Gap'] };
type Name = (id: string) => string;

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-top';
const GOOD = { color: 'var(--color-good, #187a43)', background: 'var(--color-good-soft, #e3f4ea)' };

/** The product cell: a thumbnail (the API sends no image for a pair row yet, so a placeholder), name, brand. */
function ProductCell({ r, locale, from }: { r: PairRow; locale: string; from: string }) {
  const te = useTranslations('explore');
  return (
    <span className="flex items-start gap-3">
      <RowThumb url={null} label={te('noImage')} px={44} cls="size-11 shrink-0 rounded-ctl bg-surface-2" />
      <span className="min-w-0">
        <Link
          href={productHref(locale, r.id, from, 'compare')}
          className="font-medium text-ink hover:underline focus-visible:outline-2"
        >
          <span dir="auto">{r.name}</span>
        </Link>
        <span className="block text-xs text-ink-2" dir="auto">
          {r.brand}
        </span>
      </span>
    </span>
  );
}

/** "3 of 15 products are listed", next to the matched title when the API cut the list. */
export function ShownOfTotal({ shown, total }: { shown: number; total: number }) {
  const t = useTranslations('compare.matched');
  const locale = useLocale();
  return (
    <p role="status" className="text-sm text-ink-2 tabular-nums">
      {t('shownOfTotal', {
        shown: formatCount(shown, locale),
        total: formatCount(total, locale),
        totalCount: total,
      })}
    </p>
  );
}

/**
 * "Ulta, by 9.1%" when the other shop is cheaper, "Ulta, 25% dearer" when the base is, or "Same
 * price". gap.pct is (other − base) as a share of the BASE price, so it only reads as "cheaper by"
 * from the other shop's side: 80 vs 100 is +25%, and the base is 20% cheaper, not 25%. Rather than
 * re-derive a number the API did not send, the pill names the other shop both ways.
 */
function CheaperPill({ r, data, name }: { r: Matched; data: Comparison; name: Name }) {
  const t = useTranslations('compare.matched');
  const locale = useLocale();
  if (r.gap.cheaper === 'equal')
    return <span className="pill bg-surface-2 text-ink-2 whitespace-nowrap">{t('same')}</span>;
  const shop = name(data.other);
  return (
    <span className="pill whitespace-nowrap" style={GOOD}>
      {r.gap.cheaper === 'base'
        ? t('dearer', { shop, pct: pct(r.gap.pct, locale) })
        : t('cheaperBy', { shop, pct: pct(r.gap.pct.replace(/^-/, ''), locale) })}
    </span>
  );
}

/** The signed difference (other − base, as the API sends it) with a bar centred on zero. */
function Difference({ r, share, locale }: { r: Matched; share: number; locale: string }) {
  const negative = r.gap.pct.startsWith('-');
  return (
    <span className="inline-flex items-center gap-2">
      <Money m={r.gap.amount} locale={locale} signed />
      <span aria-hidden className="relative hidden h-1.5 w-20 shrink-0 rounded-full bg-line-2 sm:block">
        <span className="absolute inset-y-[-3px] start-1/2 w-px bg-line-3" />
        {share > 0 && (
          <span
            className="absolute inset-y-0 rounded-full"
            style={{
              [negative ? 'insetInlineEnd' : 'insetInlineStart']: '50%',
              width: `${Math.round(share * 50)}%`,
              background: negative ? 'var(--color-good, #187a43)' : 'var(--color-bad, #b3261e)',
            }}
          />
        )}
      </span>
    </span>
  );
}

/**
 * The matched products: the exact same product at both shops, widest gap first, as a table on a
 * wide screen and a list on a phone. Then one fold line for everything that couldn't be compared,
 * grouped by reason, that opens into its own table.
 */
export function CompareRows({ data, name, from }: { data: Comparison; name: Name; from: string }) {
  const t = useTranslations('compare.matched');
  const locale = useLocale();
  const { matched, excluded } = splitRows(data.rows);
  const share = (r: Matched) => gapShare(r.gap.pct, matched);
  const price = (m: PairRow['basePrice']) => (
    <Price of={{ price: m }} locale={locale} fallback={<span className="text-ink-2">–</span>} />
  );
  return (
    <div className="panel overflow-hidden">
      {matched.length === 0 ? (
        <p className="px-5 py-4 text-sm text-ink-2">{t('none')}</p>
      ) : (
        <>
          <div className="relative hidden overflow-x-auto sm:block">
            <table className="w-full text-sm">
              <thead className="border-b border-line">
                <tr>
                  <th scope="col" className={`${TH} text-start`}>
                    {t('product')}
                  </th>
                  <th scope="col" className={`${TH} text-end`}>
                    <RetailerDot id={data.base} side={0} /> {name(data.base)}
                  </th>
                  <th scope="col" className={`${TH} text-end`}>
                    <RetailerDot id={data.other} side={1} /> {name(data.other)}
                  </th>
                  <th scope="col" className={`${TH} text-end`}>
                    {t('difference')}
                  </th>
                  <th scope="col" className={`${TH} text-start`}>
                    {t('cheaper')}
                  </th>
                  <th scope="col" className={TH}>
                    <span className="sr-only">{t('open')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {matched.map((r) => (
                  <tr key={r.id} className="border-t border-line-2 first:border-t-0">
                    <th scope="row" className={`${TD} min-w-56 text-start font-normal`}>
                      <ProductCell r={r} locale={locale} from={from} />
                    </th>
                    <td className={`${TD} text-end tabular-nums`}>{price(r.basePrice)}</td>
                    <td className={`${TD} text-end tabular-nums`}>{price(r.otherPrice)}</td>
                    <td className={`${TD} text-end font-semibold tabular-nums`}>
                      <Difference r={r} share={share(r)} locale={locale} />
                    </td>
                    <td className={TD}>
                      <CheaperPill r={r} data={data} name={name} />
                    </td>
                    <td className={`${TD} text-end whitespace-nowrap`}>
                      <Link
                        href={productHref(locale, r.id, from, 'compare')}
                        aria-label={`${t('open')}: ${r.name}`}
                        className="text-accent hover:underline focus-visible:outline-2"
                      >
                        {t('open')} ›
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="divide-y divide-line-2 sm:hidden">
            {matched.map((r) => (
              <li key={r.id} className="px-4 py-3 text-sm">
                <ProductCell r={r} locale={locale} from={from} />
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 tabular-nums">
                  <dt className="text-xs text-ink-2">
                    <RetailerDot id={data.base} side={0} /> {name(data.base)}
                  </dt>
                  <dd className="text-end">{price(r.basePrice)}</dd>
                  <dt className="text-xs text-ink-2">
                    <RetailerDot id={data.other} side={1} /> {name(data.other)}
                  </dt>
                  <dd className="text-end">{price(r.otherPrice)}</dd>
                  <dt className="text-xs text-ink-2">{t('difference')}</dt>
                  <dd className="text-end font-semibold">
                    <Difference r={r} share={share(r)} locale={locale} />
                  </dd>
                </dl>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <CheaperPill r={r} data={data} name={name} />
                  <Link
                    href={productHref(locale, r.id, from, 'compare')}
                    aria-label={`${t('open')}: ${r.name}`}
                    className="text-sm text-accent hover:underline focus-visible:outline-2"
                  >
                    {t('open')} ›
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      {excluded.length > 0 && <Fold rows={excluded} data={data} name={name} from={from} />}
    </div>
  );
}

/** Why a row is not compared, in plain words, naming the shop where that is the point. */
export function WhyNot({ r, data, name }: { r: PairRow; data: Comparison; name: Name }) {
  const t = useTranslations('compare.why');
  const tg = useTranslations('gap');
  const reason = r.excludedReason;
  if (!reason) return <>{tg('notCounted')}</>;
  if (reason === 'not_offered') {
    const s = onlySide(r);
    return (
      <>
        {s
          ? t('not_offered', { shop: name(s === 'base' ? data.base : data.other) })
          : t('not_offered_unknown')}
      </>
    );
  }
  if (reason === 'unpriced') {
    const s = unpricedSide(r);
    return (
      <>{s ? t('unpriced', { shop: name(s === 'base' ? data.base : data.other) }) : t('unpriced_unknown')}</>
    );
  }
  return <Known t={t} v={reason} />;
}

/** "{n} more products couldn't be compared — 2 come in different sizes, …" and the table behind it. */
function Fold({ rows, data, name, from }: { rows: PairRow[]; data: Comparison; name: Name; from: string }) {
  const t = useTranslations('compare.fold');
  const tm = useTranslations('compare.matched');
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const id = useId();
  const groups = excludedGroups(rows);
  const list = groups
    .map((g) => t(`reason.${g.reason}`, { n: formatCount(g.n, locale), count: g.n }))
    .join(locale === 'ar' ? '، ' : ', ');
  const cell = (m: PairRow['basePrice'], r: PairRow): ReactNode => {
    if (m) return <Price of={{ price: m }} locale={locale} />;
    return (
      <span className="text-ink-2">{r.excludedReason === 'unpriced' ? t('noPrice') : t('notSold')}</span>
    );
  };
  return (
    <div className="border-t border-line bg-page">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-2.5 text-sm text-ink-2">
        <p className="min-w-0 flex-1">
          <b className="font-medium text-ink">
            {t('line', { n: formatCount(rows.length, locale), count: rows.length })}
          </b>
          {' — '}
          {list}.
        </p>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={id}
          className="btn py-1 text-sm focus-visible:outline-2"
        >
          {t(open ? 'hide' : 'show')}
        </button>
      </div>
      {open && (
        <div id={id} className="relative overflow-x-auto border-t border-line-2 bg-surface">
          <table className="w-full text-sm">
            <thead className="border-b border-line">
              <tr>
                <th scope="col" className={`${TH} text-start`}>
                  {tm('product')}
                </th>
                <th scope="col" className={`${TH} text-end`}>
                  {name(data.base)}
                </th>
                <th scope="col" className={`${TH} text-end`}>
                  {name(data.other)}
                </th>
                <th scope="col" className={`${TH} text-start`}>
                  {t('why')}
                </th>
                <th scope="col" className={TH}>
                  <span className="sr-only">{t('review')}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-line-2 first:border-t-0">
                  <th scope="row" className={`${TD} min-w-48 text-start font-normal`}>
                    <Link
                      href={productHref(locale, r.id, from, 'compare')}
                      className="font-medium text-ink hover:underline focus-visible:outline-2"
                    >
                      <span dir="auto">{r.name}</span>
                    </Link>
                    <span className="block text-xs text-ink-2">
                      <bdi>{r.brand}</bdi>
                    </span>
                  </th>
                  <td className={`${TD} text-end tabular-nums`}>{cell(r.basePrice, r)}</td>
                  <td className={`${TD} text-end tabular-nums`}>{cell(r.otherPrice, r)}</td>
                  <td className={`${TD} min-w-56 text-ink-2`}>
                    <WhyNot r={r} data={data} name={name} />
                  </td>
                  <td className={`${TD} text-end whitespace-nowrap`}>
                    <Link
                      href={productHref(locale, r.id, from, 'compare')}
                      aria-label={`${t('review')}: ${r.name}`}
                      className="text-accent hover:underline focus-visible:outline-2"
                    >
                      {t('review')} ›
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
