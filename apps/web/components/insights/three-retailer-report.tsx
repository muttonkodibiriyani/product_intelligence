'use client';

import { useQueries } from '@tanstack/react-query';
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import type { Envelope } from '@/lib/api/types';
import type { Insights } from '@/lib/insights';
import { insightsServed, INSIGHTS_API } from '@/lib/insights';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { useMeta, useRetailerName } from '../use-meta';
import { activeRetailers, compareHref } from '../widgets/model';
import { Card, CardGrid } from '../ui/card';
import { Loading } from '../ui/skeleton';
import { RetailerDot } from '../ui/retailer-dot';
import { PageHeader } from '../ui/page-header';

type Pair = { base: string; other: string };

export function threeRetailerPairs(ids: string[]): Pair[] {
  return ids.flatMap((base, i) => ids.slice(i + 1).map((other) => ({ base, other })));
}

/**
 * P1 three-retailer report. The service contract is pair-based, so this view deliberately presents
 * three independent, governed pair slices. It never adds or ranks pair numbers as a three-way fact.
 */
export function ThreeRetailerReport() {
  const t = useTranslations('insights.p1');
  const locale = useLocale();
  const { api } = useAuth();
  const meta = useMeta();
  const ids = activeRetailers(meta.data?.data).slice(0, 3);
  const name = useRetailerName();
  const selected = threeRetailerPairs(ids);
  const served = insightsServed(meta.data);
  const results = useQueries({
    queries: selected.map((pair) => ({
      queryKey: ['insights-p1', pair.base, pair.other],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api!.get('/api/v1/insights', { query: { retailers: `${pair.base},${pair.other}` }, signal }),
      enabled: !!api && served === true,
    })),
  });

  if (served === undefined || meta.isLoading)
    return (
      <Loading kind="table" rows={5}>
        {t('loading')}
      </Loading>
    );
  if (served === false)
    return (
      <div role="note" className="panel px-5 py-6 text-sm text-ink-2">
        {t('unavailable', { need: INSIGHTS_API })}
      </div>
    );
  if (ids.length < 3)
    return (
      <div role="note" className="panel px-5 py-6 text-sm text-ink-2">
        {t('notEnough')}
      </div>
    );
  const failed = results.find((r) => r.isError);
  if (failed?.error)
    return (
      <ErrorNotice error={failed.error} onRetry={() => void Promise.all(results.map((r) => r.refetch()))} />
    );
  const loaded = results.every((r) => r.data);
  return (
    <section aria-labelledby="three-retailer-title" className="space-y-5">
      <PageHeader id="three-retailer-title" title={t('title')} intro={t('intro')} />
      <div className="panel border-accent/30 bg-accent/5 px-5 py-4 text-sm">
        <p className="font-semibold">{t('basisTitle')}</p>
        <p className="mt-1 text-ink-2">{t('basis')}</p>
        <p className="mt-2 text-xs text-ink-2">{t('imageNote')}</p>
      </div>
      {!loaded ? (
        <Loading kind="table" rows={5}>
          {t('loading')}
        </Loading>
      ) : (
        <CardGrid>
          <Card title={t('coverageTitle')} span={12} question={t('coverageQuestion')}>
            <div className="grid gap-3 sm:grid-cols-3">
              {ids.map((id, i) => {
                const r = meta.data?.data?.retailers.find((x) => x.id === id);
                return (
                  <div key={id} className="rounded-ctl border border-line bg-surface-2 px-4 py-3 text-sm">
                    <div className="flex items-center gap-2 font-semibold">
                      <RetailerDot id={id} index={i} />
                      {name(id)}
                    </div>
                    <p className="mt-1 text-ink-2">
                      {t(`status.${r?.status ?? 'pending'}` as 'status.supported')}
                    </p>
                  </div>
                );
              })}
            </div>
          </Card>
          {selected.map((pair, i) => {
            const env = results[i]!.data as Envelope<Insights>;
            const pricing = env.data?.pricing;
            return (
              <Card
                key={`${pair.base}-${pair.other}`}
                span={4}
                title={`${name(pair.base)} × ${name(pair.other)}`}
                question={t('pairQuestion')}
              >
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between gap-3">
                    <dt className="text-ink-2">{t('matched')}</dt>
                    <dd className="font-semibold tabular-nums">{pricing?.n ?? 0}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-ink-2">{t('unreviewed')}</dt>
                    <dd className="font-semibold tabular-nums">{pricing?.unreviewed ?? 0}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-ink-2">{t('statusLabel')}</dt>
                    <dd>{pricing?.status === 'ok' ? t('counted') : t('withheld')}</dd>
                  </div>
                </dl>
                <Link
                  className="mt-4 inline-block text-accent underline-offset-2 hover:underline"
                  href={compareHref(locale, pair)}
                >
                  {t('openEvidence')}
                </Link>
              </Card>
            );
          })}
        </CardGrid>
      )}
    </section>
  );
}
