'use client';

import { usePathname } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import {
  NAV_KEYS,
  navHref,
  navMatches,
  navState,
  type NavKey,
  type NavSignals,
  type NavState,
} from '@/lib/nav';
import { launchReadiness } from './launches/readiness';
import { useMeta } from './use-meta';
import { promotions } from './widgets/model';
import { useRetailers } from './widgets/use-compare';
import { useSummaries } from './widgets/use-summaries';

export interface NavItem {
  key: NavKey;
  href: string;
  label: string;
  state: Exclude<NavState, 'hidden'>;
  current: boolean;
}

/**
 * The nav items the data allows, in order, with the current one marked. The signals come from
 * /meta and each retailer's /summary, the same cached requests the Overview makes; a page stays
 * listed until the data says otherwise, so the nav never flickers on load.
 */
export function useNav(): NavItem[] {
  const t = useTranslations('app');
  const locale = useLocale();
  const pathname = usePathname();
  const meta = useMeta();
  const { ids } = useRetailers();
  const { rows, loading, error } = useSummaries(ids);
  const signals: NavSignals = {};
  if (meta.data) signals.launchesReady = launchReadiness(meta.data).allReady;
  if (ids.length > 0 && !loading && !error) {
    signals.priced = rows.map((r) => r.data.priced);
    signals.promoMeasured = rows.some((r) => promotions(r.data).measured);
  }
  const items: NavItem[] = [];
  for (const key of NAV_KEYS) {
    const state = navState(key, signals);
    if (state === 'hidden') continue;
    const label = key === 'dataset' ? t('nav.status') : t(`nav.${key}`);
    items.push({ key, href: navHref(key, locale), label, state, current: navMatches(key, pathname) });
  }
  return items;
}
