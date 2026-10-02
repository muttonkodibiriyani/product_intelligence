import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import en from '@/messages/en.json';
import { PageHeader } from './page-header';
import { Loading, Skeleton } from './skeleton';

afterEach(cleanup);

/** PageHeader carries the as-of line, which asks /meta: it needs the query and message providers. */
const wrap = (ui: ReactNode) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NextIntlClientProvider locale="en" messages={en}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );

describe('PageHeader', () => {
  it('names the page with one h1 carrying the id, then its intro and tools', () => {
    wrap(
      <PageHeader
        id="p-title"
        title="Promotions"
        intro="Below regular price"
        tools={<button>Reset</button>}
      />,
    );
    const h1 = screen.getByRole('heading', { level: 1, name: 'Promotions' });
    expect(h1.id).toBe('p-title');
    expect(screen.getByText('Below regular price')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeTruthy();
  });

  it('links to the data from every page, and shows no as-of date before /meta answers', () => {
    wrap(<PageHeader title="Compare" />);
    // Next's Link applies the trailing slash only in a build; the anchor is what matters here.
    expect(screen.getByRole('link', { name: 'About the data' }).getAttribute('href')).toMatch(
      /^\/en\/?#dataset$/,
    );
    expect(screen.queryByText(/Data as of/)).toBeNull();
  });

  it('draws no intro box without an intro', () => {
    const { container } = wrap(<PageHeader title="Compare" />);
    expect(container.querySelector('.max-w-prose')).toBeNull();
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
