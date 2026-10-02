import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { REVEAL_STEP_MS } from '@/lib/assistant/reveal';
import type { ChatAnswer, Citation } from '@/lib/assistant/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { AnswerView } from './answer-view';
import { ProgressChips } from './progress-chips';

const get = vi.fn(async () => ({ data: { card: { brand: 'Brand', name: 'Serum' } } }));
vi.mock('../auth-provider', () => ({ useAuth: () => ({ api: { get } }) }));

let reduced = false;
beforeEach(() => {
  reduced = false;
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: reduced && q.includes('reduce') }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const citation: Citation = {
  tool: 'compare',
  toolVersion: '1',
  apiVersion: '1.4.1',
  metricVersion: '1',
  datasetGeneration: 'g1',
  cutoff: '2026-09-30',
  market: 'uae',
  currency: 'AED',
  filters: { category: 'skincare', brands: [] },
  cohort: { description: { untrusted: 'Matched products' }, n: 42 },
};

const answer = (over: Partial<ChatAnswer> = {}): ChatAnswer => ({
  status: 'answered',
  answerMd: 'Median gap is **12.5%**.\n\nCheapest: [[product:p1]].',
  language: 'en',
  citations: [citation],
  caveats: [{ en: { untrusted: 'Prices exclude delivery.' }, ar: { untrusted: 'الأسعار لا تشمل التوصيل.' } }],
  productIds: ['p1'],
  notEnoughData: [],
  toolResults: [],
  costUsd: '0.0004',
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

describe('AnswerView', () => {
  it('reveals the verified answer section by section, then its sources', () => {
    vi.useFakeTimers();
    show(answer());
    expect(screen.queryByText(/Median gap/)).toBeNull();
    expect(screen.queryByText('Sources')).toBeNull();
    act(() => void vi.advanceTimersByTime(REVEAL_STEP_MS));
    expect(screen.getByText(/Median gap/)).toBeTruthy();
    expect(screen.queryByText(/Cheapest/)).toBeNull();
    act(() => void vi.advanceTimersByTime(REVEAL_STEP_MS));
    expect(screen.getByText(/Cheapest/)).toBeTruthy();
    expect(screen.getByText('Sources')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Show full answer' })).toBeNull();
  });

  it('skip shows everything at once', () => {
    vi.useFakeTimers();
    show(answer());
    fireEvent.click(screen.getByRole('button', { name: 'Show full answer' }));
    expect(screen.getByText(/Cheapest/)).toBeTruthy();
  });

  it('shows everything at once under prefers-reduced-motion', () => {
    reduced = true;
    show(answer());
    expect(screen.getByText(/Cheapest/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Show full answer' })).toBeNull();
  });

  it('cites tool, cutoff, cohort and filters, and names products from the API', async () => {
    reduced = true;
    show(answer());
    const summary = screen.getByText(/data to/);
    expect(summary.textContent).toContain('Price comparison');
    expect(summary.textContent).toContain('2026-09-30');
    expect(summary.textContent).toContain('Matched products');
    expect(summary.textContent).toContain('n = 42');
    expect(screen.getByText('category: skincare')).toBeTruthy();
    expect(screen.getByText('Prices exclude delivery.')).toBeTruthy();
    expect(await screen.findByText('Brand Serum')).toBeTruthy();
    expect(get).toHaveBeenCalledWith(
      '/api/v1/products/{product_id}',
      expect.objectContaining({ params: { product_id: 'p1' } }),
    );
  });

  it('renders model links and HTML as text, never as elements', () => {
    reduced = true;
    const { container } = show(
      answer({ answerMd: '[x](https://evil.example) <img src=x onerror=alert(1)>' }),
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('a[href^="https://evil"]')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
  });

  it('unverified: labels the fallback and shows tool results as a plain table', () => {
    reduced = true;
    show(
      answer({
        status: 'unverified',
        answerMd: 'Tool results below.',
        toolResults: [
          { status: 'ok', data: { rows: [{ retailer: 'A', price: 10 }] }, citation, caveats: [] },
        ],
      }),
    );
    expect(screen.getByText(en.assistant.answer.unverified)).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'retailer' })).toBeTruthy();
    expect(screen.getByRole('cell', { name: '10' })).toBeTruthy();
  });

  it('not enough data is said plainly, in the page language', () => {
    reduced = true;
    show(
      answer({
        answerMd: 'Not enough data.',
        notEnoughData: [
          {
            tool: 'index_trend',
            reason: 'few_points',
            detail: { en: { untrusted: 'Too few weeks.' }, ar: { untrusted: 'أسابيع قليلة جدًا.' } },
          },
        ],
      }),
      'ar',
    );
    expect(screen.getByText('أسابيع قليلة جدًا.')).toBeTruthy();
    expect(screen.getByText('الأسعار لا تشمل التوصيل.')).toBeTruthy();
  });

  it('unavailable: a note only, no answer text', () => {
    show(answer({ status: 'unavailable', code: 'month_cap', answerMd: '' }));
    expect(screen.getByRole('alert').textContent).toBe(en.assistant.unavailable.spendCap);
    expect(screen.queryByText('Sources')).toBeNull();
  });
});

describe('ProgressChips', () => {
  const chips = (done: boolean) =>
    render(
      <NextIntlClientProvider locale="en" messages={en}>
        <ProgressChips
          done={done}
          steps={[
            { type: 'status', stage: 'thinking' },
            { type: 'tool', name: 'compare', status: 'ok' },
            { type: 'tool', name: 'index_trend', status: 'not_enough_data' },
            { type: 'status', stage: 'verifying' },
          ]}
        />
      </NextIntlClientProvider>,
    );

  it('shows stages and tools in order, the last one current', () => {
    chips(false);
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Thinking',
      'Reading Price comparison',
      'Price index: not enough data',
      'Verifying numbers',
    ]);
    expect(screen.getByText('Verifying numbers').getAttribute('aria-current')).toBe('step');
  });

  it('nothing is current once done', () => {
    chips(true);
    expect(screen.getByText('Verifying numbers').getAttribute('aria-current')).toBeNull();
  });
});
