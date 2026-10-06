import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { CaveatView, Envelope, Schemas } from '@/lib/api/types';
import pagesAr from '@/messages/ar.json';
import pagesEn from '@/messages/en.json';
import widgetsAr from '@/messages/widgets.ar.json';
import widgetsEn from '@/messages/widgets.en.json';
import type { PairState } from '../widgets/use-compare';
import { Headline, MatchedBasket, NoMatch } from './landing';

type Comparison = Schemas['Comparison'];
const en = { ...pagesEn, widgets: widgetsEn };
const ar = { ...pagesAr, widgets: widgetsAr };
const pair = {
  base: 'shop_a',
  other: 'shop_b',
  name: (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id,
};
const body = golden('compare') as Envelope<Comparison>;
const early = body.caveats.find((c) => c.code === 'early_excluded')!;

/** /compare as served, with the caveats given (the golden carries one early_excluded item). */
const ready = (data: Comparison, caveats: CaveatView[] = []): PairState<Comparison> => ({
  kind: 'ready',
  data,
  env: { ...body, data, caveats },
});
/** A matched set of `n` with a 1-product lead for Shop A, so the verdict and basket sentence render. */
const withN = (n: number): Comparison => ({
  ...body.data!,
  summary: {
    ...body.data!.summary!,
    n,
    cheaperCounts: { shop_a: n, shop_b: 0 },
    equalCount: 0,
  },
  total: n + 9,
});
/** /compare with no matched product yet: the sides' observed counts and the total, no summary. */
const unmatched: Comparison = { ...body.data!, summary: null, rows: [] };

function show(ui: React.ReactNode, locale: 'en' | 'ar' = 'en') {
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      {ui}
    </NextIntlClientProvider>,
  );
}
const headline = (cmp: PairState<Comparison>, locale: 'en' | 'ar' = 'en') =>
  show(<Headline pair={pair} cmp={cmp} />, locale);
const tooltips = () => screen.getAllByRole('tooltip').map((t) => t.textContent);

afterEach(cleanup);

describe('Headline', () => {
  it('one line from /compare: who is cheaper on how many, the count as a chip, the scope in its tooltip', () => {
    headline(ready(body.data!));
    const h2 = screen.getByRole('heading', { level: 2 });
    expect(h2.textContent).toBe(
      'Shop A is cheaper on 3 of the 6 matched products. Shop B is cheaper on 2; 1 costs the same.',
    );
    expect(screen.getByText('6 of 15')).toBeTruthy();
    expect(tooltips()).toContain(
      'That is 6 of the 15 products either shop sells; the rest cannot be compared yet.',
    );
    expect(document.body.textContent).not.toContain('candidate');
    expect(screen.getByRole('link', { name: 'See the 6 products' }).getAttribute('href')).toMatch(
      /\/compare\/?\?retailers=shop_a(,|%2C)shop_b$/,
    );
    // No paragraph of prose: the h2, the chips and the link only.
    expect(document.querySelectorAll('p')).toHaveLength(0);
  });

  it('is an early read only when the API says items were left out, never from total alone', () => {
    headline(ready(body.data!));
    expect(document.body.textContent).not.toContain('Early read');
    expect(document.body.textContent).not.toContain(early.en);
    cleanup();
    headline(ready(body.data!, [early]));
    // The pill, not the heading, says "early"; the caveat is its tooltip.
    expect(screen.getByText('Early read:')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/^Shop A is cheaper/);
    expect(tooltips()).toContain(early.en);
  });

  it('in Arabic, with Latin digits at every count', () => {
    headline(ready(body.data!, [early]), 'ar');
    expect(screen.getByText('قراءة مبكرة:')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(
      /^Shop A أرخص في 3 من 6 منتجات مطابَقة/,
    );
    expect(screen.getByText('6 من 15')).toBeTruthy();
    expect(tooltips()).toContain(early.ar);
    cleanup();
    for (const [n, text] of [
      [1, 'Shop A أرخص في 1 من منتج مطابَق واحد.'],
      [2, 'Shop A أرخص في 2 من منتجين مطابَقين.'],
      [11, 'Shop A أرخص في 11 من 11 منتجًا مطابَقًا.'],
    ] as const) {
      headline(ready(withN(n)), 'ar');
      expect(screen.getByRole('heading', { level: 2 }).textContent).toBe(text);
      expect(document.body.textContent).not.toMatch(/[٠-٩]/);
      cleanup();
    }
  });

  it('no matched product yet: the quiet line, not a headline', () => {
    headline(ready(unmatched));
    expect(screen.queryByRole('heading', { level: 2 })).toBeNull();
    expect(document.getElementById('no-match')).toBeTruthy();
  });
});

describe('NoMatch', () => {
  const line = (data: Comparison | null, locale: 'en' | 'ar' = 'en', reason: string | null = null) =>
    show(<NoMatch pair={pair} data={data} reason={reason} />, locale);

  it('chips only: the fact, each side’s observed count, the total; the definition in the tooltip', () => {
    line(unmatched);
    const p = document.getElementById('no-match')!;
    expect(p.textContent).toContain('No matched products yet');
    // The counts the API sent, as chips: never a "0 confirmed".
    expect(p.textContent).toContain('14');
    expect(p.textContent).toContain('12');
    expect(p.textContent).toContain('15 in total');
    expect(p.textContent).not.toMatch(/\b0\b|candidate/);
    expect(tooltips()).toEqual([
      'A matched product is one reviewed and confirmed as the same item at both shops; the head-to-head needs at least one.',
      'Shop A: 14 products seen',
      'Shop B: 12 products seen',
      '15 products either shop sells',
    ]);
    expect(screen.getByRole('link', { name: 'Open compare' }).getAttribute('href')).toMatch(/\/compare\/?\?/);
  });

  it('with a summary of 0 the chip counts it; without /compare at all only the fact and the link remain', () => {
    line({ ...unmatched, summary: { ...body.data!.summary!, n: 0 } });
    expect(document.getElementById('no-match')!.textContent).toContain('No matched products yet');
    cleanup();
    line(null, 'en', 'not_enough_data');
    const p = document.getElementById('no-match')!;
    expect(p.textContent).toContain('No matched products yet');
    expect(p.textContent).not.toMatch(/\d/);
    expect(tooltips()[0]).toMatch(/at both shops;.+/);
  });

  it('Arabic counted nouns for the observed products at every count', () => {
    const forms: [number, string][] = [
      [1, 'Shop A: منتج مرصود واحد'],
      [2, 'Shop A: منتجان مرصودان'],
      [3, 'Shop A: 3 منتجات مرصودة'],
      [11, 'Shop A: 11 منتجًا مرصودًا'],
      [100, 'Shop A: 100 منتج مرصود'],
    ];
    for (const [n, text] of forms) {
      line(
        { ...unmatched, sides: { ...unmatched.sides, base: { ...unmatched.sides.base, observed: n } } },
        'ar',
      );
      expect(tooltips()).toContain(text);
      expect(document.body.textContent).not.toMatch(/[٠-٩]/);
      cleanup();
    }
  });
});

describe('MatchedBasket', () => {
  it('counts the matched set out of the products either shop sells, with Arabic noun forms', () => {
    show(<MatchedBasket pair={pair} data={body.data!} />);
    expect(document.body.textContent).toContain('6 of 15 products either shop sells');
    cleanup();
    const forms: [number, string][] = [
      [1, '1 من 10 منتجات يبيعها أحد المتجرين'],
      [2, '2 من 11 منتجًا يبيعها أحد المتجرين'],
      [91, '91 من 100 منتج يبيعها أحد المتجرين'],
    ];
    for (const [n, text] of forms) {
      show(<MatchedBasket pair={pair} data={withN(n)} />, 'ar');
      expect(document.body.textContent).toContain(text);
      cleanup();
    }
  });
});
