import { describe, expect, it } from 'vitest';
import { guarded } from './chart';

describe('guarded', () => {
  it('a formatter that throws on a mark without its fields shows no tooltip', () => {
    const read = (e: { data: { trail: string[] } }) => e.data.trail.join(' › ');
    const o = guarded({
      tooltip: { formatter: read },
      series: [{ tooltip: { formatter: read } }, { type: 'bar' }],
    });
    const top = (o.tooltip as { formatter: (e: unknown) => unknown }).formatter;
    const own = (o.series as { tooltip: { formatter: (e: unknown) => unknown } }[])[0]!.tooltip.formatter;
    expect(top({ data: {} })).toBe('');
    expect(own({ data: {} })).toBe('');
    expect(top({ data: { trail: ['MU', 'Lips'] } })).toBe('MU › Lips');
  });
});
