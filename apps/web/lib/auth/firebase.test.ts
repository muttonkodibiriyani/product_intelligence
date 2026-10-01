import { describe, expect, it } from 'vitest';
import { pickWebConfig, roleOf, signInErrorKey } from './firebase';

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
