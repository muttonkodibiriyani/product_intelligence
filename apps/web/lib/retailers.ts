/**
 * What a shop is called on screen. An internal retailer id (`ulta_ae`, `sephora_me`, `faces_ae`,
 * `ounass_ae`, `bloomingdales_ae`) never reaches a customer: the known ids map to the shop's own
 * name, in both languages (Ounass and Bloomingdale's have their own Arabic name); any other id
 * takes the name /meta gives it, and only as a last resort reads as sent.
 */
const NAMES: Readonly<Record<string, string>> = {
  ulta_ae: 'Ulta',
  sephora_me: 'Sephora',
  faces_ae: 'Faces',
  ounass_ae: 'Ounass',
  bloomingdales_ae: "Bloomingdale's",
  // The same shop under the id some fixtures and older data use.
  sephora_ae: 'Sephora',
};
/** Arabic names where the shop has its own; the rest keep their Latin name in Arabic too. */
const AR_NAMES: Readonly<Record<string, string>> = {
  ounass_ae: 'أناس',
  bloomingdales_ae: 'بلومينغديلز',
};

/**
 * The display name for a retailer id; `fallback` is the name /meta sent, if any. With `locale`
 * 'ar', a shop's own Arabic name where it has one.
 */
export function retailerName(id: string, fallback?: string | null, locale?: string): string {
  return (locale === 'ar' ? AR_NAMES[id] : undefined) ?? NAMES[id] ?? (fallback || id);
}

/** Whether the app has its own name for this id (so the API's wording can be reworded to it). */
export const hasRetailerName = (id: string): boolean => Object.hasOwn(NAMES, id);

/**
 * The API's own caveat or detail text with every retailer id it mentions replaced by the shop's
 * display name, so a sentence the API worded around `sephora_me` reads "Sephora".
 */
export function withRetailerNames(text: string, name: (id: string) => string): string {
  return text.replace(/\b[a-z][a-z0-9]*_[a-z0-9_]+\b/g, (id) => {
    const n = name(id);
    return n === id ? id : n;
  });
}
