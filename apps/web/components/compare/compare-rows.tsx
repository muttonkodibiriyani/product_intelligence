'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import { productHref } from '../explore/product-table';
import { GapView } from '../ui/pair';
import { Money } from '../ui/money';

const TH = 'th whitespace-nowrap';
const TD = 'px-3 py-2.5 align-top';

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
  if (data.rows.length === 0) return <p className="panel px-4 py-3 text-sm text-ink-2">{t('noRows')}</p>;
  return (
    <div className="relative overflow-x-auto panel">
      <table className="w-full text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={`${TH} text-start`}>
              {t('product')}
            </th>
            <th scope="col" className={`${TH} text-start`}>
              {t('gap')}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {name(data.base)}
            </th>
            <th scope="col" className={`${TH} text-end`}>
              {name(data.other)}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.id} className="border-t border-line first:border-t-0">
              <th scope="row" className={`${TD} min-w-44 text-start font-normal`}>
                <Link
                  href={productHref(locale, r.id, from, 'compare')}
                  className="text-accent hover:underline focus-visible:outline-2"
                >
                  <span dir="auto">{r.name}</span>
                </Link>
                <span className="block text-xs text-ink-2" dir="auto">
                  {r.brand}
                </span>
              </th>
              <td className={`${TD} min-w-40`}>
                <GapView
                  pair={{ base: data.base, other: data.other, gap: r.gap, excludedReason: r.excludedReason }}
                  name={name}
                />
              </td>
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
