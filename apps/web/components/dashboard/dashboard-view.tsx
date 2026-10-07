'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { ErrorNotice } from '../error-notice';
import { AsOf } from '../home/as-of';
import { Band } from '../home/band';
import { Insights } from '../home/insights';
import { Headline, TopDiscounts } from '../home/landing';
import { useLaunchCounts, usePromoShares } from '../home/use-overview-data';
import { ByCategory, HeadToHead } from '../prices/prices-view';
import { AboutDataLink, PageHeader } from '../ui/page-header';
import { Segmented } from '../ui/segmented';
import { Loading } from '../ui/skeleton';
import { useCategoryCompare } from '../widgets/use-category';
import { useCompareData, useRetailers } from '../widgets/use-compare';
import { useSummaries } from '../widgets/use-summaries';
import { VIEW_KEYS, VIEWS, viewFrom, type View, type ViewKey } from './views';

type Pair = NonNullable<ReturnType<typeof useRetailers>['pair']>;

/**
 * The dashboard: one preset view at a time (leadership, pricing, promotions, range), each built
 * from the sections the rest of the app draws, so every number keeps its chips, its empty state
 * and its link to the list it was counted from. The view is in the URL, so a view is a link.
 */
export function DashboardView() {
  const t = useTranslations('dashboard');
  const sp = useSearchParams();
  const view = viewFrom(sp.get('view'));
  const { ids, pair, loading, error } = useRetailers();
  const s = useSummaries(ids);

  // Only the query changes, so the history API is enough (as on Prices): no page payload to fetch.
  const pick = (v: ViewKey) => {
    const q = new URLSearchParams(sp.toString());
    if (v === VIEW_KEYS[0]) q.delete('view');
    else q.set('view', v);
    const qs = q.toString();
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        id="dashboard-title"
        title={t('title')}
        intro={<p>{t(`views.${view}.intro`)}</p>}
        asOf={s.rows.length > 0 ? <AsOf rows={s.rows} /> : undefined}
        tools={
          <Segmented
            label={t('view')}
            value={view}
            options={VIEW_KEYS.map((v) => ({ value: v, label: t(`views.${v}.name`) }))}
            onChange={pick}
          />
        }
      />
      {error ? (
        <ErrorNotice error={error} />
      ) : loading ? (
        <Loading kind="chart">{t('loading')}</Loading>
      ) : (
        <Body key={view} view={VIEWS[view]} s={s} ids={ids} pair={pair} />
      )}
    </div>
  );
}

function Body({
  view,
  s,
  ids,
  pair,
}: {
  view: View;
  s: ReturnType<typeof useSummaries>;
  ids: readonly string[];
  pair: Pair | null;
}) {
  const t = useTranslations('dashboard');
  const tc = useTranslations('card');
  const locale = useLocale();
  // Each read is asked for only when the view draws what it feeds; a null pair or no ids asks nothing.
  const cmp = useCompareData(view.headline ? pair : null, 'category');
  const cat = useCategoryCompare(view.insights.includes('gaps') ? pair : null);
  const promo = usePromoShares();
  const launches = useLaunchCounts(view.band || view.insights.includes('launches') ? ids : []);

  if (s.error && s.rows.length === 0) return <ErrorNotice error={s.error.error} onRetry={s.error.retry} />;
  if (s.loading && s.rows.length === 0) return <Loading kind="chart">{tc('loading')}</Loading>;
  // Nothing to report on (every retailer withheld or thin): one line, and the Dataset page says why.
  if (s.rows.length === 0)
    return (
      <p className="text-sm text-ink-2">
        {t('noRetailers')} <AboutDataLink />
      </p>
    );

  return (
    <div className="space-y-6">
      {view.band && (
        <section aria-labelledby="dashboard-band-title">
          <h2 id="dashboard-band-title" className="sr-only">
            {t('numbers')}
          </h2>
          <Band rows={s.rows} promo={promo} launches={launches.shops} />
        </section>
      )}
      {view.headline && pair && <Headline pair={pair} cmp={cmp} />}
      {view.headToHead && pair && <HeadToHead pair={pair} locale={locale} />}
      {view.byCategory && pair && <ByCategory pair={pair} locale={locale} />}
      {(view.headToHead || view.byCategory) && !pair && <p className="text-sm text-ink-2">{t('onePair')}</p>}
      <Insights rows={s.rows} pair={pair} cat={cat} launches={launches} show={view.insights} />
      {view.topDiscounts && <TopDiscounts rows={s.rows} />}
    </div>
  );
}
