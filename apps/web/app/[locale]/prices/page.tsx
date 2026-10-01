import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { PricesView } from '@/components/prices/prices-view';
import { RequireAuth } from '@/components/require-auth';

export default async function PricesPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      {/* The retailer and grouping live in the URL query, which a static page only has in the browser. */}
      <Suspense>
        <PricesView />
      </Suspense>
    </RequireAuth>
  );
}
