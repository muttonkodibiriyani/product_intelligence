import { describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  attachmentName,
  createApiClient,
  encodeQuery,
  fillPath,
  retryAfterSeconds,
} from './client';
import { golden } from './golden';

type Reply = { status: number; body?: unknown; headers?: Record<string, string> };

function json({ status, body, headers = {} }: Reply): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function setup(
  replies: Reply[],
  token: (force: boolean) => Promise<string | null> = async (f) => (f ? 'fresh' : 'old'),
) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    const r = replies.shift();
    if (!r) throw new Error('no more replies');
    return json(r);
  });
  const sleep = vi.fn(async () => {});
  const onUnauthenticated = vi.fn();
  const onGeneration = vi.fn();
  const getToken = vi.fn(token);
  const api = createApiClient({ getToken, fetch, sleep, onUnauthenticated, onGeneration });
  return { api, calls, sleep, onUnauthenticated, onGeneration, getToken };
}

const err = (code: string, message = `server says ${code} <b>q=evil</b>`) => ({ error: { code, message } });

async function failure(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (e) {
    if (e instanceof ApiError) return e;
    throw e;
  }
  throw new Error('expected an ApiError');
}

describe('requests', () => {
  it('sends a Bearer token, no cookies, no cache, GET only', async () => {
    const { api, calls } = setup([{ status: 200, body: golden('meta') }]);
    await api.get('/api/v1/meta');
    const { url, init } = calls[0]!;
    expect(url).toBe('/api/v1/meta');
    expect(init.method).toBe('GET');
    expect(init.credentials).toBe('omit');
    expect(init.cache).toBe('no-store');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer old');
    expect(init.body).toBeUndefined();
  });

  it('encodes path params and repeats multi-value filters', async () => {
    const { api, calls } = setup([
      { status: 200, body: golden('product') },
      { status: 200, body: golden('products-filtered') },
    ]);
    await api.get('/api/v1/products/{product_id}', { params: { product_id: 'a/b c' } });
    await api.get('/api/v1/products', { query: { brand: ['Dior', 'MAC'], matched: true, limit: 2 } });
    expect(calls[0]!.url).toBe('/api/v1/products/a%2Fb%20c');
    expect(calls[1]!.url).toBe('/api/v1/products?brand=Dior&brand=MAC&matched=true&limit=2');
  });

  it('passes the ordered retailer pair as one value', () => {
    expect(encodeQuery({ retailers: 'ulta_ae,sephora_ae' })).toBe('?retailers=ulta_ae%2Csephora_ae');
    expect(encodeQuery({ a: undefined, b: null })).toBe('');
    expect(() => fillPath('/x/{id}', {})).toThrow();
  });

  it.each(['compare', 'compare-blocked', 'index', 'products-gap', 'matches', 'history', 'coverage'])(
    'accepts the %s golden as is',
    async (name) => {
      const { api } = setup([{ status: 200, body: golden(name) }]);
      await expect(api.get('/api/v1/meta')).resolves.toEqual(golden(name));
    },
  );

  it('reports a new dataset generation once', async () => {
    const a = golden('meta') as { meta: { generation: string } };
    const b = { ...a, meta: { ...a.meta, generation: 'next' } };
    const { api, onGeneration } = setup([
      { status: 200, body: a },
      { status: 200, body: a },
      { status: 200, body: b },
    ]);
    await api.get('/api/v1/meta');
    await api.get('/api/v1/meta');
    expect(onGeneration).not.toHaveBeenCalled();
    await api.get('/api/v1/meta');
    expect(onGeneration).toHaveBeenCalledExactlyOnceWith('next');
  });

  it('rejects a 200 that is not an envelope', async () => {
    const { api } = setup([{ status: 200, body: { hello: 1 } }]);
    expect((await failure(api.get('/api/v1/meta'))).code).toBe('unexpected');
  });
});

describe('401', () => {
  it('retries once with a fresh token', async () => {
    const { api, calls, onUnauthenticated } = setup([
      { status: 401, body: err('unauthenticated'), headers: { 'WWW-Authenticate': 'Bearer' } },
      { status: 200, body: golden('meta') },
    ]);
    await api.get('/api/v1/meta');
    expect((calls[1]!.init.headers as Record<string, string>).Authorization).toBe('Bearer fresh');
    expect(onUnauthenticated).not.toHaveBeenCalled();
  });

  it('asks for sign-in when the fresh token is refused too', async () => {
    const { api, onUnauthenticated } = setup([
      { status: 401, body: err('unauthenticated') },
      { status: 401, body: err('unauthenticated') },
    ]);
    const e = await failure(api.get('/api/v1/meta'));
    expect(e.code).toBe('unauthenticated');
    expect(onUnauthenticated).toHaveBeenCalledOnce();
  });

  it('asks for sign-in when there is no user', async () => {
    const { api, calls, onUnauthenticated } = setup([], async () => null);
    expect((await failure(api.get('/api/v1/meta'))).code).toBe('unauthenticated');
    expect(calls).toHaveLength(0);
    expect(onUnauthenticated).toHaveBeenCalledOnce();
  });
});

describe('503 auth_unavailable', () => {
  const down = { status: 503, body: err('auth_unavailable'), headers: { 'Retry-After': '5' } };

  it('waits Retry-After and retries without signing out', async () => {
    const { api, sleep, onUnauthenticated } = setup([down, down, { status: 200, body: golden('meta') }]);
    await api.get('/api/v1/meta');
    expect(sleep).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledWith(5000);
    expect(onUnauthenticated).not.toHaveBeenCalled();
  });

  it('gives up after three retries, still signed in', async () => {
    const { api, sleep, onUnauthenticated } = setup([down, down, down, down]);
    const e = await failure(api.get('/api/v1/meta'));
    expect(e.code).toBe('auth_unavailable');
    expect(e.retryAfter).toBe(5);
    expect(sleep).toHaveBeenCalledTimes(3);
    expect(onUnauthenticated).not.toHaveBeenCalled();
  });

  it('treats a failed token refresh the same way', async () => {
    const { api, onUnauthenticated } = setup([], async () => {
      throw new Error('auth/network-request-failed');
    });
    expect((await failure(api.get('/api/v1/meta'))).code).toBe('auth_unavailable');
    expect(onUnauthenticated).not.toHaveBeenCalled();
  });
});

describe('other errors', () => {
  it.each([
    [403, 'forbidden', {}, null],
    [404, 'not_found', {}, null],
    [422, 'invalid_query', {}, null],
    [422, 'ambiguous_dataset', {}, null],
    [422, 'invalid_request', {}, null],
    [429, 'rate_limited', { 'Retry-After': '12' }, 12],
    [503, 'data_unavailable', { 'Retry-After': '30' }, 30],
    [500, 'internal_error', {}, null],
  ] as const)('%i %s surfaces as its code, without the server message', async (status, code, headers, ra) => {
    const { api, sleep, onUnauthenticated } = setup([{ status, body: err(code), headers }]);
    const e = await failure(api.get('/api/v1/meta'));
    expect(e).toMatchObject({ code, status, retryAfter: ra });
    expect(e.message).toBe(code);
    expect(JSON.stringify(e)).not.toContain('evil');
    expect(sleep).not.toHaveBeenCalled();
    expect(onUnauthenticated).not.toHaveBeenCalled();
  });

  it('maps unknown codes and non-JSON bodies to unexpected', async () => {
    const { api } = setup([{ status: 418, body: err('teapot') }]);
    expect((await failure(api.get('/api/v1/meta'))).code).toBe('unexpected');
    const f = vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502 }));
    const api2 = createApiClient({ getToken: async () => 't', fetch: f });
    expect((await failure(api2.get('/api/v1/meta'))).code).toBe('unexpected');
  });

  it('maps a dropped connection to network', async () => {
    const f = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const api = createApiClient({ getToken: async () => 't', fetch: f });
    expect((await failure(api.get('/api/v1/meta'))).code).toBe('network');
  });

  it('reads Retry-After as delta seconds only', () => {
    expect(retryAfterSeconds('30')).toBe(30);
    expect(retryAfterSeconds('0')).toBeNull();
    expect(retryAfterSeconds('Wed, 21 Oct 2026 07:28:00 GMT')).toBeNull();
    expect(retryAfterSeconds(null)).toBeNull();
  });
});

describe('409 stale_cursor', () => {
  it('drops the cursor and restarts at page 1', async () => {
    const { api, calls } = setup([
      { status: 409, body: golden('error-stale-cursor') },
      { status: 200, body: golden('products') },
    ]);
    const r = await api.page('/api/v1/products', { query: { cursor: 'abc', limit: 50 } });
    expect(r.restarted).toBe(true);
    expect(calls.map((c) => c.url)).toEqual([
      '/api/v1/products?cursor=abc&limit=50',
      '/api/v1/products?limit=50',
    ]);
  });

  it('passes through a first page untouched', async () => {
    const { api } = setup([{ status: 200, body: golden('products') }]);
    expect((await api.page('/api/v1/products', { query: { limit: 50 } })).restarted).toBe(false);
  });
});

describe('download', () => {
  const CSV = '﻿"# {""view"":""products""}"\nid,name\np01,Product p01\n';
  const file = (headers: Record<string, string> = {}) =>
    new Response(CSV, {
      status: 200,
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename="pi-products-20260930T0000Z.csv"',
        ...headers,
      },
    });

  function client(responses: (() => Response)[]) {
    const calls: { url: string; init: RequestInit }[] = [];
    const fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });
      const r = responses.shift();
      if (!r) throw new Error('no more replies');
      return r();
    });
    const sleep = vi.fn(async () => {});
    const onUnauthenticated = vi.fn();
    const api = createApiClient({
      getToken: async (f) => (f ? 'fresh' : 'old'),
      fetch,
      sleep,
      onUnauthenticated,
    });
    return { api, calls, sleep, onUnauthenticated };
  }
  const opts = {
    query: { format: 'csv' as const, brand: ['A', 'B'], sort: 'name' as const },
    fallback: 'x.csv',
  };

  it('fetches the file with the Bearer token and keeps it byte for byte', async () => {
    const { api, calls } = client([() => file()]);
    const { blob, filename } = await api.download('/api/v1/export/products', opts);
    expect(calls[0]!.url).toBe('/api/v1/export/products?format=csv&brand=A&brand=B&sort=name');
    const h = calls[0]!.init.headers as Record<string, string>;
    expect(h.Authorization).toBe('Bearer old');
    expect(h.Accept).toMatch(/^text\/csv/);
    expect(calls[0]!.init.credentials).toBe('omit');
    expect(filename).toBe('pi-products-20260930T0000Z.csv');
    expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([...new TextEncoder().encode(CSV)]);
  });

  it('asks for JSONL by its media type', async () => {
    const { api, calls } = client([() => file({ 'Content-Type': 'application/x-ndjson' })]);
    await api.download('/api/v1/export/products', { ...opts, query: { format: 'jsonl' } });
    expect((calls[0]!.init.headers as Record<string, string>).Accept).toMatch(/^application\/x-ndjson/);
  });

  it('refuses a body of any other type: a mis-routed /api answers 200 with index.html', async () => {
    const { api } = client([
      () => file({ 'Content-Type': 'text/html; charset=utf-8' }),
      () => file({ 'Content-Type': '' }),
      () => file(),
    ]);
    for (let i = 0; i < 2; i++) {
      const e = await failure(api.download('/api/v1/export/products', opts));
      expect([e.code, e.status]).toEqual(['unexpected', 200]);
    }
    // The CSV type does not stand in for JSONL either.
    const e = await failure(api.download('/api/v1/export/products', { ...opts, query: { format: 'jsonl' } }));
    expect(e.code).toBe('unexpected');
  });

  it('uses the fallback name when the header is missing or unsafe', async () => {
    const { api } = client([
      () => file({ 'Content-Disposition': '' }),
      () => file({ 'Content-Disposition': 'attachment; filename="../../etc/passwd"' }),
    ]);
    expect((await api.download('/api/v1/export/products', opts)).filename).toBe('x.csv');
    expect((await api.download('/api/v1/export/products', opts)).filename).toBe('x.csv');
  });

  it('turns refusals into codes: 422 export_too_large, 429 rate_limited with Retry-After', async () => {
    const { api } = client([
      () => json({ status: 422, body: err('export_too_large') }),
      () => json({ status: 429, body: err('rate_limited'), headers: { 'Retry-After': '5' } }),
    ]);
    const big = await failure(api.download('/api/v1/export/products', opts));
    expect([big.code, big.status]).toEqual(['export_too_large', 422]);
    const busy = await failure(api.download('/api/v1/export/products', opts));
    expect([busy.code, busy.retryAfter]).toEqual(['rate_limited', 5]);
  });

  it('waits out auth_unavailable and retries a 401 once with a fresh token, like reads', async () => {
    const { api, calls, sleep, onUnauthenticated } = client([
      () => json({ status: 401, body: err('unauthenticated') }),
      () => json({ status: 503, body: err('auth_unavailable'), headers: { 'Retry-After': '2' } }),
      () => file(),
    ]);
    await api.download('/api/v1/export/products', opts);
    expect((calls[1]!.init.headers as Record<string, string>).Authorization).toBe('Bearer fresh');
    expect(sleep).toHaveBeenCalledWith(2000);
    expect(onUnauthenticated).not.toHaveBeenCalled();
  });
});

describe('attachmentName', () => {
  it('accepts plain names only', () => {
    expect(attachmentName('attachment; filename="pi-index-20260930T0000Z.jsonl"')).toBe(
      'pi-index-20260930T0000Z.jsonl',
    );
    expect(attachmentName('attachment; filename=plain.csv')).toBe('plain.csv');
    for (const bad of [
      null,
      '',
      'attachment',
      'attachment; filename=".hidden"',
      'attachment; filename="a b.csv"',
    ])
      expect(attachmentName(bad)).toBeNull();
  });
});
