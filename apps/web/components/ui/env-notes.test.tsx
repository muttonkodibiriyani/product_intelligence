import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Envelope } from '@/lib/api/types';
import en from '@/messages/en.json';
import { EnvNotes } from './env-notes';

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
});
