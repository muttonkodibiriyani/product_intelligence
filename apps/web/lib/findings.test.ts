import { createTranslator } from 'next-intl';
import { describe, expect, it } from 'vitest';
import fixture from '@/e2e/findings-fixture.json';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import {
  barWidth,
  byTheme,
  fillArgs,
  findingId,
  HEADLINE_WORDS,
  messageArgs,
  moneyText,
  paramText,
  scale,
  signed,
  stripAxis,
  THEME_OF,
  THEMES,
  words,
  type Finding,
  type Findings,
  type Namers,
  type Param,
} from './findings';

const data = (fixture as unknown as { data: Findings }).data;
const findings = data.findings;
/** The fixture's anonymised shops under the real display names, which the word limit counts. */
const SHOPS: Record<string, string> = { shop_a: 'Ulta', shop_b: 'Sephora', shop_c: 'Faces' };
const names: Namers = { shop: (id) => SHOPS[id] ?? id, category: (c) => c };
const p = (kind: Param['kind'], value = '', currency: string | null = null, items: string[] = []): Param =>
  ({ kind, value, currency, items }) as Param;

describe('themes', () => {
  it('places every finding key in exactly one theme', () => {
    expect(Object.keys(THEME_OF)).toHaveLength(12);
    for (const t of Object.values(THEME_OF)) expect(THEMES).toContain(t);
  });

  it('groups by theme order, ranks ascending within a theme, and drops empty themes', () => {
    const groups = byTheme(findings);
    expect(groups.map(([t]) => t)).toEqual(THEMES.filter((t) => groups.some(([g]) => g === t)));
    for (const [t, fs] of groups) {
      expect(fs.every((f) => THEME_OF[f.key] === t)).toBe(true);
      expect(fs.map((f) => f.rank)).toEqual([...fs.map((f) => f.rank)].sort((a, b) => a - b));
    }
    expect(groups.flatMap(([, fs]) => fs)).toHaveLength(findings.length);
    const one = findings.filter((f) => f.key === 'stock');
    expect(byTheme(one)).toEqual([['stock', one]]);
  });

  it('gives each finding a stable dom id', () => {
    expect(findingId('brand_white_space')).toBe('finding-brand-white-space');
  });
});

describe('numbers', () => {
  it.each([
    ['-8.7', false, '−8.7'],
    ['3.1', false, '3.1'],
    ['3.1', true, '+3.1'],
    ['0.0', true, '0.0'],
  ])('signs %s (plus=%s) as %s', (v, plus, out) => {
    expect(signed(v, plus)).toBe(out);
  });

  it('scales bars, keeping a non-zero value visible and zero at zero', () => {
    const rows = [{ value: '-20' }, { value: '5' }] as Finding['chart'] extends infer C
      ? C extends { rows: infer R }
        ? R
        : never
      : never;
    expect(scale(rows)).toBe(20);
    expect(scale([])).toBe(1);
    expect(barWidth('-10', 20)).toBe(50);
    expect(barWidth('0.01', 20)).toBe(1);
    expect(barWidth('0', 20)).toBe(0);
    expect(barWidth('40', 20)).toBe(100);
    expect(barWidth('5', 0)).toBe(0);
  });

  it('pads a strip axis to include zero, and widens a flat one', () => {
    const row = (parts: string[]) => ({ label: 'x', value: '0', parts }) as never;
    expect(stripAxis([row(['2', '5'])])).toEqual({ min: 0, max: 5 });
    expect(stripAxis([row(['-3', '-1'])])).toEqual({ min: -3, max: 0 });
    expect(stripAxis([row(['0'])])).toEqual({ min: -1, max: 1 });
  });

  it('writes whole amounts without decimals and others to the fils, in Latin digits', () => {
    expect(moneyText('50.00', 'AED', 'en')).toMatch(/^AED\s50$/);
    expect(moneyText('49.5', 'AED', 'en')).toMatch(/^AED\s49\.50$/);
    expect(moneyText('85', 'AED', 'ar')).toMatch(/85/);
    expect(moneyText('85', 'AED', 'ar')).not.toMatch(/[٠-٩]/);
  });
});

describe('params', () => {
  it('words each kind of param, never an id', () => {
    expect(paramText(p('count', '1234'), 'en', names, '–')).toBe('1,234');
    expect(paramText(p('pct', '-3.9'), 'en', names, '–')).toBe('−3.9%');
    expect(paramText(p('ratio', '-0.27'), 'en', names, '–')).toBe('−0.27');
    expect(paramText(p('retailer', 'shop_a'), 'en', names, '–')).toBe('Ulta');
    expect(paramText(p('list', '', null, ['A', 'B', 'C']), 'en', names, '–')).toBe('A, B, and C');
    expect(paramText(p('missing'), 'en', names, '–')).toBe('–');
  });

  it('adds has_ and zero_ flags so a message words a missing or zero value', () => {
    const f = {
      params: { a: p('count', '0'), b: p('missing'), c: p('list'), d: p('pct', '2.0') },
    } as unknown as Finding;
    expect(messageArgs(f, 'en', names, '–')).toMatchObject({
      a: '0',
      has_a: 'yes',
      zero_a: 'yes',
      has_b: 'no',
      has_c: 'no',
      zero_d: 'no',
    });
  });

  it('fills only the arguments a message names and the finding did not send', () => {
    const out = fillArgs(
      '{x} {has_y, select, yes {{y}} other {none yet}} {zero_z, select, yes {none left} other {}}',
      {
        x: '1',
      },
      '–',
    );
    expect(out).toEqual({ x: '1', has_y: 'no', y: '–', zero_z: 'no' });
  });
});

describe.each([
  ['en', en],
  ['ar', ar],
] as const)('messages (%s) against the fixture', (locale, messages) => {
  // Keys are built from finding keys at run time, so the translator is called untyped here.
  const t = createTranslator({ locale, messages, namespace: 'insights.findings' }) as unknown as {
    (key: string, args?: Record<string, string>): string;
    raw: (key: string) => unknown;
    has: (key: string) => boolean;
  };
  const NOT = t('notMeasured');
  const say = (f: Finding, part: string) => {
    const args = {
      focus: names.shop(data.focus),
      rival: names.shop(data.rival),
      shop: names.shop(data.focus),
      threshold: String(f.threshold),
      ...messageArgs(f, locale, names, NOT),
    };
    const key = `items.${f.key}.${part}`;
    return t(key, fillArgs(t.raw(key) as string, args, NOT));
  };

  it('has every part for every finding, and the fixture serves all twelve', () => {
    expect(findings).toHaveLength(12);
    for (const f of findings)
      for (const part of ['tile', 'headline', 'decision', 'action', 'owner', 'evidence', 'cap', 'threshold'])
        expect(t.has(`items.${f.key}.${part}`), `${f.key}.${part}`).toBe(true);
  });

  // A shown finding may carry `missing` params (the engine could not measure them) or leave one
  // out; every slot then reads "not measured", never a blank (Reviewer, #263).
  it.each(findings.map((f) => [f.key, f] as const))('%s never prints a blank for a missing value', (_, f) => {
    const gone = {
      ...f,
      params: Object.fromEntries(Object.keys(f.params).map((k) => [k, { kind: 'missing' }])),
    };
    for (const g of [gone, { ...f, params: {} }] as Finding[])
      for (const part of [
        'tile',
        'headline',
        'decision',
        'action',
        'owner',
        'evidence',
        'cap',
        'threshold',
      ]) {
        const s = say(g, part);
        expect(s, `${f.key}.${part}`).not.toMatch(/ {2}|\( |\(\)| [,.:;)]|^\s|\s$/);
      }
  });

  it.each(findings.map((f) => [f.key, f] as const))('%s words cleanly, headline within the limit', (_, f) => {
    for (const part of ['tile', 'headline', 'decision', 'action', 'owner', 'evidence', 'cap']) {
      const s = say(f, part);
      expect(s.trim(), `${f.key}.${part}`).not.toBe('');
      expect(s, `${f.key}.${part}`).not.toMatch(/\{|\}|undefined|NaN|shop_[a-z]/);
    }
    const kpi = f.figure && f.figure.kind !== 'missing' ? paramText(f.figure, locale, names, '–') : '';
    expect(words(`${kpi} ${say(f, 'headline')}`), f.key).toBeLessThanOrEqual(HEADLINE_WORDS);
  });
});
