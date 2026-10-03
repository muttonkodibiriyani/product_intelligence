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
 * - The length of a list a tool returned counts as a source ("7 products" when the rows list
 *   has 7 entries): the count is a fact of the result, not arithmetic on a metric.
 * - The closing "Source:" line (the prompt asks for it, with the filters used) may also quote
 *   the echoed tool inputs (`citation.filters`, e.g. "limit 10", "priceMax 50"). Only that
 *   line: a filter value anywhere else is still unsupported, so a number the model chose
 *   cannot launder itself into the answer body.
 * - Version fields (`apiVersion`, `metricVersion`, …) are never sources, and of the citation
 *   only `cohort.n` counts: "2.5" as a version must not allow "2.5 AED".
 * - Stripped before matching, and only these:
 *   - `[[product:<id>]]` tokens (the UI renders product names from server data);
 *   - ISO dates and datetimes that a tool returned (whole value, or its date part);
 *   - clock times (HH:MM or HH:MM:SS) that appear in a datetime a tool returned;
 *   - ordered-list markers ("1. ", "2) ") that count up from 1 in sequence.
 *   Any other date, time or line-leading number is checked digit group by digit group, so
 *   "Price 2099-12-31", "12:30 AED" and "37. cheaper" fail.
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
  "apiVersion",
  "metricVersion",
  "promptVersion",
  "endpoint",
  "scope",
  "url",
  // Money is {amount, minor, currency}; the minor-unit integer is not a display value.
  "minor",
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
const ISO_VALUE = /^\d{4}-\d{2}-\d{2}(?:T(\d{2}):(\d{2})(?::(\d{2}))?[^]*)?$/;
const CLOCK = /\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b/g;
const LIST_MARKER = /^(\s*)(\d{1,2})([.)]\s)/;
const NUMBER = /\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?/g;

/** Dates and clock times the tools returned; only these may be stripped from an answer. */
export interface ToolTimes {
  readonly dates: ReadonlySet<string>;
  readonly clocks: ReadonlySet<string>;
}

const NO_TIMES: ToolTimes = { dates: new Set(), clocks: new Set() };

function clockKey(hours: string, minutes: string, seconds?: string): string {
  const base = `${hours.padStart(2, "0")}:${minutes}`;
  return seconds === undefined ? base : `${base}:${seconds}`;
}

/**
 * Collect ISO dates/datetimes from tool output. Of a citation only `cutoff` counts: `filters`
 * echo the model's own tool input and must not let a date or time the model chose through.
 * Echoed `filters` are skipped wherever they appear, and `{untrusted}` values are excluded.
 */
export function collectToolTimes(outputs: readonly unknown[]): ToolTimes {
  const dates = new Set<string>();
  const clocks = new Set<string>();
  const visit = (value: unknown): void => {
    if (typeof value === "string") {
      const match = ISO_VALUE.exec(value);
      if (!match) return;
      dates.add(value);
      dates.add(value.slice(0, 10));
      const [, hours, minutes, seconds] = match;
      if (hours !== undefined && minutes !== undefined) {
        dates.add(`${value.slice(0, 10)}T${clockKey(hours, minutes)}`);
        dates.add(`${value.slice(0, 10)} ${clockKey(hours, minutes)}`);
        clocks.add(clockKey(hours, minutes));
        if (seconds !== undefined) clocks.add(clockKey(hours, minutes, seconds));
      }
    } else if (Array.isArray(value)) {
      value.forEach(visit);
    } else if (typeof value === "object" && value !== null && !("untrusted" in value)) {
      for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
        if (key === "citation") {
          if (typeof child === "object" && child !== null && "cutoff" in child) visit(child.cutoff);
        } else if (key !== "filters") {
          visit(child);
        }
      }
    }
  };
  outputs.forEach(visit);
  return { dates, clocks };
}

/** Strip "1. ", "2. ", … only while they count up from 1; any other leading number stays. */
function stripListMarkers(text: string): string {
  let last = 0;
  return text
    .split("\n")
    .map((line) => {
      const match = LIST_MARKER.exec(line);
      if (!match) return line;
      const [whole, indent, digits, tail] = match as unknown as [string, string, string, string];
      const n = Number(digits);
      if (n !== 1 && n !== last + 1) return line;
      last = n;
      return `${indent}${" ".repeat(digits.length)}${" ".repeat(tail.length)}${line.slice(whole.length)}`;
    })
    .join("\n");
}

/** Numbers shown in an answer, as decimal text (absolute value, separators removed). */
export function extractNumbers(answer: string, times: ToolTimes = NO_TIMES): string[] {
  const cleaned = stripListMarkers(
    normaliseDigits(answer)
      .replace(PRODUCT_TOKEN, " ")
      .replace(ISO_DATETIME, (match) => (times.dates.has(match) ? " " : match))
      .replace(CLOCK, (match, hours: string, minutes: string, seconds?: string) =>
        times.clocks.has(clockKey(hours, minutes, seconds)) ? " " : match,
      ),
  );
  return Array.from(cleaned.matchAll(NUMBER), (match) => match[0].replace(/,/g, ""));
}

function abs(value: Decimal): Decimal {
  return value.units < 0n ? { units: -value.units, scale: value.scale } : value;
}

/** Collect metric values from typed fields of tool outputs. */
export function collectToolNumbers(outputs: readonly unknown[]): Decimal[] {
  const found: Decimal[] = [];
  // Of a citation, only the cohort size is a metric.
  const visitCitation = (citation: unknown): void => {
    if (typeof citation !== "object" || citation === null || !("cohort" in citation)) return;
    const { cohort } = citation;
    if (typeof cohort === "object" && cohort !== null && "n" in cohort) visit(cohort.n);
  };
  const visit = (value: unknown): void => {
    if (typeof value === "string") {
      if (DECIMAL_TEXT.test(value)) found.push(abs(parseDecimal(value)));
    } else if (typeof value === "number") {
      if (Number.isSafeInteger(value)) found.push(abs({ units: BigInt(value), scale: 0 }));
    } else if (Array.isArray(value)) {
      found.push({ units: BigInt(value.length), scale: 0 });
      value.forEach(visit);
    } else if (typeof value === "object" && value !== null && !("untrusted" in value)) {
      for (const [key, child] of Object.entries(value)) {
        if (key === "citation") visitCitation(child);
        else if (!NON_METRIC_KEYS.has(key)) visit(child);
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

/** The echoed tool inputs (`citation.filters`) of each output: numbers and decimal text. */
export function collectFilterNumbers(outputs: readonly unknown[]): Decimal[] {
  const found: Decimal[] = [];
  const visit = (value: unknown): void => {
    if (typeof value === "string") {
      if (DECIMAL_TEXT.test(value)) found.push(abs(parseDecimal(value)));
    } else if (typeof value === "number") {
      if (Number.isSafeInteger(value)) found.push(abs({ units: BigInt(value), scale: 0 }));
    } else if (Array.isArray(value)) {
      value.forEach(visit);
    } else if (typeof value === "object" && value !== null && !("untrusted" in value)) {
      Object.values(value).forEach(visit);
    }
  };
  for (const output of outputs) {
    if (typeof output !== "object" || output === null || !("citation" in output)) continue;
    const { citation } = output;
    if (typeof citation === "object" && citation !== null && "filters" in citation) {
      visit(citation.filters);
    }
  }
  return found;
}

/** The closing source line: "Source:" in English or "المصدر:" in Arabic, bold or not. */
const SOURCE_LINE = /^\s*(?:[*_]{1,2})?(?:source|sources|المصدر|المصادر)(?:[*_]{1,2})?\s*[:：]/i;

export function verifyAnswerNumbers(answer: string, toolOutputs: readonly unknown[]): VerifyResult {
  const allowed = [...collectToolNumbers(toolOutputs), ...ALWAYS_ALLOWED.map(parseDecimal)];
  const times = collectToolTimes(toolOutputs);
  const supported = (sources: readonly Decimal[]) => (text: string) => {
    const shown = parseDecimal(text);
    return sources.some((source) => isDisplayOf(shown, source));
  };
  const lines = answer.split("\n");
  let sourceAt = -1;
  lines.forEach((line, index) => {
    if (SOURCE_LINE.test(line)) sourceAt = index;
  });
  const body = sourceAt < 0 ? answer : lines.filter((_, index) => index !== sourceAt).join("\n");
  const unsupported = extractNumbers(body, times).filter((text) => !supported(allowed)(text));
  if (sourceAt >= 0) {
    const withFilters = [...allowed, ...collectFilterNumbers(toolOutputs)];
    const line = lines[sourceAt] ?? "";
    unsupported.push(
      ...extractNumbers(line, times).filter((text) => !supported(withFilters)(text)),
    );
  }
  return { ok: unsupported.length === 0, unsupported };
}
