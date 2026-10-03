import { describe, expect, it } from 'vitest';
import { perDay } from './use-overview-data';

describe('perDay', () => {
  const seen = (...dates: string[]) => dates.map((firstSeen) => ({ firstSeen }));
  it('lists every day of the window, oldest first, with the launches first seen on it', () => {
    const days = perDay(seen('2026-09-29', '2026-09-29T10:00:00Z', '2026-10-01'), '2026-09-28', '2026-10-01');
    expect(days).toEqual([
      { date: '2026-09-28', n: 0 },
      { date: '2026-09-29', n: 2 },
      { date: '2026-09-30', n: 0 },
      { date: '2026-10-01', n: 1 },
    ]);
  });
  it('drops a launch outside the window rather than stretching it; a bad window is empty', () => {
    expect(perDay(seen('2026-09-01', '2026-10-05'), '2026-09-28', '2026-10-01').map((d) => d.n)).toEqual([
      0, 0, 0, 0,
    ]);
    expect(perDay(seen('2026-09-29'), '2026-10-01', '2026-09-28')).toEqual([]);
    expect(perDay([], '', '2026-09-28')).toEqual([]);
  });
});
