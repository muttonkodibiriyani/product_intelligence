import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { Logo, LogoMark, MARK_PATH } from './logo';

function show(ui: React.ReactNode, locale: 'en' | 'ar' = 'en') {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
      {ui}
    </NextIntlClientProvider>,
  );
}

afterEach(cleanup);

describe('Logo', () => {
  it('is the link home, named after the app, with the mark decorative and the wordmark in the app’s type', () => {
    show(<Logo />);
    const link = screen.getByRole('link', { name: 'Product Intelligence' });
    expect(link.getAttribute('href')).toMatch(/^\/en\/?$/);
    const svg = link.querySelector('svg')!;
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(link.textContent).toContain('Product Intelligence');
    expect(link.textContent).toContain('UAE retail pricing');
    expect(link.querySelector('img, [style*=font-family], link[href*=font]')).toBeNull();
  });

  it('compact: the name only, still the accessible name', () => {
    show(<Logo compact />);
    const link = screen.getByRole('link', { name: 'Product Intelligence' });
    expect(link.textContent).toBe('Product Intelligence');
  });

  it('in Arabic the wordmark is the translated name and the mark is the same path', () => {
    show(<Logo />, 'ar');
    const link = screen.getByRole('link', { name: 'ذكاء المنتجات' });
    expect(link.getAttribute('href')).toMatch(/^\/ar\/?$/);
    expect(link.querySelector('path')?.getAttribute('d')).toBe(MARK_PATH);
  });

  it('the mark is one even-odd path in the current colour: no gradient, no second fill, no script', () => {
    show(<LogoMark size={16} />);
    const svg = document.querySelector('svg')!;
    expect(svg.getAttribute('width')).toBe('16');
    expect(svg.getAttribute('viewBox')).toBe('0 0 16 16');
    expect(svg.querySelectorAll('path')).toHaveLength(1);
    expect(svg.querySelector('path')?.getAttribute('fill')).toBe('currentColor');
    expect(svg.querySelector('path')?.getAttribute('fill-rule')).toBe('evenodd');
    expect(svg.querySelector('linearGradient, radialGradient, filter, script, image')).toBeNull();
  });
});
