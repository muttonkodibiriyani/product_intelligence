'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { useAuth } from '../auth-provider';
import { productHref } from '../explore/product-table';

/** A `[[product:<id>]]` token: the product's name from the API (server data, not model text). */
export function ProductRef({ id }: { id: string }) {
  const t = useTranslations('assistant.answer');
  const locale = useLocale();
  const { api } = useAuth();
  const q = useQuery({
    queryKey: ['product', id],
    queryFn: ({ signal }) =>
      api!.get('/api/v1/products/{product_id}', { params: { product_id: id }, signal }),
    enabled: !!api,
    staleTime: 5 * 60_000,
  });
  const card = q.data?.data?.card;
  return (
    <Link
      href={productHref(locale, id)}
      className="text-accent underline-offset-2 hover:underline focus-visible:outline-2"
    >
      {card ? (
        <bdi>
          {card.brand} {card.name}
        </bdi>
      ) : (
        t('product')
      )}
    </Link>
  );
}
