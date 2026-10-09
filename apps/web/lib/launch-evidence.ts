import type { Envelope, Money, Schemas } from './api/types';
import { isValidAmount } from './money';

export const EVIDENCE_STATES = [
  'first_observed_only',
  'missing',
  'not_published',
  'not_observed',
  'stale',
  'invalid',
  'contradictory',
  'unknown',
  'not_collected',
] as const;
export type LaunchEvidenceState = (typeof EVIDENCE_STATES)[number];

/**
 * - `unknown`: the product's evidence has not been read (still loading, or the detail request
 *   failed), so nothing is said about the field: never "missing".
 * - `not_collected`: the API does not collect this field at all (API 1.25.0).
 */
export type FieldState =
  | 'observed'
  | 'missing'
  | 'not_published'
  | 'not_observed'
  | 'invalid'
  | 'contradictory'
  | 'unknown'
  | 'not_collected';

export interface EvidenceField<T> {
  value: T | null;
  state: FieldState;
}

const missing = <T>(): EvidenceField<T> => ({ value: null, state: 'missing' });
const contradictory = <T>(): EvidenceField<T> => ({ value: null, state: 'contradictory' });
const unknown = <T>(): EvidenceField<T> => ({ value: null, state: 'unknown' });
const notCollected = <T>(): EvidenceField<T> => ({ value: null, state: 'not_collected' });
const invalid = <T>(): EvidenceField<T> => ({ value: null, state: 'invalid' });

/** A discount the page can show as a percentage: a number above 0 and below 100. */
function percent(value: string | null | undefined): EvidenceField<string> {
  const text = value?.trim();
  if (!text) return missing();
  const n = Number(text);
  return Number.isFinite(n) && n > 0 && n < 100 ? observed(text) : invalid();
}

/** An evidence timestamp the page can date; anything unparseable is invalid, never shown. */
function timestamp(value: string | null | undefined): EvidenceField<string> {
  const text = value?.trim();
  if (!text) return missing();
  return Number.isNaN(Date.parse(text)) ? invalid() : observed(text);
}
const observed = <T>(value: T): EvidenceField<T> => ({ value, state: 'observed' });

export interface LaunchEvidenceRow {
  launch: Schemas['Launch'];
  /** Detail is loaded separately from the public product-detail route. */
  detailState: 'loading' | 'ready' | 'unavailable';
  brand: EvidenceField<string>;
  category: EvidenceField<string[]>;
  image: EvidenceField<string>;
  sku: EvidenceField<string>;
  size: EvidenceField<Schemas['Size'] | string>;
  color: EvidenceField<string>;
  shade: EvidenceField<string>;
  currentPrice: EvidenceField<Money>;
  regularPrice: EvidenceField<Money>;
  memberPrice: EvidenceField<Money>;
  promotionPct: EvidenceField<string>;
  availability: EvidenceField<Schemas['AvailabilityState']>;
  evidenceAt: EvidenceField<string>;
  source: EvidenceField<string>;
  /** Absent from API 1.25.0: never synthesized from firstSeen. */
  retailerDeclaration: EvidenceField<string>;
  staleAsOf: string | null;
  states: LaunchEvidenceState[];
}

type ProductEnvelope = Envelope<Schemas['ProductDetail']>;

function cleanText(value: string | null | undefined): EvidenceField<string> {
  const text = value?.trim();
  return text ? observed(text) : missing();
}

function contentText(value: Schemas['TextContent'] | undefined): EvidenceField<string> {
  if (!value || value.state === 'not_captured') return missing();
  if (value.state === 'not_published') return { value: null, state: 'not_published' };
  return cleanText(value.text);
}

function offerSignature(offer: Schemas['OfferView']): string {
  return JSON.stringify({
    availability: offer.availability,
    price: offer.price,
    regular: offer.regular,
    promoPct: offer.promoPct,
    size: offer.size,
    sizeLabel: offer.sizeLabel,
    sku: offer.sku,
    capturedAt: offer.evidence.capturedAt,
    url: offer.evidence.url,
  });
}

function hasContradictoryOffer(offers: Schemas['OfferView'][]): boolean {
  const byContext = new Map<string, Set<string>>();
  for (const offer of offers) {
    const signatures = byContext.get(offer.context) ?? new Set<string>();
    signatures.add(offerSignature(offer));
    byContext.set(offer.context, signatures);
  }
  return [...byContext.values()].some((signatures) => signatures.size > 1);
}

function staleDate(caveats: readonly Schemas['CaveatView'][], retailer: string): string | null {
  const caveat = caveats.find(
    (item) => item.code === 'stale_source' && (!item.params.retailer || item.params.retailer === retailer),
  );
  return caveat?.params.asOf ?? null;
}

/**
 * Joins a first-observed launch to the matching public product detail without inventing a listing.
 * A retailer with multiple contexts is deliberately left unresolved because Launch has only a
 * retailer id; duplicate conflicting evidence for one context is called contradictory.
 */
export function launchEvidenceRow(
  launch: Schemas['Launch'],
  detail: ProductEnvelope | null | undefined,
  caveats: readonly Schemas['CaveatView'][] = [],
): LaunchEvidenceRow {
  const base = {
    launch,
    // Not collected by the API: said as such, never "missing" from the retailer's page.
    color: notCollected<string>(),
    memberPrice: notCollected<Money>(),
    retailerDeclaration: notCollected<string>(),
    staleAsOf: staleDate(caveats, launch.retailer),
  };

  if (detail === undefined) {
    return finish({
      ...base,
      detailState: 'loading',
      brand: unknown(),
      category: unknown(),
      image: unknown(),
      sku: unknown(),
      size: unknown(),
      shade: unknown(),
      currentPrice: unknown(),
      regularPrice: unknown(),
      promotionPct: unknown(),
      availability: unknown(),
      evidenceAt: unknown(),
      source: unknown(),
    });
  }

  const product = detail?.status === 'ok' ? detail.data : null;
  if (!product) {
    return finish({
      ...base,
      detailState: 'unavailable',
      brand: unknown(),
      category: unknown(),
      image: unknown(),
      sku: unknown(),
      size: unknown(),
      shade: unknown(),
      currentPrice: unknown(),
      regularPrice: unknown(),
      promotionPct: unknown(),
      availability: unknown(),
      evidenceAt: unknown(),
      source: unknown(),
    });
  }

  if (product.card.id !== launch.id) {
    return finish({
      ...base,
      detailState: 'ready',
      brand: contradictory(),
      category: contradictory(),
      image: contradictory(),
      sku: contradictory(),
      size: contradictory(),
      shade: contradictory(),
      currentPrice: contradictory(),
      regularPrice: contradictory(),
      promotionPct: contradictory(),
      availability: contradictory(),
      evidenceAt: contradictory(),
      source: contradictory(),
    });
  }

  const offers = product.offers.filter((offer) => offer.retailer === launch.retailer);
  const conflict = hasContradictoryOffer(offers);
  // Launch identifies a retailer, not one of its contexts. Do not silently pick a channel/location.
  const offer = offers.length === 1 && !conflict ? offers[0]! : null;
  const offerField = <T>(read: (item: Schemas['OfferView']) => EvidenceField<T>): EvidenceField<T> =>
    conflict ? contradictory() : offer ? read(offer) : missing();

  const currentPrice = offerField<Money>((item) => {
    if (item.priceFlag === 'invalid_low' || (item.price && !isValidAmount(item.price.amount)))
      return { value: null, state: 'invalid' };
    return item.price ? observed(item.price) : missing();
  });
  const availability = offerField<Schemas['AvailabilityState']>((item) => {
    if (item.availability === 'not_observed') return { value: null, state: 'not_observed' };
    return item.availability ? observed(item.availability) : missing();
  });
  const shade = offerField<string>((item) => {
    if (item.content.variants.state === 'not_published') return { value: null, state: 'not_published' };
    if (item.content.variants.state === 'not_captured' || !item.sku) return missing();
    const variants = item.content.variants.items.filter((variant) => variant.sku === item.sku);
    if (variants.length !== 1) return variants.length > 1 ? contradictory() : missing();
    return contentText(variants[0]!.shade);
  });

  return finish({
    ...base,
    detailState: 'ready',
    brand: cleanText(product.card.brand),
    category: product.card.category.length ? observed(product.card.category) : missing(),
    image: cleanText(product.card.image),
    sku: offerField((item) => cleanText(item.sku)),
    size: offerField((item) =>
      item.sizeLabel?.trim() ? observed(item.sizeLabel.trim()) : item.size ? observed(item.size) : missing(),
    ),
    shade,
    currentPrice,
    regularPrice: offerField((item) => {
      if (item.regular && !isValidAmount(item.regular.amount)) return invalid();
      return item.regular ? observed(item.regular) : missing();
    }),
    promotionPct: offerField((item) => percent(item.promoPct)),
    availability,
    evidenceAt: offerField((item) => timestamp(item.evidence.capturedAt)),
    source: offerField((item) => cleanText(item.evidence.url)),
  });
}

function finish(row: Omit<LaunchEvidenceRow, 'states'>): LaunchEvidenceRow {
  const fields: EvidenceField<unknown>[] = [
    row.brand,
    row.category,
    row.image,
    row.sku,
    row.size,
    row.color,
    row.shade,
    row.currentPrice,
    row.regularPrice,
    row.memberPrice,
    row.promotionPct,
    row.availability,
    row.evidenceAt,
    row.source,
    row.retailerDeclaration,
  ];
  const states = new Set<LaunchEvidenceState>(['first_observed_only']);
  for (const field of fields) if (field.state !== 'observed') states.add(field.state);
  if (row.staleAsOf) states.add('stale');
  return { ...row, states: EVIDENCE_STATES.filter((state) => states.has(state)) };
}

export interface LaunchEvidenceFilters {
  retailer: string[];
  brand: string[];
  category: string[];
  dateFrom: string;
  dateTo: string;
  priceMin: string;
  priceMax: string;
  discountMin: string;
  availability: string[];
  size: string;
  color: string;
  shade: string;
  evidence: LaunchEvidenceState[];
}

const includesText = (field: EvidenceField<string>, raw: string) => {
  const query = raw.trim().toLocaleLowerCase();
  return !query || (field.value?.toLocaleLowerCase().includes(query) ?? false);
};

function sizeText(field: EvidenceField<Schemas['Size'] | string>): string {
  if (typeof field.value === 'string') return field.value;
  return field.value ? `${field.value.value} ${field.value.unit}` : '';
}

/**
 * The active value filters a row without that observed value cannot match, so the page can say
 * those products are not in the list instead of letting them vanish.
 */
export function launchFilterGaps(filters: LaunchEvidenceFilters): LaunchFilterGap[] {
  const out: LaunchFilterGap[] = [];
  if (filters.brand.length) out.push('brand');
  if (filters.category.length) out.push('category');
  if (filters.priceMin || filters.priceMax) out.push('price');
  if (filters.discountMin) out.push('discount');
  if (filters.size.trim()) out.push('size');
  if (filters.shade.trim()) out.push('shade');
  if (filters.color.trim()) out.push('color');
  return out;
}
export type LaunchFilterGap = 'brand' | 'category' | 'price' | 'discount' | 'size' | 'shade' | 'color';

/** Client-side filters apply only to fields already exposed by the two public responses. */
export function filterLaunchEvidence(
  rows: readonly LaunchEvidenceRow[],
  filters: LaunchEvidenceFilters,
): LaunchEvidenceRow[] {
  const low = filters.priceMin ? Number(filters.priceMin) : null;
  const high = filters.priceMax ? Number(filters.priceMax) : null;
  const discount = filters.discountMin ? Number(filters.discountMin) : null;
  return rows.filter((row) => {
    if (filters.retailer.length && !filters.retailer.includes(row.launch.retailer)) return false;
    if (filters.brand.length && (!row.brand.value || !filters.brand.includes(row.brand.value))) return false;
    if (
      filters.category.length &&
      (!row.category.value || !filters.category.some((category) => row.category.value!.includes(category)))
    )
      return false;
    if (filters.dateFrom && row.launch.firstSeen < filters.dateFrom) return false;
    if (filters.dateTo && row.launch.firstSeen > filters.dateTo) return false;
    const amount = row.currentPrice.value ? Number(row.currentPrice.value.amount) : null;
    if (low !== null && (!Number.isFinite(low) || amount === null || amount < low)) return false;
    if (high !== null && (!Number.isFinite(high) || amount === null || amount > high)) return false;
    const pct = row.promotionPct.value ? Number(row.promotionPct.value) : null;
    if (discount !== null && (!Number.isFinite(discount) || pct === null || pct < discount)) return false;
    // A stock state the detail did not observe is its state ("not_observed", "unknown"), so the
    // filter's own options for those states match it instead of dropping the row.
    if (
      filters.availability.length &&
      !filters.availability.includes(row.availability.value ?? row.availability.state)
    )
      return false;
    const size = filters.size.trim().toLocaleLowerCase();
    if (size && !sizeText(row.size).toLocaleLowerCase().includes(size)) return false;
    if (!includesText(row.color, filters.color)) return false;
    if (!includesText(row.shade, filters.shade)) return false;
    if (filters.evidence.length && !filters.evidence.some((state) => row.states.includes(state)))
      return false;
    return true;
  });
}
