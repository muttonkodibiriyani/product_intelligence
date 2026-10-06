'use client';

import { useQuery } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { useCallback, useMemo } from 'react';
import { ApiError } from '@/lib/api/client';
import { byTheme, findingsServed, THEME_OF, type Finding, type Namers } from '@/lib/findings';
import { useAuth } from '../../auth-provider';
import { ErrorNotice } from '../../error-notice';
import { Loading } from '../../ui/skeleton';
import { useMeta, useRetailerName } from '../../use-meta';
import { FindingCard, useFindingText, type Pair } from './finding-card';
import { known } from './known';

/**
 * The Findings: twelve ranked decisions for `focus` against `rival`, from GET /findings (API
 * 1.23.0), above the Insights cards. A strip of tiles (each jumps to its card), then the cards by
 * theme, each keeping its rank. Every word is in the messages; the API sends numbers, names and
 * the reason a finding is withheld. An API without /findings, or a 404, shows nothing: the cards
 * below still stand on their own.
 */
export function FindingsSection({ focus, rival }: { focus: string; rival: string }) {
  const t = useTranslations('insights.findings');
  const { api } = useAuth();
  const meta = useMeta();
  const served = findingsServed(meta.data?.meta.apiVersion);
  const q = useQuery({
    queryKey: ['findings', focus, rival],
    queryFn: ({ signal }) => api!.get('/api/v1/findings', { query: { focus, rival }, signal }),
    enabled: !!api && served === true && focus !== rival,
  });
  const shop = useRetailerName();
  const names = useNames(shop);
  if (served !== true || (q.error instanceof ApiError && q.error.status === 404)) return null;
  const findings = q.data?.data.findings;
  const pair: Pair = {
    focus: q.data?.data.focus ?? focus,
    rival: q.data?.data.rival ?? rival,
    thirds: q.data?.data.thirds ?? [],
  };
  return (
    <section aria-labelledby="findings-title" className="panel px-4 py-5 sm:px-6">
      <h2 id="findings-title" className="text-xl font-semibold">
        {t('title')}
      </h2>
      <p className="mt-0.5 mb-5 text-sm text-ink-2">
        {t('intro', { focus: shop(focus), rival: shop(rival) })}
      </p>
      {q.isError ? (
        <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />
      ) : !findings ? (
        <Loading kind="table" rows={4}>
          {t('loading')}
        </Loading>
      ) : (
        <>
          <Glance findings={findings} names={names} pair={pair} />
          {byTheme(findings).map(([theme, fs]) => (
            <section key={theme} aria-labelledby={`findings-${theme}`} className="mt-7">
              <h3
                id={`findings-${theme}`}
                className="mb-2.5 border-b border-line pb-1.5 text-[13px] font-semibold tracking-[.08em] text-ink-2 uppercase rtl:text-sm rtl:tracking-normal rtl:normal-case"
              >
                {t(`themes.${theme}`)}
              </h3>
              <div className="space-y-3.5">
                {fs.map((f) => (
                  <FindingCard key={f.key} finding={f} names={names} pair={pair} />
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </section>
  );
}

/** Shop ids and category codes as the page names them. */
function useNames(shop: (id: string) => string): Namers {
  const tc = useTranslations('insights.findings.codes');
  const category = useCallback((code: string) => known(tc, '', code), [tc]);
  return useMemo(() => ({ shop, category }), [shop, category]);
}

/** The summary strip: one tile per finding, theme order, each a link to its card. */
function Glance({ findings, names, pair }: { findings: readonly Finding[]; names: Namers; pair: Pair }) {
  const t = useTranslations('insights.findings');
  const ordered = byTheme(findings).flatMap(([, fs]) => fs);
  return (
    <nav aria-labelledby="findings-glance">
      <p
        id="findings-glance"
        className="mb-2 text-xs font-semibold tracking-[.06em] text-ink-2 uppercase rtl:text-[13px] rtl:tracking-normal rtl:normal-case"
      >
        {t('glance')} <span className="font-normal tracking-normal normal-case">· {t('glanceHint')}</span>
      </p>
      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {ordered.map((f) => (
          <Tile key={f.key} finding={f} names={names} pair={pair} />
        ))}
      </ol>
    </nav>
  );
}

function Tile({ finding: f, names, pair }: { finding: Finding; names: Namers; pair: Pair }) {
  const t = useTranslations('insights.findings');
  const text = useFindingText(f, names, pair);
  return (
    <li>
      <a
        href={`#${text.id}`}
        className="flex h-full flex-col gap-0.5 rounded-lg border border-line bg-surface-2 px-3 py-2.5 hover:border-ink"
      >
        <span className="text-[11px] tracking-[.05em] text-ink-2 uppercase rtl:text-xs rtl:tracking-normal rtl:normal-case">
          {t(`themes.${THEME_OF[f.key]}`)} · {t('rank', { rank: f.rank })}
        </span>
        <strong className={`leading-tight tabular-nums ${text.kpi ? 'text-2xl' : 'text-base text-ink-2'}`}>
          {text.kpi ? <bdi>{text.kpi}</bdi> : t('withheldTile')}
        </strong>
        <span className="text-[13px] leading-snug">{text.tile}</span>
      </a>
    </li>
  );
}
