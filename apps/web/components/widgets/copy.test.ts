import { createTranslator } from 'next-intl';
import { describe, expect, it } from 'vitest';
import ar from '@/messages/widgets.ar.json';
import en from '@/messages/widgets.en.json';

/*
 * The head-to-head copy: the pair count is its own meta line ("n = 6 comparable pairs") and the
 * card question is one plain sentence, so no card reads "On 6 pairs (sentence (sentence)).".
 */
const t = (locale: 'en' | 'ar') =>
  createTranslator({ locale, messages: { widgets: locale === 'en' ? en : ar }, namespace: 'widgets' });

const leaves = (o: unknown, path = ''): [string, string][] =>
  typeof o === 'string'
    ? [[path, o]]
    : Object.entries(o as Record<string, unknown>).flatMap(([k, v]) => leaves(v, path ? `${path}.${k}` : k));

describe('head-to-head copy', () => {
  it('states the pair count as a plain n = … line in both languages', () => {
    expect(t('en')('nPairs', { n: 6 })).toBe('n = 6 comparable pairs');
    expect(t('en')('nPairs', { n: 1 })).toBe('n = 1 comparable pair');
    const arabic = t('ar')('nPairs', { n: 6 });
    expect(arabic.startsWith('n = ')).toBe(true);
    expect(arabic).toMatch(/[\u0600-\u06FF]/);
  });

  it('keeps every card question a sentence without a parenthesised clause', () => {
    for (const lang of ['en', 'ar'] as const) {
      const tr = t(lang);
      const names = { base: 'A', other: 'B', by: 'x' };
      for (const key of [
        'cross.question',
        'gaps.question',
        'index.question',
        'groupGap.question',
        'cheaperShare.question',
      ] as const)
        expect(tr(key, names), `${lang} ${key}`).not.toMatch(/[()（）]/);
    }
  });

  it('never nests one message inside another in parentheses', () => {
    for (const [lang, m] of [
      ['en', en],
      ['ar', ar],
    ] as const)
      for (const [path, text] of leaves(m)) expect(text, `${lang} ${path}`).not.toMatch(/\(\{/);
  });
});
