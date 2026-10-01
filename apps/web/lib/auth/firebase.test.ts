import { describe, expect, it } from 'vitest';
import { authCode, pickWebConfig, resetOutcome, roleOf, signInErrorKey } from './firebase';

describe('web config', () => {
  it('keeps only the web-config fields', () => {
    const c = pickWebConfig({
      apiKey: 'k',
      projectId: 'p',
      appId: 'a',
      algoliaAdminKey: 'nope',
      databaseURL: 1,
    });
    expect(c).toEqual({ apiKey: 'k', projectId: 'p', appId: 'a' });
  });
  it('rejects a config without apiKey or projectId', () => {
    expect(pickWebConfig({ projectId: 'p' })).toBeNull();
    expect(pickWebConfig('x')).toBeNull();
  });
});

describe('role claim', () => {
  it('accepts viewer and admin only', () => {
    expect(roleOf({ role: 'viewer' })).toBe('viewer');
    expect(roleOf({ role: 'admin' })).toBe('admin');
    expect(roleOf({ role: 'owner' })).toBeNull();
    expect(roleOf({})).toBeNull();
  });
});

describe('sign-in errors', () => {
  it('never says which of email or password was wrong', () => {
    expect(signInErrorKey({ code: 'auth/user-not-found' })).toBe('badCredentials');
    expect(signInErrorKey({ code: 'auth/wrong-password' })).toBe('badCredentials');
    expect(signInErrorKey({ code: 'auth/too-many-requests' })).toBe('tooMany');
    expect(signInErrorKey(new Error('x'))).toBe('generic');
  });
});

describe('password reset outcomes', () => {
  it('an unknown address reads as sent; every other failure is said', () => {
    expect(resetOutcome({ code: 'auth/user-not-found' })).toBe('sent');
    expect(resetOutcome({ code: 'auth/invalid-email' })).toBe('invalidEmail');
    expect(resetOutcome({ code: 'auth/missing-email' })).toBe('invalidEmail');
    for (const code of ['auth/too-many-requests', 'auth/quota-exceeded', 'auth/network-request-failed'])
      expect(resetOutcome({ code })).toBe('later');
    expect(resetOutcome(new Error('HTTP 403'))).toBe('later');
    expect(resetOutcome(null)).toBe('later');
  });

  it('logs only a code string, never the message', () => {
    expect(authCode(Object.assign(new Error('for a@example.com'), { code: 'auth/quota-exceeded' }))).toBe(
      'auth/quota-exceeded',
    );
    expect(authCode(new Error('for a@example.com'))).toBe('unknown');
  });
});
