import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Envelope, Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { AppHeader } from './app-header';
import type { AuthState } from './auth-provider';

type Meta = Envelope<Schemas['MetaView']>;

const ctx = vi.hoisted(() => ({
  value: {} as { state: AuthState; auth: unknown; api: null },
  meta: { data: undefined as Meta | undefined },
  useMeta: vi.fn(),
}));
vi.mock('./auth-provider', () => ({ useAuth: () => ctx.value }));
vi.mock('./use-meta', () => ({ useMeta: () => ctx.useMeta() }));
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

function renderWith(state: AuthState, m: Meta | undefined, locale: 'en' | 'ar' = 'en') {
  ctx.value = { state, auth: { signOut: vi.fn() }, api: null };
  ctx.useMeta.mockImplementation(() => ({ data: m }));
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en}>
      <AppHeader />
    </NextIntlClientProvider>,
  );
}

describe('AppHeader', () => {
  it('asks for /meta only once the nav is shown: a session still being restored must not be signed out', () => {
    renderWith({ kind: 'loading' }, undefined);
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(ctx.useMeta).not.toHaveBeenCalled();
    cleanup();
    renderWith({ kind: 'signed_out' }, undefined);
    expect(ctx.useMeta).not.toHaveBeenCalled();
  });

  it('badges Launches "soon" until every shop has two collection days; the link stays', () => {
    renderWith(signedIn, firstDay);
    const link = screen.getByRole('link', { name: /Launches/ });
    expect(link.getAttribute('href')).toMatch(/^\/en\/launches\/?$/);
    expect(link.textContent).toContain(en.app.nav.soon);
    cleanup();
    renderWith(signedIn, meta);
    expect(screen.getByRole('link', { name: /Launches/ }).textContent).not.toContain(en.app.nav.soon);
    cleanup();
    // Nothing to say until /meta has answered.
    renderWith(signedIn, undefined);
    expect(screen.getByRole('link', { name: /Launches/ }).textContent).not.toContain(en.app.nav.soon);
  });

  it('says it in Arabic too', () => {
    renderWith(signedIn, firstDay, 'ar');
    expect(screen.getByRole('link', { name: new RegExp(ar.app.nav.launches) }).textContent).toContain(
      ar.app.nav.soon,
    );
  });
});
