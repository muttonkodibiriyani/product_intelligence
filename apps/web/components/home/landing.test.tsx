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
import { EmptyHeadline, Headline, MatchedBasket } from './landing';

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

function show(ui: React.ReactNode, locale: 'en' | 'ar' = 'en') {
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} onError={() => {}}>
      {ui}
    </NextIntlClientProvider>,
  );
}
const headline = (cmp: PairState<Comparison>, locale: 'en' | 'ar' = 'en') =>
  show(<Headline pair={pair} cmp={cmp} read={null} cat={{ kind: 'empty', env: null }} />, locale);

afterEach(cleanup);

describe('Headline', () => {
  it('is an early read only when the API says items were left out, never from total alone', () => {
    headline(ready(body.data!));
    const h2 = screen.getByRole('heading', { level: 2 });
    expect(h2.textContent).toBe(
      'Shop A is cheaper on 3 of the 6 matched products. Shop B is cheaper on 2; 1 costs the same.',
    );
    expect(document.body.textContent).not.toContain('Early read');
    expect(document.body.textContent).not.toContain(early.en);
    cleanup();
    headline(ready(body.data!, [early]));
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/^Early read: Shop A is cheaper/);
    expect(document.body.textContent).toContain(early.en);
  });

  it('scopes the matched set to the products either shop sells, in the API words, in Arabic too', () => {
    headline(ready(body.data!));
    expect(document.body.textContent).toContain(
      'That is 6 of the 15 products either shop sells; the rest cannot be compared yet.',
    );
    expect(document.body.textContent).not.toContain('candidate');
    cleanup();
    headline(ready(body.data!, [early]), 'ar');
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/^قراءة مبكرة: Shop A أرخص/);
    expect(document.body.textContent).toContain(
      'أي 6 من 15 منتجًا يبيعها أحد المتجرين؛ ولا يمكن مقارنة الباقي بعد.',
    );
    expect(document.body.textContent).toContain(early.ar);
  });

  it('Arabic counted nouns in the basket sentence at every count', () => {
    const forms: [number, string][] = [
      [1, 'السلة نفسها من منتج واحد تكلف'],
      [2, 'السلة نفسها من منتجين تكلف'],
      [3, 'السلة نفسها من 3 منتجات تكلف'],
      [9, 'السلة نفسها من 9 منتجات تكلف'],
      [11, 'السلة نفسها من 11 منتجًا تكلف'],
      [100, 'السلة نفسها من 100 منتج تكلف'],
    ];
    for (const [n, text] of forms) {
      headline(ready(withN(n)), 'ar');
      expect(document.body.textContent).toContain(text);
      cleanup();
    }
  });
});

describe('EmptyHeadline', () => {
  const empty = (data: Comparison | null, locale: 'en' | 'ar' = 'en') =>
    show(
      <EmptyHeadline pair={pair} data={data} reason={null} read={null} cat={{ kind: 'empty', env: null }} />,
      locale,
    );

  it('names what each shop has observed and the products either shop sells; no "0 confirmed" without a count', () => {
    empty({ ...body.data!, summary: null, rows: [] });
    const tiles = screen.getAllByRole('listitem');
    expect(tiles).toHaveLength(3);
    expect(tiles[0]!.textContent).toContain('14');
    expect(tiles[0]!.textContent).toContain('products seen');
    expect(tiles[2]!.textContent).toContain('Products either shop sells');
    expect(tiles[2]!.textContent).toContain('15');
    expect(tiles[2]!.textContent).not.toMatch(/0|confirmed|candidate/);
    cleanup();
    empty({ ...body.data!, summary: { ...body.data!.summary!, n: 0 }, rows: [] });
    expect(screen.getAllByRole('listitem')[2]!.textContent).toContain('0 confirmed as matches');
  });

  it('Arabic counted nouns for the observed products at every count', () => {
    const forms: [number, string][] = [
      [1, 'منتج مرصود'],
      [2, 'منتجان مرصودان'],
      [3, 'منتجات مرصودة'],
      [9, 'منتجات مرصودة'],
      [11, 'منتجًا مرصودًا'],
      [100, 'منتج مرصود'],
    ];
    for (const [n, text] of forms) {
      const d = body.data!;
      empty(
        { ...d, summary: null, rows: [], sides: { ...d.sides, base: { ...d.sides.base, observed: n } } },
        'ar',
      );
      expect(screen.getAllByRole('listitem')[0]!.textContent).toContain(`${n}${text}`);
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
