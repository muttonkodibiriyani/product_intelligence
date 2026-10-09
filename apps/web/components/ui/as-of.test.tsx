import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import type { Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { sourceObservationDate, UltaPriceDate } from './as-of';

type Meta = Schemas['MetaView'];

const fixture = (retailers: string[], sources: { source: string; lastDate: string }[]): Meta =>
  ({
    retailers: retailers.map((id) => ({ id, name: id === 'ulta_ae' ? 'Ulta Beauty UAE' : 'Other' })),
    sources: sources.map(({ source, lastDate }) => ({ source, lastDate })),
  }) as Meta;

function label(meta: Meta, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en}>
      <UltaPriceDate meta={meta} />
    </NextIntlClientProvider>,
  ).container;
}

afterEach(cleanup);

describe('UltaPriceDate', () => {
  it('labels the exact Ulta latest-source date as context, without claiming every offer has that date', () => {
    const meta = fixture(
      ['ulta_ae', 'sephora_me'],
      [
        { source: 'ulta_ae', lastDate: '2026-10-01' },
        { source: 'sephora_me', lastDate: '2026-10-09' },
      ],
    );
    const container = label(meta);
    expect(container.textContent).toBe('Latest Ulta price data: 1 Oct 2026. Individual offers may be older.');
    expect(container.textContent).not.toContain('9 Oct');
    expect(container.querySelector('[data-retailer-date="ulta_ae"]')?.className).toContain('break-words');
    expect(label(meta, 'ar').textContent).toMatch(/أحدث.*Ulta.*1.*10.*2026|أحدث.*Ulta.*1.*أكتوبر.*2026/);
  });

  it('fails closed when Ulta source metadata has no usable date', () => {
    expect(label(fixture(['ulta_ae'], [])).textContent).toBe(
      'Latest Ulta price date unavailable; treat prices as stale.',
    );
    expect(
      sourceObservationDate(fixture(['ulta_ae'], [{ source: 'ulta_ae', lastDate: 'soon' }]), 'ulta_ae'),
    ).toBeNull();
  });

  it("never assigns Ulta's label or date to another retailer", () => {
    const meta = fixture(['sephora_me'], [{ source: 'sephora_me', lastDate: '2026-10-01' }]);
    expect(label(meta).textContent).toBe('');
    expect(sourceObservationDate(meta, 'ulta_ae')).toBeNull();
  });
});
