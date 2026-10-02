import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { ProductView } from '@/components/product/product-view';
import { RequireAuth } from '@/components/require-auth';

/** One static page for every product: the id is in the query (?id=…), so no per-product build. */
export default async function ProductPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      <Suspense>
        <ProductView />
      </Suspense>
    </RequireAuth>
  );
}
