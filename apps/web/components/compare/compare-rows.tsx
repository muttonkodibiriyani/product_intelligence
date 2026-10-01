'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { GapView } from '../ui/pair';
import { Money } from '../ui/money';

const TH = 'px-3 py-2 text-start font-medium text-ink-2 whitespace-nowrap';
const TD = 'px-3 py-2 align-top';

/** The product page for a row; Back returns to this comparison. */
export function compareProductHref(locale: string, id: string, from: string): string {
  const p = new URLSearchParams({ id, back: 'compare' });
  if (from) p.set('from', from.replace(/^\?/, ''));
  return `/${locale}/product/?${p.toString()}`;
}

/** Every product either side sells, largest gaps first; one not counted says why. */
export function CompareRows({
  data,
  name,
  from,
}: {
  data: Schemas['Comparison'];
  name: (id: string) => string;
  from: string;
}) {
  const t = useTranslations('compare');
  const locale = useLocale();
  if (data.rows.length === 0)
    return (
      <p className="rounded border border-line bg-surface px-3 py-2 text-sm text-ink-2">{t('noRows')}</p>
    );
  return (
    <div className="relative overflow-x-auto rounded border border-line bg-surface">
      <table className="w-full text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={TH}>
              {t('product')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {name(data.base)}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {name(data.other)}
            </th>
            <th scope="col" className={TH}>
              {t('gap')}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.id} className="border-t border-line first:border-t-0">
              <th scope="row" className={`${TD} min-w-48 text-start font-normal`}>
                <Link
                  href={compareProductHref(locale, r.id, from)}
                  className="text-accent hover:underline focus-visible:outline-2"
                >
                  <span dir="auto">{r.name}</span>
                </Link>
                <span className="block text-xs text-ink-2" dir="auto">
                  {r.brand}
                </span>
              </th>
              <td className={`${TD} text-end`}>
                {r.basePrice ? (
                  <Money m={r.basePrice} locale={locale} />
                ) : (
                  <span className="text-ink-2">–</span>
                )}
              </td>
              <td className={`${TD} text-end`}>
                {r.otherPrice ? (
                  <Money m={r.otherPrice} locale={locale} />
                ) : (
                  <span className="text-ink-2">–</span>
                )}
              </td>
              <td className={TD}>
                <GapView
                  pair={{ base: data.base, other: data.other, gap: r.gap, excludedReason: r.excludedReason }}
                  name={name}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
