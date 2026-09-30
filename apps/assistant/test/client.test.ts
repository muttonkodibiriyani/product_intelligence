import { describe, expect, it } from "vitest";

import { ApiError, HttpMetricApi, MAX_RESPONSE_BYTES, requestUrl } from "../src/api/client.js";

function fakeFetch(status: number, body: string, seen: { url?: string; init?: RequestInit } = {}) {
  return (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    seen.url = url instanceof Request ? url.url : url.toString();
    if (init) seen.init = init;
    return Promise.resolve(new Response(body, { status }));
  };
}

describe("requestUrl", () => {
  it("joins the base and repeats array parameters", () => {
    const url = requestUrl("https://api.example/base", {
      method: "GET",
      path: "/v1/products",
      query: { brand: ["A", "B & C"], limit: "10" },
    });
    expect(url.toString()).toBe(
      "https://api.example/base/v1/products?brand=A&brand=B+%26+C&limit=10",
    );
  });
});

describe("HttpMetricApi", () => {
  it("requires https", () => {
    expect(() => new HttpMetricApi("http://api.example")).toThrow();
  });

  it("forwards the ID token and JSON body", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const api = new HttpMetricApi("https://api.example/", {
      fetch: fakeFetch(200, '{"a":1}', seen),
    });
    await expect(
      api.call({ method: "POST", path: "/v1/compare", body: { ids: ["a", "b"] } }, "tok"),
    ).resolves.toEqual({ a: 1 });
    const headers = seen.init?.headers as Record<string, string>;
    expect(headers.authorization).toBe("Bearer tok");
    expect(headers["content-type"]).toBe("application/json");
    expect(seen.init?.body).toBe('{"ids":["a","b"]}');
    expect(seen.init?.redirect).toBe("error");
  });

  it("maps failures to ApiError", async () => {
    const call = (fetch: typeof globalThis.fetch) =>
      new HttpMetricApi("https://api.example", { fetch }).call(
        { method: "GET", path: "/v1/coverage" },
        "tok",
      );
    await expect(call(fakeFetch(403, '{"error":{"code":"forbidden"}}'))).rejects.toMatchObject({
      status: 403,
      code: "forbidden",
    });
    await expect(call(fakeFetch(500, '{"error":{"code":"Bad Code!"}}'))).rejects.toMatchObject({
      status: 500,
      code: "http_error",
    });
    await expect(call(fakeFetch(502, "<html>"))).rejects.toMatchObject({
      status: 502,
      code: "invalid_json",
    });
    await expect(call(fakeFetch(200, "not json"))).rejects.toMatchObject({ status: 0 });
    await expect(call(fakeFetch(200, "x".repeat(MAX_RESPONSE_BYTES + 1)))).rejects.toMatchObject({
      code: "response_too_large",
    });
    await expect(call(() => Promise.reject(new TypeError("net")))).rejects.toBeInstanceOf(ApiError);
  });
});
