import { describe, expect, it } from "vitest";

import { evidenceUrl, sanitiseText, untrusted } from "../src/guard/untrusted.js";

describe("untrusted text", () => {
  it("strips invisible characters and escapes markdown", () => {
    const value = sanitiseText("a​b‮ ![x](https://evil.example) <b>");
    expect(value).not.toMatch(/[\u200b\u202e]/);
    expect(value).toBe("a b \\!\\[x\\]\\(https://evil.example\\) \\<b\\>");
  });

  it("truncates by code point", () => {
    const value = sanitiseText("😀".repeat(10), 3);
    expect(value).toBe("😀😀😀…");
  });

  it("wraps values", () => {
    expect(untrusted("Hi *there*")).toEqual({ untrusted: "Hi \\*there\\*" });
  });
});

describe("evidenceUrl", () => {
  const hosts = ["shop.example"];
  it("allows https URLs on allowlisted hosts only", () => {
    expect(evidenceUrl("https://shop.example/p/1", hosts)).toBe("https://shop.example/p/1");
    expect(evidenceUrl("https://SHOP.example/p/1", hosts)).toBe("https://shop.example/p/1");
    expect(evidenceUrl("http://shop.example/p/1", hosts)).toBeNull();
    expect(evidenceUrl("https://evil.example/p/1", hosts)).toBeNull();
    expect(evidenceUrl("https://user:pw@shop.example/", hosts)).toBeNull();
    expect(evidenceUrl("javascript:alert(1)", hosts)).toBeNull();
    expect(evidenceUrl("not a url", hosts)).toBeNull();
    expect(evidenceUrl(null, hosts)).toBeNull();
  });
});
