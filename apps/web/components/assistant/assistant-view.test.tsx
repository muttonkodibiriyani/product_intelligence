import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ASSISTANT_CONNECTED, SUGGESTED } from '@/lib/assistant';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { AssistantView } from './assistant-view';

const auth = vi.hoisted(() => ({ api: null as null | { get: (...a: unknown[]) => Promise<unknown> } }));
vi.mock('../auth-provider', () => ({ useAuth: () => auth }));

afterEach(() => {
  cleanup();
  auth.api = null;
  vi.unstubAllGlobals();
});

const show = (locale: 'en' | 'ar', connected?: boolean) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NextIntlClientProvider locale={locale} messages={locale === 'en' ? en : ar}>
        <AssistantView connected={connected} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );

describe('AssistantView', () => {
  it('is not connected yet: the page never sends a question', () => {
    expect(ASSISTANT_CONNECTED).toBe(false);
  });

  it('shows the name, the connect state and labelled sample questions', () => {
    show('en');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Ryzan AI Assistant');
    expect(screen.getByRole('status').textContent).toContain('Connect to enable');
    expect(screen.getByText('Sample — not live data')).toBeTruthy();
    expect(screen.getAllByRole('listitem')).toHaveLength(SUGGESTED.length);
  });

  it('a suggestion fills the question, but Send stays off while not connected', () => {
    show('en');
    fireEvent.click(screen.getByText(en.assistant.q.promo));
    expect((screen.getByLabelText('Your question') as HTMLTextAreaElement).value).toBe(en.assistant.q.promo);
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(en.assistant.composer.disabled)).toBeTruthy();
  });

  it('Send turns on with a question once connected, and the connect state goes', () => {
    show('en', true);
    expect(screen.queryByRole('status')).toBeNull();
    fireEvent.click(screen.getByText(en.assistant.q.gaps));
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('Arabic uses the approved name and labels', () => {
    show('ar');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('مساعد ريزان الذكي');
    expect(screen.getByText('نموذج — ليست بيانات حية')).toBeTruthy();
    expect(ar.app.nav.assistant).toBe('مساعد ريزان');
    expect(en.app.nav.assistant).toBe('Ryzan AI');
  });
});

const summary = (over: Record<string, unknown> = {}) => ({
  status: 'ok',
  data: {
    retailer: 'Retailer_A',
    products: 1200,
    priced: 1100,
    medianPrice: { amount: '89.50', currency: 'AED', minor: 8950 },
    promoSharePct: '23.4',
    currency: 'AED',
  },
  meta: {
    apiVersion: '1.4.1',
    currency: 'AED',
    cutoff: '2026-09-30',
    endpoint: '/api/v1/summary',
    filters: {},
    generation: 'g7',
    market: 'uae',
    metricVersion: 'm1',
    scope: 'retailer',
  },
  caveats: [],
  cohort: { description: 'All listed products', n: 1200 },
  ...over,
});

describe('sample answer (S5)', () => {
  const withApi = (get: () => Promise<unknown>) => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    auth.api = { get: vi.fn(get) };
  };

  it('is built from the live /summary numbers, labelled, and cited', async () => {
    withApi(() => Promise.resolve(summary()));
    show('en');
    expect(await screen.findByText(en.assistant.sample.title)).toBeTruthy();
    expect(screen.getAllByText('Sample — not live data')).toHaveLength(2);
    const text = document.body.textContent ?? '';
    expect(text).toContain('Retailer_A lists 1200 products.');
    expect(text).toContain('1100 of them have a price.');
    expect(text).toContain('AED');
    expect(text).toContain('89.50');
    expect(text).toContain('23.4% of priced products are on promotion.');
    const cite = screen.getByText(/Market summary/);
    expect(cite.textContent).toContain('Market summary');
    expect(cite.textContent).toContain('2026-09-30');
    expect(cite.textContent).toContain('n = 1200');
    expect(auth.api!.get).toHaveBeenCalledWith('/api/v1/summary', expect.anything());
  });

  it('leaves out withheld numbers instead of showing zero', async () => {
    withApi(() =>
      Promise.resolve(
        summary({ data: { ...summary().data, priced: null, medianPrice: null, promoSharePct: null } }),
      ),
    );
    show('en');
    await screen.findByText(en.assistant.sample.title);
    const text = document.body.textContent ?? '';
    expect(text).not.toContain('have a price');
    expect(text).not.toContain('median price');
    expect(text).not.toContain('of priced products are on promotion');
  });

  it('shows nothing when the call fails or the data is not ok', async () => {
    withApi(() => Promise.reject(new Error('down')));
    show('en');
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(en.assistant.sample.title)).toBeNull();
    cleanup();
    withApi(() => Promise.resolve(summary({ status: 'not_enough_data', data: null })));
    show('en');
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(en.assistant.sample.title)).toBeNull();
  });

  it('server text is escaped, never Markdown', async () => {
    withApi(() =>
      Promise.resolve(summary({ data: { ...summary().data, retailer: '**[x](https://e.example)**' } })),
    );
    const { container } = show('en');
    await screen.findByText(en.assistant.sample.title);
    expect(container.textContent).toContain('**[x](https://e.example)** lists');
    expect(container.querySelector('a[href^="https://e"]')).toBeNull();
  });

  it('Arabic sample uses the Arabic text', async () => {
    withApi(() => Promise.resolve(summary()));
    show('ar');
    expect(await screen.findByText(ar.assistant.sample.title)).toBeTruthy();
  });
});
