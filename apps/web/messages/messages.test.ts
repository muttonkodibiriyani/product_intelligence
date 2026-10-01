import { describe, expect, it } from 'vitest';
import { API_ERROR_CODES } from '@/lib/api/types';
import type { Schemas } from '@/lib/api/types';
import { otherLocalePath } from '@/components/lang-switch';
import ar from './ar.json';
import en from './en.json';

type Tree = { [k: string]: string | Tree };
const keys = (t: Tree, p = ''): string[] =>
  Object.entries(t).flatMap(([k, v]) => (typeof v === 'string' ? [p + k] : keys(v, `${p}${k}.`)));

const REASONS: Schemas['Reason'][] = [
  'capability_off',
  'field_not_collected',
  'retailer_blocked',
  'retailer_partial',
  'cohort_too_small',
  'matches_unreviewed',
  'no_match',
  'not_in_scope',
  'currency_mismatch',
  'not_applicable',
];
const STATUSES: Schemas['RetailerStatus'][] = ['supported', 'partial', 'blocked', 'pending', 'retired'];

describe('messages', () => {
  it('English and Arabic have the same keys', () => {
    expect(keys(ar as Tree).sort()).toEqual(keys(en as Tree).sort());
  });

  it('no message is empty', () => {
    for (const [name, t] of [
      ['en', en],
      ['ar', ar],
    ] as const)
      for (const k of keys(t as Tree)) {
        const v = k.split('.').reduce<unknown>((o, s) => (o as Tree)[s], t);
        expect(v, `${name}:${k}`).not.toBe('');
      }
  });

  it('covers every API error code, not_enough_data reason and retailer status', () => {
    const k = new Set(keys(en as Tree));
    for (const c of [...API_ERROR_CODES, 'network', 'unexpected']) expect(k.has(`errors.${c}`), c).toBe(true);
    for (const r of REASONS) expect(k.has(`reasons.${r}`), r).toBe(true);
    for (const s of STATUSES) expect(k.has(`home.status.${s}`), s).toBe(true);
  });

  it('Arabic error and reason texts are Arabic', () => {
    for (const v of [...Object.values(ar.errors), ...Object.values(ar.reasons)]) expect(v).toMatch(/[؀-ۿ]/);
  });
});

describe('language switch', () => {
  it('keeps the page, swaps the language', () => {
    expect(otherLocalePath('/en/sign-in/', 'ar')).toBe('/ar/sign-in/');
    expect(otherLocalePath('/ar/', 'en')).toBe('/en/');
    expect(otherLocalePath('/en', 'ar')).toBe('/ar/');
  });
});
