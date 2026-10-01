import { describe, expect, it } from 'vitest';
import type { Money } from './api/types';
import { golden, goldenNames } from './api/golden';
import { currencyExponent, formatMoney, isValidMoney } from './money';

function moneyIn(v: unknown, out: Money[] = []): Money[] {
  if (Array.isArray(v)) v.forEach((x) => moneyIn(x, out));
  else if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if (typeof o.amount === 'string' && typeof o.minor === 'number' && typeof o.currency === 'string')
      out.push(o as unknown as Money);
    else Object.values(o).forEach((x) => moneyIn(x, out));
  }
  return out;
}

describe('money', () => {
  it('knows ISO exponents', () => {
    expect(currencyExponent('AED')).toBe(2);
    expect(currencyExponent('KWD')).toBe(3);
    expect(currencyExponent('JPY')).toBe(0);
  });

  it('accepts only exact decimals that agree with minor units', () => {
    expect(isValidMoney({ amount: '129.00', minor: 12900, currency: 'AED' })).toBe(true);
    expect(isValidMoney({ amount: '-4.50', minor: -450, currency: 'AED' })).toBe(true);
    expect(isValidMoney({ amount: '0.05', minor: 5, currency: 'AED' })).toBe(true);
    expect(isValidMoney({ amount: '1.250', minor: 1250, currency: 'KWD' })).toBe(true);
    expect(isValidMoney({ amount: '129', minor: 12900, currency: 'AED' })).toBe(false);
    expect(isValidMoney({ amount: '129.0', minor: 12900, currency: 'AED' })).toBe(false);
    expect(isValidMoney({ amount: '129.00', minor: 129, currency: 'AED' })).toBe(false);
  });

  it('every Money in every golden is exact', () => {
    let n = 0;
    for (const name of goldenNames()) {
      for (const m of moneyIn(golden(name))) {
        n++;
        expect(isValidMoney(m), `${name}: ${JSON.stringify(m)}`).toBe(true);
      }
    }
    expect(n).toBeGreaterThan(10);
  });

  it('formats the decimal string without float rounding, Latin digits in Arabic', () => {
    const big = { amount: '90071992547409.93', minor: 9007199254740993, currency: 'AED' };
    expect(formatMoney(big, 'en')).toContain('90,071,992,547,409.93');
    expect(formatMoney({ amount: '129.50', minor: 12950, currency: 'AED' }, 'ar')).toMatch(/129\.50/);
  });
});
