import { createTranslator } from 'next-intl';
import { describe, expect, it } from 'vitest';
import ar from '@/messages/widgets.ar.json';

/*
 * A chart's label is its accessible description, so a screen reader reads the count in it aloud.
 * Arabic counted nouns change form with the number (one, two, 3–10, 11–99, 100+): "11 نطاقًا",
 * never "11 نطاقات".
 */
const t = createTranslator({ locale: 'ar', messages: { widgets: ar }, namespace: 'widgets' });
const label = (key: string, v: Record<string, number | string>) =>
  t(`${key}.label` as Parameters<typeof t>[0], v as never);

const COUNTS = [1, 2, 3, 11, 100] as const;

describe('Arabic chart labels', () => {
  it.each([
    ['ladder', 'n', ['فئة واحدة', 'فئتان', '3 فئات', '11 فئة', '100 فئة']],
    ['brands', 'n', ['علامة واحدة', 'علامتان', '3 علامات', '11 علامة', '100 علامة']],
    ['mix', 'n', ['فئة رئيسية واحدة', 'فئتان رئيسيتان', '3 فئات رئيسية', '11 فئة رئيسية', '100 فئة رئيسية']],
    ['hist', 'n', ['نطاق واحد', 'نطاقان', '3 نطاقات', '11 نطاقًا', '100 نطاق']],
    ['rating', 'k', ['منتج واحد', 'منتجان', '3 منتجات', '11 منتجًا', '100 منتج']],
    ['share', 'n', ['أكبر علامة', 'أكبر علامتين', 'أكبر 3 علامات', 'أكبر 11 علامة', 'أكبر 100 علامة']],
    ['index', 'n', ['يوم واحد', 'يومان', '3 أيام', '11 يومًا', '100 يوم']],
    ['cheaper', 'n', ['فئة واحدة', 'فئتان', '3 فئات', '11 فئة', '100 فئة']],
    ['gapHist', 'n', ['نطاق واحد', 'نطاقان', '3 نطاقات', '11 نطاقًا', '100 نطاق']],
    ['groupGap', 'n', ['مجموعة واحدة', 'مجموعتان', '3 مجموعات', '11 مجموعة', '100 مجموعة']],
    ['cheaperShare', 'n', ['مجموعة واحدة', 'مجموعتان', '3 مجموعات', '11 مجموعة', '100 مجموعة']],
  ] as const)('%s takes the right noun form at every count', (key, arg, forms) => {
    COUNTS.forEach((n, i) => {
      const text = label(key, { [arg]: n, by: 'الفئة' });
      expect(text, `${key} ${n}`).toContain(`، ${forms[i]}`);
      expect(text).toMatch(/\.$/);
    });
  });

  it('the cross chart counts categories and brands separately', () => {
    expect(label('cross', { rows: 1, cols: 2 })).toContain('فئة واحدة في علامتين تجاريتين');
    expect(label('cross', { rows: 11, cols: 3 })).toContain('11 فئة في 3 علامات تجارية');
    expect(label('cross', { rows: 2, cols: 100 })).toContain('فئتان في 100 علامة تجارية');
  });

  it('every counted chart label goes through a plural, so none reads "11 نطاقات"', () => {
    const bare = Object.entries(ar as Record<string, unknown>).flatMap(([k, v]) => {
      const l = (v as { label?: unknown }).label;
      // gaps reads "the widest {n}", with no noun to agree.
      return typeof l === 'string' && k !== 'gaps' && /\{(n|k|rows|cols)\}/.test(l) ? [k] : [];
    });
    expect(bare).toEqual([]);
  });
});
