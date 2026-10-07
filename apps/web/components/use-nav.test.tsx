import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Summary } from '@/lib/api/summary';
import type { Envelope, Schemas } from '@/lib/api/types';
import en from '@/messages/en.json';
import { useNav } from './use-nav';
import type { RetailerSummary } from './widgets/kpis';

type Summaries = ReturnType<typeof import('./widgets/use-summaries').useSummaries>;

const ctx = vi.hoisted(() => ({
  meta: { data: undefined as Envelope<Schemas['MetaView']> | undefined },
  summaries: {} as {
    rows: RetailerSummary[];
    loading: boolean;
    error: { error: unknown; retry: () => void } | null;
  },
}));
vi.mock('./use-meta', () => ({ useMeta: () => ctx.meta }));
vi.mock('./widgets/use-compare', () => ({ useRetailers: () => ({ ids: ['a', 'b'] }) }));
vi.mock('./widgets/use-summaries', () => ({
  useSummaries: (): Summaries => ({ ...ctx.summaries, empty: [], missing: [] }),
}));
vi.mock('next/navigation', () => ({ usePathname: () => '/en/' }));

afterEach(cleanup);

/** Lists the nav the hook builds, one `<li data-key>` per page, to assert on. */
function Probe() {
  return (
    <ul>
      {useNav().map((i) => (
        <li key={i.key} data-key={i.key} data-state={i.state}>
          {i.label}
        </li>
      ))}
    </ul>
  );
}

function keys() {
  render(
    <NextIntlClientProvider
      locale="en"
      messages={en}
      onError={(e) => {
        throw e;
      }}
    >
      <Probe />
    </NextIntlClientProvider>,
  );
  return screen.getAllByRole('listitem').map((li) => li.getAttribute('data-key'));
}

const summary = golden('summary') as Envelope<Summary>;
const row = (data: Partial<Summary>): RetailerSummary => ({
  retailer: 'a',
  name: 'Shop A',
  data: { ...summary.data!, ...data },
  caveats: [],
});

describe('useNav', () => {
  it('keeps Products, Prices and Promotions listed while /summary is loading', () => {
    ctx.summaries = { rows: [], loading: true, error: null };
    expect(keys()).toEqual(expect.arrayContaining(['explore', 'prices', 'promotions']));
  });

  it('keeps Products, Prices and Promotions listed when /summary fails: a 500 must not empty the nav', () => {
    ctx.summaries = { rows: [], loading: false, error: { error: new Error('500'), retry: vi.fn() } };
    expect(keys()).toEqual(expect.arrayContaining(['explore', 'prices', 'promotions']));
  });

  it('drops them once every /summary has answered with nothing priced and no measured discounts', () => {
    ctx.summaries = {
      rows: [row({ priced: 0, promoSharePct: null })],
      loading: false,
      error: null,
    };
    const listed = keys();
    expect(listed).toEqual(['overview', 'compare', 'launches', 'dataset', 'assistant']);
  });

  it('lists Insights only when /meta comes from an API that serves it (1.23.0+)', () => {
    ctx.summaries = { rows: [], loading: true, error: null };
    const meta = golden('meta') as Envelope<Schemas['MetaView']>;
    ctx.meta = { data: { ...meta, meta: { ...meta.meta, apiVersion: '1.22.0' } } };
    expect(keys()).not.toContain('insights');
    cleanup();
    ctx.meta = { data: { ...meta, meta: { ...meta.meta, apiVersion: '1.23.0' } } };
    expect(keys()).toContain('insights');
    ctx.meta = { data: undefined };
  });
});
