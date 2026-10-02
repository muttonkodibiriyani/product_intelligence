import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import en from '@/messages/en.json';
import type { AuthState } from './auth-provider';
import { RequireAuth } from './require-auth';

const ctx = vi.hoisted(() => ({ value: {} as { state: AuthState; auth: unknown; api: null } }));
vi.mock('./auth-provider', () => ({ useAuth: () => ctx.value }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));

afterEach(cleanup);

function renderWith(state: AuthState, auth: unknown = null) {
  ctx.value = { state, auth, api: null };
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <RequireAuth>
        <p>content</p>
      </RequireAuth>
    </NextIntlClientProvider>,
  );
}

describe('RequireAuth', () => {
  it('an unreadable role is a retry state, not "no access"', () => {
    const recheck = vi.fn(() => Promise.resolve());
    renderWith({ kind: 'signed_in', session: { email: 'a@x', role: null, verified: false } }, { recheck });
    expect(screen.getByText(en.auth.verifying)).toBeTruthy();
    expect(screen.queryByText(en.auth.noRoleTitle)).toBeNull();
    expect(screen.queryByText('content')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: en.auth.recheck }));
    expect(recheck).toHaveBeenCalledOnce();
  });

  it('a read role that is missing is "no access"', () => {
    renderWith({ kind: 'signed_in', session: { email: 'a@x', role: null, verified: true } });
    expect(screen.getByText(en.auth.noRoleTitle)).toBeTruthy();
  });

  it('a viewer sees the content', () => {
    renderWith({ kind: 'signed_in', session: { email: 'a@x', role: 'viewer', verified: true } });
    expect(screen.getByText('content')).toBeTruthy();
  });
});
