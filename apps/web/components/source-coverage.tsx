'use client';

import { useLocale, useTranslations } from 'next-intl';
import { formatCount, formatDate } from '@/lib/format';
import type { SourceFreshness } from '@/lib/source-freshness';
import { SourceBadge, StateBadge, useFreshnessDetail } from './ui/freshness';

const NOT_OK = ['partial', 'not_collected', 'not_published', 'parse_failure', 'blocked'] as const;

/**
 * Every retailer's own source as /meta sent it: its state, its own last observation date, its
 * product count and how many of its declared fields are fully collected. A retailer with no
 * source keeps its row and says so; nothing is filled from another retailer.
 */
export function SourceCoverage({
  sources,
  name,
  heading: H = 'h2',
}: {
  sources: readonly SourceFreshness[];
  name: (id: string) => string;
  heading?: 'h2' | 'h3';
}) {
  const t = useTranslations('freshness');
  const locale = useLocale();
  const detail = useFreshnessDetail();
  const th = 'th whitespace-nowrap text-start';
  return (
    <section id="source-coverage" aria-labelledby="source-coverage-title" className="mt-8">
      <H id="source-coverage-title" className="text-base font-semibold">
        {t('title')}
      </H>
      <p className="mt-1 max-w-prose text-sm text-ink-2">{t('intro')}</p>
      <div className="relative mt-2 overflow-x-auto">
        <table className="w-full max-w-4xl text-sm">
          <thead className="border-b border-line">
            <tr>
              <th scope="col" className={th}>
                {t('colShop')}
              </th>
              <th scope="col" className={th}>
                {t('colState')}
              </th>
              <th scope="col" className={th}>
                {t('colLast')}
              </th>
              <th scope="col" className={`${th} text-end`}>
                {t('colProducts')}
              </th>
              <th scope="col" className={th}>
                {t('colFields')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => {
              const n = Object.values(s.fields).reduce((a, b) => a + (b ?? 0), 0);
              return (
                <tr key={s.retailer} data-source={s.retailer} className="border-t border-line align-top">
                  <th scope="row" className="py-2 pe-6 text-start font-medium whitespace-nowrap">
                    {name(s.retailer)}
                    {s.status === 'partial' && (
                      <span className="block text-xs font-normal text-ink-2">{t('partial')}</span>
                    )}
                  </th>
                  <td className="py-2 pe-6">
                    <SourceBadge source={s} />
                    <span className="mt-1 block max-w-64 text-xs text-ink-2">{detail(s)}</span>
                  </td>
                  <td className="py-2 pe-6 whitespace-nowrap">
                    {s.lastDate ? (
                      <time dateTime={s.lastDate}>{formatDate(s.lastDate, locale)}</time>
                    ) : (
                      <span className="text-ink-3">{t('dateNone')}</span>
                    )}
                  </td>
                  <td className="py-2 pe-6 text-end tabular-nums">
                    {s.state === 'conflict' ? (
                      <StateBadge state="conflict" />
                    ) : s.products == null ? (
                      <span className="text-ink-3">{t('productsNone')}</span>
                    ) : (
                      formatCount(s.products, locale)
                    )}
                  </td>
                  <td className="py-2 text-ink-2 tabular-nums">
                    {s.state === 'conflict' ? (
                      <StateBadge state="conflict" />
                    ) : n ? (
                      <>
                        {t('fields', { ok: s.fields.ok ?? 0, n })}
                        {NOT_OK.filter((k) => s.fields[k]).map((k) => (
                          <span key={k} data-field-status={k} className="block text-xs">
                            {t(`fieldStatus.${k}`, { n: s.fields[k] ?? 0 })}
                          </span>
                        ))}
                      </>
                    ) : (
                      <span className="text-ink-3">{t('fieldsNone')}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
