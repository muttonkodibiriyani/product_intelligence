import { describe, expect, it } from 'vitest';
import { datasetHref, NAV_KEYS, navHref, navMatches, navState, TABBAR_KEYS } from './nav';

describe('nav routes', () => {
  it('builds locale-prefixed, trailing-slash hrefs; the Dataset is an anchor on the Overview', () => {
    expect(navHref('overview', 'en')).toBe('/en/');
    expect(navHref('explore', 'ar')).toBe('/ar/explore/');
    expect(navHref('assistant', 'en')).toBe('/en/assistant/');
    expect(datasetHref('ar')).toBe('/ar/#dataset');
  });

  it('marks the current page, with a product page under Products and the Dataset never current', () => {
    expect(navMatches('overview', '/en/')).toBe(true);
    expect(navMatches('overview', '/ar')).toBe(true);
    expect(navMatches('overview', '/en/explore/')).toBe(false);
    expect(navMatches('explore', '/en/product/')).toBe(true);
    expect(navMatches('launches', '/ar/launches/')).toBe(true);
    expect(navMatches('dataset', '/en/')).toBe(false);
  });

  it('the tab bar is five pages, all of them nav pages', () => {
    expect(TABBAR_KEYS).toHaveLength(5);
    for (const k of TABBAR_KEYS) expect(NAV_KEYS).toContain(k);
  });
});

describe('navState', () => {
  it('shows every page while nothing is known yet', () => {
    for (const k of NAV_KEYS) expect(navState(k, {})).toBe('shown');
  });

  it('Overview, Compare, Dataset and the assistant always show', () => {
    const none = { priced: [0, null], promoMeasured: false, collectionDays: 1, oneOff: true };
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

  it('Launches is "soon" until two collection days and no one-off import', () => {
    expect(navState('launches', { collectionDays: 3, oneOff: false })).toBe('shown');
    expect(navState('launches', { collectionDays: 1, oneOff: false })).toBe('soon');
    expect(navState('launches', { collectionDays: 3, oneOff: true })).toBe('soon');
    expect(navState('launches', { collectionDays: 1 })).toBe('soon');
    expect(navState('launches', { oneOff: true })).toBe('soon');
    expect(navState('launches', { oneOff: false })).toBe('shown');
  });
});
