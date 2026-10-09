'use client';

import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import { formatDate, loc } from '@/lib/format';
import { retailerName } from '@/lib/retailers';
import { sourceFreshness } from '@/lib/source-freshness';
import { ErrorNotice } from './error-notice';
import { SourceCoverage } from './source-coverage';
import { useMeta } from './use-meta';
import { EnvNotes } from './ui/env-notes';
import { Known } from './ui/known';
import { importedOn } from './widgets/model';

/**
 * What data the app is looking at. Every value is shown as the API sent it, each shop by its own
 * name. "About the data" at the end is the one place on the site that explains, in plain words,
 * how the data is collected and why a figure may be missing. `nested` when it sits in a card under
 * the page's own heading.
 */
export function DatasetStatus({ nested = false }: { nested?: boolean } = {}) {
  const H = nested ? 'h2' : 'h1';
  const H2 = nested ? 'h3' : 'h2';
  const t = useTranslations('home');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const q = useMeta();

  if (q.isError) return <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data)
    return (
      <p role="status" aria-busy className="text-ink-2">
        {t('loading')}
      </p>
    );

  const env = q.data;
  const m = env.data;
  return (
    <section aria-labelledby="ds-title">
      <H id="ds-title" className={nested ? 'text-base font-semibold' : 'text-2xl font-bold tracking-tight'}>
        {t('title')}
      </H>
      {!nested && <p className="mt-1 max-w-prose text-sm text-ink-2">{t('intro')}</p>}
      {env.status === 'not_enough_data' && env.reason && (
        <p className="mt-2 text-sm text-ink-2">
          {loc(env.detail, locale) || <Known t={tr} v={env.reason} />}
        </p>
      )}
      {m && (
        <>
          {m.test && <p className="mt-2 pill bg-butter text-butter-ink">{t('testData')}</p>}
          <dl className="mt-4 grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <Row k={t('vertical')}>
              <Known t={t} k="values" v={m.vertical} />
            </Row>
            <Row k={t('kind')}>
              <Known t={t} k="values" v={m.kind} />
            </Row>
            <Row k={t('cutoff')}>
              {/* With an imported retailer, the cutoff covers the collected retailers only. */}
              <time dateTime={m.cutoff}>
                {env.caveats.some((c) => c.code === 'snapshot_import_date')
                  ? t('cutoffCollected', { date: formatDate(m.cutoff, locale) })
                  : formatDate(m.cutoff, locale)}
              </time>
            </Row>
            <Row k={t('days')}>
              <span className="tabular-nums">{m.dates.length}</span>
            </Row>
            <Row k={t('matchStage')}>
              <Known t={t} k="values" v={m.matchStage} />
            </Row>
          </dl>
          <H2 className="mt-8 text-base font-semibold">{t('retailers')}</H2>
          <div className="relative mt-2 overflow-x-auto">
            <table className="w-full max-w-3xl text-sm">
              <tbody>
                {m.retailers.map((r) => {
                  // An imported retailer has an import date, not a collection start.
                  const imported = importedOn(env.caveats, r.id);
                  return (
                    <tr key={r.id} className="border-t border-line">
                      <th scope="row" className="py-2 pe-6 text-start font-medium whitespace-nowrap">
                        {retailerName(r.id, r.name, locale)}
                      </th>
                      <td className="py-2 pe-6">
                        <Known t={t} k="status" v={r.status} />
                      </td>
                      <td className="py-2 pe-6 whitespace-nowrap text-ink-2">
                        {imported
                          ? t('imported', { date: formatDate(imported, locale) })
                          : r.since
                            ? t('since', { date: formatDate(r.since, locale) })
                            : t('notCollected')}
                      </td>
                      <td className="py-2 text-ink-2" dir="auto">
                        {loc(r.note, locale)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <SourceCoverage
            sources={sourceFreshness(m, env.caveats)}
            name={(id) => retailerName(id, m.retailers.find((r) => r.id === id)?.name, locale)}
            heading={H2}
          />
        </>
      )}
      <section id="about-data" aria-labelledby="about-data-title" className="mt-8 scroll-mt-6">
        <H2 id="about-data-title" className="text-base font-semibold">
          {t('about.title')}
        </H2>
        <div className="mt-2 max-w-prose space-y-2 text-sm text-ink-2">
          <p>{t('about.p1')}</p>
          <p>{t('about.p2')}</p>
          <p>{t('about.p3')}</p>
        </div>
        {/* The API's own notes on this collection, worded with shop names: the only note box on the site. */}
        {(env.status === 'not_enough_data' || env.caveats.length > 0) && (
          <>
            <p className="mt-4 text-sm font-medium">{t('about.notes')}</p>
            <EnvNotes env={env} className="mt-2 max-w-prose" />
          </>
        )}
      </section>
    </section>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-2">{k}</dt>
      <dd className="text-ink">{children}</dd>
    </>
  );
}
