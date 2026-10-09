import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Envelope, Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { LaunchesView } from './launches-view';

const meta = golden('meta') as Envelope<Schemas['MetaView']>;
const launches = golden('launches') as Envelope<Schemas['Launches']>;
const product = golden('product') as Envelope<Schemas['ProductDetail']>;
/** The API declining the view for this catalogue: not ok, a reason, an empty list, no caveat. */
const notApplicable: Envelope<Schemas['Launches']> = {
  ...launches,
  status: 'not_enough_data',
  reason: 'not_applicable',
  caveats: [],
  data: { items: [], total: 0, truncated: false },
};

const ctx = vi.hoisted(() => ({
  body: {} as unknown,
  detail: {} as unknown,
  asked: [] as unknown[],
  meta: {} as unknown,
}));
// Shop C restarted on the last day: still short of two days while A and B are in.
const oneBehind: Envelope<Schemas['MetaView']> = {
  ...meta,
  data: {
    ...meta.data!,
    retailers: meta.data!.retailers.map((r) => (r.id === 'shop_c' ? { ...r, since: '2026-09-30' } : r)),
  },
};
vi.mock('../auth-provider', () => ({
  useAuth: () => ({
    api: {
      get: async (path: string, opts: { query: unknown }) => {
        if (path.includes('/products/{')) return ctx.detail;
        ctx.asked.push(opts.query);
        return ctx.body;
      },
    },
  }),
}));
vi.mock('../use-meta', () => ({
  useMeta: () => ({ data: ctx.meta }),
  useRetailerName: () => (id: string) => meta.data!.retailers.find((r) => r.id === id)?.name ?? id,
}));
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(''),
  usePathname: () => '/en/launches/',
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

afterEach(() => {
  cleanup();
  ctx.asked = [];
});

function show(body: unknown, locale: 'en' | 'ar' = 'en', m: unknown = meta) {
  ctx.body = body;
  ctx.detail = product;
  ctx.meta = m;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider
        locale={locale}
        messages={locale === 'ar' ? ar : en}
        onError={(e) => {
          throw e;
        }}
      >
        <LaunchesView />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe('LaunchesView', () => {
  it('a catalogue the view does not apply to: the line names the API’s reason, no table', async () => {
    show(notApplicable);
    const line = (await screen.findByText(/Launches aren't available/)).closest('[role=status]')!;
    expect(line.textContent).toBe(`${en.launches.unavailable} ${en.reasons.not_applicable}`);
    expect(document.querySelector('table')).toBeNull();
    expect(document.querySelector('#rows')).toBeNull();
  });

  it('says the reason in Arabic too', async () => {
    show(notApplicable, 'ar');
    const line = (await screen.findByText(new RegExp(ar.launches.unavailable))).closest('[role=status]')!;
    expect(line.textContent).toBe(`${ar.launches.unavailable} ${ar.reasons.not_applicable}`);
  });

  it('names a shop still short of two days under the list, the count as a plural in both languages', async () => {
    show(launches, 'en', oneBehind);
    expect(await screen.findAllByText('Product p14')).toHaveLength(2);
    expect(document.querySelector('#launch-pending')!.textContent).toBe(
      'Shop C is not included yet: 1 of 2 collection days.',
    );
    cleanup();
    show(launches, 'ar', oneBehind);
    expect(await screen.findAllByText('Product p14')).toHaveLength(2);
    expect(document.querySelector('#launch-pending')!.textContent).toBe(
      'Shop C غير مشمول بعد: 1 من يومي جمع.',
    );
  });

  it('asks for the window ending on the last collection day, inclusive', async () => {
    show(launches);
    expect(await screen.findAllByText('Product p14')).toHaveLength(2);
    expect(ctx.asked).toEqual([{ since: '2026-09-01', limit: 100 }]);
  });

  it('anchors the window on the last collection day even when the cutoff falls late in the UTC day', async () => {
    // Golden cutoff is 00:00Z, so its UTC date equals the last collection day; a 22:30Z cutoff
    // would not, and the view must still ask from the day after 30 days before the last entry.
    const late: Envelope<Schemas['MetaView']> = {
      ...meta,
      data: { ...meta.data!, cutoff: '2026-09-30T22:30:00Z', dates: [...meta.data!.dates, '2026-10-01'] },
    };
    show(launches, 'en', late);
    expect(await screen.findAllByText('Product p14')).toHaveLength(2);
    expect(ctx.asked).toEqual([{ since: '2026-09-02', limit: 100 }]);
  });

  it('shows each listed shop source state from its own last date, without another request', async () => {
    const later: Envelope<Schemas['MetaView']> = {
      ...meta,
      data: { ...meta.data!, dates: [...meta.data!.dates, '2026-10-01'] },
    };
    show(launches, 'ar', later);
    expect(await screen.findAllByText('Product p14')).toHaveLength(2);
    const strip = screen.getByRole('region', { name: ar.freshness.title });
    const states = [...strip.querySelectorAll('[data-evidence-state]')].map((el) =>
      el.getAttribute('data-evidence-state'),
    );
    expect(states.length).toBeGreaterThan(0);
    // Every shop's own last date (30 Sep) is before the view's (1 Oct): none is called current.
    expect(states.every((s) => s === 'stale' || s === 'unavailable')).toBe(true);
    expect(ctx.asked).toHaveLength(1);
  });
});
