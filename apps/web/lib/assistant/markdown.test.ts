import { describe, expect, it } from 'vitest';
import { firstTable, unavailableNote } from './answer';
import { inlineText, parseAnswer, parseInline } from './markdown';
import { plain } from './types';

describe('parseAnswer', () => {
  it('reads paragraphs, headings, lists and tables', () => {
    const blocks = parseAnswer(
      '## Gaps\n\nMedian gap is **12.5%** today.\n\n- one\n- two\n\n1. first\n\n| Retailer | Price |\n|---|---|\n| A | 10 |',
    );
    expect(blocks.map((b) => b.t)).toEqual(['h', 'p', 'ul', 'ol', 'table']);
    const table = blocks[4];
    if (table?.t !== 'table') throw new Error('table');
    expect(table.head.map(inlineText)).toEqual(['Retailer', 'Price']);
    expect(table.rows.map((r) => r.map(inlineText))).toEqual([['A', '10']]);
  });

  it('turns product tokens into references and keeps escaped text literal', () => {
    expect(parseInline('See [[product:p_1]] \\*not bold\\*')).toEqual([
      { t: 'text', v: 'See ' },
      { t: 'product', id: 'p_1' },
      { t: 'text', v: ' *not bold*' },
    ]);
  });

  it('bold never ends inside an escape', () => {
    expect(parseInline('**\\*\\*x\\*\\*** y')).toEqual([
      { t: 'strong', c: [{ t: 'text', v: '**x**' }] },
      { t: 'text', v: ' y' },
    ]);
  });

  it('never yields links, images or HTML: they stay plain text', () => {
    const md = '[click](https://evil.example) ![x](https://evil.example/a.png) <script>alert(1)</script>';
    const blocks = parseAnswer(md);
    const kinds = new Set(blocks.flatMap((b) => (b.t === 'p' ? b.c.map((c) => c.t) : [])));
    expect([...kinds]).toEqual(['text']);
  });
});

describe('answer helpers', () => {
  it('maps refusal codes to user notes', () => {
    expect(unavailableNote('disabled')).toBe('off');
    expect(unavailableNote('label_day_cap')).toBe('spendCap');
    expect(unavailableNote('question_cap')).toBe('questionCap');
    expect(unavailableNote('model_error')).toBe('generic');
    expect(unavailableNote(undefined)).toBe('generic');
  });

  it('builds a plain fallback table from the first list of records', () => {
    const table = firstTable({
      products: [
        { id: 'a', name: { untrusted: 'A \\*1' }, price: 10, prices: [1, 2] },
        { id: 'b', name: { untrusted: 'B' }, price: null },
      ],
    });
    expect(table).toEqual({
      columns: ['id', 'name', 'price'],
      rows: [
        ['a', 'A *1', '10'],
        ['b', 'B', '—'],
      ],
      total: 2,
    });
    expect(firstTable({ n: 3 })).toBeNull();
  });

  it('unescapes untrusted text for display', () => {
    expect(plain({ untrusted: '50% \\[off\\]' })).toBe('50% [off]');
  });
});
