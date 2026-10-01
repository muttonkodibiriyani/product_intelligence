import { describe, expect, it } from 'vitest';
import { formatDate, loc } from './format';

describe('formatDate', () => {
  it('formats a date as UTC with Latin digits in both languages', () => {
    expect(formatDate('2026-09-30', 'en')).toBe('30 Sept 2026');
    expect(formatDate('2026-09-30T23:30:00Z', 'ar')).toMatch(/30/);
  });

  it('returns a malformed value as sent instead of throwing', () => {
    expect(formatDate('not-a-date', 'en')).toBe('not-a-date');
    expect(formatDate('', 'ar')).toBe('');
  });
});

describe('loc', () => {
  it('falls back to English', () => {
    expect(loc({ en: 'Makeup only.' }, 'ar')).toBe('Makeup only.');
    expect(loc({ en: 'a', ar: 'ب' }, 'ar')).toBe('ب');
    expect(loc(null, 'en')).toBe('');
  });
});
