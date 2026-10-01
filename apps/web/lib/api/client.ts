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

  async function send(
    url: string,
    force: boolean,
    signal: AbortSignal | undefined,
    accept: string,
  ): Promise<Response> {
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
        headers: { Authorization: `Bearer ${token}`, Accept: accept },
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

  /**
   * One GET with the token rules: a 401 is retried once with a fresh token, a 503
   * auth_unavailable is waited out, and any other failure becomes an ApiError. Returns the OK
   * response with its JSON body when it has one (`json` is null for a file download).
   */
  async function request(
    url: string,
    signal: AbortSignal | undefined,
    accept = 'application/json',
  ): Promise<{ res: Response; json: unknown }> {
    // A file download keeps its body unread; errors are always JSON.
    const body = async (r: Response) => (r.ok && accept !== 'application/json' ? null : await readJson(r));
    let res = await send(url, false, signal, accept);
    // An ID token lives an hour; retry once with a fresh one before treating 401 as signed out.
    if (res.status === 401) res = await send(url, true, signal, accept);
    let json = await body(res);

    // The API could not check the token (identity service down). That says nothing about the
    // user, so never sign out: wait as told and try again.
    for (let i = 0; res.status === 503 && errorCode(json) === 'auth_unavailable' && i < authRetries; i++) {
      const s = Math.min(
        retryAfterSeconds(res.headers.get('Retry-After')) ?? AUTH_RETRY_DEFAULT_S,
        AUTH_RETRY_CAP_S,
      );
      await sleep(s * 1000);
      if (signal?.aborted) throw new DOMException('aborted', 'AbortError');
      res = await send(url, false, signal, accept);
      json = await body(res);
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
    return { res, json };
  }

  async function getUrl<T>(url: string, signal?: AbortSignal): Promise<T> {
    const { res, json } = await request(url, signal);
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

  /**
   * A whole export file (CSV or JSONL) as a Blob, fetched with the Bearer token like any read.
   * The file name comes from the server's Content-Disposition when it is a plain name, else
   * `fallback`; nothing else from the response reaches the page.
   */
  async function download<P extends ExportPath>(
    path: P,
    opts: { query: QueryOf<P> & { format: 'csv' | 'jsonl' }; signal?: AbortSignal; fallback: string },
  ): Promise<{ blob: Blob; filename: string }> {
    const accept = `${EXPORT_TYPES[opts.query.format]}, application/json;q=0.5`;
    const { res } = await request(base + path + encodeQuery(opts.query as Query), opts.signal, accept);
    let blob: Blob;
    try {
      blob = await res.blob();
    } catch (e) {
      if (opts.signal?.aborted) throw e;
      throw new ApiError('network', 0);
    }
    return { blob, filename: attachmentName(res.headers.get('Content-Disposition')) ?? opts.fallback };
  }

  return { get, page, download };
}

export type ExportPath = Extract<GetPath, `/api/v1/export/${string}`>;

const EXPORT_TYPES = { csv: 'text/csv', jsonl: 'application/x-ndjson' } as const;

/** `attachment; filename="pi-products-20260930T0000Z.csv"` → the name, if it is a safe plain one. */
export function attachmentName(header: string | null): string | null {
  const m = /filename="?([^";]+)"?/i.exec(header ?? '');
  const name = m?.[1]?.trim() ?? '';
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(name) ? name : null;
}

export type ApiClient = ReturnType<typeof createApiClient>;
