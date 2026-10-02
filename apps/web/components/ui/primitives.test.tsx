import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { PageHeader } from './page-header';
import { Loading, Skeleton } from './skeleton';

afterEach(cleanup);

/** PageHeader carries the as-of line, which asks /meta: it needs the query and message providers. */
const wrap = (ui: ReactNode, locale: 'en' | 'ar' = 'en') =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NextIntlClientProvider
        locale={locale}
        messages={locale === 'ar' ? ar : en}
        onError={(e) => {
          throw e;
        }}
      >
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );

describe('PageHeader', () => {
  it('names the page with one h1 carrying the id, then its intro, as-of line and tools', () => {
    wrap(
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

  it('links to About the data on the Dataset page from every page, in the page’s language; no date before /meta answers', () => {
    wrap(<PageHeader title="Compare" />);
    // next/link drops the trailing slash outside the app's router config; the static build keeps it.
    expect(screen.getByRole('link', { name: 'About the data' }).getAttribute('href')).toMatch(
      /^\/en\/dataset\/?#about-data$/,
    );
    expect(screen.queryByText(/Data as of/)).toBeNull();
    cleanup();
    wrap(<PageHeader title="المقارنة" />, 'ar');
    expect(screen.getByRole('link', { name: 'عن البيانات' }).getAttribute('href')).toMatch(
      /^\/ar\/dataset\/?#about-data$/,
    );
  });

  it('draws no intro box without an intro', () => {
    const { container } = wrap(<PageHeader title="Compare" />);
    expect(container.querySelector('.max-w-prose')).toBeNull();
  });

  it('never draws a note box of its own', () => {
    wrap(<PageHeader title="Compare" intro="x" asOf="y" />);
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
