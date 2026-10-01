'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchCategoryCompare, type CategoryCompare } from '@/lib/api/category-compare';
import { useAuth } from '../auth-provider';
import { pairState, type PairState } from './model';

/**
 * /category-compare for a pair: the shared buckets over both full catalogues. The route is not in
 * production yet, so a 404 / not_found is "not available yet" (an honest empty state), not an
 * error; a wrong-shaped body parses to null and is empty too.
 */
export function useCategoryCompare(pair: { base: string; other: string } | null): PairState<CategoryCompare> {
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['category-compare', pair?.base, pair?.other],
    queryFn: ({ signal }) => fetchCategoryCompare(api!, pair!, signal),
    enabled: !!api && !!pair,
  });
  return pairState(q, (d) => Array.isArray(d.buckets) && d.buckets.length > 0, { notFoundIsEmpty: true });
}
