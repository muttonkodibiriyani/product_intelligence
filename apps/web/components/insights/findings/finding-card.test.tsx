import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import fixture from '@/e2e/findings-fixture.json';
import type { Findings, Finding, Namers } from '@/lib/findings';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { FindingCard, type Pair } from './finding-card';

afterEach(cleanup);

const data = (fixture as unknown as { data: Findings }).data;
const SHOPS: Record<string, string> = { shop_a: 'Ulta', shop_b: 'Sephora', shop_c: 'Faces' };
const names: Namers = { shop: (id) => SHOPS[id] ?? id, category: (c) => c };
const pair: Pair = { focus: data.focus, rival: data.rival, thirds: data.thirds };
const get = (key: Finding['key']) => data.findings.find((f) => f.key === key)!;

function card(f: Finding, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === 'en' ? en : ar} timeZone="Asia/Dubai">
      <FindingCard finding={f} names={names} pair={pair} />
    </NextIntlClientProvider>,
  );
}

describe('FindingCard', () => {
  it.each(data.findings.flatMap((f) => (['en', 'ar'] as const).map((l) => [f.key, l, f] as const)))(
    '%s renders in %s with its rank, a closed "why", and at most four products',
    (_, locale, f) => {
      const { container } = card(f, locale);
      const article = container.querySelector(`article[data-finding="${f.key}"]`)!;
      expect(article).not.toBeNull();
      expect(article.textContent).toContain(`#${f.rank}`);
      expect(article.textContent).not.toMatch(/shop_[a-z]|undefined|NaN|\{/);
      expect(container.querySelector('details')!.open).toBe(false);
      expect(within(article as HTMLElement).queryAllByRole('listitem').length).toBeLessThanOrEqual(4);
    },
  );

  it('puts the KPI inside the headline and the evidence metadata in the (i)', () => {
    const f = get('promo_strategy');
    card(f);
    const h = screen.getByRole('heading', { level: 4 });
    expect(h.querySelector('strong')!.textContent).toBe('446');
    expect(h.textContent).toMatch(/^446\s+Ulta markdowns/);
    const tip = screen.getByRole('tooltip');
    expect(tip.textContent).toContain(`${f.n.toLocaleString('en')} of ${f.of!.toLocaleString('en')}`);
    expect(tip.textContent).toContain('Ulta, Sephora, and Faces');
    expect(screen.getByRole('button', { name: /about/i }).getAttribute('aria-describedby')).toBe(tip.id);
  });

  it('shows a shop left out as a chip and leaves it out of the shops read', () => {
    card(get('price_vs_rating'));
    expect(screen.getByText(/Faces/, { selector: 'span.rounded-full' })).toBeTruthy();
    expect(screen.getByRole('tooltip').textContent).toContain('Ulta and Sephora');
  });

  it('shows a real image only from the shop’s own host, else the brand monogram', () => {
    const f = get('promo_strategy');
    const [a, b] = f.examples;
    card({
      ...f,
      examples: [
        { ...a!, retailer: 'ulta_ae', image: 'https://media.alshaya.com/adobe/assets/x.jpg' },
        { ...b!, retailer: 'ulta_ae', image: 'https://evil.example/x.jpg' },
      ],
    });
    const imgs = document.querySelectorAll('img');
    expect(imgs).toHaveLength(1);
    expect(imgs[0]!.getAttribute('src')).toContain('media.alshaya.com');
  });

  it('keeps a withheld finding in place with its reason and no number, chart or action', () => {
    const f = get('brand_price_policy');
    card({ ...f, status: 'not_enough_data', reason: 'no_match' });
    const h = screen.getByRole('heading', { level: 4 });
    expect(h.querySelector('strong')).toBeNull();
    expect(h.textContent).not.toMatch(/\d/);
    expect(document.querySelector('details')).toBeNull();
    expect(screen.queryByRole('listitem')).toBeNull();
  });
});
