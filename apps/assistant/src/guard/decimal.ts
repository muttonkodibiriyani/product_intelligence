/**
 * Exact decimal text, for the numeric verifier. Metrics are computed by the service layer
 * (pi_metrics, Python); the assistant never does arithmetic on them. It only compares the
 * decimal strings it was given with the numbers in the model's answer.
 */

export class DecimalFormatError extends Error {
  constructor(value: string) {
    super(`invalid decimal ${JSON.stringify(value)}`);
    this.name = "DecimalFormatError";
  }
}

export const DECIMAL_TEXT = /^-?\d+(?:\.\d+)?$/;

/** A decimal as an integer count of 10^-scale units. */
export interface Decimal {
  readonly units: bigint;
  readonly scale: number;
}

export function parseDecimal(text: string): Decimal {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) throw new DecimalFormatError(text);
  const [, sign = "", whole = "", fraction = ""] = match;
  const units = BigInt(`${whole}${fraction}`);
  return { units: sign === "-" ? -units : units, scale: fraction.length };
}
