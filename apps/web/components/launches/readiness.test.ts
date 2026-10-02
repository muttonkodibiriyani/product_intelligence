import { describe, expect, it } from 'vitest';
import type { Envelope, Schemas } from '@/lib/api/types';
import { golden as load } from '@/lib/api/golden';
import { launchReadiness } from './readiness';

type Meta = Envelope<Schemas['MetaView']>;
const meta = load('meta') as Meta;
const withData = (patch: Partial<Schemas['MetaView']>, caveats: Meta['caveats'] = []): Meta => ({
  ...meta,
  caveats,
  data: { ...meta.data!, ...patch },
});

describe('launchReadiness', () => {
  it('reads the golden /meta: three collected shops with three days each, the blocked one left out', () => {
    const r = launchReadiness(meta);
    expect(r.shops.map((s) => [s.id, s.kind, s.days, s.date, s.ready])).toEqual([
      ['shop_a', 'collected', 3, '2026-09-30', true],
      ['shop_b', 'collected', 3, '2026-09-30', true],
      ['shop_c', 'collected', 3, '2026-09-30', true],
    ]);
    expect(r.anyReady).toBe(true);
    expect(r.allReady).toBe(true);
  });

  it('is not ready with a single collection day, and says which day it was', () => {
    const r = launchReadiness(withData({ dates: ['2026-09-30'] }));
    expect(r.shops.every((s) => s.days === 1 && !s.ready && s.date === '2026-09-30')).toBe(true);
    expect(r.anyReady).toBe(false);
    expect(r.allReady).toBe(false);
  });

  it('credits a shop only with days on or after its own start', () => {
    const retailers = meta.data!.retailers.map((x) =>
      x.id === 'shop_c' ? { ...x, since: '2026-09-30' } : x,
    );
    const r = launchReadiness(withData({ retailers }));
    const c = r.shops.find((s) => s.id === 'shop_c')!;
    expect(c).toMatchObject({ days: 1, date: '2026-09-30', ready: false });
    expect(r.anyReady).toBe(true);
    expect(r.allReady).toBe(false);
  });

  it('counts an imported snapshot as one day, dated by its import caveat', () => {
    const r = launchReadiness(
      withData({}, [
        {
          code: 'snapshot_import_date',
          en: 'x',
          ar: 'x',
          params: { retailer: 'shop_b', date: '2026-10-01' },
        },
      ]),
    );
    const b = r.shops.find((s) => s.id === 'shop_b')!;
    expect(b).toEqual({
      id: 'shop_b',
      name: 'Shop B',
      kind: 'imported',
      days: 1,
      date: '2026-10-01',
      ready: false,
    });
    expect(r.allReady).toBe(false);
  });

  it('gives a supported shop with no start no days at all', () => {
    const retailers = meta.data!.retailers.map((x) => (x.id === 'shop_a' ? { ...x, since: null } : x));
    const a = launchReadiness(withData({ retailers })).shops[0]!;
    expect(a).toMatchObject({ kind: 'none', days: 0, date: null, ready: false });
  });

  it('is nothing without data', () => {
    expect(launchReadiness(undefined)).toEqual({ shops: [], anyReady: false, allReady: false });
    expect(launchReadiness({ ...meta, data: null })).toEqual({ shops: [], anyReady: false, allReady: false });
    expect(launchReadiness(withData({ retailers: [] }))).toEqual({
      shops: [],
      anyReady: false,
      allReady: false,
    });
  });
});
