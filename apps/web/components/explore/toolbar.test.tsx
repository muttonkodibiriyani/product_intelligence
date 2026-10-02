import { cleanup, render, screen, within } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { EMPTY, type ExploreState } from '@/lib/explore';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { Toolbar } from './toolbar';

const name = (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id;

function sortOptions(state: ExploreState, locale: 'en' | 'ar' = 'en') {
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
      <Toolbar state={state} update={() => {}} name={name} />
    </NextIntlClientProvider>,
  );
  return within(screen.getByRole('combobox')).getAllByRole('option') as HTMLOptionElement[];
}

afterEach(cleanup);

describe('Toolbar: the gap sorts', () => {
  it('without a pair, the greyed-out gap sorts say what they need, with no placeholder name', () => {
    const opts = sortOptions(EMPTY).slice(3);
    expect(opts.map((o) => [o.textContent, o.disabled])).toEqual([
      ['Gap, dearest first (pick two retailers)', true],
      ['Gap, cheapest first (pick two retailers)', true],
    ]);
    expect(opts.some((o) => o.textContent!.includes('–'))).toBe(false);
  });

  it('with a pair, they name the retailer the gap is read for', () => {
    const opts = sortOptions({ ...EMPTY, retailer: ['shop_a', 'shop_b'] }).slice(3);
    expect(opts.map((o) => [o.textContent, o.disabled])).toEqual([
      ['Gap: Shop B dearest first', false],
      ['Gap: Shop B cheapest first', false],
    ]);
  });

  it('in Arabic', () => {
    const opts = sortOptions(EMPTY, 'ar').slice(3);
    expect(opts.map((o) => o.textContent)).toEqual([
      'الفرق، الأغلى أولًا (اختر متجرين)',
      'الفرق، الأرخص أولًا (اختر متجرين)',
    ]);
  });
});
