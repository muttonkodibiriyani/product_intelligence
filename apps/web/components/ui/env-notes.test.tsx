import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Envelope } from '@/lib/api/types';
import en from '@/messages/en.json';
import { EnvNotes } from './env-notes';

// /meta is not loaded here: ids the app has no name for are shown as sent.
vi.mock('../use-meta', () => ({ useRetailerName: () => (id: string) => (id === 'ulta_ae' ? 'Ulta' : id) }));

afterEach(cleanup);

const partial = (retailer: string) => ({
  code: 'retailer_partial',
  en: `${retailer} is only partly collected.`,
  ar: `بيانات ${retailer} مجمّعة جزئياً.`,
  params: { retailer },
});

const env = (caveats: ReturnType<typeof partial>[]) =>
  ({ status: 'ok', data: null, meta: {}, caveats }) as unknown as Envelope<unknown>;

const show = (e: Envelope<unknown>) => (
  <NextIntlClientProvider locale="en" messages={en}>
    <EnvNotes env={e} />
  </NextIntlClientProvider>
);

describe('EnvNotes', () => {
  it('shows every caveat when a code repeats, also after an update', () => {
    // React reports duplicate keys here; with them, an update may drop or reuse a line.
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const r = render(show(env([partial('shop_a'), partial('shop_b')])));
    expect(r.container.textContent).toContain('shop_a is only partly collected.');
    expect(r.container.textContent).toContain('shop_b is only partly collected.');
    r.rerender(show(env([partial('shop_c'), partial('shop_b')])));
    const lines = [...r.container.querySelectorAll('p')].map((p) => p.textContent);
    expect(lines).toEqual(['shop_c is only partly collected.', 'shop_b is only partly collected.']);
    expect(error).not.toHaveBeenCalled();
    error.mockRestore();
  });

  it('shows nothing when the data is fine and there are no caveats', () => {
    expect(render(show(env([]))).container.textContent).toBe('');
  });

  it('rewords a retailer id the API mentions to the shop name, in both languages', () => {
    const r = render(show(env([partial('ulta_ae')])));
    expect(r.container.textContent).toBe('Ulta is only partly collected.');
    r.rerender(
      <NextIntlClientProvider locale="ar" messages={en}>
        <EnvNotes env={env([partial('ulta_ae')])} />
      </NextIntlClientProvider>,
    );
    expect(r.container.textContent).toBe('بيانات Ulta مجمّعة جزئياً.');
  });

  it('is the one note box: it carries the note role for the Dataset page to own', () => {
    expect(render(show(env([partial('shop_a')]))).getByRole('note')).toBeTruthy();
  });
});
