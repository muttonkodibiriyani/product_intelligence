import { createTranslator } from 'next-intl';
import { describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import {
  absence,
  FLAG_AR,
  flagText,
  listingCell,
  type ListingSummary,
  orderSignals,
  ranksComparable,
  STOP_REASONS,
} from './listing-states';

const tEn = createTranslator({ locale: 'en', messages: en, namespace: 'listing' });
const tAr = createTranslator({ locale: 'ar', messages: ar, namespace: 'listing' });

const read = (o: Partial<ListingSummary>): ListingSummary => ({
  stopReason: 'cap',
  endReached: false,
  pagesRead: 10,
  positionsCaptured: 480,
  capturedAt: '2026-10-09T03:12:00Z',
  ...o,
});

describe('absence', () => {
  it('says "not in the list" only when the whole list was read', () => {
    expect(absence(read({ stopReason: 'end', endReached: true, positionsCaptured: 212 }))).toEqual({
      kind: 'notInList',
      at: '2026-10-09T03:12:00Z',
    });
  });

  it('does not trust end_reached without the end stop reason', () => {
    expect(absence(read({ stopReason: 'cap', endReached: true }))).toEqual({
      kind: 'notInFirst',
      n: 480,
      stop: 'cap',
    });
  });

  it.each([
    ['cap', 480],
    ['robots_page1', 48],
    ['page1_ssr', 24],
    ['empty_page', 96],
    ['repeat', 48],
    ['block', 96],
    ['error', 144],
    ['pending', 48],
  ] as const)('a %s stop past page 1 gives only the first N positions', (stop, n) => {
    expect(absence(read({ stopReason: stop, positionsCaptured: n }))).toEqual({
      kind: 'notInFirst',
      n,
      stop,
    });
  });

  it('a list not read, blocked on page 1 or with no product matched is not observed', () => {
    expect(absence(null)).toEqual({ kind: 'notObserved', stop: 'not_read' });
    expect(absence(undefined)).toEqual({ kind: 'notObserved', stop: 'not_read' });
    for (const stop of ['block', 'error', 'no_products'] as const)
      expect(
        absence(read({ stopReason: stop, pagesRead: stop === 'no_products' ? 1 : 0, positionsCaptured: 0 })),
      ).toEqual({
        kind: 'notObserved',
        stop,
      });
  });

  it('reads an unknown served stop reason as an error, never as the end', () => {
    expect(absence(read({ stopReason: 'finished', endReached: true }))).toEqual({
      kind: 'notInFirst',
      n: 480,
      stop: 'error',
    });
  });

  it('every stop reason has a sentence in both languages', () => {
    for (const s of [...STOP_REASONS, 'not_read'] as const) {
      expect(tEn(`stop.${s}`)).not.toMatch(/^listing\./);
      expect(tAr(`stop.${s}`)).not.toMatch(/^listing\./);
    }
  });

  it('never words a partial or missing read as "not listed"', () => {
    const partial = [
      tEn('absence.notInFirst', { count: 48, n: '48' }),
      tEn('absence.notObserved'),
      tAr('absence.notInFirst', { count: 48, n: '48' }),
      tAr('absence.notObserved'),
    ];
    for (const s of partial) expect(s).not.toMatch(/not in .*list|not listed|ليس في قائمة/i);
    // Control: the full-read sentence does say it.
    expect(tEn('absence.notInList', { shop: 'Faces', date: '9 Oct' })).toBe("Not in Faces's list on 9 Oct");
    expect(tAr('absence.notInList', { shop: 'Faces', date: '9 Oct' })).toMatch(/ليس في قائمة/);
    expect(tEn('absence.notInFirst', { count: 48, n: '48' })).toBe('Not in the first 48 positions captured');
  });
});

describe('flagText', () => {
  const flag = { code: 'new', en: 'NEW', ar: 'جديد!' };

  it('shows the served side for the locale, untouched', () => {
    expect(flagText({ ...flag, en: ' New In ' }, 'en')).toEqual({ text: ' New In ', arMissing: false });
    expect(flagText(flag, 'ar')).toEqual({ text: 'جديد!', arMissing: false });
  });

  it('English never falls back, even with no Arabic served', () => {
    expect(flagText({ ...flag, ar: null }, 'en')).toEqual({ text: 'NEW', arMissing: false });
  });

  it.each(Object.entries(FLAG_AR))('Arabic with none served uses the reviewed text for %s', (code, text) => {
    expect(flagText({ code, en: 'X', ar: null }, 'ar')).toEqual({ text, arMissing: true });
  });

  it('an unknown code with no Arabic shows the English as served', () => {
    expect(flagText({ code: 'clean', en: 'Clean at Sephora', ar: null }, 'ar')).toEqual({
      text: 'Clean at Sephora',
      arMissing: true,
    });
    // Object prototype names are not flag codes.
    expect(flagText({ code: 'constructor', en: 'Odd', ar: null }, 'ar')).toEqual({
      text: 'Odd',
      arMissing: true,
    });
  });

  it('the drawer note says the Arabic was not captured', () => {
    expect(tEn('arNotCaptured')).toBe('The Arabic text was not captured for this product.');
    expect(tAr('arNotCaptured')).toMatch(/النص العربي/);
  });
});

describe('orderSignals', () => {
  it('keeps a flag and a first sighting apart, in a fixed order', () => {
    const out = orderSignals([
      { source: 'firstSeen', date: '2026-10-08' },
      { source: 'newIn', position: 3, page: 1, capturedAt: '2026-10-09T03:12:00Z' },
      { source: 'flag', flag: { code: 'new', en: 'NEW', ar: null } },
    ]);
    expect(out.map((s) => s.source)).toEqual(['flag', 'newIn', 'firstSeen']);
  });
});

describe('listingCell', () => {
  const row = { productId: 'P512345', position: 7, page: 1, title: 'Lip Glow Oil' };

  it('joins the held product page on product id only', () => {
    const held = new Map([['P512345', { image: 'a.jpg', price: 145 }]]);
    expect(listingCell(row, held)).toEqual({ kind: 'detailed', row, product: held.get('P512345') });
  });

  it('with no product page held, keeps only position and title as served', () => {
    const held = new Map([['P999999', { image: 'b.jpg', price: 99 }]]);
    const cell = listingCell(row, held);
    expect(cell).toEqual({ kind: 'listedOnly', row });
    expect(cell).not.toHaveProperty('product');
    expect(tEn('listedOnly')).toBe('Listed, details not observed');
    expect(tAr('listedOnly')).toBe('مُدرج، والتفاصيل لم تُرصد');
  });
});

describe('ranksComparable', () => {
  it('compares positions only within one listing category', () => {
    expect(ranksComparable({ category: 'best_seller' }, { category: 'best_seller' })).toBe(true);
    expect(ranksComparable({ category: 'best_seller' }, { category: 'new' })).toBe(false);
    expect(ranksComparable({ category: '' }, { category: '' })).toBe(false);
  });
});
