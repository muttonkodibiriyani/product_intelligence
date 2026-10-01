'use client';

import { useQuery } from '@tanstack/react-query';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { Localized } from '@/lib/api/types';
import { useAuth } from './auth-provider';
import { ErrorNotice } from './error-notice';

/** Localised text with English as the fallback when a translation is missing. */
export function loc(l: Partial<Localized> | null | undefined, locale: string): string {
  return (locale === 'ar' ? l?.ar : undefined) ?? l?.en ?? '';
}

function formatDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-AE' : 'en-GB', {
    dateStyle: 'medium',
    timeZone: 'UTC',
    numberingSystem: 'latn',
  }).format(new Date(iso));
}

/** What data the app is looking at. Every value is shown as the API sent it. */
export function DatasetStatus() {
  const t = useTranslations('home');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['meta'],
    queryFn: ({ signal }) => api!.get('/api/v1/meta', { signal }),
    enabled: !!api,
  });

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
      <h1 id="ds-title" className="text-xl font-semibold">
        {t('title')}
      </h1>
      {env.status === 'not_enough_data' && env.reason && (
        <p className="mt-2 text-sm text-ink-2">{loc(env.detail, locale) || tr(env.reason)}</p>
      )}
      {m && (
        <>
          {m.test && (
            <p className="mt-2 inline-block rounded bg-warn-bg px-2 py-0.5 text-sm text-warn">
              {t('testData')}
            </p>
          )}
          <dl className="mt-4 grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <Row k={t('vertical')}>
              <Value t={t} v={m.vertical} />
            </Row>
            <Row k={t('kind')}>
              <Value t={t} v={m.kind} />
            </Row>
            <Row k={t('cutoff')}>
              <time dateTime={m.cutoff}>{formatDate(m.cutoff, locale)}</time>
            </Row>
            <Row k={t('days')}>
              <span className="tabular-nums">{m.dates.length}</span>
            </Row>
            <Row k={t('matchStage')}>
              <Value t={t} v={m.matchStage} />
            </Row>
          </dl>
          <h2 className="mt-8 text-base font-semibold">{t('retailers')}</h2>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full max-w-3xl text-sm">
              <tbody>
                {m.retailers.map((r) => (
                  <tr key={r.id} className="border-t border-line">
                    <th scope="row" className="py-2 pe-6 text-start font-medium whitespace-nowrap">
                      {r.name}
                    </th>
                    <td className="py-2 pe-6">{t(`status.${r.status}`)}</td>
                    <td className="py-2 pe-6 whitespace-nowrap text-ink-2">
                      {r.since ? t('since', { date: formatDate(r.since, locale) }) : t('notCollected')}
                    </td>
                    <td className="py-2 text-ink-2" dir="auto">
                      {loc(r.note, locale)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

/** A known value in the user's language; an unknown one exactly as the API sent it. */
function Value({ t, v }: { t: ReturnType<typeof useTranslations>; v: string }) {
  const key = `values.${v}`;
  return t.has(key) ? (
    <>{t(key)}</>
  ) : (
    <span lang="en" dir="ltr">
      {v}
    </span>
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
