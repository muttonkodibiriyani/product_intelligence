/**
 * Numeric verifier (design §5). Every number in the model's answer must be a number some tool
 * returned this turn, or that number rounded to fewer decimal places. The rules:
 *
 * - Sources are typed fields only: decimal-text strings (money, %, index, ratings) and JSON
 *   numbers (counts). Identifier and timestamp keys are skipped. So are `{ untrusted }` values:
 *   digits inside retailer text never become allowed, so an injected "50% cheaper" in a product
 *   name cannot pass.
 * - The answer is normalised first:
 *   - Arabic-Indic and Extended Arabic-Indic digits become ASCII digits.
 *   - The Arabic decimal separator (٫) becomes "." and the thousands separator (٬) becomes ",".
 *   - The Arabic percent sign (٪) becomes "%".
 *   - "," is accepted only as a thousands separator in groups of three.
 * - Matching is exact decimal arithmetic on absolute values. A shown number matches a source if
 *   it is the same value (trailing zeros allowed), or the source rounded half away from zero to
 *   the shown number of decimal places. Nothing else counts: no rounding to tens, no unit
 *   conversion, no arithmetic on sources.
 * - Always allowed, exactly: 5 (rating scale) and 100 (index base).
 * - Stripped before matching:
 *   - `[[product:<id>]]` tokens (the UI renders product names from server data);
 *   - ISO dates and datetimes (the cited cutoff);
 *   - clock times;
 *   - leading list markers ("1. ", "2) ").
 *
 * Known limit: the verifier checks magnitudes, not direction or association. "A is 12.5% cheaper"
 * passes when the tool said B is cheaper by 12.5%. Mitigations:
 * - every gap carries an explicit `cheaper` retailer field, so the model never infers direction
 *   from a sign;
 * - the eval suite has direction-flip and wrong-attribution cases (design §8).
 */
import { DECIMAL_TEXT, type Decimal, parseDecimal } from "./decimal.js";

export const PRODUCT_TOKEN = /\[\[product:[A-Za-z0-9._:-]+\]\]/g;

/** Scale markers that may appear without a tool producing them (rating out of 5, index base 100). */
export const ALWAYS_ALLOWED: readonly string[] = ["5", "100"];

/** Keys whose values are identifiers or timestamps, never metrics. */
export const NON_METRIC_KEYS: ReadonlySet<string> = new Set([
  "id",
  "productId",
  "runId",
  "sku",
  "capturedAt",
  "date",
  "cutoff",
  "generation",
  "datasetGeneration",
  "toolVersion",
  "url",
  // Echoed tool inputs: a number the model put into a filter must not launder itself.
  "filters",
]);

const ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩";
const EXTENDED_ARABIC_INDIC = "۰۱۲۳۴۵۶۷۸۹";

export function normaliseDigits(text: string): string {
  return text.replace(/[٠-٩۰-۹٫٬٪]/g, (char) => {
    if (char === "٫") return ".";
    if (char === "٬") return ",";
    if (char === "٪") return "%";
    const index = ARABIC_INDIC.indexOf(char);
    return String(index >= 0 ? index : EXTENDED_ARABIC_INDIC.indexOf(char));
  });
}

const ISO_DATETIME =
  /\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?/g;
const CLOCK = /\b\d{1,2}:\d{2}(?::\d{2})?\b/g;
const LIST_MARKER = /^\s*\d+[.)]\s/gm;
const NUMBER = /\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?/g;

/** Numbers shown in an answer, as decimal text (absolute value, separators removed). */
export function extractNumbers(answer: string): string[] {
  const cleaned = normaliseDigits(answer)
    .replace(PRODUCT_TOKEN, " ")
    .replace(ISO_DATETIME, " ")
    .replace(CLOCK, " ")
    .replace(LIST_MARKER, " ");
  return Array.from(cleaned.matchAll(NUMBER), (match) => match[0].replace(/,/g, ""));
}

function abs(value: Decimal): Decimal {
  return value.units < 0n ? { units: -value.units, scale: value.scale } : value;
}

/** Collect metric values from typed fields of tool outputs. */
export function collectToolNumbers(outputs: readonly unknown[]): Decimal[] {
  const found: Decimal[] = [];
  const visit = (value: unknown): void => {
    if (typeof value === "string") {
      if (DECIMAL_TEXT.test(value)) found.push(abs(parseDecimal(value)));
    } else if (typeof value === "number") {
      if (Number.isSafeInteger(value)) found.push(abs({ units: BigInt(value), scale: 0 }));
    } else if (Array.isArray(value)) {
      value.forEach(visit);
    } else if (typeof value === "object" && value !== null && !("untrusted" in value)) {
      for (const [key, child] of Object.entries(value)) {
        if (!NON_METRIC_KEYS.has(key)) visit(child);
      }
    }
  };
  outputs.forEach(visit);
  return found;
}

function roundHalfAway(units: bigint, drop: number): bigint {
  const divisor = 10n ** BigInt(drop);
  return (2n * units + divisor) / (2n * divisor);
}

/** True if `shown` equals `source` or is `source` rounded half away from zero (both >= 0). */
export function isDisplayOf(shown: Decimal, source: Decimal): boolean {
  if (shown.scale >= source.scale) {
    return shown.units === source.units * 10n ** BigInt(shown.scale - source.scale);
  }
  return roundHalfAway(source.units, source.scale - shown.scale) === shown.units;
}

export interface VerifyResult {
  readonly ok: boolean;
  /** Numbers in the answer (normalised decimal text) that no tool output supports. */
  readonly unsupported: string[];
}

export function verifyAnswerNumbers(answer: string, toolOutputs: readonly unknown[]): VerifyResult {
  const allowed = [...collectToolNumbers(toolOutputs), ...ALWAYS_ALLOWED.map(parseDecimal)];
  const unsupported = extractNumbers(answer).filter((text) => {
    const shown = parseDecimal(text);
    return !allowed.some((source) => isDisplayOf(shown, source));
  });
  return { ok: unsupported.length === 0, unsupported };
}
