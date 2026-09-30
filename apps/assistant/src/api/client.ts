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

export function requestUrl(base: string, request: ApiRequest): URL {
  const url = new URL(request.path.replace(/^\//, ""), base.endsWith("/") ? base : `${base}/`);
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
      text = await response.text();
    } catch {
      throw new ApiError(0, "unavailable");
    }
    if (text.length > MAX_RESPONSE_BYTES) throw new ApiError(0, "response_too_large");
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
