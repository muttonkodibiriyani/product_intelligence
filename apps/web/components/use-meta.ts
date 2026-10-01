'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback } from 'react';
import { useAuth } from './auth-provider';

/** The dataset description (retailers, capabilities, cutoff). One cached request per generation. */
export function useMeta() {
  const { api } = useAuth();
  return useQuery({
    queryKey: ['meta'],
    queryFn: ({ signal }) => api!.get('/api/v1/meta', { signal }),
    enabled: !!api,
  });
}

/** Retailer id → its display name from /meta; the id itself until /meta has loaded. */
export function useRetailerName(): (id: string) => string {
  const retailers = useMeta().data?.data?.retailers;
  return useCallback((id: string) => retailers?.find((r) => r.id === id)?.name ?? id, [retailers]);
}
