import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { Money, Pct } from './money';

afterEach(cleanup);
// Intl separates the currency with a no-break space.
const text = (el: React.ReactElement) => render(el).container.textContent?.replace(/\u00a0/g, ' ');

describe('Money', () => {
  it('signs a gap only when asked, and never signs zero', () => {
    const m = (amount: string, minor: number) => ({ amount, currency: 'AED', minor });
    expect(text(<Money m={m('20.00', 2000)} locale="en" signed />)).toBe('+AED 20.00');
    expect(text(<Money m={m('-20.00', -2000)} locale="en" signed />)).toBe('-AED 20.00');
    expect(text(<Money m={m('0.00', 0)} locale="en" signed />)).toBe('AED 0.00');
    expect(text(<Money m={m('20.00', 2000)} locale="en" />)).toBe('AED 20.00');
  });

  it('shows a value that fails the contract check as sent, not re-rounded', () => {
    expect(text(<Money m={{ amount: '20.005', currency: 'AED', minor: 2000 }} locale="en" />)).toBe(
      '20.005 AED',
    );
  });

  it('keeps the sign of a percentage', () => {
    expect(text(<Pct v="25.0" />)).toBe('+25.0%');
    expect(text(<Pct v="-4.2" />)).toBe('-4.2%');
    expect(text(<Pct v="0.0" />)).toBe('0.0%');
  });
});
