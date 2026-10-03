import { describe, expect, it } from 'vitest';
import { hasRetailerName, retailerName, withRetailerNames } from './retailers';

describe('retailerName', () => {
  it('names the known shops by their own name, whatever /meta calls them', () => {
    expect(retailerName('ulta_ae')).toBe('Ulta');
    expect(retailerName('ulta_ae', 'Ulta Beauty UAE')).toBe('Ulta');
    expect(retailerName('sephora_me')).toBe('Sephora');
    expect(retailerName('sephora_me', null)).toBe('Sephora');
    expect(retailerName('faces_ae', 'Faces UAE')).toBe('Faces');
  });

  it('takes the /meta name for any other id, and the id only without one', () => {
    expect(retailerName('shop_a', 'Shop A')).toBe('Shop A');
    expect(retailerName('shop_a', '')).toBe('shop_a');
    expect(retailerName('shop_a')).toBe('shop_a');
    expect(hasRetailerName('shop_a')).toBe(false);
    expect(hasRetailerName('ulta_ae')).toBe(true);
  });
});

describe('withRetailerNames', () => {
  const name = (id: string) => retailerName(id, ({ shop_c: 'Shop C' } as Record<string, string>)[id]);
  it('rewords the ids the API mentions, and leaves the rest of the sentence alone', () => {
    expect(withRetailerNames('shop_c is only partly collected.', name)).toBe(
      'Shop C is only partly collected.',
    );
    expect(withRetailerNames("ulta_ae's was-prices are unverified.", name)).toBe(
      "Ulta's was-prices are unverified.",
    );
    expect(withRetailerNames('بيانات sephora_me مجمّعة جزئياً.', name)).toBe('بيانات Sephora مجمّعة جزئياً.');
  });
  it('keeps an id nobody can name, and words that merely contain an underscore pattern it cannot name', () => {
    expect(withRetailerNames('shop_x is only partly collected.', name)).toBe(
      'shop_x is only partly collected.',
    );
    expect(withRetailerNames('No ids here.', name)).toBe('No ids here.');
  });
});
