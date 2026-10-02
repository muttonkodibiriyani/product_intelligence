import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { categoryCompareBody } from '@/e2e/category-compare-fixture';
import { parseCategoryCompare, type CategoryCompare } from '@/lib/api/category-compare';
import type { Envelope, Schemas } from '@/lib/api/types';
import pagesAr from '@/messages/ar.json';
import pagesEn from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgetsEn from '@/messages/widgets.en.json';
import { CompareEmpty } from './compare-empty';
import { CompareRows } from './compare-rows';
import { Coverage, Verdict } from './compare-summary';
import { excludedGroups, gapShare, minus, retailerTone, splitRows, verdict } from './model';

type Comparison = Schemas['Comparison'];
type Env = Envelope<Comparison>;

const golden = (name: string): Env =>
  JSON.parse(
    readFileSync(join(__dirname, `../../../../docs/contracts/golden/pi-api/${name}.json`), 'utf8'),
  ) as Env;

const compare = golden('compare'); // shop_a vs shop_b: 15 rows, 6 matched, n=6, median +2.4
const blocked = golden('compare-blocked'); // shop_a vs shop_d: shop_d blocked, no summary

const en = { ...pagesEn, widgets: widgetsEn };
const ar = { ...pagesAr, widgets: widgetsAr };
const name = (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B', shop_d: 'Shop D' })[id] ?? id;
const withSummary = (d: Comparison) => ({ ...d, summary: d.summary! });

function show(ui: React.ReactNode, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      {ui}
    </NextIntlClientProvider>,
  );
}

afterEach(cleanup);

const text = (el: Element | null | undefined) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();

describe('compare model', () => {
  const s = compare.data!.summary!;

  it('names the shop that is cheaper more often, with the trailing and equal counts', () => {
    expect(verdict(s, 'shop_a', 'shop_b')).toEqual({
      kind: 'lead',
      leader: 'base',
      k: 3,
      trailing: 2,
      equal: 1,
      n: 6,
    });
    expect(verdict({ ...s, cheaperCounts: { shop_a: 2, shop_b: 3 } }, 'shop_a', 'shop_b')).toMatchObject({
      leader: 'other',
      k: 3,
      trailing: 2,
    });
    expect(
      verdict({ ...s, cheaperCounts: { shop_a: 2, shop_b: 2 }, equalCount: 2 }, 'shop_a', 'shop_b'),
    ).toEqual({
      kind: 'tie',
      k: 2,
      n: 6,
      equal: 2,
    });
    expect(verdict({ ...s, cheaperCounts: {}, equalCount: 6 }, 'shop_a', 'shop_b')).toEqual({
      kind: 'allSame',
      n: 6,
    });
  });

  it('subtracts baskets on minor units, keeping the currency and the sign', () => {
    expect(minus(s.basket.other, s.basket.base)).toEqual({ amount: '19.25', currency: 'AED', minor: 1925 });
    expect(minus(s.basket.base, s.basket.other)).toEqual({ amount: '-19.25', currency: 'AED', minor: -1925 });
    expect(
      minus({ amount: '0.05', currency: 'AED', minor: 5 }, { amount: '0.10', currency: 'AED', minor: 10 }),
    ).toEqual({ amount: '-0.05', currency: 'AED', minor: -5 });
    expect(
      minus({ amount: '1', currency: 'JPY', minor: 1 }, { amount: '3', currency: 'JPY', minor: 3 }),
    ).toEqual({
      amount: '-2',
      currency: 'JPY',
      minor: -2,
    });
    expect(minus({ amount: '1.00', currency: 'USD', minor: 100 }, s.basket.base)).toBeNull();
  });

  it('puts the matched rows first and tallies the rest by reason, largest group first', () => {
    const { matched, excluded } = splitRows(compare.data!.rows);
    expect(matched.map((r) => r.id)).toEqual(['p01', 'p02', 'p03', 'p04', 'p05', 'p06']);
    expect(excluded).toHaveLength(9);
    const groups = excludedGroups(excluded);
    expect(groups[0]).toEqual({ reason: 'not_offered', n: 2 });
    expect(groups.map((g) => g.reason)).toEqual([
      'not_offered',
      'size_mismatch',
      'unpriced',
      'match_unreviewed',
      'match_not_exact',
      'match_rejected',
      'no_match',
      'early',
    ]);
    expect(excludedGroups([{ ...excluded[0]!, excludedReason: 'brand_new' as never }])).toEqual([
      { reason: 'other', n: 1 },
    ]);
  });

  it('scales each gap bar to the widest matched gap and never past it', () => {
    const { matched } = splitRows(compare.data!.rows);
    expect(gapShare('25.0', matched)).toBe(1);
    expect(gapShare('-5.0', matched)).toBeCloseTo(0.2);
    expect(gapShare('0.0', matched)).toBe(0);
    expect(gapShare('5', [])).toBe(0);
  });

  it('gives Ulta and Sephora their own tones and any other shop a tone by side', () => {
    expect(retailerTone('ulta_ae', 1)).toContain('--color-ulta');
    expect(retailerTone('sephora_me', 0)).toContain('--color-sephora');
    expect(retailerTone('shop_a', 0)).toContain('--color-series-a');
    expect(retailerTone('shop_a', 1)).toContain('--color-series-b');
  });
});

describe('Verdict', () => {
  it('answers first: who is cheaper on how many, the basket in money, three facts', () => {
    show(<Verdict data={withSummary(compare.data!)} name={name} />);
    expect(text(screen.getByRole('heading', { level: 2 }))).toContain(
      'Shop A is cheaper on 3 of the 6 matched products; Shop B is cheaper on 2, and 1 costs the same.',
    );
    expect(
      screen.getByText(
        /Buying all 6 costs AED 580\.75 at Shop A and AED 600\.00 at Shop B, a difference of AED 19\.25\./,
      ),
    ).toBeTruthy();
    expect(screen.getByText(/6 of the 15 products either shop sells/)).toBeTruthy();
    const facts = screen.getAllByRole('definition').map((d) => d.textContent);
    expect(facts).toContain('6');
    expect(facts).toContain('+2.4%');
    expect(facts).toContain('Shop B above Shop A, median');
    expect(facts.join(' | ')).toMatch(/AED\s?19\.25/);
    expect(facts.join(' | ')).toContain('Shop B above Shop A');
    expect(
      screen.getByRole('img', { name: /Shop A cheaper 3, Same price 1, Shop B cheaper 2/ }),
    ).toBeTruthy();
  });

  it('words a tie, an all-same set and a win with nothing else to say', () => {
    const d = compare.data!;
    const s = d.summary!;
    show(
      <Verdict
        data={{ ...d, summary: { ...s, cheaperCounts: { shop_a: 3, shop_b: 3 }, equalCount: 0 } }}
        name={name}
      />,
    );
    expect(text(screen.getByRole('heading', { level: 2 }))).toContain(
      'Shop A and Shop B are each cheaper on 3 of the 6 matched products.',
    );
    cleanup();
    show(<Verdict data={{ ...d, summary: { ...s, cheaperCounts: {}, equalCount: 6 } }} name={name} />);
    expect(text(screen.getByRole('heading', { level: 2 }))).toContain(
      'All 6 matched products cost the same at Shop A and Shop B.',
    );
    cleanup();
    show(
      <Verdict
        data={{
          ...d,
          summary: { ...s, n: 1, cheaperCounts: { shop_b: 1 }, equalCount: 0, medianGapPct: '-4.0' },
        }}
        name={name}
      />,
    );
    expect(text(screen.getByRole('heading', { level: 2 }))).toContain(
      'Shop B is cheaper on 1 of the 1 matched product.',
    );
    expect(screen.getAllByRole('definition').map((d) => d.textContent)).toContain(
      'Shop B below Shop A, median',
    );
  });

  it('reads in Arabic with Latin digits and no raw placeholders', () => {
    show(<Verdict data={withSummary(compare.data!)} name={name} />, 'ar');
    const h = screen.getByRole('heading', { level: 2 }).textContent!;
    expect(h).toMatch(/[؀-ۿ]/);
    expect(h).toContain('Shop A');
    expect(h).toContain('3');
    expect(h).not.toMatch(/[{}]|undefined/);
    expect(document.body.textContent).not.toMatch(/[{}]|undefined|NaN/);
  });
});

describe('CompareRows', () => {
  it('lists the matched products with the API gap, who is cheaper, and a link to both listings', () => {
    show(<CompareRows data={compare.data!} name={name} from="?retailers=shop_a%2Cshop_b" />);
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(6);
    const p05 = screen.getByRole('row', { name: /Product p05/ });
    expect(text(p05)).toContain('AED 80.00');
    expect(text(p05)).toContain('AED 100.00');
    expect(text(p05)).toContain('+AED 20.00');
    expect(text(p05)).toContain('Shop B, 25% dearer');
    expect(
      within(p05).getByRole('link', { name: 'Both listings: Product p05' }).getAttribute('href'),
    ).toMatch(/^\/en\/product\/?\?id=p05&back=compare&from=retailers%3Dshop_a%252Cshop_b$/);
    expect(text(screen.getByRole('row', { name: /Product p02/ }))).toContain('Same price');
    expect(text(screen.getByRole('row', { name: /Product p03/ }))).toContain('Shop B, by 9.1%');
  });

  it('tells the truth about the gap from both sides, since the API measures it against the base price', () => {
    const d = compare.data!;
    const money = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(Number(amount) * 100) });
    // (basePrice, otherPrice, gap.pct, gap.cheaper) exactly as /compare sends them: pct = (other − base) / base.
    const pair = (id: string, base: string, other: string, pct: string, cheaper: 'base' | 'other') => ({
      ...d.rows.find((r) => r.id === 'p05')!,
      id,
      name: `Product ${id}`,
      basePrice: money(base),
      otherPrice: money(other),
      gap: { amount: minus(money(other), money(base))!, pct, cheaper },
    });
    const rows = [
      pair('q1', '50.00', '150.00', '200.0', 'base'), // base is 66.7% cheaper, NOT "by 200%"
      pair('q2', '150.00', '50.00', '-66.7', 'other'),
      pair('q3', '80.00', '100.00', '25.0', 'base'), // base is 20% cheaper, NOT "by 25%"
      pair('q4', '100.00', '80.00', '-20.0', 'other'),
    ];
    // Arabic percentages carry bidi marks ("25\u200e%\u200e"); drop them so the words can be read.
    const pill = (id: string) =>
      text(screen.getByRole('row', { name: new RegExp(`Product ${id}`) })).replace(/[\u200e\u200f]/g, '');
    show(<CompareRows data={{ ...d, rows, total: 4 }} name={name} from="" />);
    expect(pill('q1')).toContain('Shop B, 200% dearer');
    expect(pill('q1')).not.toContain('by 200%');
    expect(pill('q2')).toContain('Shop B, by 66.7%');
    expect(pill('q3')).toContain('Shop B, 25% dearer');
    expect(pill('q3')).not.toContain('Shop A, by');
    expect(pill('q4')).toContain('Shop B, by 20%');
    cleanup();
    show(<CompareRows data={{ ...d, rows, total: 4 }} name={name} from="" />, 'ar');
    expect(pill('q1')).toContain('Shop B، أغلى بنسبة 200%');
    expect(pill('q2')).toContain('Shop B، بنسبة 66.7%');
    expect(pill('q3')).toContain('Shop B، أغلى بنسبة 25%');
    expect(pill('q4')).toContain('Shop B، بنسبة 20%');
    expect(document.body.textContent).not.toMatch(/[{}]|undefined|NaN/);
  });

  it('folds everything that could not be compared into one line, with the reasons behind it', () => {
    show(<CompareRows data={compare.data!} name={name} from="" />);
    expect(text(screen.getByText(/9 more products could not be compared/).parentElement)).toContain(
      '9 more products could not be compared — 2 are sold at one shop only, 1 comes in different sizes at each shop, 1 has no price at one shop, 1 is waiting for a reviewer, 1 is similar but not the same product, 1 match was rejected by a reviewer, 1 has no match at the other shop, 1 is too new.',
    );
    expect(screen.queryByRole('row', { name: /Product p12/ })).toBeNull();
    const toggle = screen.getByRole('button', { name: 'Show them' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(screen.getByRole('button', { name: 'Hide them' }).getAttribute('aria-expanded')).toBe('true');
    const why = (id: string) => screen.getByRole('row', { name: new RegExp(`Product ${id}`) }).textContent;
    expect(why('p12')).toContain('Only Shop A sells it.');
    expect(why('p12')).toContain('Not sold');
    expect(why('p14')).toContain('Only Shop B sells it.');
    expect(why('p11')).toContain('No price at Shop B.');
    expect(why('p11')).toContain('No price');
    expect(why('p10')).toContain("Different sizes at each shop, so the prices aren't comparable.");
    expect(why('p07')).toContain('Waiting for a reviewer to confirm the match.');
    expect(why('p13')).toContain('Too new to compare yet.');
    expect(screen.getAllByRole('row', { name: /Product p/ })).toHaveLength(15);
  });

  it('says so when none of the listed rows is matched, and still folds the rest', () => {
    const d = compare.data!;
    show(<CompareRows data={{ ...d, rows: d.rows.filter((r) => !r.counted) }} name={name} from="" />);
    expect(screen.getByText(/None of the listed products is matched/)).toBeTruthy();
    expect(screen.getByText(/9 more products could not be compared/)).toBeTruthy();
  });
});

describe('Coverage', () => {
  it('says how much of each shop is matched to the other, from the sides as sent', () => {
    show(<Coverage data={compare.data!} name={name} />);
    expect(
      text(screen.getByText(/6 of the 14 products Shop A sells in this view are matched to Shop B\./)),
    ).toContain('8 are sold only at Shop A or not yet matched.');
    expect(text(screen.getByText(/6 of the 12 products Shop B sells/))).toContain(
      '6 are sold only at Shop B',
    );
  });
});

describe('CompareEmpty', () => {
  const ready = (): Envelope<CategoryCompare> => {
    const body = categoryCompareBody('shop_a', 'shop_b');
    return { ...body, data: parseCategoryCompare(body.data) } as unknown as Envelope<CategoryCompare>;
  };

  it('says why nothing is matched for a blocked pair, with each side as the API reports it', () => {
    show(
      <CompareEmpty
        env={blocked}
        data={blocked.data}
        pair={{ base: 'shop_a', other: 'shop_d' }}
        name={name}
        category={{ kind: 'empty', env: null }}
      />,
    );
    expect(text(screen.getByRole('heading', { level: 2 }))).toContain(
      'No products are matched between Shop A and Shop D yet',
    );
    expect(text(screen.getByText(/Nothing can be compared for this pair:/))).toContain(
      'This retailer blocks collection. A selected retailer could not be collected.',
    );
    const tiles = screen.getAllByRole('listitem').map((li) => li.textContent);
    expect(tiles[0]).toContain('Shop A');
    expect(tiles[0]).toContain('14 products seen');
    expect(tiles[1]).toContain('Shop D');
    expect(tiles[1]).toContain('0 products seen');
    expect(tiles[1]).toContain('Blocked');
    expect(tiles.find((t) => t?.startsWith('Confirmed matches'))).toContain('0');
    expect(screen.getByRole('link', { name: 'See prices by category instead' }).getAttribute('href')).toMatch(
      /^\/en\/prices\/?$/,
    );
    expect(screen.getByRole('link', { name: 'Browse all products' }).getAttribute('href')).toMatch(
      /^\/en\/explore\/?$/,
    );
    expect(screen.queryByText(/median price by category/)).toBeNull();
  });

  it('shows the category medians that already exist, and counts the rows waiting for a reviewer', () => {
    const d = compare.data!;
    const env: Env = {
      ...compare,
      data: {
        ...d,
        rows: d.rows.filter((r) => !r.counted),
        summary: { ...d.summary!, n: 0, cheaperCounts: {}, equalCount: 0 },
        sides: { base: { ...d.sides.base, counted: 0 }, other: { ...d.sides.other, counted: 0 } },
      },
    };
    const env2 = ready();
    show(
      <CompareEmpty
        env={env}
        data={env.data}
        pair={{ base: 'shop_a', other: 'shop_b' }}
        name={name}
        category={{ kind: 'ready', data: env2.data!, env: env2 }}
      />,
    );
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /No products are matched between Shop A and Shop B yet/,
      }),
    ).toBeTruthy();
    expect(screen.getByText(/Both shops have been collected/)).toBeTruthy();
    const awaiting = screen.getByText('Awaiting review').parentElement!;
    expect(text(awaiting)).toContain('1 · candidate pairs among the products listed');
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(10);
    const concealer = within(table).getByRole('row', { name: /Concealer/ });
    expect(text(concealer)).toContain('AED 110.00');
    expect(text(concealer)).toContain('AED 95.00');
    expect(text(concealer)).toContain('-13.6%');
    expect(text(concealer)).toContain('Shop B');
    expect(screen.getByRole('link', { name: /All 9 categories/ }).getAttribute('href')).toMatch(
      /^\/en\/prices\/?$/,
    );
  });

  it('leaves the "awaiting review" count out when the rows are cut, so it never reads as a total', () => {
    const d = blocked.data!;
    show(
      <CompareEmpty
        env={blocked}
        data={{ ...d, truncated: true }}
        pair={{ base: 'shop_a', other: 'shop_d' }}
        name={name}
        category={{ kind: 'loading' }}
      />,
    );
    expect(screen.queryByText('Awaiting review')).toBeNull();
  });
});
