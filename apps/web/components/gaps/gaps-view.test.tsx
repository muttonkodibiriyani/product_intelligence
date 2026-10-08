import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { gapItems, gapsData } from '@/e2e/brand-gaps-fixture';
import { golden } from '@/lib/api/golden';
import type { Envelope } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { GapsView } from './gaps-view';

const base = golden('meta') as Envelope<unknown>;
const env = <T,>(data: T | null, extra: object = {}): Envelope<T> => ({
  ...base,
  status: 'ok',
  data,
  caveats: [],
  ...extra,
});

let answers: Record<string, Envelope<unknown>> = {};
let apiVersion: string | null = '1.27.0';
let search = '';
const calls: string[] = [];
const push = vi.fn();
vi.mock('../auth-provider', () => ({
  useAuth: () => ({
    api: {
      get: async (path: string) => {
        calls.push(path);
        return answers[path];
      },
    },
  }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/en/gaps/',
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock('../use-meta', () => ({
  useRetailerName: () => (id: string) =>
    ({
      ulta_ae: 'Ulta',
      sephora_me: 'Sephora',
      faces_ae: 'Faces',
      ounass_ae: 'Ounass',
      bloomingdales_ae: "Bloomingdale's",
    })[id] ?? id,
  useMeta: () => ({ data: apiVersion ? { meta: { apiVersion } } : undefined }),
}));

afterEach(() => {
  cleanup();
  calls.length = 0;
  push.mockReset();
});

function view(query = '', locale: 'en' | 'ar' = 'en') {
  search = query;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider
        locale={locale}
        messages={locale === 'ar' ? ar : en}
        onError={(e) => {
          throw e;
        }}
      >
        <GapsView />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const M = { en: en.gaps, ar: ar.gaps };

describe('GapsView', () => {
  answers = {
    '/api/v1/brand-gaps': env(gapsData),
    '/api/v1/brand-gaps/items': env(gapItems),
  };

  it.each(['en', 'ar'] as const)(
    'headline, proven not-at per shop and withheld shops (%s)',
    async (locale) => {
      view('', locale);
      const head = await screen.findByRole('region', { name: M[locale].label.unmatched });
      expect(within(head).getByText(M[locale].labelNote.unmatched)).toBeTruthy();
      expect(within(head).getByRole('button', { name: new RegExp(`: 21\\.`) })).toBeTruthy();

      const notAt = screen.getByRole('region', { name: M[locale].notAt.title });
      expect(within(notAt).getByText('Sephora').closest('li')!.textContent).toMatch(/9$/);
      expect(within(notAt).getByText('Faces').closest('li')!.textContent).toMatch(/17$/);
      // A withheld shop has no count: it is never listed as proven, never 0.
      expect(within(notAt).queryByText('Ounass')).toBeNull();

      const withheld = screen.getByRole('region', { name: M[locale].withheld.title });
      const reasons = locale === 'ar' ? ar.reasons : en.reasons;
      expect(within(withheld).getByText('Ounass').parentElement!.textContent).toContain(
        reasons.retailer_partial,
      );
      expect(within(withheld).getByText("Bloomingdale's").parentElement!.textContent).toContain(
        reasons.retailer_blocked,
      );
    },
  );

  it('draws a not-at column only for shops the API counted', async () => {
    view();
    const table = await screen.findByRole('table');
    const cols = within(table)
      .getAllByRole('columnheader')
      .map((c) => c.textContent);
    expect(cols).toContain('Not at Sephora');
    expect(cols).toContain('Not at Faces');
    expect(cols.some((c) => /Ounass|Bloomingdale/.test(c ?? ''))).toBe(false);
  });

  it('sorts brands most unmatched first by default, and by listings when asked', async () => {
    view();
    const brands = async () =>
      within(await screen.findByRole('table'))
        .getAllByRole('rowheader')
        .map((c) => c.textContent);
    expect(await brands()).toEqual(['Dior', 'Kylie Cosmetics', 'Huda Beauty']);
    cleanup();
    view('sort=focus_n');
    expect(await brands()).toEqual(['Dior', 'Huda Beauty', 'Kylie Cosmetics']);
  });

  it('a count opens its own list in the URL', async () => {
    view();
    const table = await screen.findByRole('table');
    fireEvent.click(within(table).getByRole('button', { name: 'Not at Faces, Dior: 9. Open the list' }));
    expect(push).toHaveBeenCalledWith('/en/gaps/?list=Dior&side=not_at&retailer=faces_ae', { scroll: false });
  });

  it('a zero is plain text, not a list to open', async () => {
    view();
    const row = (await screen.findByRole('rowheader', { name: 'Huda Beauty' })).closest('tr')!;
    expect(within(row).queryByRole('button', { name: /Not at Sephora, Huda Beauty: 0/ })).toBeNull();
  });

  it.each(['en', 'ar'] as const)(
    'the open list names the listings and where they are proven absent (%s)',
    async (locale) => {
      view('list=Dior&side=not_at&retailer=faces_ae', locale);
      const list = await screen.findByRole('region', {
        name: `${M[locale].side.not_at.replace('{shop}', 'Faces')} · Dior`,
      });
      expect(await within(list).findByRole('link', { name: 'Rouge Dior Lipstick 999' })).toBeTruthy();
      expect(within(list).getByText(M[locale].list.notAt.replace('{shops}', 'Faces, Sephora'))).toBeTruthy();
      expect(calls).toContain('/api/v1/brand-gaps/items');
    },
  );

  it('a list for a withheld shop says why, never "no listings"', async () => {
    answers['/api/v1/brand-gaps/items'] = env(null, {
      status: 'not_enough_data',
      reason: 'retailer_partial',
    });
    try {
      view('side=not_at&retailer=ounass_ae');
      const list = await screen.findByRole('region', { name: 'Not at Ounass · All brands' });
      expect(await within(list).findByText(en.reasons.retailer_partial)).toBeTruthy();
      expect(within(list).queryByText(en.gaps.list.empty)).toBeNull();
    } finally {
      answers['/api/v1/brand-gaps/items'] = env(gapItems);
    }
  });

  it('only-elsewhere reads as not counted, never 0, when the focus shop is withheld', async () => {
    answers['/api/v1/brand-gaps'] = env({ ...gapsData, totals: { ...gapsData.totals, othersOnly: null } });
    try {
      view();
      const head = await screen.findByRole('region', { name: en.gaps.label.unmatched });
      expect(within(head).getByText(en.gaps.othersOnlyWithheld.replace('{shop}', 'Ulta'))).toBeTruthy();
    } finally {
      answers['/api/v1/brand-gaps'] = env(gapsData);
    }
  });

  it('an API that does not serve brand gaps is never called', async () => {
    apiVersion = '1.26.0';
    try {
      view();
      expect(await screen.findByText(en.gaps.notServed)).toBeTruthy();
      expect(calls).toEqual([]);
    } finally {
      apiVersion = '1.27.0';
    }
  });
});
