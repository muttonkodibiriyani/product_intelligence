import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { PageHeader } from './page-header';
import { Loading, Skeleton } from './skeleton';

afterEach(cleanup);

const intl = (ui: ReactNode, locale: 'en' | 'ar' = 'en') =>
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en}>
      {ui}
    </NextIntlClientProvider>,
  );

describe('PageHeader', () => {
  it('names the page with one h1 carrying the id, then its intro, as-of line and tools', () => {
    intl(
      <PageHeader
        id="p-title"
        title="Promotions"
        intro="Below regular price"
        asOf="Data as of 30 Sep 2026"
        tools={<button>Reset</button>}
      />,
    );
    const h1 = screen.getByRole('heading', { level: 1, name: 'Promotions' });
    expect(h1.id).toBe('p-title');
    expect(screen.getByText('Below regular price')).toBeTruthy();
    expect(screen.getByText(/Data as of 30 Sep 2026/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeTruthy();
  });

  it('draws no intro box without an intro', () => {
    const { container } = intl(<PageHeader title="Compare" />);
    expect(container.querySelector('.max-w-prose')).toBeNull();
  });

  it('links to About the data on the Dataset page, in the page’s language', () => {
    intl(<PageHeader title="Compare" />);
    const link = screen.getByRole('link', { name: 'About the data' });
    // next/link drops the trailing slash outside the app's router config; the static build keeps it.
    expect(link.getAttribute('href')).toMatch(/^\/en\/dataset\/?#about-data$/);
    cleanup();
    intl(<PageHeader title="المقارنة" />, 'ar');
    expect(screen.getByRole('link', { name: 'عن البيانات' }).getAttribute('href')).toMatch(
      /^\/ar\/dataset\/?#about-data$/,
    );
  });

  it('never draws a note box of its own', () => {
    intl(<PageHeader title="Compare" intro="x" asOf="y" />);
    expect(screen.queryByRole('note')).toBeNull();
  });
});

describe('Skeleton', () => {
  it.each(['lines', 'chart', 'table', 'kpi'] as const)('%s is hidden from assistive tech', (kind) => {
    const { container } = render(<Skeleton kind={kind} />);
    expect(container.firstElementChild?.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelectorAll('.skeleton').length).toBeGreaterThan(0);
  });

  it('draws the rows it is asked for', () => {
    const { container } = render(<Skeleton kind="table" rows={5} />);
    expect(container.firstElementChild?.children).toHaveLength(5);
  });
});

describe('Loading', () => {
  it('says loading in words, as a busy status, with the shape beside it', () => {
    const { container } = render(<Loading kind="table">Loading promotions…</Loading>);
    expect(screen.getByRole('status').textContent).toBe('Loading promotions…');
    expect(container.firstElementChild?.getAttribute('aria-busy')).toBe('true');
  });
});
