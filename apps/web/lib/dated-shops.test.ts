import { createTranslator } from 'next-intl';
import { describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { marketDay, shopNotices } from './dated-shops';

const tEn = createTranslator({ locale: 'en', messages: en, namespace: 'shopNotice' });
const tAr = createTranslator({ locale: 'ar', messages: ar, namespace: 'shopNotice' });

const ULTA_NOTE = { en: 'ulta.ae blocked; last collected 2026-10-01' };
// The ruled set (01a11f5d-92d0): Ulta from its U1 run, Sephora windowed to tonight's cutoff.
const cutoff = '2026-10-08T22:07:33.995321Z'; // 9 Oct, 02:07 in Dubai
const coverage = [
  { id: 'ulta_ae', freshness: '2026-10-01', note: ULTA_NOTE },
  { id: 'sephora_me', freshness: '2026-10-09', note: null },
];
const pair = ['ulta_ae', 'sephora_me'];

describe('marketDay', () => {
  it('takes the Dubai day of an instant, not the UTC one', () => {
    expect(marketDay('2026-10-08T22:07:33.995321Z')).toBe('2026-10-09');
    expect(marketDay('2026-10-08T19:59:59Z')).toBe('2026-10-08');
    expect(marketDay('2026-10-08T20:00:00Z')).toBe('2026-10-09');
    expect(marketDay('not a date')).toBeNull();
  });
});

describe('shopNotices', () => {
  it('dates Ulta to its last collected day, with the reason the data gives', () => {
    expect(shopNotices({ cutoff }, coverage, pair, pair)).toEqual([
      { kind: 'asOf', id: 'ulta_ae', date: '2026-10-01', note: ULTA_NOTE },
    ]);
  });

  it('control: a windowed Sephora collected on the cutoff day gets no notice', () => {
    expect(shopNotices({ cutoff }, coverage, ['sephora_me'], pair)).toEqual([]);
  });

  it('at the day boundary, compares Dubai days: 8 Oct is a day old at 22:07Z on 8 Oct', () => {
    const rows = [
      { id: 'shop_x', freshness: '2026-10-08', note: null },
      { id: 'shop_y', freshness: '2026-10-09', note: null },
    ];
    // A UTC compare would read the cutoff as 8 Oct and stay silent for shop_x.
    expect(shopNotices({ cutoff }, rows, ['shop_x', 'shop_y'], pair)).toEqual([
      { kind: 'asOf', id: 'shop_x', date: '2026-10-08', note: null },
    ]);
    // A minute before Dubai midnight, the cutoff day is still 8 Oct: no notice.
    expect(shopNotices({ cutoff: '2026-10-08T19:59:00Z' }, rows, ['shop_x'], pair)).toEqual([]);
  });

  it('a windowed shop whose window ended a day before the cutoff day gets the notice', () => {
    const rows = [...coverage, { id: 'synthetic_ae', freshness: '2026-10-08', note: null }];
    expect(shopNotices({ cutoff }, rows, ['synthetic_ae', 'sephora_me'], pair)).toEqual([
      { kind: 'asOf', id: 'synthetic_ae', date: '2026-10-08', note: null },
    ]);
  });

  it('reads freshness, never since: an old first sighting with a current last day is silent', () => {
    const rows = [{ id: 'sephora_me', freshness: '2026-10-09', note: null, since: '2026-09-01' }];
    expect(shopNotices({ cutoff }, rows, ['sephora_me'], pair)).toEqual([]);
  });

  it('checks only the shops shown', () => {
    expect(shopNotices({ cutoff }, coverage, ['sephora_me'], pair)).toEqual([]);
    expect(shopNotices({ cutoff }, coverage, ['ulta_ae'], pair)).toHaveLength(1);
  });

  it('names a pilot shop the data does not collect', () => {
    expect(shopNotices({ cutoff }, coverage, ['sephora_me'], ['sephora_me', 'faces_ae'])).toEqual([
      { kind: 'absent', id: 'ulta_ae' },
    ]);
  });

  it('says nothing before /meta loads, and dates nothing before /coverage loads', () => {
    expect(shopNotices(null, coverage, pair, [])).toEqual([]);
    expect(shopNotices({ cutoff }, undefined, pair, pair)).toEqual([]);
  });
});

describe('messages', () => {
  it('words each notice in both languages', () => {
    const args = { shop: 'Ulta', date: '1 Oct 2026' };
    expect(tEn('asOfNote', { ...args, note: 'ulta.ae blocked' })).toBe(
      'Ulta prices as of 1 Oct 2026: ulta.ae blocked',
    );
    expect(tEn('asOf', args)).toBe('Ulta prices as of 1 Oct 2026.');
    expect(tEn('absent', { shop: 'Ulta' })).toBe('Ulta is not in this data.');
    expect(tAr('asOfNote', { ...args, note: 'x' })).toBe('أسعار Ulta حتى 1 Oct 2026: x');
    expect(tAr('asOf', args)).toBe('أسعار Ulta حتى 1 Oct 2026.');
    expect(tAr('absent', { shop: 'Ulta' })).toBe('Ulta غير موجود في هذه البيانات.');
  });
});
