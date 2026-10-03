'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { Price } from '../ui/money';
import { MatchReviewLabel } from '../ui/product-card';
import { Tip } from '../ui/tip';
import { pct } from '../widgets/model';
import { CheaperPill, Difference, ProductCell, type Matched } from './compare-rows';
import { confidencePct, gapShare, isUnreviewed } from './model';
import { RetailerDot } from './pair-picker';

type Comparison = Schemas['Comparison'];
type Name = (id: string) => string;

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-top';

/** "Exact · Locked", with how the pair was matched (class, review, who decided, method, confidence) on hover or focus. */
export function MatchEvidence({
  match,
  at = 'end',
}: {
  match: Schemas['RowMatch'] | null | undefined;
  at?: 'start' | 'end';
}) {
  const t = useTranslations('overlap');
  const locale = useLocale();
  if (!match) return <span className="text-ink-2">–</span>;
  // A class or state the app has no words for yet reads as the API sent it.
  const word = (k: 'class' | 'review', v: string) =>
    /^[a-z_]+$/.test(v) && t.has(`${k}.${v}`) ? t(`${k}.${v}` as 'class.exact') : v;
  const cls = word('class', match.matchClass);
  const review = word('review', match.reviewState);
  const conf = confidencePct(match.confidence);
  const lines = [
    t('evidence.class', { v: cls }),
    t('evidence.review', { v: review }),
    match.decidedBy && t(`evidence.${match.decidedBy}`),
    t('evidence.method', { v: match.method }),
    conf && t('evidence.confidence', { v: pct(conf, locale) }),
  ].filter(Boolean);
  return (
    <Tip
      at={at}
      className="w-fit"
      text={lines.map((l, i) => (
        <span key={i} className="block">
          {l}
        </span>
      ))}
    >
      <span className="whitespace-nowrap text-ink-2 underline decoration-dotted underline-offset-4">
        {cls} · {review}
      </span>
    </Tip>
  );
}

/**
 * Every pair sold at both shops, in the API's order (biggest gap first): a table on a wide screen,
 * a list on a phone. An unreviewed pair carries its label under the name.
 */
export function OverlapRows({
  rows,
  data,
  name,
  from,
}: {
  rows: readonly Matched[];
  data: Pick<Comparison, 'base' | 'other'>;
  name: Name;
  from: string;
}) {
  const t = useTranslations('compare.matched');
  const to = useTranslations('overlap');
  const locale = useLocale();
  const share = (r: Matched) => gapShare(r.gap.pct, rows);
  const price = (m: Matched['basePrice']) => (
    <Price of={{ price: m }} locale={locale} fallback={<span className="text-ink-2">–</span>} />
  );
  const product = (r: Matched) => (
    <ProductCell r={r} locale={locale} from={from} back="overlap">
      <MatchReviewLabel review={isUnreviewed(r) ? 'unreviewed' : null} className="mt-1" />
    </ProductCell>
  );
  return (
    <div className="panel overflow-hidden">
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
              <th scope="col" className={`${TH} text-start`}>
                {to('match')}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-line-2 first:border-t-0">
                <th scope="row" className={`${TD} min-w-56 text-start font-normal`}>
                  {product(r)}
                </th>
                <td className={`${TD} text-end tabular-nums`}>{price(r.basePrice)}</td>
                <td className={`${TD} text-end tabular-nums`}>{price(r.otherPrice)}</td>
                <td className={`${TD} text-end font-semibold tabular-nums`}>
                  <Difference r={r} share={share(r)} locale={locale} />
                </td>
                <td className={TD}>
                  <CheaperPill r={r} data={data} name={name} />
                </td>
                <td className={`${TD} text-sm`}>
                  <MatchEvidence match={r.match} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-line-2 sm:hidden">
        {rows.map((r) => (
          <li key={r.id} className="px-4 py-3 text-sm">
            {product(r)}
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
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <CheaperPill r={r} data={data} name={name} />
              <MatchEvidence match={r.match} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
