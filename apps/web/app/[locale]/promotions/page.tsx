import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { PromotionsView } from '@/components/promotions/promotions-view';
import { RequireAuth } from '@/components/require-auth';

export default async function PromotionsPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      {/* The filters live in the URL query, which a static page only has in the browser. */}
      <Suspense>
        <PromotionsView />
      </Suspense>
    </RequireAuth>
  );
}
