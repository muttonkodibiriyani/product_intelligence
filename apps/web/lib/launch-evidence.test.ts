import { describe, expect, it } from 'vitest';
import { golden } from './api/golden';
import type { Envelope, Schemas } from './api/types';
import {
  filterLaunchEvidence,
  launchFilterGaps,
  launchEvidenceRow,
  type LaunchEvidenceFilters,
  type LaunchEvidenceRow,
} from './launch-evidence';

const productGolden = golden('product') as Envelope<Schemas['ProductDetail']>;

const launch = (retailer: string, id: string, firstSeen = '2026-10-07'): Schemas['Launch'] => ({
  id,
  name: `${retailer} synthetic product`,
  retailer,
  firstSeen,
});

function detail(
  retailer: string,
  id: string,
  change: (offer: Schemas['OfferView'], product: Schemas['ProductDetail']) => void = () => {},
): Envelope<Schemas['ProductDetail']> {
  const envelope = structuredClone(productGolden);
  const product = envelope.data!;
  product.card = {
    ...product.card,
    id,
    name: `${retailer} synthetic product`,
    brand: retailer === 'sephora_ae' ? 'Evidence Beauty' : 'Second Brand',
    category: ['makeup', 'lips'],
    image: 'https://example.invalid/product.jpg',
  };
  const offer = structuredClone(product.offers[0]!);
  offer.retailer = retailer;
  offer.context = retailer;
  offer.sku = `${retailer}-sku`;
  offer.size = { value: '4', unit: 'g' };
  offer.sizeLabel = '4 g';
  offer.content.variants = {
    state: 'observed',
    items: [
      {
        sku: offer.sku,
        gtin: { state: 'not_captured', barcode: null },
        shade: { state: 'observed', text: 'Rose' },
      },
    ],
  };
  offer.evidence = { capturedAt: '2026-10-08T09:30:00Z', url: 'https://example.invalid/source' };
  change(offer, product);
  product.offers = [offer];
  return envelope;
}

const emptyFilters = (): LaunchEvidenceFilters => ({
  retailer: [],
  brand: [],
  category: [],
  dateFrom: '',
  dateTo: '',
  priceMin: '',
  priceMax: '',
  discountMin: '',
  availability: [],
  size: '',
  color: '',
  shade: '',
  evidence: [],
});

describe('launch evidence adapter', () => {
  it('enriches Sephora from public product detail but never calls firstSeen a retailer-declared launch', () => {
    const row = launchEvidenceRow(launch('sephora_ae', 'spf-1'), detail('sephora_ae', 'spf-1'));
    expect(row.brand).toEqual({ state: 'observed', value: 'Evidence Beauty' });
    expect(row.sku.value).toBe('sephora_ae-sku');
    expect(row.size.value).toBe('4 g');
    expect(row.shade.value).toBe('Rose');
    expect(row.currentPrice.value?.amount).toBe('90.00');
    expect(row.regularPrice.value?.amount).toBe('100.00');
    expect(row.promotionPct.value).toBe('10.0');
    expect(row.availability.value).toBe('in_stock');
    expect(row.evidenceAt.value).toBe('2026-10-08T09:30:00Z');
    expect(row.source.value).toBe('https://example.invalid/source');
    // Fields the API never collects say so: never "missing" from the retailer's page.
    expect(row.retailerDeclaration).toEqual({ state: 'not_collected', value: null });
    expect(row.memberPrice).toEqual({ state: 'not_collected', value: null });
    expect(row.color).toEqual({ state: 'not_collected', value: null });
    expect(row.states).toEqual(['first_observed_only', 'not_collected']);
  });

  it('preserves null image, not_published, not_observed, stale and invalid as distinct states', () => {
    const env = detail('faces_ae', 'faces-1', (offer, product) => {
      product.card.image = null;
      offer.content.variants = { state: 'not_published', items: [] };
      offer.availability = 'not_observed';
      offer.price = null;
      offer.priceFlag = 'invalid_low';
    });
    const caveat: Schemas['CaveatView'] = {
      code: 'stale_source',
      en: 'stale',
      ar: 'قديم',
      params: { retailer: 'faces_ae', asOf: '2026-10-01' },
    };
    const row = launchEvidenceRow(launch('faces_ae', 'faces-1'), env, [caveat]);
    expect(row.image.state).toBe('missing');
    expect(row.shade.state).toBe('not_published');
    expect(row.availability.state).toBe('not_observed');
    expect(row.currentPrice.state).toBe('invalid');
    expect(row.staleAsOf).toBe('2026-10-01');
    expect(row.states).toEqual([
      'first_observed_only',
      'missing',
      'not_published',
      'not_observed',
      'stale',
      'invalid',
      'not_collected',
    ]);
  });

  it('marks an implausible regular price, discount or evidence date invalid, never shown as observed', () => {
    const env = detail('sephora_ae', 'spf-9', (offer) => {
      offer.regular = { ...offer.regular!, amount: 'abc' };
      offer.promoPct = '140';
      offer.evidence = { ...offer.evidence, capturedAt: 'not-a-date' };
    });
    const row = launchEvidenceRow(launch('sephora_ae', 'spf-9'), env);
    expect(row.regularPrice).toEqual({ state: 'invalid', value: null });
    expect(row.promotionPct).toEqual({ state: 'invalid', value: null });
    expect(row.evidenceAt).toEqual({ state: 'invalid', value: null });
    expect(row.states).toContain('invalid');
  });

  it('fails closed on contradictory same-context offers and ambiguous multi-context offers', () => {
    const conflict = detail('sephora_ae', 'spf-2');
    const second = structuredClone(conflict.data!.offers[0]!);
    second.price = { amount: '75.00', currency: 'AED', minor: 7500 };
    conflict.data!.offers.push(second);
    const contradicted = launchEvidenceRow(launch('sephora_ae', 'spf-2'), conflict);
    expect(contradicted.currentPrice.state).toBe('contradictory');
    expect(contradicted.sku.state).toBe('contradictory');
    expect(contradicted.states).toContain('contradictory');

    const contexts = detail('sephora_ae', 'spf-3');
    const pickup = structuredClone(contexts.data!.offers[0]!);
    pickup.context = 'sephora_ae:pickup:dubai';
    pickup.channel = 'pickup';
    contexts.data!.offers.push(pickup);
    const ambiguous = launchEvidenceRow(launch('sephora_ae', 'spf-3'), contexts);
    expect(ambiguous.currentPrice.state).toBe('missing');
    expect(ambiguous.states).not.toContain('contradictory');
  });

  it('keeps a failed or loading detail explicit instead of borrowing another retailer offer', () => {
    const loading = launchEvidenceRow(launch('sephora_ae', 'spf-4'), undefined);
    expect(loading.detailState).toBe('loading');
    expect(loading.currentPrice.state).toBe('unknown');
    const unavailable = launchEvidenceRow(launch('faces_ae', 'faces-4'), null);
    expect(unavailable.detailState).toBe('unavailable');
    // Evidence that was never read is unknown, never "missing" from the retailer.
    expect(unavailable.brand.state).toBe('unknown');
    expect(unavailable.states).toContain('unknown');
    expect(unavailable.states).not.toContain('missing');
  });
});

describe('launch evidence filters', () => {
  const sephora = launchEvidenceRow(launch('sephora_ae', 'spf-5'), detail('sephora_ae', 'spf-5'));
  const faces = launchEvidenceRow(
    launch('faces_ae', 'faces-5', '2026-10-02'),
    detail('faces_ae', 'faces-5', (offer) => {
      offer.availability = 'out_of_stock';
      offer.sizeLabel = '8 g';
      offer.size = { value: '8', unit: 'g' };
      offer.promoPct = null;
    }),
  );
  const rows: LaunchEvidenceRow[] = [sephora, faces];

  it.each([
    ['retailer', { retailer: ['sephora_ae'] }, ['sephora_ae']],
    ['brand', { brand: ['Evidence Beauty'] }, ['sephora_ae']],
    ['category', { category: ['lips'] }, ['sephora_ae', 'faces_ae']],
    ['date', { dateFrom: '2026-10-05', dateTo: '2026-10-09' }, ['sephora_ae']],
    ['price', { priceMin: '85', priceMax: '95' }, ['sephora_ae', 'faces_ae']],
    ['discount', { discountMin: '5' }, ['sephora_ae']],
    ['availability', { availability: ['out_of_stock'] }, ['faces_ae']],
    ['size', { size: '8 g' }, ['faces_ae']],
    ['shade', { shade: 'rose' }, ['sephora_ae', 'faces_ae']],
    ['evidence', { evidence: ['first_observed_only'] }, ['sephora_ae', 'faces_ae']],
  ] as const)('filters by %s', (_label, change, expected) => {
    const result = filterLaunchEvidence(rows, { ...emptyFilters(), ...change } as LaunchEvidenceFilters);
    expect(result.map((row) => row.launch.retailer)).toEqual(expected);
  });

  it('matches on the trimmed term, so a space still being typed changes nothing', () => {
    const only = (change: Partial<LaunchEvidenceFilters>) =>
      filterLaunchEvidence(rows, { ...emptyFilters(), ...change }).map((row) => row.launch.retailer);
    expect(only({ size: '8 ' })).toEqual(['faces_ae']);
    expect(only({ size: ' 8 g ' })).toEqual(['faces_ae']);
    expect(only({ size: '   ' })).toEqual(['sephora_ae', 'faces_ae']);
    expect(only({ shade: 'rose ' })).toEqual(['sephora_ae', 'faces_ae']);
  });

  it('fails closed for unsupported color evidence', () => {
    expect(filterLaunchEvidence(rows, { ...emptyFilters(), color: 'red' })).toEqual([]);
  });

  it('matches the "not observed" and "unknown" stock options against the field state', () => {
    const unseen = launchEvidenceRow(
      launch('faces_ae', 'faces-6'),
      detail('faces_ae', 'faces-6', (offer) => {
        offer.availability = 'not_observed';
      }),
    );
    const unread = launchEvidenceRow(launch('ulta_ae', 'ulta-6'), undefined);
    const pick = (availability: string[]) =>
      filterLaunchEvidence([unseen, unread], { ...emptyFilters(), availability }).map(
        (r) => r.launch.retailer,
      );
    expect(pick(['not_observed'])).toEqual(['faces_ae']);
    expect(pick(['unknown'])).toEqual(['ulta_ae']);
  });

  it('names every active value filter a product without that value cannot match', () => {
    expect(launchFilterGaps(emptyFilters())).toEqual([]);
    expect(
      launchFilterGaps({
        ...emptyFilters(),
        brand: ['B'],
        priceMax: '50',
        discountMin: '10',
        size: '8 g',
        shade: ' ',
        color: 'red',
      }),
    ).toEqual(['brand', 'price', 'discount', 'size', 'color']);
  });
});
