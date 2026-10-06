import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import type { Envelope, Schemas } from '@/lib/api/types';
import { toOverlapQuery } from '@/lib/compare';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { confidencePct, isUnreviewed, overlapOptions, overlapRows } from './model';
import { MatchEvidence, OverlapRows } from './overlap-rows';

type Comparison = Schemas['Comparison'];

// shop_a vs shop_b, rows=overlap&sort=gap: 6 reviewed pairs and p07, an unreviewed exact pair.
const overlap = JSON.parse(
  readFileSync(join(__dirname, '../../../../docs/contracts/golden/pi-api/compare-overlap.json'), 'utf8'),
) as Envelope<Comparison>;
const data = overlap.data!;
const rows = overlapRows(data.rows);
const name = (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id;

function show(ui: React.ReactNode, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
      {ui}
    </NextIntlClientProvider>,
  );
}

afterEach(cleanup);

describe('overlap model', () => {
  it('asks for every overlap row, biggest gap first, with the filters and nothing else', () => {
    expect(toOverlapQuery({ base: 'shop_a', other: 'shop_b', brand: [], category: [] })).toEqual({
      retailers: 'shop_a,shop_b',
      rows: 'overlap',
      sort: 'gap',
      limit: 500,
    });
    expect(
      toOverlapQuery({ base: 'shop_a', other: 'shop_b', brand: ['Sample Labs'], category: ['skincare'] }),
    ).toMatchObject({ brand: ['Sample Labs'], category: ['skincare'], rows: 'overlap' });
  });

  it('keeps every golden row (each has a gap) in the API order, and finds the one unreviewed pair', () => {
    expect(rows.map((r) => r.id)).toEqual(['p05', 'p01', 'p03', 'p06', 'p04', 'p02', 'p07']);
    expect(rows.filter(isUnreviewed).map((r) => r.id)).toEqual(['p07']);
    expect(overlapRows([{ ...data.rows[0]!, gap: null }])).toEqual([]);
  });

  it('tallies brands and top-level categories, most products first', () => {
    expect(overlapOptions(data.rows)).toEqual({
      brand: [
        { key: 'Fixture Beauty', n: 4 },
        { key: 'Sample Labs', n: 3 },
      ],
      category: [{ key: 'skincare', n: 7 }],
    });
  });

  it('reads a 0…1 confidence as a percent, and nothing readable as null', () => {
    expect(confidencePct('0.95')).toBe('95');
    expect(confidencePct('0.875')).toBe('87.5');
    expect(confidencePct(null)).toBeNull();
    expect(confidencePct('high')).toBeNull();
  });
});

describe('OverlapRows', () => {
  it('lists every pair with both prices, labels only the unreviewed one, and links back to this view', () => {
    show(<OverlapRows rows={rows} data={data} name={name} from="?retailers=shop_a,shop_b" />);
    const table = screen.getByRole('table');
    const body = within(table).getAllByRole('row').slice(1);
    expect(body).toHaveLength(7);
    expect(within(body[0]!).getByRole('rowheader').textContent).toContain('Product p05');
    expect(within(table).getAllByText(en.productCard.unreviewedMatch)).toHaveLength(1);
    expect(within(body[6]!).getByText(en.productCard.unreviewedMatch)).toBeTruthy();
    const link = within(body[6]!).getByRole('link', { name: 'Product p07' });
    expect(link.getAttribute('href')).toContain('back=overlap');
    expect(within(body[0]!).getByText('Exact · Locked')).toBeTruthy();
    expect(within(body[6]!).getByText('Exact · Not reviewed')).toBeTruthy();
  });

  it('says the unreviewed gap is listed here but left out of the Summary, not out of price gaps', () => {
    show(<OverlapRows rows={rows} data={data} name={name} from="" />);
    const tips = screen.getAllByRole('tooltip').map((t) => t.textContent);
    expect(tips).toContain(en.overlap.unreviewedHint);
    expect(tips).not.toContain(en.productCard.unreviewedMatchHint);
    cleanup();
    show(<OverlapRows rows={rows} data={data} name={name} from="" />, 'ar');
    expect(screen.getAllByRole('tooltip').map((t) => t.textContent)).toContain(ar.overlap.unreviewedHint);
  });

  it('shows the match evidence in a tooltip wired to its trigger', () => {
    show(<MatchEvidence match={data.rows[0]!.match} />);
    const tip = screen.getByRole('tooltip');
    expect(tip.textContent).toBe(
      'Match: ExactReview: LockedDecided by a reviewerMethod: fixtureConfidence: 95%',
    );
    expect(
      screen.getByText('Exact · Locked').closest('[aria-describedby]')?.getAttribute('aria-describedby'),
    ).toBe(tip.id);
  });

  it('leaves out who decided when nobody has, and shows a dash without a match', () => {
    show(<MatchEvidence match={data.rows[6]!.match} />);
    expect(screen.getByRole('tooltip').textContent).not.toContain('Decided by');
    cleanup();
    show(<MatchEvidence match={null} />);
    expect(screen.getByText('–')).toBeTruthy();
  });

  it('in Arabic', () => {
    show(<OverlapRows rows={rows} data={data} name={name} from="" />, 'ar');
    expect(screen.getAllByText(ar.productCard.unreviewedMatch).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(`${ar.overlap.class.exact} · ${ar.overlap.review.proposed}`).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(ar.overlap.match).length).toBeGreaterThan(0);
  });
});
