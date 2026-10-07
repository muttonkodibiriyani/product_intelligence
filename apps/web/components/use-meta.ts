'use client';

import { useQuery } from '@tanstack/react-query';
import { useLocale } from 'next-intl';
import { useCallback } from 'react';
import { retailerName } from '@/lib/retailers';
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

/**
 * Retailer id → the name shown to customers: the app's own name for the shops it knows, else the
 * display name from /meta, else (until /meta has loaded, or for an id it does not list) the id.
 * In Arabic, a shop's own Arabic name where it has one.
 */
export function useRetailerName(): (id: string) => string {
  const retailers = useMeta().data?.data?.retailers;
  const locale = useLocale();
  return useCallback(
    (id: string) => retailerName(id, retailers?.find((r) => r.id === id)?.name, locale),
    [retailers, locale],
  );
}
