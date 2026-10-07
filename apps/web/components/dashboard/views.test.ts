import { describe, expect, it } from 'vitest';
import en from '../../messages/en.json';
import ar from '../../messages/ar.json';
import { INSIGHT_KEYS } from '../home/insights';
import { VIEW_KEYS, VIEWS, viewFrom } from './views';

describe('dashboard views', () => {
  it('reads the view from ?view=, and anything else is the leadership summary', () => {
    expect(viewFrom('price')).toBe('price');
    expect(viewFrom('range')).toBe('range');
    expect(viewFrom(null)).toBe('lead');
    expect(viewFrom('')).toBe('lead');
    expect(viewFrom('stockouts')).toBe('lead');
  });

  it('every view draws something, and only charts the Overview can draw', () => {
    for (const k of VIEW_KEYS) {
      const v = VIEWS[k];
      const sections = [v.band, v.headline, v.headToHead, v.byCategory, v.topDiscounts].filter(Boolean);
      expect(sections.length + v.insights.length, k).toBeGreaterThan(0);
      for (const c of v.insights) expect(INSIGHT_KEYS).toContain(c);
    }
  });

  it('every view has a name and an intro in English and Arabic', () => {
    for (const m of [en, ar])
      for (const k of VIEW_KEYS) {
        expect(m.dashboard.views[k].name).toBeTruthy();
        expect(m.dashboard.views[k].intro).toBeTruthy();
      }
  });
});
