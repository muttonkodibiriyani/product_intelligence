import { describe, expect, it } from 'vitest';
import { cardSpan, pairCards } from './pair-cards';

describe('pair card layout', () => {
  it('keeps page order and drops the cards with nothing to show', () => {
    expect(pairCards(true, true, true)).toEqual(['size', 'policy', 'space']);
    expect(pairCards(false, true, true)).toEqual(['policy', 'space']);
    expect(pairCards(true, false, false)).toEqual(['size']);
    expect(pairCards(false, false, false)).toEqual([]);
  });

  it('never leaves half a row empty: an odd last card takes the whole row', () => {
    for (const shown of [
      pairCards(true, false, false),
      pairCards(true, true, false),
      pairCards(true, true, true),
      pairCards(false, true, true),
    ]) {
      const cols = shown.reduce((sum, c) => sum + cardSpan(shown, c), 0);
      expect(cols % 12).toBe(0);
    }
    const three = pairCards(true, true, true);
    expect(three.map((c) => cardSpan(three, c))).toEqual([6, 6, 12]);
    const one = pairCards(false, false, true);
    expect(cardSpan(one, 'space')).toBe(12);
  });
});
