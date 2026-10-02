import { describe, expect, it, vi } from 'vitest';
import {
  APP_CHECK_CONFIG_URL,
  chatErrorKey,
  isChatAnswer,
  isProgress,
  loadSiteKey,
  pickSiteKey,
} from './client';

describe('callable client guards', () => {
  it('accepts only known progress events', () => {
    expect(isProgress({ type: 'status', stage: 'thinking' })).toBe(true);
    expect(isProgress({ type: 'tool', name: 'compare', status: 'ok' })).toBe(true);
    expect(isProgress({ type: 'status', stage: 'typing' })).toBe(false);
    expect(isProgress({ type: 'text', delta: 'Median…' })).toBe(false);
    expect(isProgress(null)).toBe(false);
  });

  it('refuses a response that is not the answer contract', () => {
    const ok = {
      status: 'answered',
      answerMd: 'x',
      citations: [],
      caveats: [],
      productIds: [],
      notEnoughData: [],
      toolResults: [],
    };
    expect(isChatAnswer(ok)).toBe(true);
    expect(isChatAnswer({ ...ok, status: 'draft' })).toBe(false);
    expect(isChatAnswer({ ...ok, citations: undefined })).toBe(false);
    expect(isChatAnswer('answer')).toBe(false);
  });

  it('maps callable error codes', () => {
    expect(chatErrorKey({ code: 'functions/unauthenticated' })).toBe('signedOut');
    expect(chatErrorKey({ code: 'functions/permission-denied' })).toBe('noAccess');
    expect(chatErrorKey({ code: 'functions/deadline-exceeded' })).toBe('timeout');
    expect(chatErrorKey({ code: 'functions/unavailable' })).toBe('network');
    expect(chatErrorKey({ code: 'functions/internal' })).toBe('generic');
    expect(chatErrorKey(new Error('x'))).toBe('generic');
  });
});

describe('App Check site key (runtime config, never built in)', () => {
  const KEY = '6Lc_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789';

  it('keeps only a well-formed recaptchaSiteKey', () => {
    expect(pickSiteKey({ recaptchaSiteKey: KEY })).toBe(KEY);
    expect(pickSiteKey({ recaptchaSiteKey: 'short' })).toBeNull();
    expect(pickSiteKey({ recaptchaSiteKey: `${KEY}"><script>` })).toBeNull();
    expect(pickSiteKey({ recaptchaSiteKey: 42 })).toBeNull();
    expect(pickSiteKey({ siteKey: KEY })).toBeNull();
    expect(pickSiteKey(null)).toBeNull();
    expect(pickSiteKey(KEY)).toBeNull();
  });

  it('fetches the same-origin config without credentials or cache', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ recaptchaSiteKey: KEY })));
    await expect(loadSiteKey(f)).resolves.toBe(KEY);
    expect(f).toHaveBeenCalledWith(APP_CHECK_CONFIG_URL, { credentials: 'omit', cache: 'no-store' });
    expect(APP_CHECK_CONFIG_URL).toBe('/app/assistant-app-check.json');
  });

  it('is null when the file is missing, not JSON or the fetch fails', async () => {
    await expect(loadSiteKey(async () => new Response('', { status: 404 }))).resolves.toBeNull();
    await expect(loadSiteKey(async () => new Response('<html>'))).resolves.toBeNull();
    await expect(
      loadSiteKey(async () => {
        throw new TypeError('offline');
      }),
    ).resolves.toBeNull();
  });
});
