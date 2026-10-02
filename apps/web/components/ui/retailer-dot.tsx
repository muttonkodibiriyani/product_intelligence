/**
 * The colour a shop reads in everywhere: Ulta burnt orange, Sephora graphite (app/globals.css).
 * A shop the app has no colour for takes a chart series tone by its position in the list, so two
 * unknown shops still tell apart. Always a dot, a bar or a rule, never a fill behind text.
 */
const TONES: Readonly<Record<string, string>> = {
  ulta_ae: 'bg-ulta',
  sephora_me: 'bg-sephora',
  sephora_ae: 'bg-sephora',
};
const FALLBACK = ['bg-series-b', 'bg-series-a', 'bg-lav-ink', 'bg-mint-ink'];

export function retailerTone(id: string, index = 0): string {
  return TONES[id] ?? FALLBACK[Math.abs(index) % FALLBACK.length]!;
}

/** The shop's dot, drawn next to its name. Decorative: the name is what is read out. */
export function RetailerDot({ id, index = 0 }: { id: string; index?: number }) {
  return <i aria-hidden className={`inline-block size-2 shrink-0 rounded-full ${retailerTone(id, index)}`} />;
}
