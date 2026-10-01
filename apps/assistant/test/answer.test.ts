import { describe, expect, it } from "vitest";

import { cleanAnswer } from "../src/guard/answer.js";

const KNOWN = new Set(["p01", "p02"]);

describe("cleanAnswer", () => {
  it("keeps known product tokens in first-appearance order", () => {
    const result = cleanAnswer("[[product:p02]] beats [[product:p01]] and [[product:p02]]", KNOWN);
    expect(result.markdown).toBe("[[product:p02]] beats [[product:p01]] and [[product:p02]]");
    expect(result.productIds).toEqual(["p02", "p01"]);
    expect(result.removed).toBe(0);
  });

  it("replaces unknown product tokens", () => {
    const result = cleanAnswer("Try [[product:zz9]].", KNOWN);
    expect(result.markdown).toBe("Try a product.");
    expect(result.productIds).toEqual([]);
    expect(result.removed).toBe(1);
  });

  it("removes images, links, tags, comments, references and URLs", () => {
    const input = [
      "A ![x](https://evil.example/a.png) B",
      "[click](https://evil.example) here",
      "<img src=x onerror=alert(1)><b>bold</b>",
      "<!-- hidden -->visible",
      "[ref]: https://evil.example",
      "see https://evil.example/x and www.evil.example and javascript:alert(1)",
    ].join("\n");
    const result = cleanAnswer(input, KNOWN);
    expect(result.markdown).not.toMatch(/evil|<|!\[|javascript|hidden/);
    expect(result.markdown).toContain("click here");
    expect(result.markdown).toContain("bold");
    expect(result.markdown).toContain("visible");
    expect(result.markdown).toContain("[link removed]");
    expect(result.removed).toBeGreaterThanOrEqual(8);
  });

  it("does not let link syntax swallow a product token", () => {
    const result = cleanAnswer("[[[product:p01]]](https://evil.example)", KNOWN);
    expect(result.markdown).toBe("[[product:p01]]");
    expect(result.productIds).toEqual(["p01"]);
  });

  it("drops placeholder characters the model wrote itself", () => {
    const result = cleanAnswer("x0y [[product:p01]]", KNOWN);
    expect(result.markdown).toBe("x0y [[product:p01]]");
  });

  it("removes an unterminated comment or tag", () => {
    expect(cleanAnswer("ok <!-- rest", KNOWN).markdown).toBe("ok");
    expect(cleanAnswer("ok <script", KNOWN).markdown).toBe("ok");
  });
});
