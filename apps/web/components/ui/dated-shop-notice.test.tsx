import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { DatedShopNotice } from './dated-shop-notice';

const NOTE = { en: 'ulta.ae blocked; last collected 2026-10-01', ar: 'ulta.ae محظور؛ آخر جمع 2026-10-01' };
let retailers: { id: string; status: string }[] = [];
let coverage: { id: string; freshness: string | null; note: unknown }[] | undefined;

vi.mock('../use-meta', () => ({
  useRetailerName: () => (id: string) => ({ ulta_ae: 'Ulta', sephora_me: 'Sephora' })[id] ?? id,
  useMeta: () => ({ data: { data: { cutoff: '2026-10-08T22:07:33Z', retailers } } }),
  useCoverage: () => ({ data: coverage && { data: { retailers: coverage } } }),
}));

beforeEach(() => {
  retailers = [
    { id: 'ulta_ae', status: 'partial' },
    { id: 'sephora_me', status: 'supported' },
  ];
  coverage = [
    { id: 'ulta_ae', freshness: '2026-10-01', note: NOTE },
    { id: 'sephora_me', freshness: '2026-10-09', note: null },
  ];
});
afterEach(cleanup);

const show = (shops: string[], locale: 'en' | 'ar' = 'en') =>
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en}>
      <DatedShopNotice shops={shops} />
    </NextIntlClientProvider>,
  );

describe('DatedShopNotice', () => {
  it('dates Ulta to 1 Oct with its reason, and says nothing of a current Sephora', () => {
    const r = show(['ulta_ae', 'sephora_me']);
    const note = r.getByRole('note');
    expect([...note.querySelectorAll('p')].map((p) => p.textContent)).toEqual([
      'Ulta prices as of 1 Oct 2026: ulta.ae blocked; last collected 2026-10-01',
    ]);
  });

  it('control: a windowed Sephora on the cutoff day alone draws no note at all', () => {
    const r = show(['sephora_me']);
    expect(r.queryByRole('note')).toBeNull();
    expect(r.container.textContent).toBe('');
  });

  it('in Arabic, the Arabic reason and Latin digits', () => {
    const r = show(['ulta_ae', 'sephora_me'], 'ar');
    const text = r.getByRole('note').textContent ?? '';
    expect(text).toContain('أسعار Ulta حتى');
    expect(text).toContain('2026');
    expect(text).toContain(NOTE.ar);
    expect(text).not.toMatch(/[٠-٩]/);
  });

  it('without a served reason, ends at the date', () => {
    coverage = [{ id: 'ulta_ae', freshness: '2026-10-01', note: null }];
    expect(show(['ulta_ae']).getByRole('note').textContent).toBe('Ulta prices as of 1 Oct 2026.');
  });

  it('says Ulta is not in this data when the data does not collect it', () => {
    retailers = [
      { id: 'sephora_me', status: 'supported' },
      { id: 'faces_ae', status: 'partial' },
    ];
    coverage = [{ id: 'sephora_me', freshness: '2026-10-09', note: null }];
    expect(show(['sephora_me', 'faces_ae']).getByRole('note').textContent).toBe('Ulta is not in this data.');
  });

  it('a blocked Ulta counts as not in this data', () => {
    retailers = [
      { id: 'ulta_ae', status: 'blocked' },
      { id: 'sephora_me', status: 'supported' },
    ];
    expect(show(['sephora_me']).getByRole('note').textContent).toBe('Ulta is not in this data.');
  });

  it('dates nothing before /coverage loads', () => {
    coverage = undefined;
    expect(show(['ulta_ae', 'sephora_me']).queryByRole('note')).toBeNull();
  });
});
