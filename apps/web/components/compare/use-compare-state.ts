'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useMemo, useState } from 'react';
import { hasComparePair, parseCompare, toCompareSearch, type CompareState } from '@/lib/compare';
import { useMeta } from '../use-meta';
import { activeRetailers } from '../widgets/model';

/**
 * The pair and filters both Compare views read from the URL. As in the explorer, a picked value
 * shows at once, until the URL catches up; with exactly two collected shops the pair is implied.
 */
export function useCompareState() {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const meta = useMeta();
  const active = useMemo(() => activeRetailers(meta.data?.data), [meta.data]);

  const search = sp.toString();
  const parsed = useMemo(() => parseCompare(new URLSearchParams(search)), [search]);
  const [pending, setPending] = useState<{ at: string; state: CompareState } | null>(null);
  const picked = pending?.at === search ? pending.state : parsed;
  // The dataset's only pair needs no picking.
  const fixed =
    active.length === 2 &&
    (!hasComparePair(picked) || (active.includes(picked.base) && active.includes(picked.other)));
  const state: CompareState =
    fixed && !hasComparePair(picked) ? { ...picked, base: active[0]!, other: active[1]! } : picked;
  const update = (next: Partial<CompareState>) => {
    const target = { ...state, ...next };
    setPending({ at: search, state: target });
    router.push(pathname + toCompareSearch(target), { scroll: false });
  };
  return { state, update, fixed, ready: hasComparePair(state), key: toCompareSearch(state), meta };
}
