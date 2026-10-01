import {
  API_ERROR_CODES,
  type ApiErrorCode,
  type GetPath,
  type PathParamsOf,
  type QueryOf,
  type ResponseOf,
} from './types';

/**
 * A failed call. Holds only the code, HTTP status and Retry-After: the server's `message` is never
 * kept, so nothing the server says (or echoes from a query) reaches the screen. The UI picks its
 * text from the code.
 */
export class ApiError extends Error {
  constructor(
    readonly code: ApiErrorCode,
    readonly status: number,
    readonly retryAfter: number | null = null,
  ) {
    super(code);
    this.name = 'ApiError';
  }
}

/** Returns a Firebase ID token; `force` refreshes it. Null when signed out. */
export type TokenSource = (force: boolean) => Promise<string | null>;

export interface ApiClientOptions {
  getToken: TokenSource;
  /** Called when a fresh token is still refused (401): the user must sign in again. */
  onUnauthenticated?: () => void;
  /** Called when a response reports a different dataset generation than the previous one. */
  onGeneration?: (generation: string) => void;
  fetch?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  base?: string;
  /** Retries of 503 auth_unavailable before giving up (the user stays signed in either way). */
  authRetries?: number;
}

type QueryValue = string | number | boolean | readonly string[] | null | undefined;
type Query = Record<string, QueryValue>;

/**
 * Multi-value filters repeat the key (brand=A&brand=B); an ordered retailer pair is one
 * comma-joined value (retailers=base,other), passed by the caller as a string.
 */
export function encodeQuery(q: Query = {}): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null) continue;
    if (Array.isArray(v)) for (const item of v) p.append(k, item);
    else p.append(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

/** Fills `{name}` segments; every value is URI-encoded. */
export function fillPath(path: string, params: Record<string, string> = {}): string {
  return path.replace(/\{(\w+)\}/g, (_, name: string) => {
    const v = params[name];
    if (v === undefined) throw new Error(`missing path parameter ${name}`);
    return encodeURIComponent(v);
  });
}

function errorCode(body: unknown): ApiErrorCode {
  const code = (body as { error?: { code?: unknown } } | null)?.error?.code;
  return typeof code === 'string' && (API_ERROR_CODES as readonly string[]).includes(code)
    ? (code as ApiErrorCode)
    : 'unexpected';
}

/** Seconds from a delta-seconds Retry-After; null when absent or not a positive number. */
export function retryAfterSeconds(header: string | null): number | null {
  if (header === null || !/^\d+$/.test(header.trim())) return null;
  const n = Number(header);
  return n > 0 ? n : null;
}

const AUTH_RETRY_DEFAULT_S = 5;
const AUTH_RETRY_CAP_S = 30;

export type GetOptions<P extends GetPath> = {
  query?: QueryOf<P>;
  signal?: AbortSignal;
} & ([PathParamsOf<P>] extends [never] ? { params?: never } : { params: PathParamsOf<P> });

/**
 * Thin client over the read API (GET only, Bearer only, never cookies). It computes nothing: every
 * number is rendered as the API returns it. Caching belongs to the caller; responses are
 * `private, no-store`, so the browser cache is bypassed too.
 */
export function createApiClient({
  getToken,
  onUnauthenticated,
  onGeneration,
  fetch: f = (...a) => fetch(...a),
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
  base = '',
  authRetries = 3,
}: ApiClientOptions) {
  let generation: string | null = null;

  async function send(url: string, force: boolean, signal: AbortSignal | undefined): Promise<Response> {
    let token: string | null;
    try {
      token = await getToken(force);
    } catch {
      // Refreshing the token failed (offline, identity service down). Not a sign-out.
      throw new ApiError('auth_unavailable', 0);
    }
    if (!token) {
      onUnauthenticated?.();
      throw new ApiError('unauthenticated', 401);
    }
    try {
      return await f(url, {
        method: 'GET',
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
        credentials: 'omit',
        cache: 'no-store',
        signal: signal ?? null,
      });
    } catch (e) {
      if (signal?.aborted) throw e;
      throw new ApiError('network', 0);
    }
  }

  async function readJson(res: Response): Promise<unknown> {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }

  async function getUrl<T>(url: string, signal?: AbortSignal): Promise<T> {
    let res = await send(url, false, signal);
    // An ID token lives an hour; retry once with a fresh one before treating 401 as signed out.
    if (res.status === 401) res = await send(url, true, signal);
    let json = await readJson(res);

    // The API could not check the token (identity service down). That says nothing about the
    // user, so never sign out: wait as told and try again.
    for (let i = 0; res.status === 503 && errorCode(json) === 'auth_unavailable' && i < authRetries; i++) {
      const s = Math.min(
        retryAfterSeconds(res.headers.get('Retry-After')) ?? AUTH_RETRY_DEFAULT_S,
        AUTH_RETRY_CAP_S,
      );
      await sleep(s * 1000);
      if (signal?.aborted) throw new DOMException('aborted', 'AbortError');
      res = await send(url, false, signal);
      json = await readJson(res);
    }

    if (!res.ok) {
      // A 401 here, even after the auth_unavailable retries above, means the identity service
      // answered and refused this token: that is a real sign-out.
      const code = errorCode(json);
      if (res.status === 401) onUnauthenticated?.();
      throw new ApiError(
        res.status === 401 ? 'unauthenticated' : code,
        res.status,
        retryAfterSeconds(res.headers.get('Retry-After')),
      );
    }
    const env = json as { status?: unknown; meta?: { generation?: unknown } } | null;
    if (
      !env ||
      (env.status !== 'ok' && env.status !== 'not_enough_data') ||
      typeof env.meta?.generation !== 'string'
    ) {
      throw new ApiError('unexpected', res.status);
    }
    if (env.meta.generation !== generation) {
      if (generation !== null) onGeneration?.(env.meta.generation);
      generation = env.meta.generation;
    }
    return json as T;
  }

  function get<P extends GetPath>(path: P, opts?: GetOptions<P>): Promise<ResponseOf<P>> {
    const url =
      base +
      fillPath(path, opts?.params as Record<string, string> | undefined) +
      encodeQuery(opts?.query as Query);
    return getUrl<ResponseOf<P>>(url, opts?.signal);
  }

  /**
   * One page of a cursor-paged route. When the data changed under the cursor (409 stale_cursor),
   * the cursor is dropped and page 1 is fetched instead; `restarted` tells the caller to replace,
   * not append.
   */
  async function page<P extends GetPath>(
    path: P,
    opts: GetOptions<P> & { query: QueryOf<P> & { cursor?: string | null } },
  ): Promise<{ body: ResponseOf<P>; restarted: boolean }> {
    try {
      return { body: await get(path, opts), restarted: false };
    } catch (e) {
      if (!(e instanceof ApiError && e.code === 'stale_cursor') || !opts.query.cursor) throw e;
      const rest = { ...opts, query: { ...opts.query, cursor: undefined } };
      return { body: await get(path, rest), restarted: true };
    }
  }

  return { get, page };
}

export type ApiClient = ReturnType<typeof createApiClient>;
