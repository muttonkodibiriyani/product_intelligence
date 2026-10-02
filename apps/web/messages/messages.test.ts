import { createTranslator } from 'next-intl';
import { describe, expect, it } from 'vitest';
import { API_ERROR_CODES } from '@/lib/api/types';
import type { Schemas } from '@/lib/api/types';
import { otherLocalePath } from '@/components/lang-switch';
import { formats } from '@/i18n/formats';
import ar from './ar.json';
import en from './en.json';
import wAr from './widgets.ar.json';
import wEn from './widgets.en.json';

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

  it('the widgets have the same keys in both languages, and no page key is called widgets', () => {
    expect(keys(wAr as Tree).sort()).toEqual(keys(wEn as Tree).sort());
    expect('widgets' in en).toBe(false);
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

describe('Arabic counts', () => {
  it('keep Latin digits even where the engine defaults Arabic to Arabic-Indic (WebKit)', () => {
    // ar-EG defaults to Arabic-Indic digits in every engine; the app's own locale is plain ar.
    const messages = { ...ar, widgets: wAr };
    const t = createTranslator({ locale: 'ar-EG', messages, formats, onError: () => {} });
    const bad: string[] = [];
    // Every Arabic plural branch: zero, one, two, few (6), many (11), other (100).
    for (const n of [0, 1, 2, 6, 11, 100])
      for (const key of keys(messages as Tree)) {
        const src = key
          .split('.')
          .reduce<string | Tree>((o, k) => (o as Tree)[k]!, messages as Tree) as string;
        const args = Object.fromEntries([...src.matchAll(/\{(\w+)/g)].map(([, a]) => [a, n]));
        const out = (t as unknown as (k: string, a: object) => string)(key, args);
        if (/[\u0660-\u0669]/.test(out)) bad.push(`${key} (n = ${n}): ${out}`);
      }
    expect(bad).toEqual([]);
    expect(t('widgets.nPairs', { n: 6 })).toBe('n = 6 أزواج قابلة للمقارنة');
  });
});
