/**
 * The assistant's only data path: the service-layer read API (design §3; service-layer design,
 * task 01a0f488-eab6). The API computes every metric; the assistant forwards the signed-in
 * user's Firebase ID token, so the user's own permissions apply. The assistant has no service
 * account identity for data reads.
 */

export interface ApiRequest {
  readonly method: "GET" | "POST";
  /** Path under the API base, e.g. "/v1/products". Path parameters are already encoded. */
  readonly path: string;
  readonly query?: Readonly<Record<string, string | readonly string[]>>;
  readonly body?: unknown;
}

export interface MetricApi {
  call(request: ApiRequest, idToken: string): Promise<unknown>;
}

export class ApiError extends Error {
  constructor(
    /** HTTP status, or 0 for network failure, timeout or an unreadable response. */
    readonly status: number,
    readonly code: string,
  ) {
    super(`metric API error ${status} ${code}`);
    this.name = "ApiError";
  }
}

export const MAX_RESPONSE_BYTES = 1_000_000;

/**
 * The request URL. A base that already ends in the request's own prefix (PI_API_BASE_URL set to
 * ".../api/v1" while every tool path starts with "/api/v1") is not doubled: on 2026-10-03 the
 * live callable sent /api/v1/api/v1/products and every tool got a 404.
 */
export function requestUrl(base: string, request: ApiRequest): URL {
  const root = new URL(base.endsWith("/") ? base : `${base}/`);
  const basePath = root.pathname.replace(/\/+$/, "");
  const path =
    basePath !== "" && request.path.startsWith(`${basePath}/`)
      ? request.path.slice(basePath.length)
      : request.path;
  const url = new URL(path.replace(/^\//, ""), root);
  for (const [key, value] of Object.entries(request.query ?? {})) {
    for (const item of typeof value === "string" ? [value] : value) {
      url.searchParams.append(key, item);
    }
  }
  return url;
}

function errorCode(body: unknown): string {
  if (typeof body === "object" && body !== null && "error" in body) {
    const { error } = body;
    if (typeof error === "object" && error !== null && "code" in error) {
      const { code } = error;
      if (typeof code === "string" && /^[a-z_]{1,40}$/.test(code)) return code;
    }
  }
  return "http_error";
}

class TooLarge extends Error {}

/**
 * Read at most `limit` bytes of the body. Rejects before buffering when Content-Length is over
 * the limit, and cancels the stream as soon as the running byte count passes it.
 */
export async function readCapped(response: Response, limit: number): Promise<string> {
  const declared = response.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > limit) {
    await response.body?.cancel().catch(() => undefined);
    throw new TooLarge();
  }
  if (response.body === null) return "";
  const reader: ReadableStreamDefaultReader<Uint8Array> = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel().catch(() => undefined);
      throw new TooLarge();
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

/** fetch-based client. Not wired to any deployment until the service layer exists. */
export class HttpMetricApi implements MetricApi {
  constructor(
    private readonly baseUrl: string,
    private readonly options: { timeoutMs?: number; fetch?: typeof fetch } = {},
  ) {
    if (!baseUrl.startsWith("https://")) throw new Error("metric API base URL must be https");
  }

  async call(request: ApiRequest, idToken: string): Promise<unknown> {
    const doFetch = this.options.fetch ?? fetch;
    let response: Response;
    let text: string;
    try {
      response = await doFetch(requestUrl(this.baseUrl, request), {
        method: request.method,
        headers: {
          authorization: `Bearer ${idToken}`,
          accept: "application/json",
          ...(request.body === undefined ? {} : { "content-type": "application/json" }),
        },
        ...(request.body === undefined ? {} : { body: JSON.stringify(request.body) }),
        signal: AbortSignal.timeout(this.options.timeoutMs ?? 10_000),
        redirect: "error",
      });
      text = await readCapped(response, MAX_RESPONSE_BYTES);
    } catch (error) {
      throw new ApiError(0, error instanceof TooLarge ? "response_too_large" : "unavailable");
    }
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      throw new ApiError(response.ok ? 0 : response.status, "invalid_json");
    }
    if (!response.ok) throw new ApiError(response.status, errorCode(body));
    return body;
  }
}
