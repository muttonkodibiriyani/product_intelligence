import { afterEach, describe, expect, it, vi } from 'vitest';

const fb = vi.hoisted(() => ({
  getApp: vi.fn(() => ({ name: '[DEFAULT]' })),
  initializeAppCheck: vi.fn(),
  provider: vi.fn(),
  getFunctions: vi.fn(() => ({})),
  httpsCallable: vi.fn(() => ({ stream: vi.fn() })),
}));

vi.mock('@firebase/app', () => ({ getApp: fb.getApp }));
vi.mock('@firebase/app-check', () => ({
  initializeAppCheck: fb.initializeAppCheck,
  ReCaptchaEnterpriseProvider: class {
    constructor(key: string) {
      fb.provider(key);
    }
  },
}));
vi.mock('@firebase/functions', () => ({
  getFunctions: fb.getFunctions,
  httpsCallable: fb.httpsCallable,
}));

const KEY = '6Lc_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789';

/** A fresh client module per test: the cached client is module state. */
async function load() {
  vi.resetModules();
  return import('./client');
}

const serve = (body: string, status = 200) =>
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(body, { status })),
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('assistantClient App Check site key', () => {
  it.each([
    ['missing file', '', 404],
    ['malformed key', JSON.stringify({ recaptchaSiteKey: 'short' }), 200],
    ['a key in an error page', JSON.stringify({ recaptchaSiteKey: KEY }), 500],
  ])('rejects NoSiteKey without App Check on a %s', async (_, body, status) => {
    const { assistantClient, NoSiteKey } = await load();
    serve(body, status);
    await expect(assistantClient()).rejects.toBeInstanceOf(NoSiteKey);
    expect(fb.initializeAppCheck).not.toHaveBeenCalled();
    expect(fb.httpsCallable).not.toHaveBeenCalled();
  });

  it('retries on the next send and initializes exactly once when the file appears', async () => {
    const { assistantClient, NoSiteKey } = await load();
    serve('', 404);
    await expect(assistantClient()).rejects.toBeInstanceOf(NoSiteKey);

    serve(JSON.stringify({ recaptchaSiteKey: KEY }));
    const ask = await assistantClient();
    expect(typeof ask).toBe('function');
    expect(await assistantClient()).toBe(ask);
    expect(fb.provider).toHaveBeenCalledExactlyOnceWith(KEY);
    expect(fb.initializeAppCheck).toHaveBeenCalledOnce();
    expect(fb.httpsCallable).toHaveBeenCalledOnce();
  });
});
