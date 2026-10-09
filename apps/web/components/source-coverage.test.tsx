import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import type { CaveatView, Schemas } from '@/lib/api/types';
import { sourceFreshness } from '@/lib/source-freshness';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { SourceCoverage } from './source-coverage';

afterEach(cleanup);

const IDS = ['bloomingdales_ae', 'faces_ae', 'ounass_ae', 'sephora_me', 'ulta_ae'];
const LAST = ['2026-10-08', '2026-10-03', '2026-10-07', '2026-10-01', '2026-10-09'];
const PRODUCTS = [7694, 1457, 32810, 9529, 16868];
const meta = (over: Partial<Record<'retailers' | 'sources', unknown[]>> = {}) =>
  ({
    dates: ['2026-10-01', '2026-10-09'],
    retailers: [
      ...IDS.map((id, i) => ({
        id,
        name: id,
        country: 'AE',
        note: null,
        since: null,
        status: i === 1 ? 'partial' : 'supported',
      })),
      { id: 'later_ae', name: 'Later', country: 'AE', note: null, since: null, status: 'pending' },
      { id: 'quiet_ae', name: 'Quiet', country: 'AE', note: null, since: null, status: 'supported' },
    ],
    sources: [
      ...IDS.map((id, i) => ({
        source: id,
        lastDate: LAST[i],
        products: PRODUCTS[i],
        fields: { price: 'ok', size: 'partial', gtin: 'not_published' },
      })),
      { source: 'odd_ae', lastDate: '2026-13-01', products: 3, fields: {} },
      { source: 'twice_ae', lastDate: '2026-10-01', products: 1, fields: {} },
      { source: 'twice_ae', lastDate: '2026-10-09', products: 2, fields: {} },
    ],
    ...over,
  }) as unknown as Schemas['MetaView'];

const imported: CaveatView[] = [
  { code: 'snapshot_import_date', params: { retailer: 'ulta_ae', date: '2026-10-09' }, en: '', ar: '' },
];

function show(locale: 'en' | 'ar') {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'en' ? en : ar}
      timeZone="UTC"
      onError={(e) => {
        throw e;
      }}
    >
      <div dir={locale === 'ar' ? 'rtl' : 'ltr'}>
        <SourceCoverage sources={sourceFreshness(meta(), imported)} name={(id) => id} />
      </div>
    </NextIntlClientProvider>,
  );
}

const stateOf = (id: string) =>
  document
    .querySelector(`tr[data-source="${id}"] [data-evidence-state]`)
    ?.getAttribute('data-evidence-state');

describe('SourceCoverage', () => {
  it('lists every retailer with all six states, its own date and its own count', () => {
    show('en');
    expect(screen.getByRole('heading', { name: en.freshness.title })).toBeTruthy();
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(9);
    expect(IDS.map(stateOf)).toEqual(['stale', 'stale', 'stale', 'stale', 'mixed']);
    expect(stateOf('later_ae')).toBe('unavailable');
    expect(stateOf('quiet_ae')).toBe('not_observed');
    expect(stateOf('odd_ae')).toBe('invalid');
    expect(stateOf('twice_ae')).toBe('conflict');
    const ulta = document.querySelector('tr[data-source="ulta_ae"]') as HTMLElement;
    expect(within(ulta).getByText('16,868')).toBeTruthy();
    expect(ulta.textContent).toContain('Imported snapshot 9 Oct 2026: capture date unknown.');
    expect(within(ulta).getByText('1 of 3 ok')).toBeTruthy();
    // Every field that is not ok is named with its own status, not folded into the count.
    expect(within(ulta).getByText('1 partly collected')).toBeTruthy();
    expect(within(ulta).getByText('1 not published by the shop')).toBeTruthy();
    // Two sources for one shop: the cells say conflict, never "Not sent".
    const twice = document.querySelector('tr[data-source="twice_ae"]') as HTMLElement;
    expect(twice.querySelectorAll('[data-evidence-state="conflict"]')).toHaveLength(3);
    expect(twice.textContent).not.toContain(en.freshness.productsNone);
    const faces = document.querySelector('tr[data-source="faces_ae"]') as HTMLElement;
    expect(faces.textContent).toContain(en.freshness.partial);
    expect(faces.textContent).toContain('Last observed 3 Oct 2026; the dataset runs to 9 Oct 2026.');
    const quiet = document.querySelector('tr[data-source="quiet_ae"]') as HTMLElement;
    expect(quiet.textContent).toContain(en.freshness.productsNone);
    expect(quiet.textContent).toContain(en.freshness.dateNone);
    // The state is text, not only a colour, and its explanation reaches screen readers.
    const badge = ulta.querySelector('[data-evidence-state]') as HTMLElement;
    // Ulta reaches the last date but carries an imported snapshot: mixed, never "latest".
    expect(badge.textContent).toContain(en.freshness.state.mixed);
    expect(badge.textContent).not.toContain(en.freshness.state.fresh);
    expect(badge.querySelector('.sr-only')?.textContent).toContain('9 Oct 2026');
    expect(screen.getByRole('table').textContent).not.toMatch(/out of stock|removed|delisted/i);
  });

  it('reads in Arabic, right to left, with the same states', () => {
    show('ar');
    expect(screen.getByRole('heading', { name: ar.freshness.title })).toBeTruthy();
    expect(screen.getAllByText(ar.freshness.state.stale)).toHaveLength(4);
    expect(screen.getAllByText(ar.freshness.state.conflict)).toHaveLength(3);
    expect(document.querySelector('[data-field-status="partial"]')?.textContent).toMatch(/جُمعت جزئيًا/);
    expect(screen.getByText(ar.freshness.state.invalid)).toBeTruthy();
    expect(screen.getByText(ar.freshness.state.not_observed)).toBeTruthy();
    expect(screen.getByText(ar.freshness.state.unavailable)).toBeTruthy();
    expect(screen.getByRole('table').closest('[dir]')?.getAttribute('dir')).toBe('rtl');
  });
});

describe('en and ar freshness messages', () => {
  it('have the same keys', () => {
    const keys = (o: object, p = ''): string[] =>
      Object.entries(o).flatMap(([k, v]) =>
        typeof v === 'object' ? keys(v as object, `${p}${k}.`) : [`${p}${k}`],
      );
    expect(keys(ar.freshness).sort()).toEqual(keys(en.freshness).sort());
  });
});
