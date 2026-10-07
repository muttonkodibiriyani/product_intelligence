import { describe, expect, it } from 'vitest';
import { retailerColor, retailerTone } from './retailer-dot';

describe('retailerTone', () => {
  it('gives each known shop its own colour, wherever it sits in the list', () => {
    const ids = ['ulta_ae', 'sephora_me', 'faces_ae', 'ounass_ae', 'bloomingdales_ae'];
    const tones = ids.map((id, i) => retailerTone(id, i + 3));
    expect(tones).toEqual(['bg-ulta', 'bg-sephora', 'bg-faces', 'bg-ounass', 'bg-bloomingdales']);
    expect(new Set(tones).size).toBe(ids.length);
    expect(retailerColor('faces_ae')).toBe('var(--color-faces)');
    expect(retailerColor('ounass_ae')).toBe('var(--color-ounass)');
    expect(retailerColor('bloomingdales_ae')).toBe('var(--color-bloomingdales)');
  });

  it('gives an unknown shop a series tone by its position', () => {
    expect(retailerTone('shop_x', 0)).toBe('bg-series-b');
    expect(retailerTone('shop_y', 1)).toBe('bg-series-a');
  });
});
