import { describe, expect, it } from 'vitest';
import { aboutDataHref, datasetHref, NAV_KEYS, navHref, navMatches, navState, TABBAR_KEYS } from './nav';

describe('nav routes', () => {
  it('builds locale-prefixed, trailing-slash hrefs; About the data is a section of the Dataset page', () => {
    expect(navHref('overview', 'en')).toBe('/en/');
    expect(navHref('explore', 'ar')).toBe('/ar/explore/');
    expect(navHref('dashboard', 'ar')).toBe('/ar/dashboard/');
    expect(navHref('assistant', 'en')).toBe('/en/assistant/');
    expect(datasetHref('ar')).toBe('/ar/dataset/');
    expect(aboutDataHref('en')).toBe('/en/dataset/#about-data');
  });

  it('marks the current page, with a product page under Products', () => {
    expect(navMatches('overview', '/en/')).toBe(true);
    expect(navMatches('overview', '/ar')).toBe(true);
    expect(navMatches('overview', '/en/explore/')).toBe(false);
    expect(navMatches('overview', '/en/dashboard/')).toBe(false);
    expect(navMatches('dashboard', '/ar/dashboard/')).toBe(true);
    expect(navMatches('explore', '/en/product/')).toBe(true);
    expect(navMatches('launches', '/ar/launches/')).toBe(true);
    expect(navMatches('dataset', '/en/dataset/')).toBe(true);
    expect(navMatches('dataset', '/en/')).toBe(false);
  });

  it('the tab bar is five pages, all of them nav pages', () => {
    expect(TABBAR_KEYS).toHaveLength(5);
    for (const k of TABBAR_KEYS) expect(NAV_KEYS).toContain(k);
  });
});

describe('navState', () => {
  it('shows every page but Insights and Gaps while nothing is known yet', () => {
    for (const k of NAV_KEYS)
      expect(navState(k, {})).toBe(k === 'insights' || k === 'gaps' ? 'hidden' : 'shown');
  });

  it('Insights shows only once /meta says the API serves it', () => {
    expect(navState('insights', { insightsServed: true })).toBe('shown');
    expect(navState('insights', { insightsServed: false })).toBe('hidden');
    expect(navState('insights', {})).toBe('hidden');
  });

  it('Gaps shows only once /meta says the API serves brand gaps', () => {
    expect(navState('gaps', { gapsServed: true, insightsServed: false })).toBe('shown');
    expect(navState('gaps', { gapsServed: false, insightsServed: true })).toBe('hidden');
    expect(navState('gaps', {})).toBe('hidden');
  });

  it('Overview, Compare, Dataset and the assistant always show', () => {
    const none = { priced: [0, null], promoMeasured: false, launchesReady: false };
    for (const k of ['overview', 'compare', 'dataset', 'assistant'] as const)
      expect(navState(k, none)).toBe('shown');
  });

  it('Products and Prices need one retailer with priced products', () => {
    expect(navState('explore', { priced: [0, 4790] })).toBe('shown');
    expect(navState('prices', { priced: [null, 12] })).toBe('shown');
    expect(navState('explore', { priced: [0, null] })).toBe('hidden');
    expect(navState('prices', { priced: [] })).toBe('hidden');
  });

  it('Promotions need a retailer whose discounts are measured', () => {
    expect(navState('promotions', { promoMeasured: true })).toBe('shown');
    expect(navState('promotions', { promoMeasured: false })).toBe('hidden');
  });

  it('Launches is "soon" while a shop is short of the collection days a launch needs, never hidden', () => {
    expect(navState('launches', { launchesReady: true })).toBe('shown');
    expect(navState('launches', { launchesReady: false })).toBe('soon');
    expect(navState('launches', {})).toBe('shown');
  });
});
