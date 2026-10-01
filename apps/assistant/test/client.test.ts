import { describe, expect, it } from "vitest";

import {
  ApiError,
  HttpMetricApi,
  MAX_RESPONSE_BYTES,
  readCapped,
  requestUrl,
} from "../src/api/client.js";

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

describe("readCapped (reviewer #41: count bytes, check before buffering)", () => {
  it("counts UTF-8 bytes, not characters", async () => {
    // 6 characters, 12 bytes.
    await expect(readCapped(new Response("éééééé"), 11)).rejects.toThrow();
    await expect(readCapped(new Response("éééééé"), 12)).resolves.toBe("éééééé");
    const multibyte = `"${"é".repeat(MAX_RESPONSE_BYTES / 2)}"`;
    expect(multibyte.length).toBeLessThan(MAX_RESPONSE_BYTES);
    const api = new HttpMetricApi("https://api.example", {
      fetch: () => Promise.resolve(new Response(multibyte)),
    });
    await expect(api.call({ method: "GET", path: "/v1/x" }, "t")).rejects.toMatchObject({
      code: "response_too_large",
    });
  });

  it("rejects on Content-Length before reading the body", async () => {
    let pulled = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulled += 1;
        controller.enqueue(new Uint8Array(10));
        controller.close();
      },
    });
    const response = new Response(body, { headers: { "content-length": "101" } });
    await expect(readCapped(response, 100)).rejects.toThrow();
    expect(pulled).toBeLessThanOrEqual(1);
  });

  it("stops reading a stream once it passes the cap", async () => {
    let pulled = 0;
    const endless = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulled += 1;
        controller.enqueue(new Uint8Array(64));
      },
    });
    await expect(readCapped(new Response(endless), 1000)).rejects.toThrow();
    expect(pulled).toBeLessThan(40);
  });

  it("rejects invalid UTF-8 and reads an empty body", async () => {
    await expect(readCapped(new Response(new Uint8Array([0xff, 0xfe])), 10)).rejects.toThrow();
    await expect(readCapped(new Response(null), 10)).resolves.toBe("");
  });
});
