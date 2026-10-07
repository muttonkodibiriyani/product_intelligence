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

/**
 * The argument names an ICU message uses, plural and select branches included (their selectors and
 * branch text are not arguments). A quoted span ('{…}') is literal text.
 */
export function argNames(msg: string): Set<string> {
  const names = new Set<string>();
  let i = 0;
  const skipQuote = () => {
    if (msg[i + 1] === "'") return void (i += 2);
    const end = msg.indexOf("'", i + 1);
    i = end < 0 ? msg.length : end + 1;
  };
  // Message text up to an unmatched '}' (the end of a branch) or the end.
  const text = (): void => {
    while (i < msg.length) {
      const c = msg[i];
      if (c === "'" && /['{}#|]/.test(msg[i + 1] ?? '')) skipQuote();
      else if (c === '{') argument();
      else if (c === '}') return;
      else i++;
    }
  };
  const until = (stops: string): string => {
    const start = i;
    while (i < msg.length && !stops.includes(msg[i]!)) i++;
    return msg.slice(start, i).trim();
  };
  const argument = (): void => {
    i++; // {
    names.add(until(',}'));
    if (msg[i++] === '}') return;
    const type = until(',}');
    if (msg[i++] === '}') return;
    if (['plural', 'select', 'selectordinal'].includes(type)) {
      for (;;) {
        until('{}'); // selector (and offset:n)
        if (msg[i++] !== '{') return; // the argument's closing brace
        text();
        i++; // the branch's closing brace
      }
    }
    for (let depth = 1; i < msg.length && depth > 0; i++)
      depth += msg[i] === '{' ? 1 : msg[i] === '}' ? -1 : 0;
  };
  text();
  return names;
}

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

  // Arabic may add a plural companion (`count`, `…Count`: the number behind a formatted one, for
  // noun agreement), never drop an argument English shows.
  it('Arabic uses every argument English uses, key by key, adding only plural counts', () => {
    const at = (t: Tree, k: string) =>
      k.split('.').reduce<string | Tree>((o, s) => (o as Tree)[s]!, t) as string;
    const differ = [...keys(en as Tree), ...keys(wEn as Tree).map((k) => `widgets.${k}`)].flatMap((k) => {
      const [e, a] = k.startsWith('widgets.')
        ? [at(wEn as Tree, k.slice(8)), at(wAr as Tree, k.slice(8))]
        : [at(en as Tree, k), at(ar as Tree, k)];
      const [ne, na] = [[...argNames(e)].sort(), [...argNames(a)].sort()];
      const extra = na.filter((n) => !ne.includes(n) && !/^count$|Count$/.test(n));
      const ok = ne.every((n) => na.includes(n)) && extra.length === 0;
      return ok ? [] : [`${k}: en {${ne.join(', ')}} ar {${na.join(', ')}}`];
    });
    expect(differ).toEqual([]);
  });

  it('reads arguments, not plural branch text or quoted braces', () => {
    expect(
      [...argNames("{n, plural, =0 {no items at {shop}} one {# item} other {# items}} '{x}' {a}")].sort(),
    ).toEqual(['a', 'n', 'shop']);
    expect([...argNames('{p, number, ::percent} {d, date, short}')].sort()).toEqual(['d', 'p']);
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
