import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Envelope, Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { AppSidebar } from './app-sidebar';
import type { AuthState } from './auth-provider';

type Meta = Envelope<Schemas['MetaView']>;

const ctx = vi.hoisted(() => ({
  value: {} as { state: AuthState; auth: unknown; api: null },
  useMeta: vi.fn(),
}));
vi.mock('./auth-provider', () => ({ useAuth: () => ctx.value }));
vi.mock('./use-meta', () => ({ useMeta: () => ctx.useMeta() }));
// No retailer summaries yet: the nav keeps every page while its signals are unknown.
vi.mock('./widgets/use-compare', () => ({ useRetailers: () => ({ ids: [] }) }));
vi.mock('./widgets/use-summaries', () => ({
  useSummaries: () => ({ rows: [], loading: true, error: null }),
}));
vi.mock('next/navigation', () => ({
  usePathname: () => '/en/launches/',
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

afterEach(() => {
  cleanup();
  ctx.useMeta.mockClear();
});

const signedIn: AuthState = { kind: 'signed_in', session: { email: 'a@x', role: 'viewer', verified: true } };
const meta = golden('meta') as Meta;
// The dataset after its first run only: no shop has two collection days yet.
const firstDay: Meta = { ...meta, data: { ...meta.data!, dates: ['2026-09-30'] } };

function renderWith(m: Meta | undefined, locale: 'en' | 'ar' = 'en') {
  ctx.value = { state: signedIn, auth: { signOut: vi.fn() }, api: null };
  ctx.useMeta.mockImplementation(() => ({ data: m }));
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
      <AppSidebar />
    </NextIntlClientProvider>,
  );
}

describe('AppSidebar', () => {
  it('badges Launches "soon" until every shop has two collection days; the link stays and is current', () => {
    renderWith(firstDay);
    const link = screen.getByRole('link', { name: /Launches/ });
    expect(link.getAttribute('href')).toMatch(/^\/en\/launches\/?$/);
    expect(link.getAttribute('aria-current')).toBe('page');
    expect(link.textContent).toContain(en.app.nav.soon);
    cleanup();
    renderWith(meta);
    expect(screen.getByRole('link', { name: /Launches/ }).textContent).not.toContain(en.app.nav.soon);
    cleanup();
    // Nothing to say until /meta has answered.
    renderWith(undefined);
    expect(screen.getByRole('link', { name: /Launches/ }).textContent).not.toContain(en.app.nav.soon);
  });

  it('says it in Arabic too', () => {
    renderWith(firstDay, 'ar');
    expect(screen.getByRole('link', { name: new RegExp(ar.app.nav.launches) }).textContent).toContain(
      ar.app.nav.soon,
    );
  });

  it('links the Dataset page under the data rule', () => {
    renderWith(meta);
    expect(screen.getByRole('link', { name: en.app.nav.status }).getAttribute('href')).toMatch(
      /^\/en\/dataset\/?$/,
    );
  });
});
