import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatAnswer, Citation, ToolEnvelope } from '@/lib/assistant/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { formatDate } from '@/lib/format';
import { AnswerView } from './answer-view';

const arDate = formatDate('2026-09-30T00:00:00Z', 'ar');

vi.mock('../auth-provider', () => ({ useAuth: () => ({ api: null }) }));

beforeEach(() => vi.stubGlobal('matchMedia', () => ({ matches: true })));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const u = (s: string) => ({ untrusted: s });
const money = (amount: string) => ({ amount, currency: 'AED' });

const cite = (over: Partial<Citation>): Citation => ({
  tool: 'compare',
  toolVersion: '4',
  apiVersion: '1.11.0',
  metricVersion: 'm1',
  datasetGeneration: 'g7',
  cutoff: '2026-09-30T00:00:00Z',
  market: 'uae',
  currency: 'AED',
  filters: {},
  cohort: null,
  ...over,
});

/** The compare tool's result as the server sanitises it: names wrapped, `minor` dropped. */
const compare: ToolEnvelope = {
  status: 'ok',
  citation: cite({
    tool: 'compare',
    filters: { retailers: { base: 'ulta_ae', other: 'sephora_me' }, category: ['makeup'], limit: 25 },
    cohort: { description: u('exact pairs'), n: 4 },
  }),
  caveats: [],
  data: {
    base: 'ulta_ae',
    other: 'sephora_me',
    rows: [
      {
        id: 'p01',
        name: u('Double Wear Foundation'),
        brand: u('Estée Lauder'),
        category: [u('makeup'), u('foundation')],
        basePrice: money('215.00'),
        otherPrice: money('225.00'),
        counted: true,
        excludedReason: null,
        gap: { amount: money('10.00'), pct: '4.7', cheaper: 'base' },
      },
      {
        id: 'p02',
        name: u('Easy Bake <b>Powder</b>'),
        brand: u('Huda Beauty'),
        category: [u('makeup')],
        basePrice: money('150.00'),
        otherPrice: money('150.00'),
        counted: true,
        excludedReason: null,
        gap: { amount: money('0.00'), pct: '0.0', cheaper: 'equal' },
      },
    ],
    total: 4,
    truncated: false,
  },
};

const promotions: ToolEnvelope = {
  status: 'ok',
  citation: cite({ tool: 'promotions', filters: { retailer: ['sephora_me'], minPct: 20, limit: 25 } }),
  caveats: [],
  data: {
    items: [
      {
        id: 'p05',
        name: u('Moisture Surge'),
        retailer: 'sephora_me',
        price: money('80.00'),
        regular: money('120.00'),
        depthPct: '33.3',
      },
    ],
    retailers: [
      { retailer: 'sephora_me', n: 4790, onPromo: 881, share: '18.4', reason: null },
      { retailer: 'ulta_ae', n: 7316, onPromo: 0, share: null, reason: 'was_price_unverified' },
    ],
    total: 1,
    truncated: false,
  },
};

const answer = (toolResults: ToolEnvelope[], over: Partial<ChatAnswer> = {}): ChatAnswer => ({
  status: 'answered',
  answerMd: 'Ulta is cheaper on 3 of the 4 products matched.\n\nOnly 4 products are matched yet.',
  language: 'en',
  citations: toolResults.map((r) => r.citation),
  caveats: [],
  productIds: [],
  notEnoughData: [],
  toolResults,
  costUsd: '0.001',
  ...over,
});

const show = (a: ChatAnswer, locale: 'en' | 'ar' = 'en') =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NextIntlClientProvider locale={locale} messages={locale === 'en' ? en : ar}>
        <AnswerView answer={a} id="m1" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );

describe('answer renderer', () => {
  it('styles the first paragraph as the conclusion, the rest as body', () => {
    show(answer([]));
    const first = screen.getByText('Ulta is cheaper on 3 of the 4 products matched.');
    expect(first.tagName).toBe('P');
    expect(first.className).toContain('font-medium');
    expect(screen.getByText('Only 4 products are matched yet.').className).toBe('');
  });

  it('compare rows are product cards: shop names, both prices, the verdict; text never HTML', () => {
    const { container } = show(answer([compare]));
    const cards = screen.getByRole('list', { name: en.assistant.answer.products });
    expect(cards.querySelectorAll('li')).toHaveLength(2);
    const el = screen.getByRole('link', { name: 'Double Wear Foundation' });
    expect(el.getAttribute('href')).toMatch(/^\/en\/product\/?\?id=p01$/);
    expect(screen.getByText('Estée Lauder')).toBeTruthy();
    expect(screen.getByText('Sephora 4.7% dearer')).toBeTruthy();
    expect(screen.getByText('Same price')).toBeTruthy();
    expect(screen.getAllByText('Ulta').length).toBeGreaterThan(0);
    expect(container.textContent).toContain('215.00');
    expect(container.textContent).toContain('225.00');
    expect(container.textContent).not.toContain('ulta_ae');
    expect(container.textContent).toContain('Easy Bake <b>Powder</b>');
    expect(container.querySelector('b')?.textContent).not.toBe('Powder');
    expect(container.querySelector('[dangerouslysetinnerhtml]')).toBeNull();
  });

  it('promotion shares are tiles with the share, the priced count and a not-measured line', () => {
    const { container } = show(answer([promotions]));
    const tiles = screen.getByRole('list', { name: en.assistant.share.label });
    expect(tiles.querySelectorAll('li')).toHaveLength(2);
    expect(screen.getByText('18.4%')).toBeTruthy();
    expect(screen.getByText('4,790 priced')).toBeTruthy();
    expect(screen.getByText('7,316 priced')).toBeTruthy();
    expect(screen.getByText(/Not available yet\./).textContent).toContain(en.reasons.was_price_unverified);
    expect(container.textContent).not.toContain('0%');
    expect(container.textContent).not.toContain('null');
    // The promoted item is a card with now, was and the depth.
    expect(screen.getByRole('link', { name: 'Moisture Surge' })).toBeTruthy();
    expect(screen.getByText('−33.3%')).toBeTruthy();
    expect(container.textContent).toContain('120.00');
  });

  it('source pills name the page, the scope, the count and the date, and open the same filters', () => {
    show(answer([compare, promotions]));
    expect(screen.getByText('From')).toBeTruthy();
    const c = screen.getByRole('link', { name: /^Compare/ });
    expect(c.textContent).toBe('CompareUlta vs Sephora · makeup · 4 matched · 30 Sept 2026');
    expect(c.getAttribute('href')).toMatch(
      /^\/en\/compare\/?\?retailers=ulta_ae%2Csephora_me&category=makeup$/,
    );
    const p = screen.getByRole('link', { name: /^Promotions/ });
    expect(p.textContent).toBe('PromotionsSephora · 1 product · 30 Sept 2026');
    expect(p.getAttribute('href')).toMatch(/^\/en\/promotions\/?\?retailer=sephora_me&minPct=20$/);
    expect(document.body.textContent).not.toContain('2026-09-30');
  });

  it('Arabic: the same cards, tiles and pills in Arabic with Latin digits', () => {
    const { container } = show(answer([compare, promotions], { language: 'ar' }), 'ar');
    expect(screen.getByText('Sephora أغلى بنسبة 4.7%')).toBeTruthy();
    expect(screen.getByText('السعر نفسه')).toBeTruthy();
    expect(screen.getByText('4,790 مسعّر')).toBeTruthy();
    expect(screen.getByText('ضمن عروض')).toBeTruthy();
    expect(screen.getByText('من')).toBeTruthy();
    const c = screen.getByRole('link', { name: /^المقارنة/ });
    expect(c.textContent).toBe(`المقارنةUlta مقابل Sephora · makeup · 4 منتجات متطابقة · ${arDate}`);
    expect(c.getAttribute('href')).toMatch(
      /^\/ar\/compare\/?\?retailers=ulta_ae%2Csephora_me&category=makeup$/,
    );
    expect(screen.getByRole('link', { name: /^العروض/ }).textContent).toBe(
      `العروضSephora · منتج واحد · ${arDate}`,
    );
    expect(container.textContent).not.toMatch(/[٠-٩]/);
  });

  it('a tool without products or shares adds nothing but its pill', () => {
    const coverage: ToolEnvelope = {
      status: 'ok',
      citation: cite({ tool: 'coverage_status' }),
      caveats: [],
      data: { retailers: [{ retailer: 'ulta_ae', status: 'supported' }] },
    };
    show(answer([coverage]));
    expect(screen.queryByRole('list', { name: en.assistant.answer.products })).toBeNull();
    expect(screen.queryByRole('list', { name: en.assistant.share.label })).toBeNull();
    const pill = screen.getByRole('link', { name: /^Dataset/ });
    expect(pill.textContent).toBe('Dataset30 Sept 2026');
    expect(pill.getAttribute('href')).toMatch(/^\/en\/dataset\/?$/);
  });
});
