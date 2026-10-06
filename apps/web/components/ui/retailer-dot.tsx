/**
 * The colour a shop reads in everywhere: Ulta burnt orange, Sephora graphite, Faces deep teal
 * (app/globals.css). A shop the app has no colour for takes a chart series tone by its position in the list, so two
 * unknown shops still tell apart. Always a dot, a bar or a rule, never a fill behind text. One
 * table serves the class (`retailerTone`) and the inline value (`retailerColor`), so a shop's dot,
 * its count bars and its gap bars are the same colour.
 */
const TONES: Readonly<Record<string, string>> = {
  ulta_ae: 'bg-ulta',
  sephora_me: 'bg-sephora',
  sephora_ae: 'bg-sephora',
  faces_ae: 'bg-faces',
};
const FALLBACK = ['bg-series-b', 'bg-series-a', 'bg-lav-ink', 'bg-mint-ink'];

export function retailerTone(id: string, index = 0): string {
  return TONES[id] ?? FALLBACK[Math.abs(index) % FALLBACK.length]!;
}

/** The same colour as a CSS value, for a fill set inline (a bar sized from the data). */
export function retailerColor(id: string, index = 0): string {
  return `var(--color-${retailerTone(id, index).slice('bg-'.length)})`;
}

/** The shop's dot, drawn next to its name. Decorative: the name is what is read out. */
export function RetailerDot({ id, index = 0 }: { id: string; index?: number }) {
  return <i aria-hidden className={`inline-block size-2 shrink-0 rounded-full ${retailerTone(id, index)}`} />;
}
