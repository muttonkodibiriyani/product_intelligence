/**
 * Retailer-sourced text is data, never instructions (design §7, AIG-04). Every such string leaves
 * the tool layer as `{ untrusted: "<escaped text>" }`: control, zero-width and bidi-override
 * characters are removed, the text is truncated, and Markdown/HTML syntax is backslash-escaped
 * so it cannot render as links, images or markup.
 */

export interface Untrusted {
  readonly untrusted: string;
}

export const UNTRUSTED_MAX_CHARS = 200;

// Cc = control characters, Cf = format characters (zero-width joiners, bidi embeddings/overrides,
// isolates, BOM). Both are invisible and are the usual carriers for hidden instructions.
const INVISIBLE = /[\p{Cc}\p{Cf}]/gu;
const MARKDOWN_SPECIAL = /[\\`*_{}[\]()#+!|<>~&"]/g;

export function sanitiseText(value: string, maxChars = UNTRUSTED_MAX_CHARS): string {
  const visible = value.replace(INVISIBLE, " ").replace(/\s+/g, " ").trim();
  const chars = Array.from(visible);
  const clipped = chars.length > maxChars ? `${chars.slice(0, maxChars).join("")}…` : visible;
  return clipped.replace(MARKDOWN_SPECIAL, (char) => `\\${char}`);
}

export function untrusted(value: string, maxChars = UNTRUSTED_MAX_CHARS): Untrusted {
  return { untrusted: sanitiseText(value, maxChars) };
}

/**
 * Evidence URLs are shown only for https hosts on the deployment's allowlist (config, not code:
 * ADR-0007 keeps retailer names out of the package). Anything else becomes null.
 */
export function evidenceUrl(value: string | null, allowedHosts: readonly string[]): string | null {
  if (value === null) {
    return null;
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username !== "" || url.password !== "") {
      return null;
    }
    return allowedHosts.includes(url.hostname.toLowerCase()) ? url.toString() : null;
  } catch {
    return null;
  }
}
