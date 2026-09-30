/**
 * ADR-0007 literal guard: market, currency, retailer and dataset-path literals never appear in
 * shipped code. They come from API responses or deployment config.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const FORBIDDEN = [
  /["'`]AED["'`]/,
  /["'`]AE["'`]/,
  /["'`][us]["'`]/,
  /datasets\/uae/i,
  /sephora/i,
  /ulta/i,
];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe("literal guard", () => {
  it("keeps market, currency and retailer literals out of src", () => {
    const hits = files(new URL("../src", import.meta.url).pathname).flatMap((path) => {
      const source = readFileSync(path, "utf8");
      return FORBIDDEN.filter((pattern) => pattern.test(source)).map(
        (pattern) => `${path}: ${pattern}`,
      );
    });
    expect(hits).toEqual([]);
  });
});
